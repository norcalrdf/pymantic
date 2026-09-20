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
    assert name == '"Foo"^^<http://example.com/garply>'


def test_random_datatype_prefixed(primitives, profile, turtle_repr):
    profile.setPrefix("ex", primitives.NamedNode("http://example.com/"))
    lit = primitives.Literal(
        value="Foo", datatype=primitives.NamedNode("http://example.com/garply")
    )
    name = turtle_repr(node=lit, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == '"Foo"^^ex:garply'


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
        == """@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
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
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
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
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
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
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
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
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.com/> .
@prefix dc: <http://purl.org/dc/terms/> .
ex:foo dc:author ("Foo" "Bar" "Baz") ;
       .""".strip()
    )


def test_turtle_string_escape():
    from pymantic.serializers import turtle_string_escape

    assert turtle_string_escape('a"b\nc\\d\re\tf') == '"a\\"b\\nc\\\\d\\re\\tf"'
    # Apostrophes need no escape inside a double-quoted string.
    assert turtle_string_escape("it's") == '"it\'s"'


def test_turtle_literal_injection_round_trip(
    primitives, profile, turtle_parser, serialize_turtle
):
    """A literal containing quotes must not break out of the string and inject
    triples into the serialized Turtle."""
    s = primitives.NamedNode("http://x/s")
    p = primitives.NamedNode("http://x/p")
    o = primitives.Literal(
        'x" . <http://attacker/s> <http://attacker/p> <http://attacker/o> . '
        '<http://x/s> <http://x/p> "y',
        datatype=primitives.XSD("string"),
    )
    graph = primitives.Graph()
    graph.add(primitives.Triple(s, p, o))
    f = StringIO()
    serialize_turtle(graph=graph, f=f, profile=profile)
    parsed = turtle_parser.parse(f.getvalue())
    assert len(parsed) == 1
    assert primitives.Triple(s, p, o) in parsed


def test_turtle_literal_backslash_not_double_escaped(
    primitives, profile, turtle_parser, serialize_turtle
):
    s = primitives.NamedNode("http://x/s")
    p = primitives.NamedNode("http://x/p")
    o = primitives.Literal(
        'back\\slash "quote" new\nline', datatype=primitives.XSD("string")
    )
    graph = primitives.Graph()
    graph.add(primitives.Triple(s, p, o))
    f = StringIO()
    serialize_turtle(graph=graph, f=f, profile=profile)
    parsed = turtle_parser.parse(f.getvalue())
    assert len(parsed) == 1
    assert primitives.Triple(s, p, o) in parsed


