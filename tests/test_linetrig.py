"""Tests for the Line-TriG reader (docs/line-trig.rst)."""

from io import StringIO

import pytest

from pymantic.compare import isomorphic
from pymantic.parsers import linetrig_parser
from pymantic.primitives import Dataset, Graph, NamedNode, Quad
from pymantic.serializers import serialize_linetrig

S = NamedNode("http://e/s")
P = NamedNode("http://e/p")
O = NamedNode("http://e/o")  # noqa: E741
G = NamedNode("http://e/g")
EMPTY = NamedNode("http://e/empty")

TRIPLE = "<http://e/s> <http://e/p> <http://e/o> ."


def test_default_graph_line_is_a_default_graph_quad():
    ds = linetrig_parser.parse(TRIPLE + "\n")
    assert Quad(S, P, O, None) in ds and len(ds) == 1


def test_named_graph_line():
    ds = linetrig_parser.parse("<http://e/g> { " + TRIPLE + " }\n")
    assert Quad(S, P, O, G) in ds and len(ds) == 1


def test_empty_named_graph_exists():
    ds = linetrig_parser.parse("<http://e/g> { }\n")
    assert len(ds) == 0
    assert [g.uri for g in ds.graphs if g.uri is not None] == [G]


def test_empty_graph_line_after_triples_keeps_them():
    ds = linetrig_parser.parse("<http://e/g> { " + TRIPLE + " }\n<http://e/g> { }\n")
    assert Quad(S, P, O, G) in ds and len(ds) == 1


def test_blank_node_label_is_document_scoped():
    ds = linetrig_parser.parse(
        "_:g { _:b <http://e/p> <http://e/o> . }\n_:b <http://e/p> _:g .\n"
    )
    (named,) = [q for q in ds if q.graph is not None]
    (default,) = [q for q in ds if q.graph is None]
    assert named.subject is default.subject and named.graph is default.object


def test_repeated_graph_name_is_a_union():
    ds = linetrig_parser.parse(
        "<http://e/g> { " + TRIPLE + " }\n"
        "<http://e/g> { <http://e/s> <http://e/p> <http://e/o2> . }\n"
    )
    assert len(ds) == 2
    assert Quad(S, P, O, G) in ds
    assert Quad(S, P, NamedNode("http://e/o2"), G) in ds


def test_comments_and_blank_lines_are_ignored():
    ds = linetrig_parser.parse(
        "# a comment\n\n" + TRIPLE + " # trailing\n   \n# another\n"
        "<http://e/g> { " + TRIPLE + " }"
    )
    assert len(ds) == 2


def test_stream_and_string_agree():
    text = TRIPLE + "\n<http://e/g> { " + TRIPLE + " }\n<http://e/h> { }\n"
    assert linetrig_parser.parse(StringIO(text)).toArray() == (
        linetrig_parser.parse_string(text.encode("utf-8")).toArray()
    )


def test_literal_with_line_separator_character_is_one_line():
    ds = linetrig_parser.parse('<http://e/s> <http://e/p> "a b" .\n')
    assert len(ds) == 1


def test_parse_adds_to_the_given_dataset():
    ds = linetrig_parser.parse(TRIPLE + "\n")
    assert linetrig_parser.parse("<http://e/g> { }\n", ds) is ds
    assert len(ds.graphs) == 2


OUT_OF_PROFILE = {
    "two statements on one line": TRIPLE + " " + TRIPLE,
    "two triples in braces": "<http://e/g> { " + TRIPLE + " " + TRIPLE + " }",
    "prefixed name": "ex:s <http://e/p> <http://e/o> .",
    "GRAPH keyword": "GRAPH <http://e/g> { " + TRIPLE + " }",
    "missing dot in braces": "<http://e/g> { <http://e/s> <http://e/p> <http://e/o> }",
    "literal graph name": '"g" { ' + TRIPLE + " }",
}


@pytest.mark.parametrize("line", OUT_OF_PROFILE.values(), ids=OUT_OF_PROFILE.keys())
@pytest.mark.parametrize("wrap", [str, StringIO], ids=["string", "stream"])
def test_out_of_profile_line_is_rejected_with_its_line_number(line, wrap):
    with pytest.raises(ValueError, match="line 2"):
        linetrig_parser.parse(wrap(TRIPLE + "\n" + line + "\n"))


def test_writer_puts_default_graph_first_then_named_then_empty():
    ds = Dataset()
    ds.add(Quad(S, P, O, G))
    ds.add(Quad(S, P, O, None))
    ds.add_graph(Graph(), named=EMPTY)
    out = StringIO()
    serialize_linetrig(ds, out)
    assert out.getvalue() == (
        "<http://e/s> <http://e/p> <http://e/o> .\n"
        "<http://e/g> { <http://e/s> <http://e/p> <http://e/o> . }\n"
        "<http://e/empty> { }\n"
    )


def test_round_trip_keeps_empty_graphs_and_shared_blank_nodes():
    original = linetrig_parser.parse(
        "_:g { _:b <http://e/p> <http://e/o> . }\n"
        "_:b <http://e/p> _:g .\n"
        "<http://e/empty> { }\n"
        '<http://e/g> { <http://e/s> <http://e/p> "a\\nb\\u2028c"@en . }\n'
    )
    out = StringIO()
    serialize_linetrig(original, out)
    reparsed = linetrig_parser.parse(out.getvalue())
    assert isomorphic(original, reparsed)
    assert [g.uri for g in reparsed.graphs if len(g) == 0] == [EMPTY]
