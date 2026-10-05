import gc
import pathlib
import pytest
import random
import sys

from pymantic import triple_index
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


def check_dataset_against_reference(ds, ref, names, rng):
    assert len(ds) == len(ref)
    # The running count compaction reads, against the indexes themselves.
    assert ds._quad_count == sum(len(index) for index in ds._graphs.values())
    quads = list(ds)
    assert len(quads) == len(ref)
    assert set(quads) == set(ref)
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


def test_view_remove_of_an_absent_triple_leaves_the_dataset_unchanged():
    name = NamedNode("http://e/g")
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), name))
    ds.add(Quad(S, P, Literal("b"), None))
    (view,) = [g for g in ds.graphs if g.uri == name]
    # Every term is known to the dataset, but the triple is not in this graph.
    with pytest.raises(KeyError):
        view.remove(Triple(S, P, Literal("b")))
    assert ds._quad_count == 2
    assert len(view) == 1
    view.remove(Triple(S, P, Literal("a")))
    assert ds._quad_count == 1


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


@pytest.mark.parametrize(
    "item",
    [
        "x",
        (1, 2),
        (S, P, Literal("a"), S),
        ([], P, Literal("a")),
        Triple(S, P, Literal("a")),
    ],
    ids=["string", "pair", "four-tuple", "unhashable-term", "triple"],
)
def test_membership_on_a_view_of_a_removed_graph_raises_for_any_item(item):
    name = NamedNode("http://e/g")
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), name))
    (view,) = [g for g in ds.graphs if g.uri == name]
    ds.remove_graph(name)
    with pytest.raises(RuntimeError):
        item in view


REMOVED_VIEW_USES = {
    "add": lambda v: v.add(Triple(S, P, Literal("b"))),
    "add-wrong-shape": lambda v: v.add((S, P)),
    "addAll-empty-list": lambda v: v.addAll([]),
    "addAll-empty-graph": lambda v: v.addAll(Graph()),
    "addAll-empty-generator": lambda v: v.addAll(t for t in ()),
    "addAll-triples": lambda v: v.addAll([Triple(S, P, Literal("b"))]),
    "remove": lambda v: v.remove(Triple(S, P, Literal("a"))),
    "remove-unknown": lambda v: v.remove(Triple(S, P, Literal("nowhere"))),
    "remove-wrong-shape": lambda v: v.remove((S, P)),
    "removeMatches-all": lambda v: v.removeMatches(),
    "removeMatches-no-match": lambda v: v.removeMatches(S, P, Literal("nowhere")),
    "removeMatches-unknown": lambda v: v.removeMatches(UNSEEN),
    "match-all": lambda v: list(v.match()),
    "match-unknown": lambda v: list(v.match(UNSEEN)),
    "match-no-match": lambda v: list(v.match(S, P, Literal("nowhere"))),
    "subjects": lambda v: list(v.subjects()),
    "predicates": lambda v: list(v.predicates()),
    "objects": lambda v: list(v.objects()),
    "iter": lambda v: list(v),
    "len": lambda v: len(v),
    "contains-triple": lambda v: Triple(S, P, Literal("a")) in v,
    "contains-unknown": lambda v: Triple(UNSEEN, P, Literal("a")) in v,
    "contains-string": lambda v: "x" in v,
    "contains-pair": lambda v: (1, 2) in v,
    "contains-unhashable": lambda v: ([], P, Literal("a")) in v,
    "toArray": lambda v: v.toArray(),
    "merge-empty-graph": lambda v: v.merge(Graph()),
    "merge-empty-list": lambda v: v.merge([]),
}


@pytest.mark.parametrize("use", REMOVED_VIEW_USES.values(), ids=REMOVED_VIEW_USES)
@pytest.mark.parametrize("keeps_terms", [False, True], ids=["emptied", "terms-kept"])
def test_every_use_of_a_removed_graphs_view_raises(use, keeps_terms):
    name = NamedNode("http://e/g")
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), name))
    if keeps_terms:
        # Another graph keeps the terms known to the dataset's dictionary.
        ds.add(Quad(S, P, Literal("a"), NamedNode("http://e/other")))
    (view,) = [g for g in ds.graphs if g.uri == name]
    ds.remove_graph(name)
    with pytest.raises(RuntimeError):
        use(view)


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


