import gc
import pytest
import random
import sys

from pymantic import triple_index
from pymantic.primitives import (
    XSD_STRING,
    BlankNode,
    Graph,
    Literal,
    NamedNode,
    Quad,
    Triple,
)

IRIS = [NamedNode("")] + [NamedNode("http://e/%d" % i) for i in range(5)]
BLANKS = [BlankNode() for _ in range(4)]
LITERALS = [Literal(""), Literal("x"), Literal("x", "en"), Literal("1", IRIS[1])]
SUBJECTS = IRIS + BLANKS
OBJECTS = IRIS + BLANKS + LITERALS
# Never added to any graph, so a pattern binding it must match nothing.
UNSEEN = NamedNode("http://e/unseen")

# Every combination of bound (True) and wildcard (False) positions.
PATTERNS = [
    (bs, bp, bo) for bs in (False, True) for bp in (False, True) for bo in (False, True)
]


def random_triple(rng):
    return Triple(rng.choice(SUBJECTS), rng.choice(IRIS), rng.choice(OBJECTS))


def random_pattern(rng, ref):
    """Bound values from a present triple half the time, so bound patterns
    usually have matches; otherwise from the pool or an unseen term."""
    if ref and rng.random() < 0.5:
        s, p, o = rng.choice(list(ref))
    else:
        s, p, o = random_triple(rng)
        if rng.random() < 0.1:
            s = UNSEEN
    bs, bp, bo = rng.choice(PATTERNS)
    return (s if bs else None, p if bp else None, o if bo else None)


def matching(ref, s, p, o):
    return {
        t
        for t in ref
        if (s is None or t.subject == s)
        and (p is None or t.predicate == p)
        and (o is None or t.object == o)
    }


def check_against_reference(graph, ref, rng):
    """Compare every read operation of `graph` with the ordered set `ref`."""
    assert len(graph) == len(ref)
    assert list(graph) == list(ref)
    for t in rng.sample(list(ref), min(3, len(ref))):
        assert t in graph
    for _ in range(3):
        t = random_triple(rng)
        assert (t in graph) == (t in ref)
    s, p, o = random_pattern(rng, ref)
    for bs, bp, bo in PATTERNS:
        qs = s if bs else None
        qp = p if bp else None
        qo = o if bo else None
        got = list(graph.match(qs, qp, qo))
        assert len(got) == len(set(got))
        assert set(got) == matching(ref, qs, qp, qo), (qs, qp, qo)
    assert set(graph.subjects()) == {t.subject for t in ref}
    assert set(graph.predicates()) == {t.predicate for t in ref}
    assert set(graph.objects()) == {t.object for t in ref}


@pytest.fixture(params=["default", "small"])
def index_constants(request, monkeypatch):
    """The index's own constants, then constants small enough that the
    model tests fold pending adds, turn rows into lists, rebuild list rows
    and filter rows in remove_many. Gives whether the constants are the small ones."""
    small = request.param == "small"
    if small:
        monkeypatch.setattr(triple_index, "FOLD_MIN", 8)
        monkeypatch.setattr(triple_index, "LIST_DEGREE", 4)
        monkeypatch.setattr(triple_index, "_FILTER_MIN", 2)
        monkeypatch.setattr(triple_index, "_REBUILD_MIN", 1)
    return small


def index_paths(indexes):
    """Which of folding and list rows the indexes have been through."""
    paths = set()
    for index in indexes:
        if index.folds:
            paths.add("folded")
        if any(type(row) is list for rows in index._orders for row in rows.values()):
            paths.add("list rows")
    return paths


@pytest.mark.parametrize("seed", range(10))
def test_graph_agrees_with_a_reference_model(index_constants, seed):
    rng = random.Random(seed)
    graph = Graph()
    # A dict used as an ordered set: re-adding after a remove moves to the end.
    ref = {}
    paths = set()
    for _ in range(1000):
        roll = rng.random()
        if roll < 0.5:
            t = random_triple(rng)
            graph.add(t)
            ref.setdefault(t, None)
        elif roll < 0.8:
            if ref and rng.random() < 0.8:
                t = rng.choice(list(ref))
                graph.remove(t)
                del ref[t]
            else:
                t = random_triple(rng)
                if t in ref:
                    continue
                with pytest.raises(KeyError):
                    graph.remove(t)
        elif roll < 0.95:
            s, p, o = random_pattern(rng, ref)
            graph.removeMatches(s, p, o)
            for t in matching(ref, s, p, o):
                del ref[t]
        else:
            # A batch the next query folds with the small constants, and
            # inserts one by one with the index's own.
            batch = [random_triple(rng) for _ in range(40)]
            graph.addAll(batch)
            for t in batch:
                ref.setdefault(t, None)
        check_against_reference(graph, ref, rng)
        assert len(graph._dictionary) <= 6 * len(graph)
        paths |= index_paths([graph._index])
    if index_constants:
        assert paths == {"folded", "list rows"}