@pytest.mark.parametrize(
    "local,expected",
    [
        ("foo", "ex:foo"),
        ("", "ex:"),
        ("foo;bar.baz", "ex:foo\\;bar.baz"),
        ("foo)bar", "ex:foo\\)bar"),
        ("foo.", "ex:foo\\."),
        (".foo", "ex:\\.foo"),
        ("-foo", "ex:\\-foo"),
        ("foo-bar_baz", "ex:foo-bar_baz"),
        ("a:b", "ex:a:b"),
        ("100%", "ex:100\\%"),
        ("foo%20bar", "ex:foo\\%20bar"),
        ("a/b?c=d#e", "ex:a\\/b\\?c\\=d\\#e"),
        ("~!$&'()*+,;=@", "ex:\\~\\!\\$\\&\\'\\(\\)\\*\\+\\,\\;\\=\\@"),
    ],
)
def test_named_node_prefixed_local_escaping(
    primitives, profile, turtle_repr, turtle_parser, local, expected
):
    profile.setPrefix("ex", primitives.NamedNode("http://example.com/"))
    node = primitives.NamedNode("http://example.com/" + local)
    name = turtle_repr(node=node, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == expected
    parsed = turtle_parser.parse(
        f"@prefix ex: <http://example.com/> . {name} <http://x/p> <http://x/o> ."
    )
    assert next(iter(parsed)).subject == node


@pytest.mark.parametrize(
    "local,expected",
    [
        ("foo bar", "<http://example.com/foo%20bar>"),
        ("foo>bar", "<http://example.com/foo%3Ebar>"),
        ("foo|bar", "<http://example.com/foo%7Cbar>"),
    ],
)
def test_named_node_prefixed_local_unrepresentable_falls_back_to_iri(
    primitives, profile, turtle_repr, local, expected
):
    profile.setPrefix("ex", primitives.NamedNode("http://example.com/"))
    node = primitives.NamedNode("http://example.com/" + local)
    name = turtle_repr(node=node, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == expected


def test_named_node_bare_iri_escaping(primitives, profile, turtle_repr):
    node = primitives.NamedNode("http://x/a> <http://attacker/s")
    name = turtle_repr(node=node, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == "<http://x/a%3E%20%3Chttp://attacker/s>"
    node = primitives.NamedNode('http://x/a"b\\c{d}|e^f`g')
    name = turtle_repr(node=node, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == "<http://x/a%22b%5Cc%7Bd%7D%7Ce%5Ef%60g>"


def test_named_node_with_base_iri_escaping(primitives, profile, turtle_repr):
    node = primitives.NamedNode("https://example.com/foo bar>baz")
    name = turtle_repr(
        node=node,
        profile=profile,
        name_map=None,
        bnode_name_maker=None,
        base="https://example.com/",
    )
    assert name == "<foo%20bar%3Ebaz>"
    node = primitives.NamedNode("https://example.com/foo#bar baz")
    name = turtle_repr(
        node=node,
        profile=profile,
        name_map=None,
        bnode_name_maker=None,
        base="https://example.com/foo#",
    )
    assert name == "<#bar%20baz>"


def test_turtle_iri_injection_round_trip(
    primitives, profile, turtle_parser, serialize_turtle
):
    s = primitives.NamedNode(
        "http://x/s> <http://attacker/p> <http://attacker/o> . <http://x/s"
    )
    p = primitives.NamedNode("http://x/p")
    o = primitives.NamedNode("http://x/o")
    graph = primitives.Graph()
    graph.add(primitives.Triple(s, p, o))
    f = StringIO()
    serialize_turtle(graph=graph, f=f, profile=profile)
    parsed = turtle_parser.parse(f.getvalue())
    assert len(parsed) == 1
    triple = next(iter(parsed))
    assert triple.predicate == p
    assert triple.object == o
    assert "attacker" not in triple.subject or triple.subject.startswith(
        "http://x/s%3E"
    )


def test_blank_node_round_trip(primitives, profile, turtle_parser, serialize_turtle):
    basic_turtle = """@prefix dc: <http://purl.org/dc/terms/> .
    @prefix example: <http://example.com/> .

    _:a dc:title "A" ;
        dc:relation _:b .
    _:b dc:title "B" .
    example:foo dc:relation _:a ."""

    graph = turtle_parser.parse(basic_turtle)
    f = StringIO()
    profile.setPrefix("ex", primitives.NamedNode("http://example.com/"))
    profile.setPrefix("dc", primitives.NamedNode("http://purl.org/dc/terms/"))
    serialize_turtle(graph=graph, f=f, profile=profile)
    parsed = turtle_parser.parse(f.getvalue())
    assert len(parsed) == 4
    dc = primitives.Prefix("http://purl.org/dc/terms/")
    xsd_string = primitives.XSD("string")
    (a_triple,) = list(
        parsed.match(
            predicate=dc("title"), object=primitives.Literal("A", datatype=xsd_string)
        )
    )
    (b_triple,) = list(
        parsed.match(
            predicate=dc("title"), object=primitives.Literal("B", datatype=xsd_string)
        )
    )
    a, b = a_triple.subject, b_triple.subject
    assert a.interfaceName == "BlankNode"
    assert b.interfaceName == "BlankNode"
    assert a is not b
    assert primitives.Triple(a, dc("relation"), b) in parsed
    assert (
        primitives.Triple(
            primitives.NamedNode("http://example.com/foo"), dc("relation"), a
        )
        in parsed
    )


def test_nt_escape_control_characters():
    """Canonical N-Triples (https://www.w3.org/TR/rdf12-n-triples/#canonical-ntriples):
    BS, HT, LF, FF, CR, quote and backslash use ECHAR; U+0000-U+0007, VT,
    U+000E-U+001F and DEL use a lowercase \\u with uppercase hex."""
    from pymantic.serializers import nt_escape

    assert nt_escape("a\x00b\x08c\x0cd\x1fe\x7ff") == (
        "a\\u0000b\\bc\\fd\\u001Fe\\u007Ff"
    )
    assert nt_escape("tab\tlf\ncr\rvt\x0b") == "tab\\tlf\\ncr\\rvt\\u000B"
    assert nt_escape('q"b\\') == 'q\\"b\\\\'


def test_nt_escape_writes_non_ascii_raw():
    """Characters that need neither ECHAR nor UCHAR are written natively."""
    from pymantic.serializers import nt_escape

    assert nt_escape("caf\u00e9 \u65e5\u672c \U0001F600 \U0010FFFF") == (
        "caf\u00e9 \u65e5\u672c \U0001F600 \U0010FFFF"
    )


def test_nt_escape_non_xml_chars_use_uchar():
    """U+FFFE, U+FFFF and surrogates are not XML 1.1 Chars, so they must be
    escaped."""
    from pymantic.serializers import nt_escape

    assert nt_escape("\ufffe\uffff\ud800\udfff") == ("\\uFFFE\\uFFFF\\uD800\\uDFFF")


def test_ntriples_non_ascii_round_trip(primitives):
    s = primitives.NamedNode("http://x/s")
    p = primitives.NamedNode("http://x/p")
    o = primitives.Literal("caf\u00e9 \u65e5\u672c \U0001F600 \ufffe")
    graph = primitives.Graph().add(primitives.Triple(s, p, o))
    f = StringIO()
    serialize_ntriples(graph, f)
    assert f.getvalue() == (
        '<http://x/s> <http://x/p> "caf\u00e9 \u65e5\u672c \U0001F600 \\uFFFE" .\n'
    )
    f.seek(0)
    parsed = primitives.Graph()
    ntriples_parser.parse(f, parsed)
    assert list(parsed) == [primitives.Triple(s, p, o)]


def test_ntriples_omits_xsd_string_datatype(primitives):
    """Canonical N-Triples never writes ^^xsd:string, and the Turtle parser
    (which sets that datatype) and the N-Triples parser (which leaves it
    unset) must serialize a simple literal identically."""
    from pymantic.parsers import turtle_parser

    xsd_string = primitives.XSD("string")
    assert primitives.Literal("foo", datatype=xsd_string).toNT() == '"foo"'
    assert primitives.Literal("foo").toNT() == '"foo"'
    line = '<http://x/s> <http://x/p> "foo" .\n'
    from_turtle = StringIO()
    serialize_ntriples(turtle_parser.parse(line), from_turtle)
    from_ntriples = StringIO()
    serialize_ntriples(ntriples_parser.parse(line), from_ntriples)
    assert from_turtle.getvalue() == line
    assert from_ntriples.getvalue() == line


def test_ntriples_lowercases_language_tag(primitives):
    graph = primitives.Graph().add(
        primitives.Triple(
            primitives.NamedNode("http://x/s"),
            primitives.NamedNode("http://x/p"),
            primitives.Literal("chat", language="EN-Gb"),
        )
    )
    f = StringIO()
    serialize_ntriples(graph, f)
    assert f.getvalue() == '<http://x/s> <http://x/p> "chat"@en-gb .\n'


def test_ntriples_control_character_round_trip(primitives):
    s = primitives.NamedNode("http://x/s")
    p = primitives.NamedNode("http://x/p")
    o = primitives.Literal("a\x00b\x08c\x0cd\x1fe")
    graph = primitives.Graph()
    graph.add(primitives.Triple(s, p, o))
    f = StringIO()
    serialize_ntriples(graph, f)
    f.seek(0)
    parsed = primitives.Graph()
    ntriples_parser.parse(f, parsed)
    assert len(parsed) == 1
    assert primitives.Triple(s, p, o) in parsed


def test_named_node_non_ascii_iri_serializes_raw(
    primitives, profile, turtle_repr, turtle_parser
):
    node = primitives.NamedNode("http://example.com/café/日本#É")
    name = turtle_repr(node=node, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == "<http://example.com/café/日本#É>"
    parsed = turtle_parser.parse(f"{name} <http://x/p> <http://x/o> .")
    assert next(iter(parsed)).subject == node


def test_named_node_percent_encoded_iri_left_as_is(primitives, profile, turtle_repr):
    node = primitives.NamedNode("http://example.com/a%20b?q=100%25")
    name = turtle_repr(node=node, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == "<http://example.com/a%20b?q=100%25>"


def test_named_node_control_characters_percent_encoded(
    primitives, profile, turtle_repr
):
    node = primitives.NamedNode("http://example.com/a\x00b\tc\x7fd")
    name = turtle_repr(node=node, profile=profile, name_map=None, bnode_name_maker=None)
    assert name == "<http://example.com/a%00b%09c\x7fd>"


@pytest.mark.parametrize("datatype", ["integer", "decimal", "double", "boolean"])
@pytest.mark.parametrize("value", ['not a number; "quoted"\nvalue', "1 . 2", ""])
def test_typed_literal_unsafe_value_round_trip(
    primitives, turtle_parser, serialize_turtle, datatype, value
):
    triple = primitives.Triple(
        primitives.NamedNode("http://x/s"),
        primitives.NamedNode("http://x/p"),
        primitives.Literal(value, datatype=primitives.XSD(datatype)),
    )
    graph = primitives.Graph().add(triple)
    output = StringIO()
    serialize_turtle(graph, output)
    parsed = turtle_parser.parse(output.getvalue())
    assert len(parsed) == 1
    assert triple in parsed


@pytest.mark.parametrize(
    "datatype,value",
    [("decimal", "1"), ("double", "1.0"), ("double", "INF"), ("boolean", "1")],
)
def test_typed_literal_preserves_datatype(
    primitives, turtle_parser, serialize_turtle, datatype, value
):
    test_typed_literal_unsafe_value_round_trip(
        primitives, turtle_parser, serialize_turtle, datatype, value
    )


@pytest.mark.parametrize("language", ["en\n", "en us", "en;", "en-", "é"])
@pytest.mark.parametrize("format", ["turtle", "nt"])
def test_serializers_reject_invalid_language(primitives, language, format):
    from pymantic.serializers import serialize_turtle

    graph = primitives.Graph().add(
        primitives.Triple(
            primitives.NamedNode("http://x/s"),
            primitives.NamedNode("http://x/p"),
            primitives.Literal("text", language=language),
        )
    )
    serializer = serialize_turtle if format == "turtle" else serialize_ntriples
    with pytest.raises(ValueError, match="language"):
        serializer(graph, StringIO())


@pytest.mark.parametrize("directive", ["base", "prefix"])
def test_turtle_directive_iri_escaping(
    primitives, profile, turtle_parser, serialize_turtle, directive
):
    iri = 'http://example.com/a> <b"c\n'
    kwargs = {}
    if directive == "base":
        kwargs["base"] = iri
    else:
        profile.setPrefix("ex", iri)
    output = StringIO()
    serialize_turtle(primitives.Graph(), output, profile=profile, **kwargs)
    assert "<http://example.com/a%3E%20%3Cb%22c%0A>" in output.getvalue()
    assert len(turtle_parser.parse(output.getvalue())) == 0


@pytest.mark.parametrize("prefix", ["ex:", "ex name", "ex\n", "ex.", "_ex"])
def test_turtle_rejects_invalid_prefix(primitives, profile, serialize_turtle, prefix):
    profile.setPrefix(prefix, "http://example.com/")
    with pytest.raises(ValueError, match="prefix"):
        serialize_turtle(primitives.Graph(), StringIO(), profile=profile)


@pytest.mark.parametrize("prefix", ["", "ex", "é", "a.b", "ex_1"])
def test_turtle_valid_prefix_round_trip(
    primitives, profile, turtle_parser, serialize_turtle, prefix
):
    profile.setPrefix(prefix, "http://example.com/")
    triple = primitives.Triple(
        primitives.NamedNode("http://example.com/s"),
        primitives.NamedNode("http://example.com/p"),
        primitives.NamedNode("http://example.com/o"),
    )
    output = StringIO()
    serialize_turtle(primitives.Graph().add(triple), output, profile=profile)
    parsed = turtle_parser.parse(output.getvalue())
    assert len(parsed) == 1
    assert triple in parsed


def test_nquads_round_trip_escapes(primitives):
    from pymantic.parsers import nquads_parser
    from pymantic.serializers import serialize_nquads

    quads = [
        primitives.Quad(
            primitives.NamedNode("http://x/s"),
            primitives.NamedNode("http://x/p"),
            primitives.Literal('v" . <http://a/s> <http://a/p> <http://a/o>'),
            primitives.NamedNode("http://x/g"),
        ),
        primitives.Quad(
            primitives.NamedNode("http://x/s"),
            primitives.NamedNode("http://x/p"),
            primitives.Literal("text", language="en-us"),
            primitives.NamedNode("http://x/g"),
        ),
    ]
    dataset = primitives.Dataset()
    for quad in quads:
        dataset.add(quad)
    output = StringIO()
    serialize_nquads(dataset, output)
    parsed = nquads_parser.parse(output.getvalue())
    assert len(parsed) == 2
    for quad in quads:
        assert quad in parsed


def test_prefix_shrink_only_strips_leading_namespace(
    primitives, profile, turtle_parser, serialize_turtle
):
    profile.setPrefix("ex", primitives.NamedNode("http://example.com/"))
    triple = primitives.Triple(
        primitives.NamedNode("http://example.com/a?u=http://example.com/b"),
        primitives.NamedNode("http://example.com/p"),
        primitives.NamedNode("http://example.com/o"),
    )
    output = StringIO()
    serialize_turtle(primitives.Graph().add(triple), output, profile=profile)
    parsed = turtle_parser.parse(output.getvalue())
    assert len(parsed) == 1
    assert triple in parsed


def test_turtle_declares_rdf_prefix(primitives, serialize_turtle):
    graph = primitives.Graph().add(
        primitives.Triple(
            primitives.NamedNode("http://x/s"),
            primitives.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
            primitives.NamedNode("http://x/C"),
        )
    )
    output = StringIO()
    serialize_turtle(graph, output)
    text = output.getvalue()
    assert "rdf:type" in text
    assert "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n" in text


def test_ntriples_serializes_in_insertion_order(primitives):
    p = primitives.NamedNode("http://x/p")
    o = primitives.NamedNode("http://x/o")
    graph = primitives.Graph()
    for name in ("c", "a", "b"):
        graph.add(primitives.Triple(primitives.NamedNode("http://x/" + name), p, o))
    f = StringIO()
    serialize_ntriples(graph, f)
    assert f.getvalue() == (
        "<http://x/c> <http://x/p> <http://x/o> .\n"
        "<http://x/a> <http://x/p> <http://x/o> .\n"
        "<http://x/b> <http://x/p> <http://x/o> .\n"
    )


def test_nquads_serializes_in_insertion_order(primitives):
    from pymantic.serializers import serialize_nquads

    p = primitives.NamedNode("http://x/p")
    o = primitives.NamedNode("http://x/o")
    g = primitives.NamedNode("http://x/g")
    dataset = primitives.Dataset()
    for name in ("c", "a", "b"):
        dataset.add(primitives.Quad(primitives.NamedNode("http://x/" + name), p, o, g))
    f = StringIO()
    serialize_nquads(dataset, f)
    assert f.getvalue() == (
        "<http://x/c> <http://x/p> <http://x/o> <http://x/g> .\n"
        "<http://x/a> <http://x/p> <http://x/o> <http://x/g> .\n"
        "<http://x/b> <http://x/p> <http://x/o> <http://x/g> .\n"
    )


def to_rdflib(graph):
    import rdflib

    out = rdflib.Graph()

    def term(node):
        if node.interfaceName == "BlankNode":
            return rdflib.BNode(node.value)
        if node.interfaceName == "Literal":
            if node.language:
                return rdflib.Literal(node.value, lang=node.language)
            datatype = node.datatype or "http://www.w3.org/2001/XMLSchema#string"
            return rdflib.Literal(node.value, datatype=rdflib.URIRef(str(datatype)))
        return rdflib.URIRef(str(node))

    for triple in graph:
        out.add((term(triple.subject), term(triple.predicate), term(triple.object)))
    return out


def assert_turtle_round_trip(turtle_parser, serialize_turtle, turtle, profile=None):
    """Serialize the parsed graph and check the reparsed result is isomorphic.
    Returns the serialized text for further assertions."""
    from rdflib.compare import isomorphic

    graph = turtle_parser.parse(turtle)
    f = StringIO()
    serialize_turtle(graph, f, profile=profile)
    reparsed = turtle_parser.parse(f.getvalue())
    assert isomorphic(to_rdflib(graph), to_rdflib(reparsed)), f.getvalue()
    assert len(reparsed) == len(graph)
    return f.getvalue()


@pytest.mark.parametrize(
    "turtle",
    [
        '<http://x/s> <http://x/p> (1 "2" <http://x/o>) .',
        "<http://x/s> <http://x/p> ((1)) .",
        "<http://x/s> <http://x/p> ((1) 2) .",
        "<http://x/s> <http://x/p> (1 (2)) .",
        '<http://x/s> <http://x/p> (1 2 (1 2) (( "a") "b" <http://x/o>)) .',
        "<http://x/a> <http://x/b> ([ <http://x/t> <http://x/c> ]) .",
        "<http://x/a> <http://x/b> (_:x _:x) . _:x <http://x/p> <http://x/o> .",
        "<http://x/s> <http://x/p> () .",
        "<http://x/s> <http://x/p> (()) .",
        "<http://x/s> <http://x/p> (1) . <http://x/t> <http://x/p> (1) .",
    ],
)
def test_turtle_list_object_round_trip(turtle_parser, serialize_turtle, turtle):
    assert_turtle_round_trip(turtle_parser, serialize_turtle, turtle)


def test_turtle_two_lists_as_objects_of_one_predicate(
    primitives, profile, turtle_parser, serialize_turtle
):
    from rdflib.compare import isomorphic

    profile.setPrefix("ex", primitives.NamedNode("http://x/"))
    graph = turtle_parser.parse(
        "<http://x/s> <http://x/p> (1) . <http://x/s> <http://x/p> (2) ."
    )
    f = StringIO()
    serialize_turtle(graph, f, profile=profile)
    assert "ex:s ex:p (1),\n" "          (2) ;\n" in f.getvalue()
    reparsed = turtle_parser.parse(f.getvalue())
    assert isomorphic(to_rdflib(graph), to_rdflib(reparsed))


def test_turtle_list_with_iri_blank_node_and_nested_list_members(
    primitives, profile, turtle_parser, serialize_turtle
):
    profile.setPrefix("ex", primitives.NamedNode("http://x/"))
    text = assert_turtle_round_trip(
        turtle_parser,
        serialize_turtle,
        '<http://x/s> <http://x/p> (1 <http://x/o> ("a" ()) [ <http://x/q> 2 ]) .',
        profile,
    )
    assert 'ex:s ex:p (1 ex:o ("a" rdf:nil) _:b0) ;' in text
    assert "_:b0 ex:q 2 ;" in text
    assert "rdf:first" not in text


@pytest.mark.parametrize(
    "turtle",
    [
        "(1) <http://x/p> <http://x/o> .",
        "(1) <http://x/p> (1) .",
        "(()) <http://x/p> (()) .",
        '(1 2 (1 2)) <http://x/p> (( "a") "b" <http://x/o>) .',
        "(1) <http://x/p> <http://x/o> ; <http://x/q> (2) .",
        "() <http://x/p> <http://x/o> .",
    ],
)
def test_turtle_list_subject_round_trip(turtle_parser, serialize_turtle, turtle):
    assert_turtle_round_trip(turtle_parser, serialize_turtle, turtle)


def test_turtle_list_subject_output(
    primitives, profile, turtle_parser, serialize_turtle
):
    profile.setPrefix("ex", primitives.NamedNode("http://x/"))
    text = assert_turtle_round_trip(
        turtle_parser,
        serialize_turtle,
        '(1 "2") <http://x/p> <http://x/o> ; <http://x/q> (3) .',
        profile,
    )
    assert text.endswith('(1 "2") ex:p ex:o ;\n' "        ex:q (3) ;\n" "        .\n\n")
    assert "rdf:first" not in text
    assert "rdf:rest" not in text


def test_turtle_empty_list_is_rdf_nil(
    primitives, profile, turtle_parser, serialize_turtle
):
    profile.setPrefix("ex", primitives.NamedNode("http://x/"))
    text = assert_turtle_round_trip(
        turtle_parser,
        serialize_turtle,
        "<http://x/s> <http://x/p> () . () <http://x/q> <http://x/o> .",
        profile,
    )
    assert "ex:s ex:p rdf:nil ;" in text
    assert "rdf:nil ex:q ex:o ;" in text


@pytest.mark.parametrize(
    "turtle",
    [
        # The head is both an object and has its own predicates, so it must
        # keep a label rather than be written as ( ... ) twice.
        "<http://x/s> <http://x/p> _:l . _:l <http://x/q> <http://x/o> ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 1 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> () .",
        # Referenced twice.
        "<http://x/s> <http://x/p> _:l . <http://x/t> <http://x/p> _:l ."
        " _:l <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 1 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> () .",
        # A named node with rdf:first/rdf:rest is not a collection.
        "<http://x/l> <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 1 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> () .",
        # Two rdf:first values.
        "<http://x/s> <http://x/p> _:l ."
        " _:l <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 1, 2 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> () .",
        # A cell in the middle of the chain with an extra predicate.
        "<http://x/s> <http://x/p> _:l . _:l"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 1 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> _:m . _:m"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 2 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> () ;"
        " <http://x/q> <http://x/o> .",
        # A chain that never reaches rdf:nil.
        "<http://x/s> <http://x/p> _:l . _:l"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 1 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> <http://x/end> .",
        # Cycles through rdf:first and rdf:rest.
        "_:l <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> _:l ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> () .",
        "_:l <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> _:m ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> () . _:m"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> _:l ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> () .",
        "_:l <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 1 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> _:l .",
        # rdf:nil as a subject.
        "<http://www.w3.org/1999/02/22-rdf-syntax-ns#nil> <http://x/p> <http://x/o> .",
    ],
)
def test_turtle_malformed_list_round_trip(turtle_parser, serialize_turtle, turtle):
    assert_turtle_round_trip(turtle_parser, serialize_turtle, turtle)


# stable=True ---------------------------------------------------------------


def shuffled_relabelled(graph, seed):
    """A copy with fresh blank nodes and its triples added in another order."""
    import random

    from pymantic.primitives import BlankNode, Graph, Triple

    rng = random.Random(seed)
    fresh = {}

    def term(node):
        if isinstance(node, BlankNode):
            return fresh.setdefault(node, BlankNode())
        return node

    triples = [Triple(term(s), term(p), term(o)) for s, p, o in graph]
    rng.shuffle(triples)
    return Graph().addAll(triples)


STABLE_SHAPES = """
@prefix : <http://x/> .
:Shape :property [ :path :name ; :minCount 1 ] ,
                 [ :path :age ; :in ( 1 2 3 ) ] ,
                 [ :path :pet ; :or ( [ :class :Cat ] [ :class :Dog ] ) ] .
:Shape :label "Shape" , "Forme"@fr ; :type :NodeShape .
"""


def stable_turtle(graph, serialize_turtle, profile):
    f = StringIO()
    serialize_turtle(graph, f, profile=profile, stable=True)
    return f.getvalue()


def objects_under(text, predicate_name):
    """The object names written under one predicate, in order."""
    import re

    (objects,) = re.findall(r"%s (.*?) ;\n" % re.escape(predicate_name), text, re.S)
    return [name.strip() for name in objects.split(",")]


def test_turtle_stable_is_byte_identical_after_shuffle_and_relabel(
    primitives, profile, turtle_parser, serialize_turtle
):
    profile.setPrefix("ex", primitives.NamedNode("http://x/"))
    graph = turtle_parser.parse(STABLE_SHAPES)
    first = stable_turtle(graph, serialize_turtle, profile)
    for seed in range(4):
        copy = shuffled_relabelled(graph, seed)
        assert stable_turtle(copy, serialize_turtle, profile) == first
    reparsed = turtle_parser.parse(first)
    from rdflib.compare import isomorphic

    assert isomorphic(to_rdflib(graph), to_rdflib(reparsed))


def test_turtle_stable_uses_canonical_labels(
    primitives, profile, turtle_parser, serialize_turtle
):
    from pymantic.compare import canonical_labels

    # Every blank node here is referenced twice, so none is inlined.
    graph = turtle_parser.parse(
        "@prefix : <http://x/> . :s :p _:a, _:b . :t :p _:a, _:b ."
        " _:a :path :name . _:b :path :age ."
    )
    text = stable_turtle(graph, serialize_turtle, profile)
    labels = canonical_labels(graph)
    for triple in graph:
        node = triple.subject
        if node.interfaceName == "BlankNode":
            assert "_:" + labels[node] + " " in text
    assert "_:b0 " not in text


def test_turtle_stable_orders_sibling_blank_nodes_by_canonical_form(
    primitives, profile, turtle_parser, serialize_turtle
):
    import re

    from pymantic.compare import canonical_labels_and_order

    profile.setPrefix("ex", primitives.NamedNode("http://x/"))
    graph = turtle_parser.parse(STABLE_SHAPES)
    text = stable_turtle(graph, serialize_turtle, profile)
    labels, order = canonical_labels_and_order(graph)
    path = primitives.NamedNode("http://x/path")
    siblings = [
        t.object
        for t in graph.match(predicate=primitives.NamedNode("http://x/property"))
    ]
    # The siblings are inlined, so their order shows in the order of their
    # ex:path values rather than of their labels.
    expected = [
        profile.prefixes.shrink(next(graph.match(subject=n, predicate=path)).object)
        for n in sorted(siblings, key=order.__getitem__)
    ]
    assert re.findall(r"ex:path (ex:\w+)", text) == expected
    assert objects_under(text, "ex:label") == ['"Forme"@fr', '"Shape"']


def test_turtle_stable_mixed_objects_named_before_blank(
    primitives, profile, turtle_parser, serialize_turtle
):
    profile.setPrefix("ex", primitives.NamedNode("http://x/"))
    graph = turtle_parser.parse(
        '@prefix : <http://x/> . :s :p [ :v 1 ] , :b , "a" , :a .'
    )
    text = stable_turtle(graph, serialize_turtle, profile)
    objects = objects_under(text, "ex:s ex:p")
    assert objects == ['"a"', "ex:a", "ex:b", "[ ex:v 1 ]"]


def test_turtle_stable_self_referencing_list_is_deterministic(
    primitives, profile, turtle_parser, serialize_turtle
):
    turtle = (
        "@prefix : <http://x/> . "
        "_:l <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 1 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> _:l ."
        "_:m <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 2 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> _:m ."
    )
    graph = turtle_parser.parse(turtle)
    first = stable_turtle(graph, serialize_turtle, profile)
    for seed in range(4):
        copy = shuffled_relabelled(graph, seed)
        assert stable_turtle(copy, serialize_turtle, profile) == first


def test_turtle_default_output_unchanged_by_stable_keyword(
    primitives, profile, turtle_parser, serialize_turtle
):
    graph = turtle_parser.parse(STABLE_SHAPES)
    plain, explicit = StringIO(), StringIO()
    serialize_turtle(graph, plain, profile=profile)
    serialize_turtle(graph, explicit, profile=profile, stable=False)
    assert plain.getvalue() == explicit.getvalue()
    assert "_:b0 " in plain.getvalue()


# Inline blank nodes in stable mode -----------------------------------------


def stable_round_trip(turtle_parser, serialize_turtle, profile, turtle):
    """Stable output of the parsed graph, checked to be the same after a
    shuffle and to reparse to an isomorphic graph."""
    from pymantic.compare import isomorphic

    graph = turtle_parser.parse(turtle)
    text = stable_turtle(graph, serialize_turtle, profile)
    for seed in range(3):
        copy = shuffled_relabelled(graph, seed)
        assert stable_turtle(copy, serialize_turtle, profile) == text
    reparsed = turtle_parser.parse(text)
    assert isomorphic(graph, reparsed), text
    assert len(reparsed) == len(graph)
    return text


@pytest.fixture()
def ex_profile(primitives, profile):
    profile.setPrefix("ex", primitives.NamedNode("http://x/"))
    return profile


def test_turtle_stable_inlines_single_reference_blank_node(
    ex_profile, turtle_parser, serialize_turtle
):
    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> . :s :p [ :b 2 ; :a 1 ] .",
    )
    assert "ex:s ex:p [ ex:a 1 ;\n" "            ex:b 2 ] ;\n" "     .\n" in text
    assert "_:" not in text


def test_turtle_stable_inlines_nested_blank_nodes(
    ex_profile, turtle_parser, serialize_turtle
):
    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> . :s :p [ :d 3 ; :a [ :c 2 ; :b 1 ] ] .",
    )
    assert (
        "ex:s ex:p [ ex:a [ ex:b 1 ;\n"
        "                   ex:c 2 ] ;\n"
        "            ex:d 3 ] ;\n"
        "     .\n"
    ) in text
    assert "_:" not in text


def test_turtle_stable_inline_objects_of_one_predicate_align(
    ex_profile, turtle_parser, serialize_turtle
):
    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> . :s :p [ :v 1 ; :w 2 ], :o .",
    )
    assert (
        "ex:s ex:p ex:o,\n"
        "          [ ex:v 1 ;\n"
        "            ex:w 2 ] ;\n"
        "     .\n"
    ) in text


def test_turtle_stable_keeps_label_for_blank_node_referenced_twice(
    ex_profile, turtle_parser, serialize_turtle
):
    import re

    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> . :s :p _:x . :t :p _:x . _:x :a 1 .",
    )
    labels = set(re.findall(r"_:b[0-9a-f]{12}", text))
    assert len(labels) == 1
    (label,) = labels
    assert text.count(label) == 3
    assert "[" not in text


def test_turtle_stable_cycle_back_to_ancestor_keeps_label(
    ex_profile, turtle_parser, serialize_turtle
):
    from pymantic.compare import canonical_labels

    graph = turtle_parser.parse(
        "@prefix : <http://x/> . :s :p _:a . _:a :p _:b . _:b :p _:a ."
    )
    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> . :s :p _:a . _:a :p _:b . _:b :p _:a .",
    )
    (a,) = [t.object for t in graph if str(t.subject) == "http://x/s"]
    label = "_:" + canonical_labels(graph)[a]
    # _:a is referenced from ex:s and again from the node inlined under it,
    # so it keeps its label; _:b has one reference and is inlined.
    assert f"ex:s ex:p {label} ;\n" in text
    assert f"{label} ex:p [ ex:p {label} ] ;\n" in text


def test_turtle_stable_cycle_of_single_reference_nodes_is_deterministic(
    ex_profile, turtle_parser, serialize_turtle
):
    import re

    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> . _:a :p _:b . _:b :p _:c . _:c :p _:a .",
    )
    # Nothing outside the cycle refers to it, so one node keeps its label
    # and is written as a subject; the others are inlined beneath it.
    labels = set(re.findall(r"_:b[0-9a-f]{12}n\d", text))
    assert len(labels) == 1
    (label,) = labels
    assert f"{label} ex:p [ ex:p [ ex:p {label} ] ] ;\n" in text


