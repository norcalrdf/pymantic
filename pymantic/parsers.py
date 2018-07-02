__all__ = ['ntriples_parser', 'nquads_parser', 'turtle_parser', 'jsonld_parser']

from collections import defaultdict, namedtuple, OrderedDict
from lepl import *
from lxml import etree
import re
from threading import local
from .compat.moves.urllib.parse import urljoin
from pymantic.util import (
    normalize_iri,
    smart_urljoin
)
from pymantic.compat import (
    binary_type,
    unichr,
)
import pymantic.primitives

def discrete_pairs(iterable):
    "s -> (s0,s1), (s2,s3), (s4, s5), ..."
    previous = None
    for v in iterable:
        if previous is None:
            previous = v
        else:
            yield (previous, v)
            previous = None

unicode_re = re.compile(r'\\u([0-9A-Za-z]{4})|\\U([0-9A-Za-z]{8})')

def nt_unescape(nt_string):
    """Un-do nt escaping style."""
    output_string = u''

    if isinstance(nt_string, binary_type):
        nt_string = nt_string.decode('utf-8')

    nt_string = nt_string.replace('\\t', u'\u0009')
    nt_string = nt_string.replace('\\n', u'\u000A')
    nt_string = nt_string.replace('\\r', u'\u000D')
    nt_string = nt_string.replace('\\"', u'\u0022')
    nt_string = nt_string.replace('\\\\', u'\u005C')
    def chr_match(matchobj):
        ordinal = matchobj.group(1) or matchobj.group(2)
        return unichr(int(ordinal, 16))
    nt_string = unicode_re.sub(chr_match, nt_string)
    return nt_string

class BaseLeplParser(object):

    def __init__(self, environment=None):
        self.env = environment or pymantic.primitives.RDFEnvironment()
        self.profile = self.env.createProfile()
        self._call_state = local()

    def make_datatype_literal(self, values):
        return self.env.createLiteral(value = values[0], datatype = values[1])

    def make_language_literal(self, values):
        if len(values) == 2:
            return self.env.createLiteral(value = values[0],
                                                  language = values[1])
        else:
            return self.env.createLiteral(value = values[0])

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

    def parse(self, f, sink = None):
        if sink is None:
            sink = self._make_graph()
        self._prepare_parse(sink)
        self.document.parse_file(f)
        self._cleanup_parse()

        return sink

    def parse_string(self, string, sink = None):
        from .compat.moves import cStringIO as StringIO

        if isinstance(string, binary_type):
            string = string.decode('utf8')

        if sink is None:
            sink = self._make_graph()
        self._prepare_parse(sink)
        self.document.parse(StringIO(string))
        self._cleanup_parse()

        return sink

class BaseNParser(BaseLeplParser):
    """Base parser that establishes common grammar rules and interfaces used for
    parsing both n-triples and n-quads."""

    def __init__(self, environment=None):
        super(BaseNParser, self).__init__(environment)
        self.string = Regexp(r'(?:[ -!#-[\]-~]|\\[trn"\\]|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8})*')
        self.name = Regexp(r'[A-Za-z][A-Za-z0-9]*')
        self.absoluteURI = Regexp(r'(?:[ -=?-[\]-~]|\\[trn"\\]|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8})+')
        self.language = Regexp(r'[a-z]+(?:-[a-zA-Z0-9]+)*')
        self.uriref = ~Literal('<') & self.absoluteURI & ~Literal('>') \
            > self.make_named_node
        self.datatypeString = ~Literal('"') & self.string & ~Literal('"') \
            & ~Literal('^^') & self.uriref > self.make_datatype_literal
        self.langString = ~Literal('"') & self.string & ~Literal('"') \
            & Optional(~Literal('@') & self.language) > self.make_language_literal
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
            return self.env.createLiteral(value = nt_unescape(values[0]),
                                          language = values[1])
        else:
            return self.env.createLiteral(value = nt_unescape(values[0]))

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

class NQuadsParser(BaseNParser):
    def make_quad(self, values):
        quad = self.env.createQuad(*values)
        self._call_state.graph.add(quad)
        return quad

    def __init__(self, environment=None):
        super(NQuadsParser, self).__init__(environment)
        self.graph_name = self.uriref
        self.quad = self.subject & ~Plus(Space()) & self.predicate \
            & ~Plus(Space()) & self.object_ & ~Plus(Space()) & self.graph_name \
            & ~Star(Space()) & ~Literal('.') & ~Star(Space()) >= self.make_quad
        self.line = Star(Space()) & Optional(~self.quad | ~self.comment) \
            & ~Literal('\n')
        self.document = Star(self.line)

    def _make_graph(self):
        return self.env.createDataset()

    def parse(self, f, dataset=None):
        return super(NQuadsParser, self).parse(f, dataset)

