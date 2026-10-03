from collections import Counter
import gc
import pathlib
import pytest
import random
import sys
import threading

from pymantic.primitives import (
    XSD_STRING,
    BlankNode,
    Dataset,
    Graph,
    Literal,
    NamedNode,
    Quad,
    Triple,
)
from pymantic import triple_index

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


def mark(term):
    """The term function the mapped-read tests expect to see applied."""
    return ("mapped", term)


class CountingMark:
    """`mark`, counting the calls made with each term."""

    def __init__(self):
        self.calls = Counter()

    def __call__(self, term):
        self.calls[term] += 1
        return mark(term)


def check_mapped_triples(graph):
    """mapped_triples gives what iterating and mapping each term gives,
    calling the function once per distinct term."""
    fn = CountingMark()
    expected = [(mark(s), mark(p), mark(o)) for s, p, o in graph]
    assert list(graph.mapped_triples(fn)) == expected
    assert fn.calls == Counter({term: 1 for t in graph for term in t})


def check_against_reference(graph, ref, rng):
    """Compare every read operation of `graph` with the ordered set `ref`."""
    assert len(graph) == len(ref)
    assert list(graph) == list(ref)
    # Before any match, while a batch of adds may still be pending.
    assert graph.object_counts() == Counter(t.object for t in ref)
    check_mapped_triples(graph)
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
    model tests fold pending adds, turn rows into lists and filter rows in
    remove_many. Gives whether the constants are the small ones."""
    small = request.param == "small"
    if small:
        monkeypatch.setattr(triple_index, "FOLD_MIN", 8)
        monkeypatch.setattr(triple_index, "LIST_DEGREE", 4)
        monkeypatch.setattr(triple_index, "_FILTER_MIN", 2)
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


def test_view_remove_matches_by_keyword_removes_only_from_that_graph():
    first, second = NamedNode("http://e/g1"), NamedNode("http://e/g2")
    other = NamedNode("http://e/other-s")
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), first))
    ds.add(Quad(other, P, Literal("a"), first))
    ds.add(Quad(S, P, Literal("a"), second))
    ds.add(Quad(S, P, Literal("a"), None))
    (view,) = [g for g in ds.graphs if g.uri == first]
    assert view.removeMatches(subject=S) is view
    assert set(ds) == {
        Quad(other, P, Literal("a"), first),
        Quad(S, P, Literal("a"), second),
        Quad(S, P, Literal("a"), None),
    }


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


@pytest.mark.parametrize("graph", [None, NamedNode("http://e/g")])
def test_dataset_remove_matches_with_a_fully_bound_pattern(graph):
    quad = Quad(S, P, Literal("a"), graph)
    kept = Quad(S, P, Literal("b"), graph)
    ds = Dataset()
    ds.add(quad)
    ds.add(kept)
    ds.removeMatches(S, P, Literal("a"), graph)
    assert quad not in ds
    assert kept in ds


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


# Dataset


FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "datasets"
G0 = NamedNode("http://e/g0")
G1 = NamedNode("http://e/g1")
# BLANKS[0] also appears in triples, so one graph name is shared with them.
DS_NAMES = [G0, G1, BLANKS[0]]
DS_GRAPHS = [None] + DS_NAMES


def load_dataset(name):
    # Imported here so the tests that need no fixture still run where the
    # parsers cannot be imported.
    from pymantic.parsers import linetrig_parser

    with open(FIXTURES / name, encoding="utf-8") as f:
        return linetrig_parser.parse(f)


def random_quad(rng):
    return Quad(*random_triple(rng), rng.choice(DS_GRAPHS))


def random_quad_pattern(rng, ref):
    """Like random_pattern, drawing bound values from the quads in ref."""
    if ref and rng.random() < 0.5:
        s, p, o, _ = rng.choice(list(ref))
    else:
        s, p, o = random_triple(rng)
        if rng.random() < 0.1:
            s = UNSEEN
    bs, bp, bo = rng.choice(PATTERNS)
    return (s if bs else None, p if bp else None, o if bo else None)


def matching_quads(ref, s, p, o, graph=None):
    return {
        q
        for q in matching(ref, s, p, o)
        if graph is None or (q.graph is not None and q.graph == graph)
    }


def named_graphs(ds):
    return {g.uri for g in ds.graphs if g.uri is not None}


def check_mapped_quads(ds):
    """mapped_quads gives what iterating and mapping each term gives, None
    for the default graph, calling the function once per distinct term
    across the dataset."""
    fn = CountingMark()
    expected = [
        (mark(s), mark(p), mark(o), None if g is None else mark(g)) for s, p, o, g in ds
    ]
    assert list(ds.mapped_quads(fn)) == expected
    assert fn.calls == Counter({term: 1 for q in ds for term in q if term is not None})


def check_dataset_against_reference(ds, ref, names, rng):
    assert len(ds) == len(ref)
    # The running count compaction reads, against the indexes themselves.
    assert ds._quad_count == sum(len(index) for index in ds._graphs.values())
    quads = list(ds)
    assert len(quads) == len(ref)
    assert set(quads) == set(ref)
    check_mapped_quads(ds)
    for view in ds.graphs:
        objects = Counter(q.object for q in ref if q.graph == view.uri)
        assert view.object_counts() == objects
        check_mapped_triples(view)
    for q in rng.sample(list(ref), min(3, len(ref))):
        assert (q in ds) is True
    for _ in range(3):
        q = random_quad(rng)
        assert (q in ds) is (q in ref)
        t = Triple(q.subject, q.predicate, q.object)
        assert (t in ds) is (Quad(*t, None) in ref)
    s, p, o = random_quad_pattern(rng, ref)
    graph = rng.choice(DS_NAMES)
    for bs, bp, bo in PATTERNS:
        qs = s if bs else None
        qp = p if bp else None
        qo = o if bo else None
        for g in (None, graph):
            got = list(ds.match(qs, qp, qo, g))
            assert len(got) == len(set(got))
            assert set(got) == matching_quads(ref, qs, qp, qo, g), (qs, qp, qo, g)
    assert [g.uri for g in ds.graphs][0] is None
    assert named_graphs(ds) == names
    # Each view reads the shared dictionary, compacted or not.
    sizes = {name: 0 for name in [None, *names]}
    for q in ref:
        sizes[q.graph] += 1
    assert {g.uri: len(g) for g in ds.graphs} == sizes
    assert len(ds._dictionary) <= 6 * len(ds) + len(names)


def edit_a_view(rng, ds, ref):
    """Add, remove or removeMatches through the view of a random graph,
    keeping `ref` in step."""
    view = rng.choice(ds.graphs)
    name = view.uri
    in_view = [q for q in ref if q.graph == name]
    roll = rng.random()
    if roll < 0.3:
        t = random_triple(rng)
        view.add(t)
        ref.setdefault(Quad(*t, name), None)
    elif roll < 0.5:
        triples = [random_triple(rng) for _ in range(rng.randrange(1, 6))]
        view.addAll(triples)
        for t in triples:
            ref.setdefault(Quad(*t, name), None)
    elif roll < 0.8:
        if in_view:
            q = rng.choice(in_view)
            view.remove(Triple(q.subject, q.predicate, q.object))
            del ref[q]
    else:
        s, p, o = random_quad_pattern(rng, in_view)
        view.removeMatches(s, p, o)
        for q in matching(in_view, s, p, o):
            del ref[q]


@pytest.mark.parametrize("seed", range(10))
def test_dataset_agrees_with_a_reference_model(index_constants, seed):
    rng = random.Random(seed)
    ds = Dataset()
    ref = {}
    names = set()
    paths = set()

    def add(q):
        ref.setdefault(q, None)
        if q.graph is not None:
            names.add(q.graph)

    for _ in range(1000):
        roll = rng.random()
        if roll < 0.35:
            q = random_quad(rng)
            ds.add(q)
            add(q)
        elif roll < 0.6:
            if ref and rng.random() < 0.8:
                q = rng.choice(list(ref))
                ds.remove(q)
                del ref[q]
            else:
                q = random_quad(rng)
                if q in ref:
                    continue
                with pytest.raises(KeyError):
                    ds.remove(q)
        elif roll < 0.73:
            s, p, o = random_quad_pattern(rng, ref)
            graph = rng.choice(DS_GRAPHS)
            assert ds.removeMatches(s, p, o, graph) is ds
            for q in matching_quads(ref, s, p, o, graph):
                del ref[q]
        elif roll < 0.8:
            edit_a_view(rng, ds, ref)
        elif roll < 0.87:
            name = rng.choice(DS_NAMES)
            if name in names:
                ds.remove_graph(name)
                names.discard(name)
                for q in [q for q in ref if q.graph == name]:
                    del ref[q]
            else:
                with pytest.raises(KeyError):
                    ds.remove_graph(name)
        elif roll < 0.94:
            name = rng.choice(DS_NAMES)
            triples = [random_triple(rng) for _ in range(rng.randrange(4))]
            ds.add_graph(Graph().addAll(triples), named=name)
            names.add(name)
            for t in triples:
                add(Quad(*t, name))
        else:
            # A batch the next query folds with the small constants, and
            # inserts one by one with the index's own.
            batch = [random_quad(rng) for _ in range(40)]
            ds.addAll(batch)
            for q in batch:
                add(q)
        check_dataset_against_reference(ds, ref, names, rng)
        paths |= index_paths(ds._graphs.values())
    if index_constants:
        assert paths == {"folded", "list rows"}


def test_empty_named_graphs_persist_until_removed():
    ds = load_dataset("empty-graphs.trig")
    empty1, full = NamedNode("http://e/empty1"), NamedNode("http://e/full")
    empty2 = NamedNode("http://e/empty2")
    assert len(ds) == 1
    assert named_graphs(ds) == {empty1, full, empty2}
    ds.remove(Quad(S, P, NamedNode("http://e/o"), full))
    assert len(ds) == 0
    assert named_graphs(ds) == {empty1, full, empty2}
    ds.remove_graph(full)
    ds.remove_graph(next(g for g in ds.graphs if g.uri == empty1))
    assert [g.uri for g in ds.graphs] == [None, empty2]


def test_remove_graph_rejects_the_default_graph_and_unknown_names():
    ds = load_dataset("default-only.trig")
    with pytest.raises(ValueError):
        ds.remove_graph(None)
    with pytest.raises(KeyError):
        ds.remove_graph(NamedNode("http://e/nowhere"))
    with pytest.raises(KeyError):
        # Known as a term, but it names no graph.
        ds.remove_graph(S)
    assert len(ds) == 3
    assert [g.uri for g in ds.graphs] == [None]


def test_reads_create_no_graphs():
    ds = Dataset()
    name = NamedNode("http://e/g")
    assert list(ds.match(graph=name)) == []
    assert list(ds.match(S, P, Literal("a"), name)) == []
    assert Quad(S, P, Literal("a"), name) not in ds
    assert [g.uri for g in ds.graphs] == [None]
    assert len(ds._dictionary) == 0


def test_triple_membership_is_default_graph_membership():
    t = Triple(S, P, Literal("a"))
    ds = Dataset()
    ds.add(Quad(*t, NamedNode("http://e/g")))
    assert (t in ds) is False
    assert (Quad(*t, NamedNode("http://e/g")) in ds) is True
    ds.add(Quad(*t, None))
    assert (t in ds) is True
    assert (Quad(*t, None) in ds) is True
    assert ("not a statement" in ds) is False
    assert ((S, P) in ds) is False


def test_blank_nodes_are_shared_across_graphs():
    ds = load_dataset("shared-blank-nodes.trig")
    (default,) = [q for q in ds if q.graph is None]
    b = default.subject
    assert isinstance(b, BlankNode)
    (in_g1,) = ds.match(graph=NamedNode("http://e/g1"))
    assert in_g1.subject is b
    named_by_b = [g for g in ds.graphs if g.uri is b]
    assert len(named_by_b) == 1
    assert list(named_by_b[0]) == [Triple(S, P, NamedNode("http://e/o"))]
    assert {q.graph for q in ds.match(subject=S)} == {b}


def test_add_graph_copies_the_graph():
    ds = load_dataset("shared-blank-nodes.trig")
    b = next(q.subject for q in ds if q.graph is None)
    name = NamedNode("http://e/copied")
    g = Graph().add(Triple(b, P, Literal("x")))
    ds.add_graph(g, named=name)
    g.add(Triple(S, P, Literal("later")))
    assert list(ds.match(graph=name)) == [Quad(b, P, Literal("x"), name)]
    (copied,) = ds.match(graph=name)
    assert copied.subject is b
    # Same name again: the union of both graphs.
    ds.add_graph(Graph().add(Triple(S, P, Literal("y"))), named=name)
    assert set(ds.match(graph=name)) == {
        Quad(b, P, Literal("x"), name),
        Quad(S, P, Literal("y"), name),
    }


def test_add_graph_uses_the_graph_uri_as_its_name():
    name = NamedNode("http://e/g")
    ds = Dataset()
    ds.add_graph(Graph(name).add(Triple(S, P, Literal("a"))))
    assert list(ds) == [Quad(S, P, Literal("a"), name)]
    with pytest.raises(ValueError):
        ds.add_graph(Graph())


def test_a_view_of_a_removed_graph_raises():
    name = NamedNode("http://e/g")
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), name))
    (view,) = [g for g in ds.graphs if g.uri == name]
    pending = view.match(subject=S)
    ds.remove_graph(name)
    with pytest.raises(RuntimeError):
        len(view)
    with pytest.raises(RuntimeError):
        list(view)
    with pytest.raises(RuntimeError):
        list(view.mapped_triples(mark))
    with pytest.raises(RuntimeError):
        view.object_counts()
    with pytest.raises(RuntimeError):
        list(pending)
    # The removal emptied the dataset, so compaction freed every term and
    # these reads find unknown terms before reaching the index.
    with pytest.raises(RuntimeError):
        Triple(S, P, Literal("a")) in view
    with pytest.raises(RuntimeError):
        list(view.match(S, P, Literal("a")))
    with pytest.raises(RuntimeError):
        view.remove(Triple(S, P, Literal("a")))
    with pytest.raises(RuntimeError):
        view.removeMatches(S, None, None)
    with pytest.raises(RuntimeError):
        view.add(Triple(S, P, Literal("b")))
    # The refused add interned nothing into the dataset's dictionary.
    assert len(ds._dictionary) == 0
    # Adding to the name again makes a new graph; the old view stays dead.
    ds.add(Quad(S, P, Literal("c"), name))
    with pytest.raises(RuntimeError):
        len(view)


def test_view_edits_reach_the_dataset():
    name = NamedNode("http://e/g")
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), name))
    (view,) = [g for g in ds.graphs if g.uri == name]
    view.add(Triple(S, P, Literal("b")))
    view.remove(Triple(S, P, Literal("a")))
    assert list(ds) == [Quad(S, P, Literal("b"), name)]


def test_match_takes_a_graph_name_as_a_plain_string():
    q = Quad(S, P, Literal("a"), NamedNode("http://e/g"))
    ds = Dataset()
    ds.add(q)
    assert list(ds.match(graph="http://e/g")) == [q]
    assert list(ds.match(S, P, Literal("a"), "http://e/g")) == [q]


def test_dataset_remove_of_an_absent_quad_raises_key_error():
    name = NamedNode("http://e/g")
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), name))
    for absent in (
        Quad(S, P, Literal("a"), None),
        Quad(S, P, Literal("a"), NamedNode("http://e/other")),
        Quad(S, P, Literal("b"), name),
    ):
        with pytest.raises(KeyError):
            ds.remove(absent)
    assert len(ds) == 1


def test_compaction_keeps_terms_used_by_other_graphs():
    many, few = NamedNode("http://e/many"), NamedNode("http://e/few")
    quads = [
        Quad(NamedNode("http://e/s%d" % i), P, Literal(str(i)), many)
        for i in range(100)
    ]
    ds = Dataset().addAll(quads)
    # Its terms are first seen in `many` and outlive every quad there.
    kept = Quad(quads[0].subject, P, quads[0].object, few)
    ds.add(kept)
    for q in quads:
        ds.remove(q)
    assert len(ds._dictionary) <= 6 * len(ds) + 2
    assert list(ds) == [kept]
    assert list(ds.match(subject=kept.subject)) == [kept]
    assert list(ds.match(object=kept.object, graph=few)) == [kept]
    assert [g.uri for g in ds.graphs] == [None, many, few]


def test_fully_bound_match_is_unaffected_by_removes_while_open():
    s, p, o = S, P, NamedNode("http://e/o")
    other = NamedNode("http://e/other")
    d, e, f = (NamedNode("http://e/" + c) for c in "def")
    ds = Dataset()
    ds.add(Quad(d, e, f, None))
    ds.add(Quad(s, p, o, None))
    ds.add(Quad(*(NamedNode("http://e/" + c) for c in "abc"), other))
    ds.remove(Quad(d, e, f, None))
    found = ds.match(s, p, o)
    first = next(found)
    assert first == Quad(s, p, o, None)
    # Emptying the default graph compacts the dictionary, freeing the ids of
    # s, p and o; these adds reuse them for other terms in `other`.
    ds.remove(first)
    x, y, z = (NamedNode("http://e/" + c) for c in "xyz")
    ds.add(Quad(x, y, z, other))
    ds.add(Quad(z, y, x, other))
    assert list(found) == []


def check_lookups_against_match(graph, s, p, o):
    """Each Triple-free lookup, for every combination of s, p and o it takes
    with at least one bound, yields the matching column of what match()
    yields for that pattern, in match()'s order."""
    for bs, bp, bo in PATTERNS:
        qs = s if bs else None
        qp = p if bp else None
        qo = o if bo else None
        triples = list(graph.match(qs, qp, qo))
        if qs is None and (qp is not None or qo is not None):
            got = list(graph.subjects(predicate=qp, object=qo))
            assert got == [t.subject for t in triples], (qp, qo)
        if qp is None and (qs is not None or qo is not None):
            got = list(graph.predicates(subject=qs, object=qo))
            assert got == [t.predicate for t in triples], (qs, qo)
        if qo is None and (qs is not None or qp is not None):
            got = list(graph.objects(subject=qs, predicate=qp))
            assert got == [t.object for t in triples], (qs, qp)
        if qs is not None and qp is None and qo is None:
            got = list(graph.predicate_objects(qs))
            assert got == [(t.predicate, t.object) for t in triples], qs


