import gc
import pytest
import random
import sys

from pymantic.primitives import (
    XSD_STRING,
    BlankNode,
    Graph,
    Literal,
    NamedNode,
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
