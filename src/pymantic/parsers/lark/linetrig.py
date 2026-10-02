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


class LineTriGTransformer(NTriplesTransformer):
    """Transform the tokenized Line-TriG into quads and empty graph markers."""

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

        try:
            if dataset is None:
                dataset = tf._make_graph()

            tf._prepare_parse(dataset)

            if hasattr(string_or_stream, "readline"):
                lines = string_or_stream
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

    @staticmethod
    def _add(dataset, statement):
        if isinstance(statement, EmptyGraph):
            # add_graph replaces a graph of the same name, which would drop
            # triples from earlier lines. A graph name is a union.
            if not any(graph.uri == statement.name for graph in dataset.graphs):
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