def test_turtle_stable_empty_blank_node_is_brackets(
    ex_profile, turtle_parser, serialize_turtle
):
    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> . :s :p [] .",
    )
    assert "ex:s ex:p [] ;\n" in text
    assert "_:" not in text


def test_turtle_stable_list_of_inline_blank_nodes(
    ex_profile, turtle_parser, serialize_turtle
):
    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> . :s :p ( [ :a 1 ] [ :a 2 ; :b 3 ] ) .",
    )
    assert (
        "ex:s ex:p ([ ex:a 1 ] [ ex:a 2 ;\n"
        "                        ex:b 3 ]) ;\n"
        "     .\n"
    ) in text
    assert "_:" not in text


def test_turtle_stable_list_head_with_other_predicates_is_not_inlined(
    ex_profile, turtle_parser, serialize_turtle
):
    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> . :s :p _:l . _:l :q :o ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 1 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> () .",
    )
    assert "[" not in text
    assert "rdf:first 1 ;" in text


def test_turtle_stable_list_subject_with_inline_members(
    ex_profile, turtle_parser, serialize_turtle
):
    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> . ( [ :a 1 ] [ :a 2 ] ) :p [ :b 3 ] .",
    )
    assert "([ ex:a 1 ] [ ex:a 2 ]) ex:p [ ex:b 3 ] ;\n" in text
    assert "_:" not in text


