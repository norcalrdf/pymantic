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
    from pymantic.serializers import nt_escape

    assert nt_escape("a\x00b\x08c\x0cd\x1fe\x7ff") == (
        "a\\u0000b\\u0008c\\u000Cd\\u001Fe\\u007Ff"
    )
    assert nt_escape("tab\tlf\ncr\r") == "tab\\tlf\\ncr\\r"


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
