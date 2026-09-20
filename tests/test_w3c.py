"""Run the W3C RDF conformance suites against pymantic's parsers and serializers.

The suites live under tests/w3c, vendored from https://github.com/w3c/rdf-tests
by tests/w3c/sync_from_upstream.py (see tests/w3c/UPSTREAM.md for the commit).
Each suite is described by a manifest.ttl in the test-manifest vocabulary
(mf: and rdft:). The manifests are read with rdflib so that this file works
even when pymantic's own Turtle parser is broken.

One pytest test is generated per manifest entry, named after the suite
directory and the entry's IRI fragment, for example
``rdf11/rdf-turtle/turtle-syntax-bad-numeric-escape-01``. What a test does
depends on its rdft: type:

* ``*PositiveSyntax``  parsing the action file must succeed
* ``*NegativeSyntax``  parsing the action file must raise
* ``TestTurtleEval``   the parsed graph must be isomorphic to the N-Triples
                       result file; a second test, ``<id>[roundtrip]``,
                       also serializes the graph as Turtle, reparses it and
                       compares again
* ``*PositiveC14N``    parsing then serializing as N-Triples/N-Quads must
                       reproduce the result file byte for byte
* anything else        skipped, so a new upstream test type is visible

Tests that pymantic is known to fail are listed in
tests/w3c/expected_failures.txt (one ``<test id><TAB><reason>`` per line)
and marked xfail. Every other test must pass.
"""

from io import StringIO
import pathlib
import pytest
import rdflib
from rdflib.collection import Collection
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, Namespace
import signal
from urllib.parse import urljoin, urlparse
from urllib.request import url2pathname

from pymantic.parsers import nquads_parser, ntriples_parser, turtle_parser
from pymantic.primitives import BlankNode, Literal, NamedNode
from pymantic.serializers import (
    serialize_nquads,
    serialize_ntriples,
    serialize_turtle,
)

W3C_DIR = pathlib.Path(__file__).parent / "w3c"
TOP_LEVEL_MANIFESTS = [
    W3C_DIR / "rdf11" / "rdf-n-triples" / "manifest.ttl",
    W3C_DIR / "rdf11" / "rdf-n-quads" / "manifest.ttl",
    W3C_DIR / "rdf11" / "rdf-turtle" / "manifest.ttl",
    W3C_DIR / "rdf12" / "rdf-n-triples" / "manifest.ttl",
    W3C_DIR / "rdf12" / "rdf-n-quads" / "manifest.ttl",
    W3C_DIR / "rdf12" / "rdf-turtle" / "manifest.ttl",
]
EXPECTED_FAILURES_FILE = W3C_DIR / "expected_failures.txt"

MF = Namespace("http://www.w3.org/2001/sw/DataAccess/tests/test-manifest#")
RDFT = Namespace("http://www.w3.org/ns/rdftest#")

# A hung parser must not hang the whole run. signal.alarm exists only on
# POSIX; elsewhere the guard is a no-op.
PER_TEST_SECONDS = 10


class ManifestEntry:
    """One test from a manifest, with everything needed to run it."""

    def __init__(self, id, kind, action, result, base_iri):
        self.id = id  # e.g. "rdf12/rdf-turtle/syntax/turtle12-1"
        self.kind = kind  # rdft: type without the namespace
        self.action = action  # pathlib.Path of the input file
        self.result = result  # pathlib.Path of the expected output, or None
        self.base_iri = base_iri  # base IRI to parse the Turtle input with

    def __repr__(self):
        return "ManifestEntry(%s)" % self.id


def local_path(iri):
    """rdflib resolves the manifests' relative IRIs against the manifest's
    own file:// location, so an action or result IRI is a local path."""
    parsed = urlparse(str(iri))
    if parsed.scheme != "file":
        raise ValueError("%s does not point at a vendored file" % iri)
    return pathlib.Path(url2pathname(parsed.path))


def load_manifest(manifest_path, loaded):
    """Return the entries of one manifest and, recursively, of every
    manifest it mf:includes. `loaded` records manifests already read: the
    RDF 1.2 manifests include the RDF 1.1 ones, which must not run twice."""
    manifest_path = manifest_path.resolve()
    if manifest_path in loaded:
        return []
    loaded.add(manifest_path)
    suite_dir = manifest_path.parent
    suite = suite_dir.relative_to(W3C_DIR).as_posix()

    graph = rdflib.Graph()
    graph.parse(manifest_path, format="turtle")
    manifest = graph.value(predicate=RDF.type, object=MF.Manifest)
    if manifest is None:
        raise ValueError("%s declares no mf:Manifest" % manifest_path)
    assumed_base = graph.value(manifest, MF.assumedTestBase)

    entries = []
    entry_list = graph.value(manifest, MF.entries)
    for entry in Collection(graph, entry_list) if entry_list else []:
        kind = str(graph.value(entry, RDF.type)).replace(str(RDFT), "")
        action = local_path(graph.value(entry, MF.action))
        result = graph.value(entry, MF.result)
        base_iri = None
        if kind.startswith("TestTurtle"):
            if assumed_base is None:
                raise ValueError(
                    "%s has no mf:assumedTestBase; Turtle tests need one to "
                    "resolve relative IRIs" % manifest_path
                )
            base_iri = urljoin(
                str(assumed_base), action.relative_to(suite_dir).as_posix()
            )
        entries.append(
            ManifestEntry(
                id="%s/%s" % (suite, str(entry).rsplit("#", 1)[-1]),
                kind=kind,
                action=action,
                result=local_path(result) if result is not None else None,
                base_iri=base_iri,
            )
        )

    include_list = graph.value(manifest, MF.include)
    for included in Collection(graph, include_list) if include_list else []:
        entries.extend(load_manifest(local_path(included), loaded))
    return entries