def lookup_terms(rng, ref):
    """A subject, predicate and object to bind in every combination: from a
    present triple half the time, so lookups usually find matches;
    otherwise from the pool, sometimes with an unseen subject."""
    if ref and rng.random() < 0.5:
        return rng.choice(list(ref))
    s, p, o = random_triple(rng)
    if rng.random() < 0.1:
        s = UNSEEN
    return s, p, o


@pytest.mark.parametrize("seed", range(10))
def test_lookups_agree_with_match(index_constants, seed):
    rng = random.Random(seed)
    graph = Graph()
    ref = {}
    paths = set()
    for step in range(300):
        roll = rng.random()
        if roll < 0.6:
            t = random_triple(rng)
            graph.add(t)
            ref.setdefault(t, None)
        elif roll < 0.85:
            if ref:
                t = rng.choice(list(ref))
                graph.remove(t)
                del ref[t]
        else:
            # A batch the next query folds with the small constants, and
            # inserts one by one with the index's own.
            batch = [random_triple(rng) for _ in range(40)]
            graph.addAll(batch)
            for t in batch:
                ref.setdefault(t, None)
        if step % 5 == 0:
            for _ in range(3):
                check_lookups_against_match(graph, *lookup_terms(rng, ref))
            paths |= index_paths([graph._index])
    if index_constants:
        assert paths == {"folded", "list rows"}


