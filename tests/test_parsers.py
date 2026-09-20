from io import StringIO
import pytest

from pymantic.parsers import (
    jsonld_parser,
    nquads_parser,
    ntriples_parser,
    turtle_parser,
)
from pymantic.primitives import (
    BlankNode,
    Graph,
    Literal,
    NamedNode,
    Quad,
    Triple,
)
from pymantic.serializers import serialize_nquads


def test_parse_ntriples_named_nodes():
    test_ntriples = """<http://example.com/objects/1> <http://example.com/predicates/1> <http://example.com/objects/2> .
<http://example.com/objects/2> <http://example.com/predicates/2> <http://example.com/objects/1> .
"""
    g = Graph()
    ntriples_parser.parse(StringIO(test_ntriples), g)
    assert len(g) == 2
    assert (
        Triple(
            NamedNode("http://example.com/objects/1"),
            NamedNode("http://example.com/predicates/1"),
            NamedNode("http://example.com/objects/2"),
        )
        in g
    )
    assert (
        Triple(
            NamedNode("http://example.com/objects/2"),
            NamedNode("http://example.com/predicates/2"),
            NamedNode("http://example.com/objects/1"),
        )
        in g
    )


def test_parse_ntriples_bare_literals():
    test_ntriples = """<http://example.com/objects/1> <http://example.com/predicates/1> "Foo" .
<http://example.com/objects/2> <http://example.com/predicates/2> "Bar" .
"""
    g = Graph()
    ntriples_parser.parse(StringIO(test_ntriples), g)
    assert len(g) == 2
    assert (
        Triple(
            NamedNode("http://example.com/objects/1"),
            NamedNode("http://example.com/predicates/1"),
            Literal("Foo"),
        )
        in g
    )
    assert (
        Triple(
            NamedNode("http://example.com/objects/2"),
            NamedNode("http://example.com/predicates/2"),
            Literal("Bar"),
        )
        in g
    )


def test_parse_ntriples_language_literals():
    test_ntriples = """<http://example.com/objects/1> <http://example.com/predicates/1> "Foo"@en-US .
<http://example.com/objects/2> <http://example.com/predicates/2> "Bar"@fr .
"""
    g = Graph()
    ntriples_parser.parse(StringIO(test_ntriples), g)
    assert len(g) == 2
    assert (
        Triple(
            NamedNode("http://example.com/objects/1"),
            NamedNode("http://example.com/predicates/1"),
            Literal("Foo", language="en-US"),
        )
        in g
    )
    assert (
        Triple(
            NamedNode("http://example.com/objects/2"),
            NamedNode("http://example.com/predicates/2"),
            Literal("Bar", language="fr"),
        )
        in g
    )


def test_parse_ntriples_datatyped_literals():
    test_ntriples = """<http://example.com/objects/1> <http://example.com/predicates/1> "Foo"^^<http://www.w3.org/2001/XMLSchema#string> .
<http://example.com/objects/2> <http://example.com/predicates/2> "9.99"^^<http://www.w3.org/2001/XMLSchema#decimal> .
"""
    g = Graph()
    ntriples_parser.parse(StringIO(test_ntriples), g)
    assert len(g) == 2
    assert (
        Triple(
            NamedNode("http://example.com/objects/1"),
            NamedNode("http://example.com/predicates/1"),
            Literal(
                "Foo", datatype=NamedNode("http://www.w3.org/2001/XMLSchema#string")
            ),
        )
        in g
    )
    assert (
        Triple(
            NamedNode("http://example.com/objects/2"),
            NamedNode("http://example.com/predicates/2"),
            Literal(
                "9.99", datatype=NamedNode("http://www.w3.org/2001/XMLSchema#decimal")
            ),
        )
        in g
    )


