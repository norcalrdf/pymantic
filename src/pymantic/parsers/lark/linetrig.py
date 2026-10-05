"""Parse Line-TriG, the line-oriented TriG profile described in
``docs/line-trig.rst``, into a :py:class:`~pymantic.primitives.Dataset`.

Usage::

  from pymantic.parsers.lark import linetrig_parser
  dataset = linetrig_parser.parse(io.open('a_file.trig', mode='rt'))
  dataset2 = linetrig_parser.parse("<http://a.example/g> { }")

Every line is parsed on its own, so a statement outside the profile is
rejected with a ``ValueError`` naming its line number.
"""

from collections import namedtuple
from lark import Lark
from lark.exceptions import LarkError
import re

from pymantic.primitives import Graph, Quad

from .base import LarkParser
from .ntriples import NTriplesTransformer, grammar

linetrig_grammar = grammar + r"""
linetrig_start: EOL* (statement EOL+)* statement?
?statement: triple | graph_triple | empty_graph
graph_triple: graph_name "{" subject predicate object "." "}"
empty_graph: graph_name "{" "}"
?graph_name: iriref
           | BLANK_NODE_LABEL -> blank_node_label
"""

# A "G { }" line: the dataset has a graph named ``name`` even without triples.
EmptyGraph = namedtuple("EmptyGraph", ["name"])

# Line endings as the N-Triples EOL production defines them. str.splitlines
# would also split inside a literal that holds U+2028 or similar.
LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
TERMINATED_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)")

READ_SIZE = 64 * 1024


def stream_lines(stream):
    """Yield the lines of a text stream split like :py:data:`LINE` splits a
    string, reading it a chunk at a time. A stream's own readline would miss
    a bare CR."""
    pending = ""
    while chunk := stream.read(READ_SIZE):
        pending += chunk
        # A CR at the end of what is read may be the first half of a CRLF.
        end = len(pending) - 1 if pending.endswith("\r") else len(pending)
        consumed = 0
        for match in TERMINATED_LINE.finditer(pending, 0, end):
            yield match.group()
            consumed = match.end()
        pending = pending[consumed:]
    if pending:
        yield pending


class LineTriGTransformer(NTriplesTransformer):
    """Transform the tokenized Line-TriG into quads and empty graph markers."""

    reads_quads = True

    def triple(self, children):
        subject, predicate, object_ = children
        return self.make_quad(subject, predicate, object_, None)

    def graph_triple(self, children):
        graph, subject, predicate, object_ = children
        return self.make_quad(subject, predicate, object_, graph)

    def empty_graph(self, children):
        (name,) = children
        return EmptyGraph(name)

    def linetrig_start(self, children):
        for child in children:
            if isinstance(child, (Quad, EmptyGraph)):
                yield child

    def _make_graph(self):
        return self.env.createDataset()


class LineTriGParser(LarkParser):
    """Parse Line-TriG into a dataset, one line at a time."""

    def parse(self, string_or_stream, dataset=None):
        """Parse a string or file-like object into a dataset, either the
        one provided or a new one."""
        tf = self.lark.options.transformer
        tf._check_sink(dataset)

        try:
            if dataset is None:
                dataset = tf._make_graph()

            tf._prepare_parse(dataset)

            if hasattr(string_or_stream, "read"):
                lines = stream_lines(string_or_stream)
            else:
                lines = LINE.findall(string_or_stream)

            for number, line in enumerate(lines, start=1):
                try:
                    statements = list(self.lark.parse(line))
                except (LarkError, ValueError) as error:
                    raise ValueError(f"line {number}: {error}") from error
                for statement in statements:
                    self._add(dataset, statement)
        finally:
            tf._cleanup_parse()

        return dataset

    def parse_string(self, string_or_bytes, dataset=None):
        """Parse a string, decoding it from bytes to UTF-8 if necessary."""
        if isinstance(string_or_bytes, bytes):
            string_or_bytes = string_or_bytes.decode("utf-8")

        return self.parse(string_or_bytes, dataset)

    @staticmethod
    def _add(dataset, statement):
        if isinstance(statement, EmptyGraph):
            # add_graph takes the union, so an existing graph keeps its triples.
            dataset.add_graph(Graph(), named=statement.name)
        else:
            dataset.add(statement)


linetrig_lark = Lark(
    linetrig_grammar,
    start="linetrig_start",
    parser="lalr",
    transformer=LineTriGTransformer(),
)

# A fully-instantiated Line-TriG parser
linetrig_parser = LineTriGParser(linetrig_lark)