def test_lookups_of_unknown_terms_are_empty():
    g = Graph().add(Triple(S, P, Literal("a")))
    assert list(g.subjects(predicate=UNSEEN)) == []
    assert list(g.subjects(P, UNSEEN)) == []
    assert list(g.predicates(subject=UNSEEN)) == []
    assert list(g.predicates(S, UNSEEN)) == []
    assert list(g.objects(subject=UNSEEN)) == []
    assert list(g.objects(UNSEEN, P)) == []
    assert list(g.predicate_objects(UNSEEN)) == []
    # Known terms in a combination no triple has.
    assert list(g.objects(P, S)) == []


def test_lookups_treat_an_empty_iri_as_a_term():
    empty = NamedNode("")
    g = Graph().add(Triple(empty, empty, empty)).add(Triple(S, P, Literal("b")))
    assert list(g.subjects(object=empty)) == [empty]
    assert list(g.predicates(subject=empty)) == [empty]
    assert list(g.objects(empty, empty)) == [empty]
    assert list(g.predicate_objects(empty)) == [(empty, empty)]


def test_lookups_without_arguments_are_distinct_term_lists():
    other = NamedNode("http://e/other")
    g = Graph().add(Triple(S, P, Literal("a"))).add(Triple(other, P, S))
    g.add(Triple(S, P, Literal("b")))
    assert g.subjects() == [S, other]
    assert g.predicates() == [P]
    assert g.objects() == [S, Literal("a"), Literal("b")]