def test_parse_ntriples_mixed_literals():
    test_ntriples = """<http://example.com/objects/1> <http://example.com/predicates/1> "Foo"@en-US .
<http://example.com/objects/2> <http://example.com/predicates/2> "9.99"^^<http://www.w3.org/2001/XMLSchema#decimal> .
"""
    g = Graph()
    ntriples_parser.parse(StringIO(test_ntriples), g)
    assert len(g) == 2
    assert (
        Triple(
            NamedNode("http://example.com/objects/1"),
            NamedNode("http://example.com/predicates/1"),
            Literal("Foo", language="en-US"),
        )
        in g
    )
    assert (
        Triple(
            NamedNode("http://example.com/objects/2"),
            NamedNode("http://example.com/predicates/2"),
            Literal(
                "9.99", datatype=NamedNode("http://www.w3.org/2001/XMLSchema#decimal")
            ),
        )
        in g
    )


def test_parse_ntriples_bnodes():
    test_ntriples = """<http://example.com/objects/1> <http://example.com/predicates/1> _:A1 .
_:A1 <http://example.com/predicates/2> <http://example.com/objects/1> .
"""
    g = Graph()
    ntriples_parser.parse(StringIO(test_ntriples), g)
    assert len(g) == 2
    # assert Triple(NamedNode('http://example.com/objects/1'),
    # NamedNode('http://example.com/predicates/1'),
    # NamedNode('http://example.com/objects/2')) in g
    # assert Triple(NamedNode('http://example.com/objects/2'),
    # NamedNode('http://example.com/predicates/2'),
    # NamedNode('http://example.com/objects/1')) in g


def test_parse_nquads_named_nodes():
    test_nquads = """<http://example.com/objects/1> <http://example.com/predicates/1> <http://example.com/objects/2> <http://example.com/graphs/1> .
<http://example.com/objects/2> <http://example.com/predicates/2> <http://example.com/objects/1> <http://example.com/graphs/1> .
"""
    g = Graph()
    nquads_parser.parse(StringIO(test_nquads), g)
    assert len(g) == 2
    assert (
        Quad(
            NamedNode("http://example.com/objects/1"),
            NamedNode("http://example.com/predicates/1"),
            NamedNode("http://example.com/objects/2"),
            NamedNode("http://example.com/graphs/1"),
        )
        in g
    )
    assert (
        Quad(
            NamedNode("http://example.com/objects/2"),
            NamedNode("http://example.com/predicates/2"),
            NamedNode("http://example.com/objects/1"),
            NamedNode("http://example.com/graphs/1"),
        )
        in g
    )


def test_parse_turtle_example_1():
    ttl = """@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix dc: <http://purl.org/dc/elements/1.1/> .
@prefix ex: <http://example.org/stuff/1.0/> .

<http://www.w3.org/TR/rdf-syntax-grammar>
  dc:title "RDF/XML Syntax Specification (Revised)" ;
  ex:editor [
    ex:fullname "Dave Beckett";
    ex:homePage <http://purl.org/net/dajobe/>
  ] ."""
    g = Graph()
    turtle_parser.parse(ttl, g)
    assert len(g) == 4


def test_parse_turtle_blank_node_property_list_in_object_list():
    ttl = """<http://a.example/s> <http://a.example/p> [ <http://a.example/p2> <http://a.example/o> ]
                                          , <http://a.example/o2> ."""
    g = turtle_parser.parse(ttl)
    s = NamedNode("http://a.example/s")
    p = NamedNode("http://a.example/p")
    (list_node,) = [
        t.object for t in g if t.subject == s and isinstance(t.object, BlankNode)
    ]
    assert set(g) == {
        Triple(s, p, list_node),
        Triple(
            list_node, NamedNode("http://a.example/p2"), NamedNode("http://a.example/o")
        ),
        Triple(s, p, NamedNode("http://a.example/o2")),
    }


def test_parse_turtle_blank_node_property_list_after_object_in_object_list():
    ttl = """<http://a.example/s> <http://a.example/p> <http://a.example/o2>,
        [ <http://a.example/p2> <http://a.example/o> ] ."""
    g = turtle_parser.parse(ttl)
    s = NamedNode("http://a.example/s")
    p = NamedNode("http://a.example/p")
    (list_node,) = [
        t.object for t in g if t.subject == s and isinstance(t.object, BlankNode)
    ]
    assert set(g) == {
        Triple(s, p, list_node),
        Triple(
            list_node, NamedNode("http://a.example/p2"), NamedNode("http://a.example/o")
        ),
        Triple(s, p, NamedNode("http://a.example/o2")),
    }