@pytest.mark.parametrize(
    "turtle",
    [
        # A node that refers to itself.
        "@prefix : <http://x/> . _:a :p _:a .",
        # An inline node whose object is a shared node.
        "@prefix : <http://x/> . :s :p [ :q _:x ] . :t :p _:x . _:x :a 1 .",
        # A list that contains itself, with inline members.
        "_:l <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> [ <http://x/a> 1 ] ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> _:l .",
        # Inline nodes nested in lists nested in inline nodes.
        "@prefix : <http://x/> . :s :p [ :or ( [ :c :A ] [ :c :B ; :in ( 1 [] ) ] ) ] .",
        # A broken chain written as ordinary triples with an inline tail.
        "@prefix : <http://x/> . :s :p _:c ."
        " _:c <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 1 ;"
        " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> [ :q :o ] .",
    ],
)
def test_turtle_stable_inline_shapes_round_trip(
    ex_profile, turtle_parser, serialize_turtle, turtle
):
    stable_round_trip(turtle_parser, serialize_turtle, ex_profile, turtle)


def blank_node_chain(primitives, length):
    """s p [ p [ p ... "end" ] ]: ``length`` blank nodes, each the object of
    exactly one triple."""
    p = primitives.NamedNode("http://x/p")
    graph = primitives.Graph()
    previous = primitives.NamedNode("http://x/s")
    for _ in range(length):
        node = primitives.BlankNode()
        graph.add(primitives.Triple(previous, p, node))
        previous = node
    graph.add(primitives.Triple(previous, p, primitives.Literal("end")))
    return graph