LOOKUPS = [
    lambda g: g.subjects(predicate=P),
    lambda g: g.predicates(subject=S),
    lambda g: g.objects(subject=S),
    lambda g: g.predicate_objects(S),
    lambda g: g.mapped_triples(mark),
]


@pytest.mark.parametrize("lookup", LOOKUPS)
@pytest.mark.parametrize("change", ["add", "remove"])
def test_changing_the_graph_during_a_lookup_raises(lookup, change):
    g = Graph()
    for value in ("a", "b", "c"):
        g.add(Triple(S, P, Literal(value)))
    found = lookup(g)
    next(found)
    if change == "add":
        g.add(Triple(S, P, Literal("d")))
    else:
        g.remove(Triple(S, P, Literal("c")))
    with pytest.raises(RuntimeError):
        next(found)


@pytest.mark.parametrize("lookup", LOOKUPS)
def test_lookups_on_a_view_of_a_removed_graph_raise(lookup):
    name = NamedNode("http://e/g")
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), name))
    ds.add(Quad(S, P, Literal("b"), name))
    (view,) = [g for g in ds.graphs if g.uri == name]
    assert len(list(lookup(view))) == 2
    pending = lookup(view)
    ds.remove_graph(name)
    # The removal freed every term, so these find unknown terms before
    # reaching the index.
    with pytest.raises(RuntimeError):
        list(pending)
    with pytest.raises(RuntimeError):
        list(lookup(view))