def test_parse_turtle_collection_in_object_list():
    ttl = """<http://a.example/s> <http://a.example/p> ( <http://a.example/o> ), <http://a.example/o2> ."""
    g = turtle_parser.parse(ttl)
    s = NamedNode("http://a.example/s")
    p = NamedNode("http://a.example/p")
    rdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    (list_node,) = [
        t.object for t in g if t.subject == s and isinstance(t.object, BlankNode)
    ]
    assert set(g) == {
        Triple(s, p, list_node),
        Triple(list_node, NamedNode(rdf + "first"), NamedNode("http://a.example/o")),
        Triple(list_node, NamedNode(rdf + "rest"), NamedNode(rdf + "nil")),
        Triple(s, p, NamedNode("http://a.example/o2")),
    }


def test_jsonld_basic():
    import json

    jsonld = """[{
  "@id": "http://example.com/id1",
  "@type": ["http://example.com/t1"],
  "http://example.com/term1": ["v1"],
  "http://example.com/term2": [{"@value": "v2", "@type": "http://example.com/t2"}],
  "http://example.com/term3": [{"@value": "v3", "@language": "en"}],
  "http://example.com/term4": [4],
  "http://example.com/term5": [50, 51]
}]
"""
    g = Graph()
    jsonld_parser.parse_json(json.loads(jsonld), g)
    assert len(g) == 7


def test_parse_ntriples_language_tag_with_digits():
    g = Graph()
    ntriples_parser.parse(
        StringIO(
            '<http://x/s> <http://x/p> "a"@zh-Hant-1 .\n'
            '<http://x/s> <http://x/p> "b"@en-2 .\n'
        ),
        g,
    )
    assert len(g) == 2
    assert (
        Triple(
            NamedNode("http://x/s"),
            NamedNode("http://x/p"),
            Literal("a", language="zh-Hant-1"),
        )
        in g
    )


EX_S = NamedNode("http://example/s")
EX_P = NamedNode("http://example/p")
EX_O = NamedNode("http://example/o")


def test_parse_ntriples_line_by_line_with_comments_and_blank_lines():
    lines = StringIO(
        "# a comment on its own line\n"
        "\n"
        "   \t  \n"
        "  # a comment after whitespace\n"
        "<http://example/s> <http://example/p> <http://example/o> . # trailing\n"
        "\n"
        '<http://example/s> <http://example/p> "o" .\n'
        "# a comment with no newline at the end of the file"
    )
    g = Graph()
    ntriples_parser.parse(lines, g)
    assert len(g) == 2
    assert Triple(EX_S, EX_P, EX_O) in g
    assert Triple(EX_S, EX_P, Literal("o")) in g


def test_parse_nquads_line_by_line_with_comments_and_blank_lines():
    lines = StringIO(
        "# comment\n"
        "\n"
        "<http://example/s> <http://example/p> <http://example/o> <http://example/g> . # c\n"
        "\n"
        "<http://example/s> <http://example/p> <http://example/o> .\n"
    )
    g = Graph()
    nquads_parser.parse(lines, g)
    assert len(g) == 2
    assert Quad(EX_S, EX_P, EX_O, NamedNode("http://example/g")) in g
    assert Quad(EX_S, EX_P, EX_O, None) in g


def test_parse_nquads_without_graph_label_is_default_graph():
    """N-Quads 1.1: a statement without a graph label belongs to the
    default graph, which pymantic represents as graph=None (as the JSON-LD
    parser already does). Serializing it back must give a triple line."""
    g = Graph()
    nquads_parser.parse("<http://example/s> <http://example/p> <http://example/o> .", g)
    assert len(g) == 1
    assert Quad(EX_S, EX_P, EX_O, None) in g
    out = StringIO()
    serialize_nquads(g, out)
    assert (
        out.getvalue() == "<http://example/s> <http://example/p> <http://example/o> .\n"
    )