def bracket_nesting(text, opening="[", closing="]"):
    """The deepest nesting of the given brackets in Turtle text that has no
    brackets in literals. ``opening`` and ``closing`` may name several
    characters each, to count [ and ( together."""
    depth = deepest = 0
    for char in text:
        if char in opening:
            depth += 1
            deepest = max(deepest, depth)
        elif char in closing:
            depth -= 1
    assert depth == 0
    return deepest


def test_turtle_stable_caps_inline_nesting_depth(
    primitives, turtle_parser, serialize_turtle
):
    from pymantic.compare import isomorphic
    from pymantic.serializers import MAX_INLINE_DEPTH

    graph = blank_node_chain(primitives, 500)
    profile = primitives.Profile()
    text = stable_turtle(graph, serialize_turtle, profile)
    assert bracket_nesting(text) == MAX_INLINE_DEPTH
    for seed in range(2):
        copy = shuffled_relabelled(graph, seed)
        assert stable_turtle(copy, serialize_turtle, profile) == text
    reparsed = turtle_parser.parse(text)
    assert isomorphic(graph, reparsed)
    assert len(reparsed) == len(graph)


def test_turtle_stable_inline_depth_boundary(primitives, serialize_turtle):
    from pymantic.serializers import MAX_INLINE_DEPTH

    profile = primitives.Profile()
    within = stable_turtle(
        blank_node_chain(primitives, MAX_INLINE_DEPTH), serialize_turtle, profile
    )
    assert "_:" not in within
    assert bracket_nesting(within) == MAX_INLINE_DEPTH
    beyond = stable_turtle(
        blank_node_chain(primitives, MAX_INLINE_DEPTH + 1), serialize_turtle, profile
    )
    # The node past the cap keeps its label: named once as an object and
    # once as the subject of its own block.
    assert beyond.count("_:") == 2
    assert bracket_nesting(beyond) == MAX_INLINE_DEPTH


