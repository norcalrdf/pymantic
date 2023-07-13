from io import StringIO
import pytest

from pymantic.parsers import ntriples_parser
from pymantic.primitives import Graph, NamedNode, Triple
from pymantic.serializers import serialize_ntriples


def test_parse_ntriples_named_nodes():
    test_ntriples = """<http://example.com/objects/1> <http://example.com/predicates/1> <http://example.com/objects/2> .
<http://example.com/objects/2> <http://example.com/predicates/2> <http://example.com/objects/1> .
"""
    g = Graph()
    ntriples_parser.parse(StringIO(test_ntriples), g)
    f = StringIO()
    serialize_ntriples(g, f)
    f.seek(0)
    g2 = Graph()
    ntriples_parser.parse(f, g2)
    assert len(g) == 2
    assert (
        Triple(
            NamedNode("http://example.com/objects/1"),
            NamedNode("http://example.com/predicates/1"),
            NamedNode("http://example.com/objects/2"),
        )
        in g2
    )
    assert (
        Triple(
            NamedNode("http://example.com/objects/2"),
            NamedNode("http://example.com/predicates/2"),
            NamedNode("http://example.com/objects/1"),
        )
        in g2
    )


@pytest.fixture()
def turtle_repr():
    from pymantic.serializers import turtle_repr

    return turtle_repr


@pytest.fixture()
def primitives():
    import pymantic.primitives

    return pymantic.primitives


@pytest.fixture()
def profile(primitives):
    return primitives.Profile()


