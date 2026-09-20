import random

from pymantic.primitives import (
    BlankNode,
    Dataset,
    Graph,
    Literal,
    NamedNode,
    Quad,
    Triple,
    to_curie,
)


def en(s):
    return Literal(s, "en")


def test_to_curie_multi_match():
    """Test that the longest match for prefix is used"""
    namespaces = {"short": "aa", "long": "aaa"}
    curie = to_curie("aaab", namespaces)
    assert curie == "long:b"


def test_simple_add():
    t = Triple(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        en("Never!"),
    )
    g = Graph()
    g.add(t)
    assert t in g


def test_simple_remove():
    t = Triple(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        en("Never!"),
    )
    g = Graph()
    g.add(t)
    g.remove(t)
    assert t not in g


def test_match_VVV_pattern():
    t = Triple(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        en("Never!"),
    )
    g = Graph()
    g.add(t)
    matches = g.match(None, None, None)
    assert t in matches


def test_match_sVV_pattern():
    t = Triple(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        en("Never!"),
    )
    g = Graph()
    g.add(t)
    matches = g.match(NamedNode("http://example.com"), None, None)
    assert t in matches


def test_match_sVo_pattern():
    t = Triple(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        en("Never!"),
    )
    g = Graph()
    g.add(t)
    matches = g.match(NamedNode("http://example.com"), None, en("Never!"))
    assert t in matches


def test_match_spV_pattern():
    t = Triple(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        en("Never!"),
    )
    g = Graph()
    g.add(t)
    matches = g.match(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        None,
    )
    assert t in matches


def test_match_Vpo_pattern():
    t = Triple(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        en("Never!"),
    )
    g = Graph()
    g.add(t)
    matches = g.match(None, NamedNode("http://purl.org/dc/terms/issued"), en("Never!"))
    assert t in matches


def test_match_VVo_pattern():
    t = Triple(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        en("Never!"),
    )
    g = Graph()
    g.add(t)
    matches = g.match(None, None, en("Never!"))
    assert t in matches


def test_match_VpV_pattern():
    t = Triple(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        en("Never!"),
    )
    g = Graph()
    g.add(t)
    matches = g.match(None, NamedNode("http://purl.org/dc/terms/issued"), None)
    assert t in matches


def generate_triples(n=10):
    for i in range(1, n):
        yield Triple(
            NamedNode("http://example/" + str(random.randint(1, 1000))),
            NamedNode("http://example/terms/" + str(random.randint(1, 1000))),
            Literal(random.randint(1, 1000)),
        )


def test_10000_triples():
    n = 10000
    g = Graph()
    for t in generate_triples(n):
        g.add(t)
    assert len(g) > n * 0.9
    g.match(NamedNode("http://example.com/42"), None, None)
    g.match(None, NamedNode("http://example/terms/42"), None)
    g.match(None, None, Literal(42))


def test_iter_10000_triples():
    n = 10000
    g = Graph()
    triples = set()
    for t in generate_triples(n):
        g.add(t)
        triples.add(t)
    assert len(g) > n * 0.9
    for t in g:
        triples.remove(t)
    assert len(triples) == 0


# Dataset Tests


def test_add_quad():
    q = Quad(
        NamedNode("http://example.com/graph"),
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        Literal("Never!"),
    )
    ds = Dataset()
    ds.add(q)
    assert q in ds


def test_remove_quad():
    q = Quad(
        NamedNode("http://example.com/graph"),
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        Literal("Never!"),
    )
    ds = Dataset()
    ds.add(q)
    ds.remove(q)
    assert q not in ds


def test_ds_len():
    n = 10
    ds = Dataset()
    for q in generate_quads(n):
        ds.add(q)
    assert len(ds) == 10


def test_match_ds_sVV_pattern():
    q = Quad(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        Literal("Never!"),
        NamedNode("http://example.com/graph"),
    )
    ds = Dataset()
    ds.add(q)
    matches = ds.match(subject=NamedNode("http://example.com"))
    assert q in matches


def test_match_ds_quad_pattern():
    q = Quad(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        Literal("Never!"),
        NamedNode("http://example.com/graph"),
    )
    ds = Dataset()
    ds.add(q)
    matches = ds.match(graph="http://example.com/graph")
    assert q in matches


def test_add_graph():
    t = Triple(
        NamedNode("http://example.com"),
        NamedNode("http://purl.org/dc/terms/issued"),
        Literal("Never!"),
    )
    g = Graph("http://example.com/graph")
    g.add(t)
    ds = Dataset()
    ds.add_graph(g)
    assert t in ds


def generate_quads(n):
    for i in range(n):
        yield Quad(
            NamedNode("http://example/" + str(random.randint(1, 1000))),
            NamedNode("http://purl.org/dc/terms/" + str(random.randint(1, 100))),
            Literal(random.randint(1, 1000)),
            NamedNode("http://example/graph/" + str(random.randint(1, 1000))),
        )


def test_10000_quads():
    n = 10000
    ds = Dataset()
    for q in generate_quads(n):
        ds.add(q)
    assert len(ds) > n * 0.9
    ds.match(
        subject=NamedNode("http://example.com/42"),
        graph=NamedNode("http://example/graph/42"),
    )


def test_iter_10000_quads():
    n = 10000
    ds = Dataset()
    quads = set()
    for q in generate_quads(n):
        ds.add(q)
        quads.add(q)
    assert len(ds) > n * 0.9
    for quad in ds:
        quads.remove(quad)
    assert len(quads) == 0


def test_interfaceName():
    assert Literal("Bob", "en").interfaceName == "Literal"
    assert NamedNode().interfaceName == "NamedNode"


def test_BlankNode_id():
    b1 = BlankNode()
    b2 = BlankNode()
    assert b1.value != b2.value


def test_BlankNode_label_is_stable_unique_and_not_an_address():
    import gc
    import re

    b1 = BlankNode()
    label = b1.value
    assert b1.value == label
    assert str(b1) == "_:" + label
    assert b1.toNT() == "_:" + label
    # Valid BLANK_NODE_LABEL for both the N-Triples and Turtle grammars.
    assert re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_\-]*", label)
    assert format(id(b1), "x") not in label
    seen = {label}
    for _ in range(100):
        node = BlankNode()
        assert node.value not in seen
        seen.add(node.value)
        del node
        gc.collect()


def test_BlankNode_ntriples_round_trip():
    from io import StringIO

    from pymantic.parsers import ntriples_parser
    from pymantic.serializers import serialize_ntriples

    b = BlankNode()
    p = NamedNode("http://x/p")
    graph = Graph()
    graph.add(Triple(b, p, b))
    f = StringIO()
    serialize_ntriples(graph, f)
    f.seek(0)
    parsed = Graph()
    ntriples_parser.parse(f, parsed)
    (triple,) = list(parsed)
    assert triple.subject.interfaceName == "BlankNode"
    assert triple.subject is triple.object
