from lepl import (
    Literal,
    Optional,
    Plus,
    Regexp,
    Space,
    Star,
)

from .base import (
    nt_unescape,
    normalize_iri,
    BaseLeplParser,
)


class BaseNParser(BaseLeplParser):
    """Base parser that establishes common grammar rules and interfaces used for
    parsing both n-triples and n-quads."""

    def __init__(self, environment=None):
        super(BaseNParser, self).__init__(environment)
        self.string = Regexp(
            r'(?:[ -!#-[\]-~]|\\[trn"\\]|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8})*'
        )
        self.name = Regexp(r'[A-Za-z][A-Za-z0-9]*')
        self.absoluteURI = Regexp(
            r'(?:[ -=?-[\]-~]|\\[trn"\\]|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8})+'
        )
        self.language = Regexp(r'[a-z]+(?:-[a-zA-Z0-9]+)*')
        self.uriref = ~Literal('<') & self.absoluteURI & ~Literal('>') \
            > self.make_named_node
        self.datatypeString = ~Literal('"') & self.string & ~Literal('"') \
            & ~Literal('^^') & self.uriref > self.make_datatype_literal
        self.langString = ~Literal('"') & self.string & ~Literal('"') \
            & Optional(
                ~Literal('@') & self.language) > self.make_language_literal
        self.literal = self.datatypeString | self.langString
        self.nodeID = ~Literal('_:') & self.name > self.make_blank_node
        self.object_ = self.uriref | self.nodeID | self.literal
        self.predicate = self.uriref
        self.subject = self.uriref | self.nodeID
        self.comment = Literal('#') & Regexp(r'[ -~]*')

    def make_named_node(self, values):
        return self.env.createNamedNode(normalize_iri(nt_unescape(values[0])))

    def make_language_literal(self, values):
        if len(values) == 2:
            return self.env.createLiteral(value=nt_unescape(values[0]),
                                          language=values[1])
        else:
            return self.env.createLiteral(value=nt_unescape(values[0]))


class NTriplesParser(BaseNParser):
    def make_triple(self, values):
        triple = self.env.createTriple(*values)
        self._call_state.graph.add(triple)
        return triple

    def __init__(self, environment=None):
        super(NTriplesParser, self).__init__(environment)
        self.triple = self.subject & ~Plus(Space()) & self.predicate & \
            ~Plus(Space()) & self.object_ & ~Star(Space()) & ~Literal('.') \
            & ~Star(Space()) >= self.make_triple
        self.line = Star(Space()) & Optional(~self.triple | ~self.comment) & \
            ~Literal('\n')
        self.document = Star(self.line)

    def _make_graph(self):
        return self.env.createGraph()

    def parse(self, f, graph=None):
        return super(NTriplesParser, self).parse(f, graph)


ntriples_parser = NTriplesParser()
