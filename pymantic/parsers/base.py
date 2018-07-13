from collections import defaultdict
from threading import local

from pymantic.compat import (
    binary_type,
)
import pymantic.primitives
from pymantic.util import (
    normalize_iri,
)


class BaseParser(object):
    """Common base class for all parsers

    Provides shared utilities for creating RDF objects, handling IRIs, and
    tracking parser state.
    """

    def __init__(self, environment=None):
        self.env = environment or pymantic.primitives.RDFEnvironment()
        self.profile = self.env.createProfile()
        self._call_state = local()

    def make_datatype_literal(self, values):
        return self.env.createLiteral(value=values[0], datatype=values[1])

    def make_language_literal(self, values):
        if len(values) == 2:
            return self.env.createLiteral(value=values[0], language=values[1])
        else:
            return self.env.createLiteral(value=values[0])

    def make_named_node(self, values):
        return self.env.createNamedNode(normalize_iri(values[0]))

    def make_blank_node(self, values):
        if values[0] not in self._call_state.bnodes:
            self._call_state.bnodes[values[0]] = self.env.createBlankNode()
        return self._call_state.bnodes[values[0]]

    def _prepare_parse(self, graph):
        self._call_state.bnodes = defaultdict(self.env.createBlankNode)
        self._call_state.graph = graph

    def _cleanup_parse(self):
        del self._call_state.bnodes
        del self._call_state.graph

    def _make_graph(self):
        return self.env.createGraph()
