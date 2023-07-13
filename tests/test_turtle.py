import os.path
import pytest
from urllib.parse import urljoin

from pymantic.parsers import ntriples_parser, turtle_parser
import pymantic.rdf as rdf

turtle_tests_url = "http://www.w3.org/2013/TurtleTests/"

prefixes = {
    "mf": "http://www.w3.org/2001/sw/DataAccess/tests/test-manifest#",
    "qt": "http://www.w3.org/2001/sw/DataAccess/tests/test-query#",
    "rdft": "http://www.w3.org/ns/rdftest#",
}


def isomorph_triple(triple):
    from pymantic.primitives import BlankNode, Literal, NamedNode

    if isinstance(triple.subject, BlankNode):
        triple = triple._replace(subject=None)
    if isinstance(triple.object, BlankNode):
        triple = triple._replace(object=None)
    if isinstance(triple.object, Literal) and triple.object.datatype is None:
        triple = triple._replace(
            object=triple.object._replace(
                datatype=NamedNode("http://www.w3.org/2001/XMLSchema#string")
            )
        )

    return triple


def isomorph(graph):
    return {isomorph_triple(t) for t in graph._triples}


@rdf.register_class("mf:Manifest")
class Manifest(rdf.Resource):
    prefixes = prefixes

    scalars = frozenset(("rdfs:comment", "mf:entries"))


@rdf.register_class("rdft:TestTurtleEval")
class TurtleEvalTest(rdf.Resource):
    prefixes = prefixes

    scalars = frozenset(("mf:name", "rdfs:comment", "mf:action", "mf:result"))

    def execute(self):
        with open(str(self["mf:action"]), "rb") as f:
            in_data = f.read()

        with open(str(self["mf:result"]), "rb") as f:
            compare_data = f.read()

        base = urljoin(turtle_tests_url, os.path.basename(str(self["mf:action"])))

        test_graph = turtle_parser.parse(in_data, base=base)
        compare_graph = ntriples_parser.parse_string(compare_data)
        assert isomorph(test_graph) == isomorph(compare_graph), self[
            "rdfs:comment"
        ].value


@rdf.register_class("rdft:TestTurtlePositiveSyntax")
class TurtlePositiveSyntaxTest(rdf.Resource):
    prefixes = prefixes

    scalars = frozenset(("mf:name", "rdfs:comment", "mf:action"))

    def execute(self):
        with open(str(self["mf:action"]), "rb") as f:
            in_data = f.read()

        base = urljoin(turtle_tests_url, os.path.basename(str(self["mf:action"])))
        turtle_parser.parse(in_data, base=base)


@rdf.register_class("rdft:TestTurtleNegativeSyntax")
class TurtleNegativeSyntaxTest(rdf.Resource):
    prefixes = prefixes

    scalars = frozenset(("mf:name", "rdfs:comment", "mf:action"))

    def execute(self):
        with open(str(self["mf:action"]), "rb") as f:
            in_data = f.read()

        base = urljoin(turtle_tests_url, os.path.basename(str(self["mf:action"])))
        with pytest.raises(Exception):
            turtle_parser.parse(in_data, base=base)


@rdf.register_class("rdft:TestTurtleNegativeEval")
class TurtleNegativeEvalTest(rdf.Resource):
    prefixes = prefixes

    scalars = frozenset(("mf:name", "rdfs:comment", "mf:action"))

    def execute(self):
        with open(str(self["mf:action"]), "rb") as f:
            in_data = f.read()

        base = urljoin(turtle_tests_url, os.path.basename(str(self["mf:action"])))
        with pytest.raises(Exception):
            turtle_parser.parse(in_data, base=base)


base = os.path.join(os.path.dirname(__file__), "TurtleTests/")

manifest_name = os.path.join(base, "manifest.ttl")

with open(manifest_name, "rb") as f:
    manifest_turtle = f.read()

manifest_graph = turtle_parser.parse(manifest_turtle, base=base)

manifest = Manifest(manifest_graph, base)

turtle_test_cases = {
    test_case["mf:name"].value: test_case
    for test_case in manifest["mf:entries"].as_(rdf.List)
}


@pytest.mark.parametrize(["turtle_test_case_name"], zip(turtle_test_cases.keys()))
def test_turtle(turtle_test_case_name):
    turtle_test_cases[turtle_test_case_name].execute()
