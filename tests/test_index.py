import gc
import pathlib
import pytest
import random
import sys

from pymantic.adjacency_index import AdjacencyTripleIndex
import pymantic.primitives
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
from pymantic.triple_index import TripleIndex

# Every implementation of the triple index interface; each test here runs
# once per entry, with Graph and Dataset building that index.
INDEXES = [
    TripleIndex,
    AdjacencyTripleIndex,
]


@pytest.fixture(autouse=True, params=INDEXES, ids=lambda cls: cls.__name__)
def index_class(request, monkeypatch):
    monkeypatch.setattr(pymantic.primitives, "TripleIndex", request.param)
    return request.param


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


@pytest.mark.parametrize("seed", range(10))
def test_graph_agrees_with_a_reference_model(seed):
    rng = random.Random(seed)
    graph = Graph()
    # A dict used as an ordered set: re-adding after a remove moves to the end.
    ref = {}
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
            # A batch past the merge threshold, so the next query re-sorts.
            batch = [random_triple(rng) for _ in range(40)]
            graph.addAll(batch)
            for t in batch:
                ref.setdefault(t, None)
        check_against_reference(graph, ref, rng)
        assert len(graph._dictionary) <= 6 * len(graph)


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
    with pytest.raises(TypeError, match="parse N-Quads into a Dataset"):
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


@pytest.mark.parametrize("seed", range(10))
def test_dataset_agrees_with_a_reference_model(seed):
    rng = random.Random(seed)
    ds = Dataset()
    ref = {}
    names = set()

    def add(q):
        ref.setdefault(q, None)
        if q.graph is not None:
            names.add(q.graph)

    for _ in range(1000):
        roll = rng.random()
        if roll < 0.4:
            q = random_quad(rng)
            ds.add(q)
            add(q)
        elif roll < 0.65:
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
        elif roll < 0.8:
            s, p, o = random_quad_pattern(rng, ref)
            graph = rng.choice(DS_GRAPHS)
            assert ds.removeMatches(s, p, o, graph) is ds
            for q in matching_quads(ref, s, p, o, graph):
                del ref[q]
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
            # A batch past the merge threshold, so the next query re-sorts.
            batch = [random_quad(rng) for _ in range(40)]
            ds.addAll(batch)
            for q in batch:
                add(q)
        check_dataset_against_reference(ds, ref, names, rng)


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