def nested_list(primitives, depth):
    """s p ((( ... ("end") ... ))): ``depth`` one-member lists, each the
    member of the next."""
    rdf = primitives.Prefix("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    graph = primitives.Graph()
    member = primitives.Literal("end")
    for _ in range(depth):
        head = primitives.BlankNode()
        graph.add(primitives.Triple(head, rdf("first"), member))
        graph.add(primitives.Triple(head, rdf("rest"), rdf("nil")))
        member = head
    graph.add(
        primitives.Triple(
            primitives.NamedNode("http://x/s"),
            primitives.NamedNode("http://x/p"),
            member,
        )
    )
    return graph


def alternating_chain(primitives, length):
    """s p [ p ( [ p ( ... "end" ) ] ) ]: ``length`` levels alternating an
    inline blank node and a one-member list."""
    rdf = primitives.Prefix("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    p = primitives.NamedNode("http://x/p")
    graph = primitives.Graph()
    member = primitives.Literal("end")
    for level in range(length):
        node = primitives.BlankNode()
        if level % 2:
            graph.add(primitives.Triple(node, p, member))
        else:
            graph.add(primitives.Triple(node, rdf("first"), member))
            graph.add(primitives.Triple(node, rdf("rest"), rdf("nil")))
        member = node
    graph.add(primitives.Triple(primitives.NamedNode("http://x/s"), p, member))
    return graph


@pytest.mark.parametrize("stable", [False, True])
def test_turtle_caps_collection_nesting_depth(
    primitives, turtle_parser, serialize_turtle, stable
):
    """A list nested deeper than the cap is written without recursing as
    deep as the data: the head past the cap keeps its label and is written
    as a block of rdf:first/rdf:rest triples, which reads back as the same
    list."""
    from pymantic.compare import isomorphic
    from pymantic.serializers import MAX_INLINE_DEPTH

    graph = nested_list(primitives, 500)
    profile = primitives.Profile()
    f = StringIO()
    serialize_turtle(graph, f, profile=profile, stable=stable)
    text = f.getvalue()
    assert bracket_nesting(text, "(", ")") == MAX_INLINE_DEPTH
    assert "rdf:first" in text
    if stable:
        for seed in range(2):
            copy = shuffled_relabelled(graph, seed)
            assert stable_turtle(copy, serialize_turtle, profile) == text
    reparsed = turtle_parser.parse(text)
    assert isomorphic(graph, reparsed)
    assert len(reparsed) == len(graph)


def test_turtle_stable_collection_depth_boundary(
    primitives, turtle_parser, serialize_turtle
):
    from pymantic.compare import isomorphic
    from pymantic.serializers import MAX_INLINE_DEPTH

    profile = primitives.Profile()
    within = stable_turtle(
        nested_list(primitives, MAX_INLINE_DEPTH), serialize_turtle, profile
    )
    assert "_:" not in within
    assert "rdf:first" not in within
    assert bracket_nesting(within, "(", ")") == MAX_INLINE_DEPTH
    graph = nested_list(primitives, MAX_INLINE_DEPTH + 1)
    beyond = stable_turtle(graph, serialize_turtle, profile)
    # The innermost list is past the cap: its head is named once as the
    # member of the list above it and once as the subject of its own
    # rdf:first/rdf:rest block.
    assert beyond.count("_:") == 2
    assert 'rdf:first "end" ;' in beyond
    assert bracket_nesting(beyond, "(", ")") == MAX_INLINE_DEPTH
    reparsed = turtle_parser.parse(beyond)
    assert isomorphic(graph, reparsed)
    assert len(reparsed) == len(graph)


def test_turtle_stable_lists_and_inline_nodes_share_the_depth_cap(
    primitives, turtle_parser, serialize_turtle
):
    from pymantic.compare import isomorphic
    from pymantic.serializers import MAX_INLINE_DEPTH

    graph = alternating_chain(primitives, 200)
    profile = primitives.Profile()
    text = stable_turtle(graph, serialize_turtle, profile)
    assert bracket_nesting(text, "[(", "])") == MAX_INLINE_DEPTH
    for seed in range(2):
        copy = shuffled_relabelled(graph, seed)
        assert stable_turtle(copy, serialize_turtle, profile) == text
    reparsed = turtle_parser.parse(text)
    assert isomorphic(graph, reparsed)
    assert len(reparsed) == len(graph)


# Used prefixes only in stable mode -----------------------------------------


def directives(text):
    return [line for line in text.splitlines() if line.startswith("@")]


def test_turtle_stable_declares_only_used_prefixes(
    primitives, ex_profile, turtle_parser, serialize_turtle
):
    ex_profile.setPrefix("unused", primitives.NamedNode("http://unused/"))
    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> . @prefix xsd: <http://www.w3.org/2001/XMLSchema#> ."
        ' :s :p "2020-01-01"^^xsd:date .',
    )
    assert directives(text) == [
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix ex: <http://x/> .",
    ]


@pytest.mark.parametrize(
    "turtle, declared",
    [
        ("@prefix : <http://x/> . :s :p 1 .", False),
        ("@prefix : <http://x/> . :s a :C .", True),
        ("@prefix : <http://x/> . :s :p () .", True),
        (
            "@prefix : <http://x/> . :s :p _:l . _:l :q :o ;"
            " <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> 1 ;"
            " <http://www.w3.org/1999/02/22-rdf-syntax-ns#rest> () .",
            True,
        ),
    ],
)
def test_turtle_stable_declares_rdf_exactly_when_written(
    ex_profile, turtle_parser, serialize_turtle, turtle, declared
):
    text = stable_round_trip(turtle_parser, serialize_turtle, ex_profile, turtle)
    rdf_line = "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> ."
    assert (rdf_line in directives(text)) == declared
    assert ("rdf:" in text.split("\n", len(directives(text)))[-1]) == declared


def test_turtle_stable_prefix_unused_when_local_name_falls_back_to_iri(
    primitives, ex_profile, turtle_parser, serialize_turtle
):
    ex_profile.setPrefix("y", primitives.NamedNode("http://y/"))
    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "<http://x/a[b]> <http://y/p> <http://y/o> .",
    )
    assert directives(text) == ["@prefix y: <http://y/> ."]
    assert "<http://x/a[b]> y:p y:o ;" in text