def test_parse_nquads_blank_node_graph_label():
    g = Graph()
    nquads_parser.parse(
        "<http://example/s> <http://example/p> _:o _:g .\n"
        "_:g <http://example/p> <http://example/o> _:g .\n",
        g,
    )
    assert len(g) == 2
    quads = list(g)
    (graph_label,) = {q.graph for q in quads}
    assert isinstance(graph_label, BlankNode)
    # The same label names the same blank node whether it is a graph or a subject.
    assert Quad(graph_label, EX_P, EX_O, graph_label) in g


def test_parse_ntriples_minimal_whitespace():
    g = Graph()
    ntriples_parser.parse(
        "<http://example/s><http://example/p><http://example/o>.\n"
        '_:s<http://example/p>"Alice".\n'
        "_:s<http://example/p>_:bnode1.\n",
        g,
    )
    assert len(g) == 3
    assert Triple(EX_S, EX_P, EX_O) in g


def test_parse_nquads_minimal_whitespace():
    g = Graph()
    nquads_parser.parse(
        '<http://example/s><http://example/p>"Alice"<http://example/g>.\n'
        "_:s<http://example/p>_:o _:g.\n",
        g,
    )
    assert len(g) == 2
    assert Quad(EX_S, EX_P, Literal("Alice"), NamedNode("http://example/g")) in g


@pytest.mark.parametrize(
    "document",
    [
        "_::a <http://example/p> <http://example/o> .",
        "_:abc:def <http://example/p> <http://example/o> .",
        "<http://example/s> <http://example/p> _:o:o .",
    ],
)
def test_parse_ntriples_rejects_colon_in_blank_node_label(document):
    with pytest.raises(Exception):
        ntriples_parser.parse(document, Graph())


@pytest.mark.parametrize(
    "document",
    [
        "<http://example/s> <http://example/p> <//example/missing-scheme> .",
        "<relative> <http://example/p> <http://example/o> .",
        '<http://example/s> <http://example/p> "o"^^<dt> .',
        "<http://example/s> <http://example/p> <http://example/o> <g> .",
    ],
)
def test_parse_nquads_rejects_relative_iri(document):
    with pytest.raises(ValueError):
        nquads_parser.parse(document, Graph())


@pytest.mark.parametrize(
    "document",
    [
        '<http://example/s> <http://example/p> "o"^^<http://www.w3.org/1999/02/22-rdf-syntax-ns#langString> .',
        '<http://example/s> <http://example/p> "o"^^<http://www.w3.org/1999/02/22-rdf-syntax-ns#dirLangString> .',
    ],
)
def test_parse_ntriples_rejects_langstring_datatype_without_language_tag(document):
    with pytest.raises(ValueError):
        ntriples_parser.parse(document, Graph())


def test_parse_ntriples_rejects_language_subtag_longer_than_eight_characters():
    with pytest.raises(Exception):
        ntriples_parser.parse(
            '<http://example/s> <http://example/p> "o"@cantbethislong .', Graph()
        )


def test_parse_ntriples_rejects_two_triples_on_one_line():
    with pytest.raises(Exception):
        ntriples_parser.parse(
            "<http://example/s> <http://example/p> <http://example/o> . "
            "<http://example/s> <http://example/p> <http://example/o> .",
            Graph(),
        )


def test_parsed_literals_carry_their_datatype():
    """Every literal a parser makes has a datatype: xsd:string for one
    written without a datatype or language, rdf:langString for a
    language-tagged string (RDF 1.1 Concepts 3.3)."""
    from pymantic.primitives import RDF_LANGSTRING, XSD_STRING

    text = (
        '<http://example.com/s> <http://example.com/p> "Foo" .\n'
        '<http://example.com/s> <http://example.com/p> "Foo"@en .\n'
        '<http://example.com/s> <http://example.com/p> "Foo"^^'
        "<http://www.w3.org/2001/XMLSchema#string> .\n"
    )
    for parser in (ntriples_parser, turtle_parser):
        g = parser.parse(text)
        # The plain literal and the explicit xsd:string are one term.
        assert len(g) == 2
        datatypes = {(t.object.language, t.object.datatype) for t in g}
        assert datatypes == {(None, XSD_STRING), ("en", RDF_LANGSTRING)}
