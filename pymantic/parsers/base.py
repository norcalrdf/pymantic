from collections import defaultdict
from threading import local

import pymantic.primitives


class BaseParser(object):
    """Common base class for all parsers

    Provides shared utilities for creating RDF objects, handling IRIs, and
    tracking parser state.
    """

    def __init__(self, environment=None):
        self.env = environment or pymantic.primitives.RDFEnvironment()
        self.profile = self.env.createProfile()
        self._call_state = local()

    def make_datatype_literal(self, value, datatype):
        return self.env.createLiteral(value=value, datatype=datatype)

    def make_language_literal(self, value, lang=None):
        if lang:
            return self.env.createLiteral(value=value, language=lang)
        else:
            return self.env.createLiteral(value=value)

    def make_named_node(self, iri):
        return self.env.createNamedNode(iri)

    def make_blank_node(self, label=None):
        if label:
            return self._call_state.bnodes[label]
        else:
            return self.env.createBlankNode()

    def make_triple(self, subject, predicate, object):
        return self.env.createTriple(subject, predicate, object)

    def make_quad(self, subject, predicate, object, graph):
        return self.env.createQuad(subject, predicate, object, graph)

    def _prepare_parse(self, graph):
        self._call_state.bnodes = defaultdict(self.env.createBlankNode)
        self._call_state.graph = graph

    def _cleanup_parse(self):
        del self._call_state.bnodes
        del self._call_state.graph

    def _make_graph(self):
        return self.env.createGraph()
