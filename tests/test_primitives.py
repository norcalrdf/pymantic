import pytest
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


def test_to_curie_only_shrinks_leading_namespace():
    from pymantic.primitives import to_curie

    namespaces = {"ex": "http://example.com/"}
    assert (
        to_curie("http://example.com/a?u=http://example.com/b", namespaces)
        == "ex:a?u=http://example.com/b"
    )
    assert to_curie("http://other.example/a", namespaces) == "http://other.example/a"


def ordered_triples(n=3):
    return [
        Triple(
            NamedNode("http://example.com/s%d" % i),
            NamedNode("http://example.com/p"),
            NamedNode("http://example.com/o"),
        )
        for i in range(n)
    ]


def test_graph_iterates_in_insertion_order():
    triples = ordered_triples(20)
    g = Graph()
    for t in reversed(triples):
        g.add(t)
    assert list(g) == list(reversed(triples))
    assert list(g.match(None, None, None)) == list(reversed(triples))


def test_graph_readding_a_triple_keeps_its_position():
    a, b, c = ordered_triples(3)
    g = Graph().add(a).add(b).add(c).add(a)
    assert list(g) == [a, b, c]
    assert len(g) == 3


def test_graph_remove_keeps_order_of_the_rest():
    a, b, c = ordered_triples(3)
    g = Graph().add(a).add(b).add(c)
    g.remove(b)
    assert list(g) == [a, c]
    assert b not in g
    assert g.toArray() == frozenset((a, c))
    g.add(b)
    assert list(g) == [a, c, b]


def test_graph_merge_keeps_argument_then_self_order():
    a, b, c = ordered_triples(3)
    merged = Graph().add(c).merge(Graph().add(a).add(b))
    assert list(merged) == [a, b, c]


def test_dataset_iterates_in_insertion_order_within_a_graph():
    graph_name = NamedNode("http://example.com/g")
    quads = [
        Quad(t.subject, t.predicate, t.object, graph_name)
        for t in reversed(ordered_triples(20))
    ]
    ds = Dataset()
    for quad in quads:
        ds.add(quad)
    assert list(ds) == quads
    assert list(ds.match()) == quads


def test_literal_language_tag_is_lowercased():
    """RDF 1.2 Concepts: language tags compare ASCII case-insensitively and
    may be case normalized; RDF 1.1 Concepts: their value space is lowercase.
    Normalizing on construction makes Literal("x", "EN") and Literal("x", "en")
    the same term, as the specs require."""
    assert Literal("chat", "EN-Gb").language == "en-gb"
    assert Literal("chat", "EN") == Literal("chat", "en")
    assert hash(Literal("chat", "EN")) == hash(Literal("chat", "en"))
    assert Literal("chat", "en")._replace(language="FR").language == "fr"
    assert Literal._make(("chat", "FR", None)).language == "fr"
    assert Literal("chat").language is None
    assert Literal("chat", "EN").toNT() == '"chat"@en'


def test_parsers_lowercase_language_tags():
    from pymantic.parsers import ntriples_parser, turtle_parser

    (triple,) = list(ntriples_parser.parse('<http://x/s> <http://x/p> "chat"@EN .'))
    assert triple.object == Literal("chat", "en")
    (triple,) = list(turtle_parser.parse('<http://x/s> <http://x/p> "chat"@EN-US .'))
    assert triple.object == Literal("chat", "en-us")


def test_literal_normalizes_datatype_on_construction():
    """RDF 1.1 Concepts 3.3: every literal has a datatype IRI. A simple
    literal is syntactic sugar for one typed xsd:string, and a
    language-tagged string always has the datatype rdf:langString."""
    from pymantic.primitives import RDF_LANGSTRING, XSD_STRING

    assert Literal("v").datatype == XSD_STRING
    assert Literal("v").language is None
    assert Literal("v", datatype=XSD_STRING).datatype == XSD_STRING
    assert Literal("v", "en").datatype == RDF_LANGSTRING
    assert Literal("v", "en", RDF_LANGSTRING).language == "en"
    assert Literal("42", datatype=NamedNode("http://x/dt")).datatype == NamedNode(
        "http://x/dt"
    )


def test_literal_equality_across_the_two_string_forms():
    """The two ways of writing a simple literal are one RDF term, so they
    are equal and hash alike."""
    from pymantic.primitives import XSD_STRING

    assert Literal("v") == Literal("v", datatype=XSD_STRING)
    assert hash(Literal("v")) == hash(Literal("v", datatype=XSD_STRING))
    assert len({Literal("v"), Literal("v", datatype=XSD_STRING)}) == 1
    assert Literal("v") != Literal("v", "en")


def test_literal_rejects_a_language_with_a_foreign_datatype():
    """Literals may not have both a datatype and a language."""
    with pytest.raises(ValueError):
        Literal("v", "en", NamedNode("http://www.w3.org/2001/XMLSchema#string"))
    with pytest.raises(ValueError):
        Literal._make(("v", "en", NamedNode("http://x/dt")))
    with pytest.raises(ValueError):
        Literal("v", datatype=NamedNode("http://x/dt"))._replace(language="en")


def test_literal_replace_keeps_normalization():
    from pymantic.primitives import RDF_LANGSTRING, XSD_STRING

    assert Literal("v")._replace(value="w").datatype == XSD_STRING
    assert Literal("v")._replace(language="EN").datatype == RDF_LANGSTRING
    assert Literal("v", "en")._replace(value="w").language == "en"
    assert Literal("v", "en")._replace(language=None).datatype == XSD_STRING
    assert Literal._make(("v", None, None)).datatype == XSD_STRING


def test_literal_rejects_langstring_without_a_language():
    """rdf:langString is ill-formed without a language tag, so it may not be
    given as a datatype on its own."""
    from pymantic.primitives import RDF_LANGSTRING

    with pytest.raises(ValueError):
        Literal("v", datatype=RDF_LANGSTRING)
    with pytest.raises(ValueError):
        Literal._make(("v", None, RDF_LANGSTRING))


def test_literal_normalization_writes_no_implicit_datatype():
    from pymantic.primitives import XSD_STRING

    assert Literal("v").toNT() == '"v"'
    assert Literal("v", datatype=XSD_STRING).toNT() == '"v"'
    assert Literal("v", "en").toNT() == '"v"@en'


def test_graph_holds_one_triple_for_the_two_string_forms():
    from pymantic.primitives import XSD_STRING

    s, p = NamedNode("http://x/s"), NamedNode("http://x/p")
    g = Graph()
    g.add(Triple(s, p, Literal("v")))
    g.add(Triple(s, p, Literal("v", datatype=XSD_STRING)))
    assert len(g) == 1
    assert Triple(s, p, Literal("v")) in g
    assert Triple(s, p, Literal("v", datatype=XSD_STRING)) in g