def load_expected_failures():
    """Map test id to reason from expected_failures.txt. Blank lines and
    lines starting with # are ignored."""
    expected = {}
    for line in EXPECTED_FAILURES_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        test_id, _, reason = line.partition("\t")
        if not reason.strip():
            raise ValueError(
                "%s: line %r needs '<test id><TAB><reason>'"
                % (EXPECTED_FAILURES_FILE, line)
            )
        expected[test_id] = reason.strip()
    return expected


def parametrize_cases(entries, expected_failures, id_suffix=""):
    """Build pytest.param objects, marking listed ids as xfail."""
    cases = []
    for entry in entries:
        test_id = entry.id + id_suffix
        marks = []
        if test_id in expected_failures:
            # Strict: a test that starts passing must be removed from the list.
            marks.append(
                pytest.mark.xfail(reason=expected_failures[test_id], strict=True)
            )
        cases.append(pytest.param(entry, id=test_id, marks=marks))
    return cases


loaded_manifests = set()
ENTRIES = []
for top_level in TOP_LEVEL_MANIFESTS:
    ENTRIES.extend(load_manifest(top_level, loaded_manifests))
EVAL_ENTRIES = [e for e in ENTRIES if e.kind == "TestTurtleEval"]
EXPECTED_FAILURES = load_expected_failures()
ALL_TEST_IDS = {e.id for e in ENTRIES} | {e.id + "[roundtrip]" for e in EVAL_ENTRIES}


@pytest.fixture(autouse=True)
def per_test_timeout():
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def on_alarm(signum, frame):
        raise TimeoutError("test exceeded %d seconds" % PER_TEST_SECONDS)

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(PER_TEST_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def parse_action(entry):
    """Parse the entry's input file with the pymantic parser for its kind."""
    data = entry.action.read_bytes()
    if entry.kind.startswith("TestTurtle"):
        return turtle_parser.parse(data, base=entry.base_iri)
    if entry.kind.startswith("TestNTriples"):
        return ntriples_parser.parse_string(data)
    if entry.kind.startswith("TestNQuads"):
        return nquads_parser.parse_string(data)
    raise ValueError("no parser for %s" % entry.kind)


def to_rdflib(graph):
    """Convert a pymantic graph to an rdflib graph for isomorphism checks.
    rdflib represents a language-tagged string by its language alone, with no
    explicit rdf:langString datatype, so those are converted by language."""
    out = rdflib.Graph()

    def term(node):
        if isinstance(node, BlankNode):
            return rdflib.BNode(node.value)
        if isinstance(node, Literal):
            if node.language:
                return rdflib.Literal(node.value, lang=node.language)
            return rdflib.Literal(
                node.value, datatype=rdflib.URIRef(str(node.datatype))
            )
        if not isinstance(node, NamedNode):
            raise TypeError("parser produced %r, which is not an RDF term" % (node,))
        return rdflib.URIRef(str(node))

    for triple in graph:
        out.add((term(triple.subject), term(triple.predicate), term(triple.object)))
    return out


def assert_isomorphic(graph, entry):
    expected = ntriples_parser.parse_string(entry.result.read_bytes())
    assert isomorphic(
        to_rdflib(graph), to_rdflib(expected)
    ), "graph parsed from %s differs from %s" % (entry.action.name, entry.result.name)


def assert_canonical(graph, entry):
    out = StringIO()
    if entry.kind.startswith("TestNQuads"):
        serialize_nquads(graph, out)
    else:
        serialize_ntriples(graph, out)
    assert out.getvalue().encode("utf-8") == entry.result.read_bytes(), (
        "canonical output differs from %s" % entry.result.name
    )


@pytest.mark.parametrize("entry", parametrize_cases(ENTRIES, EXPECTED_FAILURES))
def test_w3c(entry):
    if entry.kind.endswith("NegativeSyntax"):
        with pytest.raises(Exception):
            parse_action(entry)
    elif entry.kind.endswith("PositiveSyntax"):
        parse_action(entry)
    elif entry.kind == "TestTurtleEval":
        assert_isomorphic(parse_action(entry), entry)
    elif entry.kind.endswith("PositiveC14N"):
        assert_canonical(parse_action(entry), entry)
    else:
        pytest.skip("test type %s is not handled by this harness" % entry.kind)


@pytest.mark.parametrize(
    "entry", parametrize_cases(EVAL_ENTRIES, EXPECTED_FAILURES, "[roundtrip]")
)
def test_w3c_turtle_roundtrip(entry):
    """Serializing a correctly parsed graph as Turtle and reading it back
    must give the same graph. This checks serialize_turtle, which the
    upstream suites do not cover."""
    out = StringIO()
    serialize_turtle(parse_action(entry), out)
    assert_isomorphic(turtle_parser.parse(out.getvalue(), base=entry.base_iri), entry)


def test_expected_failures_name_real_tests():
    """A stale entry in expected_failures.txt would silently xfail nothing."""
    unknown = sorted(set(EXPECTED_FAILURES) - ALL_TEST_IDS)
    assert not unknown, "unknown test ids in %s: %s" % (
        EXPECTED_FAILURES_FILE.name,
        ", ".join(unknown),
    )