S = NamedNode("http://e/s")
P = NamedNode("http://e/p")


def test_subjects_drops_a_subject_whose_last_triple_is_removed():
    other = NamedNode("http://e/other")
    g = Graph().add(Triple(S, P, Literal("a"))).add(Triple(other, P, Literal("b")))
    g.remove(Triple(S, P, Literal("a")))
    assert list(g.subjects()) == [other]
    assert list(g.objects()) == [Literal("b")]


def test_remove_matches_removes_every_match():
    kept = Triple(NamedNode("http://e/kept"), P, Literal("k"))
    g = Graph().add(kept)
    for value in ("a", "b", "c"):
        g.add(Triple(S, P, Literal(value)))
    assert g.removeMatches(S, None, None) is g
    assert list(g) == [kept]


def _removal_graph():
    """Triples where each single position and each pair of positions has
    both matching and non-matching triples."""
    other_s = NamedNode("http://e/other-s")
    other_p = NamedNode("http://e/other-p")
    triples = [
        Triple(S, P, Literal("a")),
        Triple(S, P, Literal("b")),
        Triple(S, other_p, Literal("a")),
        Triple(other_s, P, Literal("a")),
        Triple(other_s, other_p, Literal("b")),
    ]
    g = Graph()
    for triple in triples:
        g.add(triple)
    return g, triples, other_s, other_p


@pytest.mark.parametrize(
    "keywords",
    [
        {"subject": "S"},
        {"predicate": "P"},
        {"object": "A"},
        {"subject": "S", "predicate": "P"},
        {"subject": "S", "object": "A"},
        {"predicate": "P", "object": "A"},
        {"subject": "S", "predicate": "P", "object": "A"},
        {},
    ],
    ids=lambda keywords: "+".join(sorted(keywords)) or "none",
)
def test_remove_matches_takes_keyword_patterns(keywords):
    g, triples, other_s, other_p = _removal_graph()
    values = {"S": S, "P": P, "A": Literal("a")}
    bound = {name: values[v] for name, v in keywords.items()}
    expected = [
        t
        for t in triples
        if not all(getattr(t, name) == term for name, term in bound.items())
    ]
    assert g.removeMatches(**bound) is g
    assert list(g) == expected


def test_remove_matches_with_nothing_bound_empties_the_graph():
    g, _, _, _ = _removal_graph()
    assert g.removeMatches() is g
    assert len(g) == 0
    assert list(g) == []


def test_match_treats_an_empty_iri_as_a_term():
    empty = NamedNode("")
    t = Triple(empty, P, Literal("a"))
    g = Graph().add(t).add(Triple(S, P, Literal("b")))
    assert list(g.match(subject=empty)) == [t]


def test_match_finds_named_node_triples_by_plain_string():
    t = Triple(S, P, Literal("a"))
    g = Graph().add(t)
    assert list(g.match(subject="http://e/s")) == [t]


def test_remove_of_an_absent_triple_raises_key_error():
    g = Graph().add(Triple(S, P, Literal("a")))
    with pytest.raises(KeyError):
        g.remove(Triple(S, P, Literal("b")))
    # Every term known, but not in this combination.
    g.add(Triple(P, S, Literal("b")))
    with pytest.raises(KeyError):
        g.remove(Triple(S, P, Literal("b")))
    assert len(g) == 2


def test_simple_literal_and_xsd_string_literal_are_one_triple():
    g = Graph()
    g.add(Triple(S, P, Literal("x")))
    g.add(Triple(S, P, Literal("x", datatype=XSD_STRING)))
    assert len(g) == 1


