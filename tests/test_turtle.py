import os.path
from pymantic.compat.moves.urllib.parse import urljoin
import unittest
from pymantic.parsers import turtle_parser, ntriples_parser
import pymantic.rdf as rdf
from pymantic.compat import text_type

turtle_tests_url =\
    'http://www.w3.org/2013/TurtleTests/'

prefixes = {
    'mf': 'http://www.w3.org/2001/sw/DataAccess/tests/test-manifest#',
    'qt': 'http://www.w3.org/2001/sw/DataAccess/tests/test-query#',
    'rdft': 'http://www.w3.org/ns/rdftest#',
}


def isomorph_triple(triple):
    from pymantic.primitives import (
        BlankNode,
        Literal,
        NamedNode,
    )

    if isinstance(triple.subject, BlankNode):
        triple = triple._replace(subject=None)
    if isinstance(triple.object, BlankNode):
        triple = triple._replace(object=None)
    if isinstance(triple.object, Literal) and triple.object.datatype is None:
        triple = triple._replace(object=triple.object._replace(
            datatype=NamedNode('http://www.w3.org/2001/XMLSchema#string')))

    return triple


def isomorph(graph):
    return {
        isomorph_triple(t) for t in graph._triples
    }


@rdf.register_class('mf:Manifest')
class Manifest(rdf.Resource):
    prefixes = prefixes

    scalars = frozenset(('rdfs:comment', 'mf:entries'))


@rdf.register_class('rdft:TestTurtleEval')
class TestTurtleEval(rdf.Resource):
    prefixes = prefixes

    scalars = frozenset(('mf:name', 'rdfs:comment', 'mf:action', 'mf:result'))

    def execute(self, test_case):
        with open(text_type(self['mf:action']), 'rb') as f:
            in_data = f.read()

        with open(text_type(self['mf:result']), 'rb') as f:
            compare_data = f.read()

        base = urljoin(turtle_tests_url,
                       os.path.basename(text_type(self['mf:action'])))

        test_graph = turtle_parser.parse(in_data, base=base)
        compare_graph = ntriples_parser.parse_string(compare_data)
        test_case.assertEqual(
            isomorph(test_graph),
            isomorph(compare_graph),
        )


@rdf.register_class('rdft:TestTurtlePositiveSyntax')
class TestTurtlePositiveSyntax(rdf.Resource):
    prefixes = prefixes

    scalars = frozenset(('mf:name', 'rdfs:comment', 'mf:action'))

    def execute(self, test_case):
        with open(text_type(self['mf:action']), 'rb') as f:
            in_data = f.read()

        base = urljoin(turtle_tests_url,
                       os.path.basename(text_type(self['mf:action'])))
        test_graph = turtle_parser.parse(in_data, base=base)


@rdf.register_class('rdft:TestTurtleNegativeSyntax')
class TestTurtleNegativeSyntax(rdf.Resource):
    prefixes = prefixes

    scalars = frozenset(('mf:name', 'rdfs:comment', 'mf:action'))

    def execute(self, test_case):
        with open(text_type(self['mf:action']), 'rb') as f:
            in_data = f.read()

        base = urljoin(turtle_tests_url,
                       os.path.basename(text_type(self['mf:action'])))
        with test_case.assertRaises(Exception):
            turtle_parser.parse(in_data, base=base)


@rdf.register_class('rdft:TestTurtleNegativeEval')
class TestTurtleNegativeEval(rdf.Resource):
    prefixes = prefixes

    scalars = frozenset(('mf:name', 'rdfs:comment', 'mf:action'))

    def execute(self, test_case):
        with open(text_type(self['mf:action']), 'rb') as f:
            in_data = f.read()

        base = urljoin(turtle_tests_url,
                       os.path.basename(text_type(self['mf:action'])))
        with test_case.assertRaises(Exception):
            turtle_parser.parse(in_data, base=base)


base = os.path.join(os.path.dirname(__file__), 'TurtleTests/')

manifest_name = os.path.join(base, 'manifest.ttl')

with open(manifest_name, 'rb') as f:
    manifest_turtle = f.read()

manifest_graph = turtle_parser.parse(manifest_turtle, base=base)

manifest = Manifest(manifest_graph, base)


class TurtleTests(unittest.TestCase):
    @classmethod
    def _make_test_case(cls, test_case):
        def test_method(self):
            return test_case.execute(self)

        test_name = 'test_' + test_case['mf:name'].value.replace('-', '_')
        test_method.__name__ = str(test_name)
        test_method.func_name = test_name.encode('utf8')
        test_method.func_doc = u'{} ({})'.format(
            test_case['rdfs:comment'].value,
            test_name,
        )
        setattr(cls, test_name, test_method)


for test_case in list(manifest['mf:entries'].as_(rdf.List)):
    TurtleTests._make_test_case(test_case)