@pytest.mark.parametrize("read", ["iter"])
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


def test_dataset_add_all_rejects_a_triple():
    ds = Dataset()
    with pytest.raises(TypeError, match="a Dataset holds quads"):
        ds.addAll([Quad(S, P, Literal("a"), GA), Triple(S, P, Literal("b"))])
    assert list(ds) == [Quad(S, P, Literal("a"), GA)]


def test_a_statement_with_an_unhashable_term_is_not_contained():
    # No graph can hold an unhashable term, so `in` answers False as it
    # does for anything else that is not a statement.
    g = Graph().add(Triple(S, P, Literal("a")))
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), GA))
    assert ((S, P, ["a"]) in g) is False
    assert (([], P, Literal("a")) in ds) is False
    assert ((S, P, Literal("a"), {}) in ds) is False
    assert ((S, {}, Literal("a"), GA) in ds) is False


def test_membership_on_a_view_of_a_removed_graph_raises_whatever_the_term():
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), GA))
    view = view_of(ds, GA)
    ds.remove_graph(GA)
    with pytest.raises(RuntimeError):
        (S, P, ["a"]) in view
    with pytest.raises(RuntimeError):
        ({}, P, Literal("a")) in view


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


# Changes to the graph a dataset read walks first, beside those to others.
DATASET_CHANGES = {
    **OTHER_GRAPH_CHANGES,
    "add to the default graph": lambda ds: ds.add(Quad(S, P, Literal("new"), None)),
    "remove from the default graph": lambda ds: ds.remove(
        Quad(S, P, Literal("d1"), None)
    ),
    "removeMatches in the default graph": lambda ds: ds.removeMatches(graph=None),
}


@pytest.mark.parametrize("change", DATASET_CHANGES)
@pytest.mark.parametrize("read", DATASET_READERS)
def test_a_dataset_read_raises_if_the_dataset_changed_after_the_call(read, change):
    ds = three_graph_dataset()
    it = DATASET_READERS[read](ds)
    DATASET_CHANGES[change](ds)
    with pytest.raises(RuntimeError):
        next(it)


# Each takes the quad (S, P, "b1", GB) away or puts (S, P, "b1") in GA.
B1_CHANGES = {
    "remove": lambda ds: ds.remove(Quad(S, P, Literal("b1"), GB)),
    "removeMatches": lambda ds: ds.removeMatches(graph=GB),
    "remove_graph": lambda ds: ds.remove_graph(GB),
    "view remove": lambda ds: view_of(ds, GB).remove(Triple(S, P, Literal("b1"))),
    "add": lambda ds: ds.add(Quad(S, P, Literal("b1"), GA)),
}


@pytest.mark.parametrize("change", B1_CHANGES)
def test_a_fully_bound_dataset_match_answers_as_of_the_call(change):
    ds = three_graph_dataset()
    in_gb = ds.match(S, P, Literal("b1"), GB)
    anywhere = ds.match(S, P, Literal("b1"))
    absent = ds.match(S, P, Literal("b1"), GA)
    B1_CHANGES[change](ds)
    assert list(in_gb) == [Quad(S, P, Literal("b1"), GB)]
    assert list(anywhere) == [Quad(S, P, Literal("b1"), GB)]
    assert list(absent) == []


S2 = NamedNode("http://e/s2")


def split_subject_dataset():
    """As three_graph_dataset, but GB's and GA's quads have subject S2, so
    one removeMatches changes both graphs and not the default graph."""
    ds = Dataset()
    for name, prefix, subject in ((None, "d", S), (GB, "b", S2), (GA, "a", S2)):
        for n in (1, 2):
            ds.add(Quad(subject, P, Literal(prefix + str(n)), name))
    return ds