def test_turtle_stable_exact_output(ex_profile, turtle_parser, serialize_turtle):
    text = stable_round_trip(
        turtle_parser,
        serialize_turtle,
        ex_profile,
        "@prefix : <http://x/> ."
        " :Shape :property [ :path :age ; :in ( 1 2 ) ; :node [ :class :Age ] ] ;"
        ' :label "Shape" ; :type :NodeShape .',
    )
    assert text == (
        "@prefix ex: <http://x/> .\n"
        'ex:Shape ex:label "Shape" ;\n'
        "         ex:property [ ex:in (1 2) ;\n"
        "                       ex:node [ ex:class ex:Age ] ;\n"
        "                       ex:path ex:age ] ;\n"
        "         ex:type ex:NodeShape ;\n"
        "         .\n"
        "\n"
    )


def test_turtle_default_mode_declares_every_prefix(
    primitives, ex_profile, turtle_parser, serialize_turtle
):
    ex_profile.setPrefix("unused", primitives.NamedNode("http://unused/"))
    graph = turtle_parser.parse("@prefix : <http://x/> . :s :p 1 .")
    f = StringIO()
    serialize_turtle(graph, f, profile=ex_profile)
    assert directives(f.getvalue()) == [
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix ex: <http://x/> .",
        "@prefix unused: <http://unused/> .",
    ]


def test_ntriples_stable_sorts_lines_with_canonical_labels(primitives, turtle_parser):
    from pymantic.compare import canonical_labels

    graph = turtle_parser.parse(STABLE_SHAPES)
    labels = canonical_labels(graph)
    f = StringIO()
    serialize_ntriples(graph, f, stable=True)
    lines = f.getvalue().splitlines(keepends=True)
    assert lines == sorted(lines)
    assert len(lines) == len(graph)
    assert all(line.endswith(" .\n") for line in lines)
    for label in labels.values():
        assert any("_:" + label + " " in line for line in lines)
    for seed in range(4):
        g = StringIO()
        serialize_ntriples(shuffled_relabelled(graph, seed), g, stable=True)
        assert g.getvalue() == f.getvalue()
    reparsed = ntriples_parser.parse_string(f.getvalue())
    from pymantic.compare import isomorphic

    assert isomorphic(graph, reparsed)


def test_ntriples_default_output_unchanged_by_stable_keyword(primitives):
    p = primitives.NamedNode("http://x/p")
    graph = primitives.Graph()
    for name in ("c", "a"):
        graph.add(primitives.Triple(primitives.NamedNode("http://x/" + name), p, p))
    plain, explicit = StringIO(), StringIO()
    serialize_ntriples(graph, plain)
    serialize_ntriples(graph, explicit, stable=False)
    assert plain.getvalue() == explicit.getvalue()
    assert plain.getvalue().startswith("<http://x/c>")


def test_nquads_stable_sorts_lines_with_canonical_labels(primitives):
    import random

    from pymantic.serializers import serialize_nquads

    p = primitives.NamedNode("http://x/p")
    g1, g2 = primitives.NamedNode("http://x/g1"), primitives.NamedNode("http://x/g2")

    def build(seed):
        a, b = primitives.BlankNode(), primitives.BlankNode()
        quads = [
            primitives.Quad(a, p, primitives.NamedNode("http://x/o"), g1),
            primitives.Quad(a, p, b, g2),
            primitives.Quad(b, p, primitives.Literal("v"), None),
            primitives.Quad(primitives.NamedNode("http://x/s"), p, b, None),
        ]
        random.Random(seed).shuffle(quads)
        dataset = primitives.Dataset()
        dataset.addAll(quads)
        return dataset

    f = StringIO()
    serialize_nquads(build(0), f, stable=True)
    lines = f.getvalue().splitlines(keepends=True)
    assert lines == sorted(lines)
    assert len(lines) == 4
    assert "_:b0 " not in f.getvalue()
    assert any(line.endswith(" <http://x/g2> .\n") for line in lines)
    for seed in range(1, 4):
        g = StringIO()
        serialize_nquads(build(seed), g, stable=True)
        assert g.getvalue() == f.getvalue()


def test_nquads_stable_accepts_parsed_quads(primitives):
    from pymantic.parsers import nquads_parser
    from pymantic.serializers import serialize_nquads

    text = "_:x <http://x/p> _:y <http://x/g> .\n" '_:y <http://x/p> "v" .\n'
    f = StringIO()
    serialize_nquads(nquads_parser.parse_string(text), f, stable=True)
    lines = f.getvalue().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith(" <http://x/g> .") or lines[1].endswith(" <http://x/g> .")
    assert "_:x" not in f.getvalue()


def equivalent_string_graphs(primitives):
    """Three graphs that are one RDF graph: "v" as a simple literal, as an
    explicit xsd:string, and as both written forms at once. The two forms are
    one term, so the third graph holds one triple like the others."""
    s, p = primitives.NamedNode("http://x/s"), primitives.NamedNode("http://x/p")
    simple = primitives.Literal("v")
    typed = primitives.Literal("v", datatype=primitives.XSD_STRING)
    assert simple == typed
    return [
        primitives.Graph().addAll(primitives.Triple(s, p, o) for o in objects)
        for objects in ([simple], [typed], [simple, typed])
    ]


def test_ntriples_stable_writes_equivalent_literals_once(primitives):
    outputs = []
    for graph in equivalent_string_graphs(primitives):
        f = StringIO()
        serialize_ntriples(graph, f, stable=True)
        outputs.append(f.getvalue())
    assert outputs[0] == outputs[1] == outputs[2]
    assert outputs[2] == '<http://x/s> <http://x/p> "v" .\n'


def test_ntriples_default_output_writes_equivalent_literals_once(primitives):
    """Default output writes whatever the graph holds, and the graph holds
    the value once however it was written."""
    graph = equivalent_string_graphs(primitives)[2]
    f = StringIO()
    serialize_ntriples(graph, f)
    assert f.getvalue().count('"v"') == 1


def test_nquads_stable_writes_equivalent_literals_once(primitives):
    from pymantic.serializers import serialize_nquads

    g = primitives.NamedNode("http://x/g")
    outputs = []
    for graph in equivalent_string_graphs(primitives):
        dataset = primitives.Dataset()
        for triple in graph:
            dataset.add(primitives.Quad(*triple, g))
        f = StringIO()
        serialize_nquads(dataset, f, stable=True)
        outputs.append(f.getvalue())
    assert outputs[0] == outputs[1] == outputs[2]
    assert outputs[2] == '<http://x/s> <http://x/p> "v" <http://x/g> .\n'


def test_turtle_stable_writes_equivalent_literals_once(primitives, serialize_turtle):
    outputs = [
        stable_turtle(graph, serialize_turtle, primitives.Profile())
        for graph in equivalent_string_graphs(primitives)
    ]
    assert outputs[0] == outputs[1] == outputs[2]
    assert outputs[2].count('"v"') == 1


def test_turtle_default_output_writes_equivalent_literals_once(
    primitives, serialize_turtle
):
    """Default output writes whatever the graph holds, and the graph holds
    the value once however it was written."""
    graph = equivalent_string_graphs(primitives)[2]
    f = StringIO()
    serialize_turtle(graph, f)
    assert f.getvalue().count('"v"') == 1


def test_turtle_stable_keeps_distinct_blank_nodes_that_render_alike(
    primitives, turtle_parser, serialize_turtle
):
    """Two empty blank nodes are two terms even though both are written []."""
    from pymantic.compare import isomorphic

    graph = turtle_parser.parse("<http://x/s> <http://x/p> [] , [] .")
    text = stable_turtle(graph, serialize_turtle, primitives.Profile())
    assert text.count("[]") == 2
    assert isomorphic(graph, turtle_parser.parse(text))