def test_predicate_objects_needs_a_subject():
    g = Graph().add(Triple(S, P, Literal("a")))
    with pytest.raises(TypeError, match="predicate_objects needs a subject"):
        g.predicate_objects(None)


def test_object_counts_count_triples_per_object():
    g = Graph()
    for s, o in [(S, "a"), (NamedNode("http://e/t"), "a"), (S, "b")]:
        g.add(Triple(s, P, Literal(o)))
    g.add(Triple(S, NamedNode("http://e/q"), Literal("a")))
    assert g.object_counts() == Counter({Literal("a"): 3, Literal("b"): 1})
    g.remove(Triple(S, P, Literal("b")))
    assert g.object_counts() == Counter({Literal("a"): 3})
    assert Graph().object_counts() == Counter()


def test_view_object_counts_cover_only_its_graph():
    name = NamedNode("http://e/g")
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), None))
    ds.add(Quad(S, P, Literal("a"), name))
    ds.add(Quad(S, P, Literal("b"), name))
    default, named = ds.graphs
    assert default.object_counts() == Counter({Literal("a"): 1})
    assert named.object_counts() == Counter({Literal("a"): 1, Literal("b"): 1})


def test_mapped_triples_never_calls_the_function_for_an_empty_graph():
    def fail(term):
        raise AssertionError(term)

    assert list(Graph().mapped_triples(fail)) == []
    assert list(Dataset().mapped_quads(fail)) == []


