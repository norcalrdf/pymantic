import os.path
import unittest

from betamax import Betamax

from pymantic.sparql import SPARQLServer, SPARQLQueryException


with Betamax.configure() as config:
    config.cassette_library_dir = os.path.join(
        os.path.dirname(__file__), 'playbacks',
    )


class TestSparql(unittest.TestCase):
    def testMockSPARQL(self):
        """Test a SPARQL query against a mocked-up endpoint."""
        test_query = """PREFIX dc: <http://purl.org/dc/terms/>
        SELECT ?product ?title WHERE { ?product dc:title ?title } LIMIT 10"""

        sparql = SPARQLServer(
            'http://localhost/tenuki/sparql', post_queries=True,
        )

        with Betamax(sparql.s).use_cassette('mock_sparql', record='none'):
            results = sparql.query(test_query)

        self.assertEqual(results['results']['bindings'][0]['product']['value'],
                         'test_product')
        self.assertEqual(results['results']['bindings'][0]['title']['value'],
                         'Test Title')

    def testMockSPARQLError(self):
        """Test a SPARQL query against a mocked-up endpoint."""
        test_query = """PREFIX dc: <http://purl.org/dc/terms/>
        SELECT ?product ?title WHERE { ?product dc:title ?title } LIMIT 10"""

        sparql = SPARQLServer(
            'http://localhost/tenuki/sparql', post_queries=True,
        )
        with Betamax(sparql.s).use_cassette(
            'mock_sparql_error', record='none',
        ):
            self.assertRaises(SPARQLQueryException, sparql.query, test_query)