def test_turtle_stable_collection_head_with_equivalent_literal_firsts(
    primitives, serialize_turtle
):
    """A list cell whose rdf:first is asserted in both written literal forms
    (a simple literal and one typed xsd:string) is still one well-formed
    one-element list -- RDF 1.1 Concepts 3.3 makes the two forms one term --
    and is written as a collection exactly as if it held only one form."""
    rdf = primitives.Prefix("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    s, p = primitives.NamedNode("http://x/s"), primitives.NamedNode("http://x/p")

    def build(literals):
        graph = primitives.Graph()
        head = primitives.BlankNode()
        for literal in literals:
            graph.add(primitives.Triple(head, rdf("first"), literal))
        graph.add(primitives.Triple(head, rdf("rest"), rdf("nil")))
        graph.add(primitives.Triple(s, p, head))
        return graph

    mixed = build(
        [
            primitives.Literal("v"),
            primitives.Literal("v", datatype=primitives.XSD_STRING),
        ]
    )
    single = build([primitives.Literal("v")])
    profile = primitives.Profile()
    mixed_text = stable_turtle(mixed, serialize_turtle, profile)
    single_text = stable_turtle(single, serialize_turtle, profile)
    assert mixed_text == single_text
    assert '("v")' in mixed_text


def mixed_literal_forms_graph(primitives):
    """A graph holding a value written in both literal forms (a simple
    literal and one typed xsd:string) at once, in three subject-less
    positions: the objects of an ordinary predicate, inside an inline blank
    node, and as a list cell's rdf:first. Isomorphic to, and one RDF graph
    with, ``single_literal_form_graph``."""
    rdf = primitives.Prefix("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    s = primitives.NamedNode("http://x/s")
    p1 = primitives.NamedNode("http://x/p1")
    p2 = primitives.NamedNode("http://x/p2")
    p3 = primitives.NamedNode("http://x/p3")
    q = primitives.NamedNode("http://x/q")

    def forms(value):
        return [
            primitives.Literal(value),
            primitives.Literal(value, datatype=primitives.XSD_STRING),
        ]

    graph = primitives.Graph()
    for literal in forms("v"):
        graph.add(primitives.Triple(s, p1, literal))
    inline_node = primitives.BlankNode()
    graph.add(primitives.Triple(s, p2, inline_node))
    for literal in forms("w"):
        graph.add(primitives.Triple(inline_node, q, literal))
    head = primitives.BlankNode()
    for literal in forms("x"):
        graph.add(primitives.Triple(head, rdf("first"), literal))
    graph.add(primitives.Triple(head, rdf("rest"), rdf("nil")))
    graph.add(primitives.Triple(s, p3, head))
    return graph


def single_literal_form_graph(primitives):
    """The graph ``mixed_literal_forms_graph`` is equivalent to, with each
    position holding only one literal form."""
    rdf = primitives.Prefix("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    s = primitives.NamedNode("http://x/s")
    p1 = primitives.NamedNode("http://x/p1")
    p2 = primitives.NamedNode("http://x/p2")
    p3 = primitives.NamedNode("http://x/p3")
    q = primitives.NamedNode("http://x/q")

    graph = primitives.Graph()
    graph.add(primitives.Triple(s, p1, primitives.Literal("v")))
    inline_node = primitives.BlankNode()
    graph.add(primitives.Triple(s, p2, inline_node))
    graph.add(primitives.Triple(inline_node, q, primitives.Literal("w")))
    head = primitives.BlankNode()
    graph.add(primitives.Triple(head, rdf("first"), primitives.Literal("x")))
    graph.add(primitives.Triple(head, rdf("rest"), rdf("nil")))
    graph.add(primitives.Triple(s, p3, head))
    return graph


def test_turtle_stable_mixed_literal_forms_byte_identical(primitives, serialize_turtle):
    profile = primitives.Profile()
    mixed_text = stable_turtle(
        mixed_literal_forms_graph(primitives), serialize_turtle, profile
    )
    single_text = stable_turtle(
        single_literal_form_graph(primitives), serialize_turtle, profile
    )
    assert mixed_text == single_text
    assert mixed_text.count('"v"') == 1
    assert mixed_text.count('"w"') == 1
    assert mixed_text.count('"x"') == 1


def test_ntriples_stable_mixed_literal_forms_byte_identical(primitives):
    f_mixed, f_single = StringIO(), StringIO()
    serialize_ntriples(mixed_literal_forms_graph(primitives), f_mixed, stable=True)
    serialize_ntriples(single_literal_form_graph(primitives), f_single, stable=True)
    assert f_mixed.getvalue() == f_single.getvalue()


def test_nquads_stable_mixed_literal_forms_byte_identical(primitives):
    from pymantic.serializers import serialize_nquads

    g = primitives.NamedNode("http://x/g")

    def as_dataset(graph):
        dataset = primitives.Dataset()
        for triple in graph:
            dataset.add(primitives.Quad(*triple, g))
        return dataset

    f_mixed, f_single = StringIO(), StringIO()
    serialize_nquads(
        as_dataset(mixed_literal_forms_graph(primitives)), f_mixed, stable=True
    )
    serialize_nquads(
        as_dataset(single_literal_form_graph(primitives)), f_single, stable=True
    )
    assert f_mixed.getvalue() == f_single.getvalue()


def nested_list_as_subject(primitives, depth):
    """(((...("end")...))) :q :r .: ``depth`` one-member lists, each nested
    in the next, with the outermost list as the subject of a statement, so
    plan_collections classifies it as an ``as_subject`` collection (an
    ``( ... ) p o .`` statement) rather than as the object of one."""
    rdf = primitives.Prefix("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    graph = primitives.Graph()
    member = primitives.Literal("end")
    head = None
    for _ in range(depth):
        head = primitives.BlankNode()
        graph.add(primitives.Triple(head, rdf("first"), member))
        graph.add(primitives.Triple(head, rdf("rest"), rdf("nil")))
        member = head
    graph.add(
        primitives.Triple(
            head,
            primitives.NamedNode("http://x/q"),
            primitives.NamedNode("http://x/r"),
        )
    )
    return graph


def test_turtle_stable_collection_subject_depth_boundary(
    primitives, turtle_parser, serialize_turtle
):
    """Members nested beneath a collection subject count the subject's own
    enclosing '(' as one level of nesting, so the cap lands in the same
    place as for a list nested under an ordinary collection object (compare
    test_turtle_stable_collection_depth_boundary)."""
    from pymantic.compare import isomorphic
    from pymantic.serializers import MAX_INLINE_DEPTH

    profile = primitives.Profile()
    within = stable_turtle(
        nested_list_as_subject(primitives, MAX_INLINE_DEPTH), serialize_turtle, profile
    )
    assert "_:" not in within
    assert "rdf:first" not in within
    assert bracket_nesting(within, "(", ")") == MAX_INLINE_DEPTH

    graph = nested_list_as_subject(primitives, MAX_INLINE_DEPTH + 1)
    beyond = stable_turtle(graph, serialize_turtle, profile)
    # The innermost list is past the cap: its head is named once as the
    # member of the list above it and once as the subject of its own
    # rdf:first/rdf:rest block.
    assert beyond.count("_:") == 2
    assert 'rdf:first "end" ;' in beyond
    assert bracket_nesting(beyond, "(", ")") == MAX_INLINE_DEPTH
    reparsed = turtle_parser.parse(beyond)
    assert isomorphic(graph, reparsed)
    assert len(reparsed) == len(graph)


def test_stable_serializers_raise_undecidable(primitives, serialize_turtle):
    from pymantic.compare import Undecidable
    from pymantic.serializers import serialize_nquads

    p = primitives.NamedNode("http://x/p")
    nodes = [primitives.BlankNode() for _ in range(10)]
    graph = primitives.Graph()
    for s in nodes:
        for o in nodes:
            graph.add(primitives.Triple(s, p, o))
    with pytest.raises(Undecidable):
        serialize_turtle(graph, StringIO(), stable=True)
    with pytest.raises(Undecidable):
        serialize_ntriples(graph, StringIO(), stable=True)
    dataset = primitives.Dataset()
    for triple in graph:
        dataset.add(primitives.Quad(*triple, None))
    with pytest.raises(Undecidable):
        serialize_nquads(dataset, StringIO(), stable=True)