def test_mapped_quads_maps_a_shared_term_once_across_graphs():
    blank = BlankNode()
    name = NamedNode("http://e/g")
    ds = Dataset()
    ds.add(Quad(blank, P, Literal("a"), None))
    ds.add(Quad(blank, P, Literal("a"), name))
    ds.add(Quad(S, P, blank, blank))
    fn = CountingMark()
    assert list(ds.mapped_quads(fn)) == [
        (mark(blank), mark(P), mark(Literal("a")), None),
        (mark(blank), mark(P), mark(Literal("a")), mark(name)),
        (mark(S), mark(P), mark(blank), mark(blank)),
    ]
    assert set(fn.calls.values()) == {1}


@pytest.mark.parametrize("change", ["add", "remove"])
def test_changing_the_dataset_during_mapped_quads_raises(change):
    ds = Dataset()
    for value in ("a", "b", "c"):
        ds.add(Quad(S, P, Literal(value), None))
    found = ds.mapped_quads(mark)
    next(found)
    if change == "add":
        ds.add(Quad(S, P, Literal("d"), None))
    else:
        ds.remove(Quad(S, P, Literal("c"), None))
    with pytest.raises(RuntimeError):
        next(found)


GA, GB, GC = (NamedNode("http://e/" + name) for name in ("A", "B", "C"))


def view_of(ds, name):
    (view,) = [g for g in ds.graphs if g.uri == name]
    return view


# Each changes graph GB, or adds graph GC, never the graph a reader is in.
OTHER_GRAPH_CHANGES = {
    "add": lambda ds: ds.add(Quad(S, P, Literal("new"), GB)),
    "add to a new graph": lambda ds: ds.add(Quad(S, P, Literal("new"), GC)),
    "remove": lambda ds: ds.remove(Quad(S, P, Literal("b1"), GB)),
    "removeMatches": lambda ds: ds.removeMatches(graph=GB),
    "add_graph": lambda ds: ds.add_graph(
        Graph().add(Triple(S, P, Literal("new"))), named=GB
    ),
    "add_graph new": lambda ds: ds.add_graph(Graph(), named=GC),
    "remove_graph": lambda ds: ds.remove_graph(GB),
    "view add": lambda ds: view_of(ds, GB).add(Triple(S, P, Literal("new"))),
    "view remove": lambda ds: view_of(ds, GB).remove(Triple(S, P, Literal("b1"))),
    "view removeMatches": lambda ds: view_of(ds, GB).removeMatches(),
}