# Each changes nothing: every quad it adds is present, and nothing it
# names to remove is.
DIRECT_NO_CHANGES = {
    "add": lambda ds: ds.add(Quad(S2, P, Literal("b1"), GB)),
    "removeMatches": lambda ds: ds.removeMatches(subject=S2, graph=None, object=S),
    "add_graph": lambda ds: ds.add_graph(
        Graph().add(Triple(S2, P, Literal("b1"))), named=GB
    ),
    "addAll": lambda ds: ds.addAll(
        [Quad(S2, P, Literal("b1"), GB), Quad(S, P, Literal("d2"), None)]
    ),
}


@pytest.mark.parametrize("change", DIRECT_NO_CHANGES)
@pytest.mark.parametrize("read", DATASET_READERS)
def test_a_dataset_read_goes_on_past_a_direct_call_that_changes_nothing(read, change):
    ds = split_subject_dataset()
    reader = DATASET_READERS[read](ds)
    next(reader)
    DIRECT_NO_CHANGES[change](ds)
    assert len(list(reader)) == 5


# Each reads only GA, whose two quads three_graph_dataset adds last.
GA_READERS = {
    "match graph": lambda ds: ds.match(graph=GA),
    "match predicate graph": lambda ds: ds.match(predicate=P, graph=GA),
    "view iter": lambda ds: iter(view_of(ds, GA)),
    "view match": lambda ds: view_of(ds, GA).match(),
    "view match subject": lambda ds: view_of(ds, GA).match(S),
}


@pytest.mark.parametrize("change", OTHER_GRAPH_CHANGES)
@pytest.mark.parametrize("read", GA_READERS)
def test_a_read_of_one_graph_goes_on_past_a_change_to_another(read, change):
    # A graph's reads watch only that graph; reads of the whole dataset
    # watch every graph.
    expected = list(GA_READERS[read](three_graph_dataset()))
    ds = three_graph_dataset()
    graph_read = GA_READERS[read](ds)
    dataset_read = iter(ds)
    first = next(graph_read)
    next(dataset_read)
    OTHER_GRAPH_CHANGES[change](ds)
    assert [first, *graph_read] == expected
    with pytest.raises(RuntimeError, match="Dataset changed during iteration"):
        next(dataset_read)


def raises_key_error(call):
    with pytest.raises(KeyError):
        call()


# Each changes nothing in split_subject_dataset: it adds only what is
# present, or fails, or names nothing to remove.
CALLS_THAT_CHANGE_NOTHING = {
    "add_graph of an empty graph onto a graph": lambda ds: ds.add_graph(
        Graph(), named=GB
    ),
    "remove of an absent quad": lambda ds: raises_key_error(
        lambda: ds.remove(Quad(S2, P, Literal("a1"), GB))
    ),
    "remove from a missing graph": lambda ds: raises_key_error(
        lambda: ds.remove(Quad(S2, P, Literal("a1"), GC))
    ),
    "removeMatches of a missing graph": lambda ds: ds.removeMatches(graph=GC),
    "view add of a present triple": lambda ds: view_of(ds, GB).add(
        Triple(S2, P, Literal("b1"))
    ),
    "view addAll of present triples": lambda ds: view_of(ds, GB).addAll(
        [Triple(S2, P, Literal("b1")), Triple(S2, P, Literal("b2"))]
    ),
    "view remove of an absent triple": lambda ds: raises_key_error(
        lambda: view_of(ds, GB).remove(Triple(S2, P, Literal("a1")))
    ),
    "view removeMatches matching nothing": lambda ds: view_of(ds, GB).removeMatches(S),
}


@pytest.mark.parametrize("change", CALLS_THAT_CHANGE_NOTHING)
@pytest.mark.parametrize("read", DATASET_READERS)
def test_a_dataset_read_goes_on_past_any_call_that_changes_nothing(read, change):
    ds = split_subject_dataset()
    reader = DATASET_READERS[read](ds)
    next(reader)
    CALLS_THAT_CHANGE_NOTHING[change](ds)
    assert len(list(reader)) == 5