nquads_parser = NQuadsParser()

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

        PN_CHARS_BASE = Regexp(u'[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF'
                               u'\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F'
                               u'\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD'
                               u'\U00010000-\U000EFFFF]')

        PN_CHARS_U = PN_CHARS_BASE | Literal('_')

        PN_CHARS = PN_CHARS_U | Regexp(u'[\-0-9\u00B7\u0300-\u036F\u203F-\u2040]')

        PN_PREFIX = PN_CHARS_BASE & Optional(Star(PN_CHARS | Literal(".")) & PN_CHARS ) > ''.join

        PERCENT = Regexp('%[0-9A-Fa-f]{2}')

        PN_LOCAL_ESC = Regexp(r'\\[_~.\-!$&\'()*+,;=/?#@%]') >> self.decode_pn_local_esc

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

        STRING_LITERAL1 = (Literal("'") &\
                           Star(Regexp(r"[^'\\\n\r]") | ECHAR | UCHAR ) &\
                           Literal("'")) > self.string_contents

        STRING_LITERAL2 = (Literal('"') &\
                           Star(Regexp(r'[^"\\\n\r]') | ECHAR | UCHAR ) &\
                           Literal('"')) > self.string_contents

        STRING_LITERAL_LONG1 = (Literal("'''") &\
                                Star(Optional( Regexp("''?")) &\
                                     ( Regexp(r"[^'\\]") | ECHAR | UCHAR ) ) &\
                                Literal("'''")) > self.string_contents

        STRING_LITERAL_LONG2 = (Literal('"""') &\
                                Star(Optional( Regexp(r'""?') ) &\
                                     ( Regexp(r'[^\"\\]') | ECHAR | UCHAR ) ) &\
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

scheme_re = re.compile(r'[a-zA-Z](?:[a-zA-Z0-9]|\+|-|\.)*')

class RDFXMLParser(object):
    RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'

    def __init__(self):
        self.namespaces = {'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',}
        self._call_state = local()

    def clark(self, prefix, tag):
        return '{%s}%s' % (self.namespaces[prefix], tag)

    def parse(self, f, sink = None):
        self._call_state.bnodes = {}
        tree = etree.parse(f)
        if tree.getroot() != self.clark('rdf', 'RDF'):
            raise ValueError('Invalid XML document.')
        for element in tree.getroot():
            self._handle_resource(element, sink)

    def _handle_resource(self, element, sink):
        from pymantic.primitives import BlankNode, NamedNode, Triple
        subject = self._determine_subject(element)
        if element.tag != self.clark('rdf', 'Description'):
            resource_class = self._resolve_tag(element)
            sink.add(Triple(subject, NamedNode(self.RDF_TYPE), resource_class))
        for property_element in element:
            if property_element.tag == self.clark('rdf', 'li'):
                pass
            else:
                predicate = self._resolve_tag(property_element)
            if self.clark('rdf', 'resource') in property_element.attrib:
                object_ = self._resolve_uri(
                    property_element, property_element.attrib[self.clark(
                        'rdf', 'resource')])
                sink.add(Triple(subject, NamedNode(predicate), NamedNode(object_)))
        return subject

    def _resolve_tag(self, element):
        if element.tag[0] == '{':
            tag_bits = element[1:].partition('}')
            return NamedNode(tag_bits[0] + tag_bits[2])
        else:
            return NamedNode(urljoin(element.base, element.tag))

    def _determine_subject(self, element):
        if self.clark('rdf', 'about') not in element.attrib and\
           self.clark('rdf', 'nodeID') not in element.attrib and\
           self.clark('rdf', 'ID') not in element.attrib:
            return BlankNode()
        elif self.clark('rdf', 'nodeID') in element.attrib:
            node_id = element.attrib[self.clark('rdf', 'nodeID')]
            if node_id not in self._call_state.bnodes:
                self._call_state.bnodes[node_id] = BlankNode()
            return self._call_state.bnodes[node_id]
        elif self.clark('rdf', 'ID') in element.attrib:
            if not element.base:
                raise ValueError('No XML base for %r', element)
            return NamedNode(element.base + '#' +\
                             element.attrib[self.clark('rdf', 'ID')])
        elif self.clark('rdf', 'about') in element.attrib:
            return self._resolve_uri(element, element.attrib[
                self.clark('rdf', 'resource')])

    def _resolve_uri(self, element, uri):
        if not scheme_re.match(uri):
            return NamedNode(urljoin(element.base, uri))
        else:
            return NamedNode(uri)


import json


class PyLDLoader(BaseLeplParser):
    class _Loader(object):
        def __init__(self, pyld_loader):
            self.pyld_loader = pyld_loader

        def parse_file(self, f):
            jobj = json.load(f)
            self.pyld_loader.process_jobj(jobj)

        def parse(self, string):
            jobj = json.loads(string)
            self.pyld_loader.process_jobj(jobj)


    def parse_json(self, jobj, sink=None):
        if sink is None:
            sink = self._make_graph()
        self._prepare_parse(sink)
        self.process_jobj(jobj)
        self._cleanup_parse()

        return sink

    def make_quad(self, values):
        quad = self.env.createQuad(*values)
        self._call_state.graph.add(quad)
        return quad

    def _make_graph(self):
        return self.env.createDataset()

    def __init__(self, *args, **kwargs):
        self.document = self._Loader(self)
        super(PyLDLoader, self).__init__(*args, **kwargs)

    def process_triple_fragment(self, triple_fragment):
        if triple_fragment['type'] == 'IRI':
            return self.env.createNamedNode(triple_fragment['value'])
        elif triple_fragment['type'] == 'blank node':
            return self._call_state.bnodes[triple_fragment['value']]
        elif triple_fragment['type'] == 'literal':
            if 'language' in triple_fragment:
                raise NotImplemented('Languages not supported yet')
            return self.env.createLiteral(
                value=triple_fragment['value'],
                datatype=self.env.createNamedNode(triple_fragment['datatype']),
            )

    def process_jobj(self, jobj):
        from pyld.jsonld import to_rdf
        dataset = to_rdf(jobj)
        for graph_name, triples in dataset.items():
            graph_iri = self.env.createNamedNode(graph_name) if graph_name != '@default' else None
            for triple in triples:
                self.make_quad(
                    (self.process_triple_fragment(triple['subject']),
                     self.process_triple_fragment(triple['predicate']),
                     self.process_triple_fragment(triple['object']),
                     graph_iri,
                     )
                )

jsonld_parser = PyLDLoader()