def test_integer(primitives, profile, turtle_repr):
    lit = primitives.Literal(value="42", datatype=profile.resolve("xsd:integer"))
    name = turtle_repr(node=lit, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == "42"


def test_decimal(primitives, profile, turtle_repr):
    lit = primitives.Literal(value="4.2", datatype=profile.resolve("xsd:decimal"))
    name = turtle_repr(node=lit, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == "4.2"


def test_double(primitives, profile, turtle_repr):
    lit = primitives.Literal(value="4.2e1", datatype=profile.resolve("xsd:double"))
    name = turtle_repr(node=lit, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == "4.2e1"


def test_boolean(primitives, profile, turtle_repr):
    lit = primitives.Literal(value="true", datatype=profile.resolve("xsd:boolean"))
    name = turtle_repr(node=lit, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == "true"


def test_bare_string(primitives, profile, turtle_repr):
    lit = primitives.Literal(value="Foo", datatype=profile.resolve("xsd:string"))
    name = turtle_repr(node=lit, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == '"Foo"'


def test_language_string(primitives, profile, turtle_repr):
    lit = primitives.Literal(value="Foo", language="en")
    name = turtle_repr(node=lit, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == '"Foo"@en'


def test_random_datatype_bare_url(primitives, profile, turtle_repr):
    lit = primitives.Literal(
        value="Foo", datatype=primitives.NamedNode("http://example.com/garply")
    )
    name = turtle_repr(node=lit, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == '"Foo"^<http://example.com/garply>'


def test_random_datatype_prefixed(primitives, profile, turtle_repr):
    profile.setPrefix("ex", primitives.NamedNode("http://example.com/"))
    lit = primitives.Literal(
        value="Foo", datatype=primitives.NamedNode("http://example.com/garply")
    )
    name = turtle_repr(node=lit, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == '"Foo"^ex:garply'


def test_named_node_bare(primitives, profile, turtle_repr):
    node = primitives.NamedNode("http://example.com/foo")
    name = turtle_repr(node=node, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == "<http://example.com/foo>"


def test_named_node_prefixed(primitives, profile, turtle_repr):
    profile.setPrefix("ex", primitives.NamedNode("http://example.com/"))
    node = primitives.NamedNode("http://example.com/foo")
    name = turtle_repr(node=node, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == "ex:foo"


def test_named_node_with_hash_base(primitives, profile, turtle_repr):
    node = primitives.NamedNode("https://example.com/foo#bar")
    name = turtle_repr(
        node=node,
        profile=profile,
        name_map=None,
        bnode_name_maker=None,
        base="https://example.com/foo#",
    )
    assert name == "<#bar>"


def test_named_node_with_path_base(primitives, profile, turtle_repr):
    node = primitives.NamedNode("https://example.com/foo")
    name = turtle_repr(
        node=node,
        profile=profile,
        name_map=None,
        bnode_name_maker=None,
        base="https://example.com/",
    )
    assert name == "<foo>"


def test_named_node_with_multi_path_base(primitives, profile, turtle_repr):
    node = primitives.NamedNode("https://example.com/foo/bar")
    name = turtle_repr(
        node=node,
        profile=profile,
        name_map=None,
        bnode_name_maker=None,
        base="https://example.com/",
    )
    assert name == "<foo/bar>"


@pytest.fixture()
def turtle_parser():
    from pymantic.parsers import turtle_parser

    return turtle_parser


@pytest.fixture()
def serialize_turtle():
    from pymantic.serializers import serialize_turtle

    return serialize_turtle


def testSimpleSerialization(primitives, profile, turtle_parser, serialize_turtle):
    basic_turtle = """@prefix dc: <http://purl.org/dc/terms/> .
    @prefix example: <http://example.com/> .

    example:foo dc:title "Foo" .
    example:bar dc:title "Bar" .
    example:baz dc:subject example:foo ."""

    graph = turtle_parser.parse(basic_turtle)
    f = StringIO()
    profile.setPrefix("ex", primitives.NamedNode("http://example.com/"))
    profile.setPrefix("dc", primitives.NamedNode("http://purl.org/dc/terms/"))
    serialize_turtle(graph=graph, f=f, profile=profile)
    f.seek(0)
    turtle_parser.parse(f.read())
    f.seek(0)
    assert (
        f.read().strip()
        == """@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.com/> .
@prefix dc: <http://purl.org/dc/terms/> .
ex:bar dc:title "Bar" ;
       .

ex:baz dc:subject ex:foo ;
       .

ex:foo dc:title "Foo" ;
       .
    """.strip()
    )


def testBaseSerialization(primitives, profile, turtle_parser, serialize_turtle):
    basic_turtle = """@prefix dc: <http://purl.org/dc/terms/> .
    @prefix example: <http://example.com/> .

    example:foo dc:title "Foo" .
    example:bar dc:title "Bar" .
    example:baz dc:subject example:foo ."""

    graph = turtle_parser.parse(basic_turtle)
    f = StringIO()
    profile.setPrefix("dc", primitives.NamedNode("http://purl.org/dc/terms/"))
    serialize_turtle(
        graph=graph,
        f=f,
        profile=profile,
        base="http://example.com/",
    )
    f.seek(0)
    turtle_parser.parse(f.read())
    f.seek(0)
    assert (
        f.read().strip()
        == """@base <http://example.com/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix dc: <http://purl.org/dc/terms/> .
<bar> dc:title "Bar" ;
      .

<baz> dc:subject <foo> ;
      .

<foo> dc:title "Foo" ;
      .
    """.strip()
    )


def testBaseAndPrefixSerialization(
    primitives, profile, turtle_parser, serialize_turtle
):
    basic_turtle = """@prefix dc: <http://purl.org/dc/terms/> .
    @prefix example: <http://example.com/> .

    example:foo dc:title "Foo" .
    example:bar dc:title "Bar" .
    example:baz dc:subject example:foo ."""

    graph = turtle_parser.parse(basic_turtle)
    f = StringIO()
    profile.setPrefix("ex", primitives.NamedNode("http://example.com/"))
    profile.setPrefix("dc", primitives.NamedNode("http://purl.org/dc/terms/"))
    serialize_turtle(
        graph=graph,
        f=f,
        profile=profile,
        base="http://example.com/",
    )
    f.seek(0)
    turtle_parser.parse(f.read())
    f.seek(0)
    assert (
        f.read().strip()
        == """@base <http://example.com/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.com/> .
@prefix dc: <http://purl.org/dc/terms/> .
ex:bar dc:title "Bar" ;
       .

ex:baz dc:subject ex:foo ;
       .

ex:foo dc:title "Foo" ;
       .
    """.strip()
    )


def testMultiplePredicates(primitives, profile, turtle_parser, serialize_turtle):
    basic_turtle = """@prefix dc: <http://purl.org/dc/terms/> .
    @prefix example: <http://example.com/> .

    example:foo dc:title "Foo" ;
                dc:author "Bar" ;
                dc:subject example:yesfootoo .

    example:garply dc:title "Garply" ;
                dc:author "Baz" ;
                dc:subject example:thegarply ."""

    graph = turtle_parser.parse(basic_turtle)
    f = StringIO()
    profile.setPrefix("ex", primitives.NamedNode("http://example.com/"))
    profile.setPrefix("dc", primitives.NamedNode("http://purl.org/dc/terms/"))
    serialize_turtle(graph=graph, f=f, profile=profile)
    f.seek(0)
    turtle_parser.parse(f.read())
    f.seek(0)
    assert (
        f.read().strip()
        == """
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.com/> .
@prefix dc: <http://purl.org/dc/terms/> .
ex:foo dc:author "Bar" ;
       dc:subject ex:yesfootoo ;
       dc:title "Foo" ;
       .

ex:garply dc:author "Baz" ;
          dc:subject ex:thegarply ;
          dc:title "Garply" ;
          .""".strip()
    )


def testListSerialization(primitives, profile, turtle_parser, serialize_turtle):
    basic_turtle = """@prefix dc: <http://purl.org/dc/terms/> .
    @prefix example: <http://example.com/> .

    example:foo dc:author ("Foo" "Bar" "Baz") ."""

    graph = turtle_parser.parse(basic_turtle)
    f = StringIO()
    profile.setPrefix("ex", primitives.NamedNode("http://example.com/"))
    profile.setPrefix("dc", primitives.NamedNode("http://purl.org/dc/terms/"))
    serialize_turtle(graph=graph, f=f, profile=profile)
    f.seek(0)
    turtle_parser.parse(f.read())
    f.seek(0)
    assert (
        f.read().strip()
        == """
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.com/> .
@prefix dc: <http://purl.org/dc/terms/> .
ex:foo dc:author ("Foo" "Bar" "Baz") ;
       .""".strip()
    )
