from collections import (
    OrderedDict,
    namedtuple,
)
import re

from lepl import (
    Delayed,
    Eos,
    Literal,
    Optional,
    Regexp,
    Separator,
    Star,
)

from .base import (
    BaseLeplParser,
    discrete_pairs,
)
from pymantic.compat import (
    binary_type,
    unichr,
)
from pymantic.util import (
    smart_urljoin,
)


TriplesClause = namedtuple('TriplesClause', ['subject', 'predicate_objects'])

PredicateObject = namedtuple('PredicateObject', ['predicate', 'object'])

BindPrefix = namedtuple('BindPrefix', ['prefix', 'iri'])

SetBase = namedtuple('SetBase', ['iri'])

NamedNodeToBe = namedtuple('NamedNodeToBe', ['iri'])

LiteralToBe = namedtuple('LiteralToBe', ['value', 'datatype', 'language'])

PrefixReference = namedtuple('PrefixReference', ['prefix', 'local'])


class TurtleParser(BaseLeplParser):
    """Parser for turtle as described at:
    http://dvcs.w3.org/hg/rdf/raw-file/e8b1d7283925/rdf-turtle/index.html"""

    RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'

    echar_map = OrderedDict((
        ('\\', u'\\'),
        ('t', u'\t'),
        ('b', u'\b'),
        ('n', u'\n'),
        ('r', u'\r'),
        ('f', u'\f'),
        ('"', u'"'),
        ("'", u"'"),
    ))
    def __init__(self, environment=None):
        super(TurtleParser, self).__init__(environment)

        UCHAR = (Regexp(r'\\u([0-9a-fA-F]{4})') |\
                 Regexp(r'\\U([0-9a-fA-F]{8})')) >> self.decode_uchar

        ECHAR = Regexp(r'\\([tbnrf\\"\'])') >> self.decode_echar

        PN_CHARS_BASE = Regexp(
            u'[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF'
            u'\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F'
            u'\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD'
            u'\U00010000-\U000EFFFF]'
        )

        PN_CHARS_U = PN_CHARS_BASE | Literal('_')

        PN_CHARS = PN_CHARS_U | Regexp(
            u'[\-0-9\u00B7\u0300-\u036F\u203F-\u2040]')

        PN_PREFIX = PN_CHARS_BASE & Optional(
            Star(PN_CHARS | Literal(".")) & PN_CHARS) > ''.join

        PERCENT = Regexp('%[0-9A-Fa-f]{2}')

        PN_LOCAL_ESC = Regexp(
            r'\\[_~.\-!$&\'()*+,;=/?#@%]') >> self.decode_pn_local_esc

        PLX = PERCENT | PN_LOCAL_ESC

        PN_LOCAL = (
            PN_CHARS_U | Literal(':') | Regexp('[0-9]') | PLX
        ) & Optional(
            Star(PN_CHARS | Literal(".") | Literal(":") | PLX) &
            (PN_CHARS | Literal(':') | PLX)
        ) > ''.join

        WS = Regexp(r'[\t\n\r ]')

        ANON = ~(Literal('[') & Star(WS) & Literal(']'))

        NIL = Literal('(') & Star(WS) & Literal(')')

        STRING_LITERAL1 = (Literal("'") &
                           Star(Regexp(r"[^'\\\n\r]") | ECHAR | UCHAR) &
                           Literal("'")) > self.string_contents

        STRING_LITERAL2 = (Literal('"') &
                           Star(Regexp(r'[^"\\\n\r]') | ECHAR | UCHAR) &
                           Literal('"')) > self.string_contents

        STRING_LITERAL_LONG1 = (Literal("'''") &
                                Star(Optional(Regexp("''?")) &
                                     (Regexp(r"[^'\\]") | ECHAR | UCHAR)) &
                                Literal("'''")) > self.string_contents

        STRING_LITERAL_LONG2 = (Literal('"""') &
                                Star(Optional(Regexp(r'""?')) &
                                     (Regexp(r'[^\"\\]') | ECHAR | UCHAR)) &
                                Literal('"""')) > self.string_contents

        INTEGER = Regexp(r'[+-]?[0-9]+')

        DECIMAL = Regexp(r'[+-]?(?:[0-9]+\.[0-9]+|\.[0-9]+)')

        DOUBLE = Regexp(r'[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)[eE][+-]?[0-9]+')

        IRI_REF = (~Literal('<') & (Star(Regexp(u'[^<>"{}|^`\\\\\u0000-\u0020]') | UCHAR | ECHAR) > ''.join) & ~Literal('>')) >> self.check_iri_chars

        PNAME_NS = Optional(PN_PREFIX) & Literal(":")

        PNAME_LN = PNAME_NS & PN_LOCAL

        BLANK_NODE_LABEL = ~Literal("_:") & PN_LOCAL

        LANGTAG = ~Literal("@") & (Literal('base') | Literal('prefix') |\
                                   Regexp(r'[a-zA-Z]+(?:-[a-zA-Z0-9]+)*'))

        intertoken = ~Regexp(r'[ \t\r\n]+|#[^\r\n]+')[:]
        with Separator(intertoken):
            BlankNode = (BLANK_NODE_LABEL >> self.create_blank_node) |\
                (ANON > self.create_anon_node)

            prefixID = (~Literal('@prefix') & PNAME_NS & IRI_REF) > self.bind_prefixed_name

            base = (~Literal('@base') & IRI_REF) >> self.set_base

            PrefixedName = (PNAME_LN | PNAME_NS) > self.resolve_prefixed_name

            IRIref = PrefixedName | (IRI_REF >> self.create_named_node)

            BooleanLiteral = (Literal('true') | Literal('false')) >> self.boolean_value

            String = STRING_LITERAL1 | STRING_LITERAL2 | STRING_LITERAL_LONG1 | STRING_LITERAL_LONG2

            RDFLiteral = ((String & LANGTAG) > self.langtag_string) |\
                       ((String & ~Literal('^^') & IRIref) > self.typed_string) |\
                        (String > self.bare_string)

            literal = RDFLiteral | (INTEGER  >> self.int_value) |\
                    (DECIMAL >> self.decimal_value) |\
                    (DOUBLE >> self.double_value) | BooleanLiteral

            object = Delayed()

            predicateObjectList = Delayed()

            blankNodePropertyList = ~Literal('[') & predicateObjectList & ~Literal(']') > self.make_blank_node_property_list

            collection = (~Literal('(') & object[:] & ~Literal(')')) > self.make_collection

            blank = BlankNode | blankNodePropertyList | collection

            subject = IRIref | blank

            predicate = IRIref

            object += IRIref | blank | literal

            verb = predicate | (~Literal('a') > self.create_rdf_type)

            objectList = ((object & (~Literal(',') & object)[:]) | object) > self.make_object

            predicateObjectList += (
                (verb & objectList &
                 (~Literal(';') & Optional(verb & objectList))[:]) |
                (verb & objectList)
            ) > self.make_object_list

            triples = (
                (subject & predicateObjectList) |
                (blankNodePropertyList & Optional(predicateObjectList))
            ) > self.make_triples

            directive = prefixID | base

            sparql_prefixID = (~Regexp('[Pp][Rr][Ee][Ff][Ii][Xx]') & PNAME_NS & IRI_REF) > self.bind_prefixed_name

            sparql_base = (~(Regexp('[Bb][Aa][Ss][Ee]')) & IRI_REF) >> self.set_base

            statement = ((directive | triples) & ~Literal('.')) | sparql_base | sparql_prefixID

            self.turtle_doc = intertoken & statement[:] & intertoken & Eos()
            self.turtle_doc.config.clear()

    def _prepare_parse(self, graph):
        super(TurtleParser, self)._prepare_parse(graph)
        self._call_state.base_iri = self._base
        self._call_state.prefixes = {}
        self._call_state.current_subject = None
        self._call_state.current_predicate = None

    def check_iri_chars(self, iri):
        from lepl.matchers.error import make_error

        if re.search(u'[\u0000-\u0020<>"{}|^`\\\\]', iri):
            return make_error('Invalid \\u-sequence in IRI')

        return iri

    def decode_uchar(self, uchar_string):
        return unichr(int(uchar_string, 16))

    def decode_echar(self, echar_string):
        return self.echar_map[echar_string]

    def decode_pn_local_esc(self, pn_local_esc):
        return pn_local_esc[1]

    def string_contents(self, string_chars):
        return u''.join(string_chars[1:-1])

    def int_value(self, value):
        return LiteralToBe(value, language=None,
                           datatype=NamedNodeToBe(self.profile.resolve('xsd:integer')))

    def decimal_value(self, value):
        return LiteralToBe(value, language=None,
                           datatype=NamedNodeToBe(self.profile.resolve('xsd:decimal')))

    def double_value(self, value):
        return LiteralToBe(value, language=None,
                           datatype=NamedNodeToBe(self.profile.resolve('xsd:double')))

    def boolean_value(self, value):
        return LiteralToBe(value, language=None,
                           datatype=NamedNodeToBe(self.profile.resolve('xsd:boolean')))

    def langtag_string(self, values):
        return LiteralToBe(values[0], language=values[1], datatype=None)

    def typed_string(self, values):
        return LiteralToBe(values[0], language=None, datatype=values[1])

    def bare_string(self, values):
        return LiteralToBe(values[0], language=None,
                           datatype=NamedNodeToBe(self.profile.resolve('xsd:string')))

    def create_named_node(self, iri):
        return NamedNodeToBe(iri)

    def create_blank_node(self, name=None):
        if name is None:
            return self.env.createBlankNode()
        return self._call_state.bnodes[name]

    def create_anon_node(self, anon_tokens):
        return self.env.createBlankNode()

    def create_rdf_type(self, values):
        return self.profile.resolve('rdf:type')

    def resolve_prefixed_name(self, values):
        if values[0] == ':':
            pname = ''
            local = values[1] if len(values) == 2 else ''
        elif values[-1] == ':':
            pname = values[0]
            local = ''
        else:
            pname = values[0]
            local = values[2]

        return NamedNodeToBe(PrefixReference(pname, local))

    def bind_prefixed_name(self, values):
        iri = values.pop()
        assert values.pop() == ':'
        pname = values.pop() if values else ''
        return BindPrefix(pname, iri)

    def set_base(self, base_iri):
        return SetBase(base_iri)

    def make_object(self, values):
        return values

    def make_object_list(self, values):
        return list(discrete_pairs(values))

    def make_blank_node_property_list(self, values):
        subject = self.env.createBlankNode()
        predicate_objects = []
        for predicate, objects in values[0]:
            for obj in objects:
                predicate_objects.append(PredicateObject(predicate, obj))
        return TriplesClause(subject, predicate_objects)

    def make_triples(self, values):
        subject = values[0]
        if len(values) == 2:
            predicate_objects = [PredicateObject(predicate, obj) for
                                 predicate, objects in values[1] for obj in objects]
            return TriplesClause(subject, predicate_objects)
        else:
            return subject

    def make_collection(self, values):
        prev_node = TriplesClause(self.profile.resolve('rdf:nil'), [])
        for value in reversed(values):
            prev_node = TriplesClause(
                self.env.createBlankNode(),
                [PredicateObject(self.profile.resolve('rdf:first'), value),
                 PredicateObject(self.profile.resolve('rdf:rest'), prev_node)])
        return prev_node

    def _interpret_parse(self, data, sink):
        for line in data:
            if isinstance(line, BindPrefix):
                self._call_state.prefixes[line.prefix] = smart_urljoin(
                    self._call_state.base_iri, line.iri)
            elif isinstance(line, SetBase):
                self._call_state.base_iri = smart_urljoin(
                    self._call_state.base_iri, line.iri)
            else:
                self._interpret_triples_clause(line)

    def _interpret_triples_clause(self, triples_clause):
        assert isinstance(triples_clause, TriplesClause)
        subject = self._resolve_node(triples_clause.subject)
        for predicate_object in triples_clause.predicate_objects:
            self._call_state.graph.add(self.env.createTriple(
                subject, self._resolve_node(predicate_object.predicate),
                self._resolve_node(predicate_object.object)))
        return subject

    def _resolve_node(self, node):
        if isinstance(node, NamedNodeToBe):
            if isinstance(node.iri, PrefixReference):
                return self.env.createNamedNode(
                    self._call_state.prefixes[node.iri.prefix] + node.iri.local)
            else:
                resolved = smart_urljoin(self._call_state.base_iri, node.iri)
                return self.env.createNamedNode(resolved)
        elif isinstance(node, TriplesClause):
            return self._interpret_triples_clause(node)
        elif isinstance(node, LiteralToBe):
            if node.datatype:
                return self.env.createLiteral(
                    node.value, datatype=self._resolve_node(node.datatype))
            else:
                return self.env.createLiteral(node.value, language=node.language)
        else:
            return node

    def parse(self, data, sink = None, base = ''):
        if isinstance(data, binary_type):
            data = data.decode('utf8')

        if sink is None:
            sink = self._make_graph()
        self._base = base
        self._prepare_parse(sink)
        self._interpret_parse(self.turtle_doc.parse(data), sink)
        self._cleanup_parse()

        return sink

    def parse_string(self, string, sink = None):
        return self.parse(string, sink)


turtle_parser = TurtleParser()