DATASET_READERS = {
    "iter": iter,
    "match": lambda ds: ds.match(),
    "match predicate": lambda ds: ds.match(predicate=P),
    "mapped_quads": lambda ds: ds.mapped_quads(mark),
}


def three_graph_dataset():
    """Two quads in each of the default graph, GB and GA, walked in that
    order."""
    ds = Dataset()
    for name, prefix in ((None, "d"), (GB, "b"), (GA, "a")):
        for n in (1, 2):
            ds.add(Quad(S, P, Literal(prefix + str(n)), name))
    return ds


@pytest.mark.parametrize("change", OTHER_GRAPH_CHANGES)
@pytest.mark.parametrize("read", DATASET_READERS)
@pytest.mark.parametrize("walked", [1, 5], ids=["before GB", "past GB"])
def test_changing_another_graph_during_dataset_iteration_raises(read, change, walked):
    ds = three_graph_dataset()
    it = DATASET_READERS[read](ds)
    for _ in range(walked):
        next(it)
    OTHER_GRAPH_CHANGES[change](ds)
    with pytest.raises(RuntimeError, match="Dataset changed during iteration"):
        next(it)


@pytest.mark.parametrize("read", DATASET_READERS)
def test_re_adding_a_present_quad_during_dataset_iteration_is_no_change(read):
    ds = three_graph_dataset()
    it = DATASET_READERS[read](ds)
    next(it)
    ds.add(Quad(S, P, Literal("b1"), GB))
    view_of(ds, GB).add(Triple(S, P, Literal("b2")))
    assert len(list(it)) == 5


@pytest.mark.parametrize("read", ["iter", "mapped_quads"])
def test_a_term_freed_and_reused_during_dataset_iteration_is_never_read(read):
    # Emptying GA, already walked, compacts the dictionary; the next add
    # reuses a freed id, which a reader in GB must not go on to read.
    ds = Dataset()
    for i in range(10):
        ds.add(Quad(NamedNode(f"http://e/a{i}"), P, Literal(f"a{i}"), GA))
    ds.add(Quad(S, P, Literal("b1"), GB))
    ds.add(Quad(S, P, Literal("b2"), GB))
    ds.add(Quad(S, P, Literal("c"), GC))
    it = DATASET_READERS[read](ds)
    for _ in range(11):
        next(it)
    ds.removeMatches(graph=GA)
    assert ds._dictionary._free
    ds.add(Quad(S, P, Literal("new"), GC))
    with pytest.raises(RuntimeError, match="Dataset changed during iteration"):
        next(it)


def test_a_dataset_and_its_views_share_one_lock():
    ds = three_graph_dataset()
    assert all(view._lock is ds._lock for view in ds.graphs)
    assert Graph()._lock is not Graph()._lock


needs_threads = pytest.mark.skipif(
    sys.platform == "emscripten", reason="Pyodide cannot start threads"
)


def finishes(call):
    """Run call in a thread and say whether it finished: a call that waits
    on a lock it already holds never does."""
    done = []
    thread = threading.Thread(target=lambda: done.append(call()), daemon=True)
    thread.start()
    thread.join(timeout=10)
    return bool(done)


@needs_threads
@pytest.mark.parametrize("target", [GB, GC])
def test_add_graph_reads_a_view_of_the_same_dataset(target):
    ds = three_graph_dataset()
    assert finishes(lambda: ds.add_graph(view_of(ds, GB), named=target))
    assert {q for q in ds if q.graph == target} == {
        Quad(S, P, Literal("b1"), target),
        Quad(S, P, Literal("b2"), target),
    }


@needs_threads
def test_add_all_reads_this_graph_or_a_view_of_the_same_dataset():
    g = Graph().add(Triple(S, P, Literal("a")))
    assert finishes(lambda: g.addAll(g))
    assert list(g) == [Triple(S, P, Literal("a"))]
    ds = three_graph_dataset()
    view = view_of(ds, GA)
    assert finishes(lambda: view.addAll(view_of(ds, GB)))
    assert finishes(lambda: ds.addAll(Quad(*t, GC) for t in view))
    assert {q.object for q in ds.match(graph=GC)} == {
        Literal(v) for v in ("a1", "a2", "b1", "b2")
    }


def test_add_all_adds_a_stream_longer_than_a_batch():
    triples = [Triple(S, P, Literal(str(i))) for i in range(2500)]
    assert list(Graph().addAll(iter(triples))) == triples
    quads = [Quad(*t, GA) for t in triples]
    assert list(Dataset().addAll(iter(quads))) == quads