def test_removing_triples_compacts_the_dictionary():
    triples = [
        Triple(
            NamedNode("http://e/s%d" % i),
            NamedNode("http://e/p%d" % i),
            Literal(str(i)),
        )
        for i in range(100)
    ]
    g = Graph().addAll(triples)
    for t in triples[:99]:
        g.remove(t)
        assert len(g._dictionary) <= 6 * len(g) + 0
    assert list(g.match()) == [triples[99]]
    assert list(g.match(subject=triples[99].subject)) == [triples[99]]
    # Freed ids are reused for new terms without disturbing the live ones.
    fresh = Triple(S, P, Literal("fresh"))
    g.add(fresh)
    assert list(g.match(predicate=P)) == [fresh]
    assert list(g.match(object=Literal("99"))) == [triples[99]]
    assert list(g) == [triples[99], fresh]


def tracked_objects():
    gc.collect()
    return len(gc.get_objects())


@pytest.mark.skipif(
    sys.implementation.name != "cpython",
    reason="counts objects tracked by CPython's cyclic garbage collector",
)
def test_graph_adds_almost_no_tracked_objects():
    before = tracked_objects()
    triples = [
        Triple(
            NamedNode("http://e/s%d" % (i // 10)),
            NamedNode("http://e/p%d" % (i % 10)),
            Literal(str(i)),
        )
        for i in range(10_000)
    ]
    distinct_terms = len({term for t in triples for term in t})
    g = Graph().addAll(triples)
    list(g.match(subject=triples[0].subject))  # merge the pending buffer
    del triples
    delta = tracked_objects() - before
    assert len(g) == 10_000
    assert delta < distinct_terms + 50


def test_removing_the_match_of_a_fully_bound_pattern():
    t = Triple(S, P, Literal("a"))
    g = Graph().add(t).add(Triple(S, P, Literal("b")))
    for found in g.match(S, P, Literal("a")):
        g.remove(found)
    assert t not in g
    assert len(g) == 1


def test_distinct_terms_support_len_membership_and_reiteration():
    other = NamedNode("http://e/other")
    g = Graph().add(Triple(S, P, Literal("a"))).add(Triple(other, P, S))
    for terms, expected in (
        (g.subjects(), [S, other]),
        (g.predicates(), [P]),
        (g.objects(), [S, Literal("a")]),
    ):
        assert len(terms) == len(expected)
        assert list(terms) == expected
        assert list(terms) == expected
        assert expected[0] in terms


def test_remove_of_a_quad_raises_type_error():
    g = Graph().add(Triple(S, P, Literal("a")))
    with pytest.raises(
        TypeError, match="a Graph holds triples; use a Dataset for quads"
    ):
        g.remove(Quad(S, P, Literal("a"), NamedNode("http://e/g")))


# Each reader below sees the graph that `abc_graph` builds.
GRAPH_READERS = {
    "iter": iter,
    "match": lambda g: g.match(),
    "match subject": lambda g: g.match(S),
    "match subject predicate": lambda g: g.match(S, P),
    "match object": lambda g: g.match(object=Literal("a")),
}

# Each really changes the graph that `abc_graph` builds.
GRAPH_CHANGES = {
    "add": lambda g: g.add(Triple(S, P, Literal("d"))),
    "remove": lambda g: g.remove(Triple(S, P, Literal("c"))),
    "removeMatches": lambda g: g.removeMatches(S, P, Literal("c")),
}


def abc_graph():
    g = Graph()
    for value in ("a", "b", "c"):
        g.add(Triple(S, P, Literal(value)))
    return g


@pytest.mark.parametrize("change", GRAPH_CHANGES)
@pytest.mark.parametrize("read", GRAPH_READERS)
def test_a_graph_read_raises_if_the_graph_changed_after_the_call(read, change):
    g = abc_graph()
    it = GRAPH_READERS[read](g)
    GRAPH_CHANGES[change](g)
    with pytest.raises(RuntimeError):
        next(it)


@pytest.mark.parametrize("change", GRAPH_CHANGES)
def test_a_fully_bound_graph_match_answers_as_of_the_call(change):
    g = abc_graph()
    present = g.match(S, P, Literal("c"))
    absent = g.match(S, P, Literal("d"))
    GRAPH_CHANGES[change](g)
    assert list(present) == [Triple(S, P, Literal("c"))]
    assert list(absent) == []
