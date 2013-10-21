import unittest
import os
from pymantic.parsers import jsonld_parser, nquads_parser
from test_turtle import MetaRDFTest, Action

class JSONLDTests(unittest.TestCase):
    __metaclass__ = MetaRDFTest

    base = os.path.join(os.path.dirname(__file__), 'jsonld_tests/')

    manifest = os.path.join(base, 'manifest.ttl')

    def execute(self, entry):
        with open(unicode(entry['mf:action']), 'r') as f:
            in_data = f.read()
        with open(unicode(entry['mf:result'])) as f:
            compare_data = f.read()
        test_graph = jsonld_parser.parse(in_data)
        compare_graph = nquads_parser.parse_string(compare_data)