@pytest.mark.parametrize("read", DATASET_READERS)
def test_a_removed_graph_and_an_add_graph_source_never_end_a_dataset_read(read):
    # Neither is part of the dataset any more: the removed graph's view
    # refuses every change, and add_graph copied the source.
    ds = split_subject_dataset()
    source = Graph().add(Triple(S2, P, Literal("c1")))
    ds.add_graph(source, named=GC)
    removed = view_of(ds, GB)
    ds.remove_graph(GB)
    reader = DATASET_READERS[read](ds)
    next(reader)
    for change in (
        lambda: removed.add(Triple(S2, P, Literal("new"))),
        lambda: removed.addAll([Triple(S2, P, Literal("new"))]),
        lambda: removed.remove(Triple(S2, P, Literal("b1"))),
        lambda: removed.removeMatches(),
    ):
        with pytest.raises(RuntimeError):
            change()
    source.add(Triple(S2, P, Literal("c2")))
    source.remove(Triple(S2, P, Literal("c1")))
    source.removeMatches()
    assert len(list(reader)) == 4


class NamedTriples(list):
    """Triples with a name, as add_graph reads a graph: by iterating it
    and reading its `uri`. A Graph cannot hold an unhashable term, so this
    is how one reaches add_graph."""

    def __init__(self, uri, triples):
        super().__init__(triples)
        self.uri = uri


# Each puts one statement with the unhashable term [] in the graph GB, or
# in the default graph for a name of None.
FAILING_ADDS = {
    "add": lambda ds, stmt, name: ds.add(Quad(*stmt, name)),
    "addAll": lambda ds, stmt, name: ds.addAll([Quad(*stmt, name)]),
    "add_graph": lambda ds, stmt, name: ds.add_graph(NamedTriples(name, [stmt])),
    "view-add": lambda ds, stmt, name: view_of(ds, name).add(stmt),
    "view-addAll": lambda ds, stmt, name: view_of(ds, name).addAll([stmt]),
}
UNHASHABLE_STATEMENTS = {
    "subject": ([], P, Literal("x")),
    "predicate": (S, [], Literal("x")),
    "object": (S, P, []),
}


# A view's graph exists, so views add only to an existing graph.
FAILING_ADD_CASES = [
    pytest.param(add, exists, id="%s-%s" % (name, "existing" if exists else "new"))
    for name, add in FAILING_ADDS.items()
    for exists in (False, True)
    if exists or not name.startswith("view")
]


@pytest.mark.parametrize("add, graph_exists", FAILING_ADD_CASES)
@pytest.mark.parametrize(
    "stmt", UNHASHABLE_STATEMENTS.values(), ids=UNHASHABLE_STATEMENTS
)
def test_a_failed_dataset_add_leaves_no_graph_behind(add, graph_exists, stmt):
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), GA))
    if graph_exists:
        ds.add(Quad(S, P, Literal("b"), GB))
    names = [g.uri for g in ds.graphs]
    quads = list(ds)
    version = ds._changes.version
    with pytest.raises(TypeError):
        add(ds, stmt, GB)
    assert [g.uri for g in ds.graphs] == names
    assert len(ds) == len(quads)
    assert list(ds) == quads
    assert ds._changes.version == version


@pytest.mark.parametrize(
    "add", [FAILING_ADDS["add"], FAILING_ADDS["addAll"]], ids=["add", "addAll"]
)
def test_a_dataset_add_with_an_unhashable_graph_name_creates_nothing(add):
    ds = Dataset()
    ds.add(Quad(S, P, Literal("a"), GA))
    version = ds._changes.version
    with pytest.raises(TypeError):
        add(ds, (S, P, Literal("x")), [])
    assert [g.uri for g in ds.graphs] == [None, GA]
    assert list(ds) == [Quad(S, P, Literal("a"), GA)]
    assert ds._changes.version == version


def test_a_failed_batched_add_keeps_the_quads_before_it_and_no_empty_graph():
    # The quads before the bad one are added, as adding them one by one
    # would; the bad quad's graph, new to the dataset, is not.
    ds = Dataset()
    with pytest.raises(TypeError):
        ds.addAll([Quad(S, P, Literal("a"), GA), Quad(S, P, [], GB)])
    assert [g.uri for g in ds.graphs] == [None, GA]
    assert list(ds) == [Quad(S, P, Literal("a"), GA)]
    assert len(ds) == 1