def test_add_all_keeps_the_triples_before_a_bad_one():
    g = Graph()
    with pytest.raises(TypeError, match="a Graph holds triples; use a Dataset"):
        g.addAll([Triple(S, P, Literal("a")), Quad(S, P, Literal("b"), GA)])
    assert list(g) == [Triple(S, P, Literal("a"))]


GAP_READERS = {
    "iter": lambda g, a, b, c: iter(g),
    "match": lambda g, a, b, c: g.match(a),
    "mapped_triples": lambda g, a, b, c: (
        tuple(m[1] for m in t) for t in g.mapped_triples(mark)
    ),
    "objects": lambda g, a, b, c: ((a, b, o) for o in g.objects(a, b)),
    "predicate_objects": lambda g, a, b, c: (
        (a, p, o) for p, o in g.predicate_objects(a)
    ),
    "subjects": lambda g, a, b, c: ((s, b, c) for s in g.subjects(b, c)),
    "dataset iter": lambda ds, a, b, c: (q[:3] for q in ds),
    "dataset match": lambda ds, a, b, c: (q[:3] for q in ds.match(a)),
    "mapped_quads": lambda ds, a, b, c: (
        tuple(m[1] for m in q[:3]) for q in ds.mapped_quads(mark)
    ),
}


@pytest.mark.parametrize("read", GAP_READERS)
def test_a_change_between_the_index_and_the_terms_never_misnames(monkeypatch, read):
    # Another thread's remove, compaction and reuse of the freed ids can
    # run after the index hands a read its checked ids and before the read
    # turns them into terms. The read must still name the triple it read.
    from pymantic.triple_index import TripleIndex

    a, b, c = (NamedNode(f"http://e/gap-{x}") for x in "abc")
    new = Triple(*(NamedNode(f"http://e/new-{x}") for x in "def"))
    target = Dataset() if read.startswith(("dataset", "mapped_quads")) else Graph()
    if isinstance(target, Dataset):
        target.add(Quad(a, b, c, None))
    else:
        target.add(Triple(a, b, c))
    graph = target if isinstance(target, Graph) else view_of(target, None)

    def change():
        graph.removeMatches()
        graph.add(new)
        assert {graph._dictionary.lookup(t) for t in new} == {0, 1, 2}

    def with_gap(method):
        def read_with_gap(self, *args):
            for ids in method(self, *args):
                if not done:
                    done.append(True)
                    change()
                yield ids

        return read_with_gap

    done = []
    monkeypatch.setattr(TripleIndex, "match", with_gap(TripleIndex.match))
    monkeypatch.setattr(TripleIndex, "__iter__", with_gap(TripleIndex.__iter__))
    found = GAP_READERS[read](target, a, b, c)
    assert next(found) == (a, b, c)
    with pytest.raises(RuntimeError, match="changed during iteration"):
        next(found)


class SourceError(Exception):
    pass


def failing_after(items, count):
    """Yield the first `count` items, then raise, as a parser does at a
    syntax error part way through a stream."""
    yield from items[:count]
    raise SourceError(count)


@pytest.mark.parametrize("count", [0, 5, 1024, 1500, 2048])
def test_add_all_keeps_what_a_failing_source_produced(count):
    triples = [Triple(S, P, Literal(str(i))) for i in range(3000)]
    g = Graph()
    with pytest.raises(SourceError):
        g.addAll(failing_after(triples, count))
    assert list(g) == triples[:count]
    quads = [Quad(*t, GA) for t in triples]
    ds = Dataset()
    with pytest.raises(SourceError):
        ds.addAll(failing_after(quads, count))
    assert list(ds) == quads[:count]


def test_dataset_add_all_rejects_a_triple():
    ds = Dataset()
    with pytest.raises(TypeError, match="a Dataset holds quads"):
        ds.addAll([Quad(S, P, Literal("a"), GA), Triple(S, P, Literal("b"))])
    assert list(ds) == [Quad(S, P, Literal("a"), GA)]


def test_add_all_raises_the_source_error_when_the_partial_batch_fails_too():
    # The partial batch holds a quad, which the Graph refuses; the source's
    # own error is still the one raised, with the refusal as its context.
    items = [Triple(S, P, Literal("a")), Quad(S, P, Literal("b"), GA)]
    g = Graph()
    with pytest.raises(SourceError) as raised:
        g.addAll(failing_after(items, 2))
    assert isinstance(raised.value.__context__, TypeError)
    assert list(g) == [Triple(S, P, Literal("a"))]
