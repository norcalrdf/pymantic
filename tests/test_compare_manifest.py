"""Run the hand-written comparison pairs in tests/compare/manifest.ttl.

The manifest follows the W3C rdf-tests conventions (mf:Manifest,
mf:entries, mf:action and mf:result) with two entry types of its own:
pc:IsomorphicTest and pc:NonIsomorphicTest. It is read with rdflib so the
harness does not depend on the code it tests. Both files of a pair are
parsed with the pymantic parser for their extension and compared both ways
round; for triple files rdflib's isomorphism check is used as an oracle.
"""

from io import StringIO
import pathlib
import pytest
import rdflib
from rdflib.collection import Collection
from rdflib.compare import isomorphic as rdflib_isomorphic
from rdflib.namespace import RDF, Namespace
from urllib.parse import urlparse
from urllib.request import url2pathname

from pymantic.compare import isomorphic
from pymantic.parsers import nquads_parser, ntriples_parser, turtle_parser
from pymantic.serializers import serialize_nquads, serialize_ntriples
from tests.test_w3c import to_rdflib

COMPARE_DIR = pathlib.Path(__file__).parent / "compare"
MANIFEST = COMPARE_DIR / "manifest.ttl"
MF = Namespace("http://www.w3.org/2001/sw/DataAccess/tests/test-manifest#")
PC = Namespace("https://github.com/norcalrdf/pymantic/tests/compare#")


class Pair:
    def __init__(self, id, expected, action, result):
        self.id = id
        self.expected = expected  # True when the pair must be isomorphic
        self.action = action
        self.result = result


def local_path(iri):
    parsed = urlparse(str(iri))
    assert parsed.scheme == "file", iri
    return pathlib.Path(url2pathname(parsed.path))


def load_pairs():
    graph = rdflib.Graph()
    graph.parse(MANIFEST, format="turtle")
    manifest = graph.value(predicate=RDF.type, object=MF.Manifest)
    pairs = []
    for entry in Collection(graph, graph.value(manifest, MF.entries)):
        kind = graph.value(entry, RDF.type)
        if kind == PC.IsomorphicTest:
            expected = True
        elif kind == PC.NonIsomorphicTest:
            expected = False
        else:
            raise ValueError("%s has unknown type %s" % (entry, kind))
        pairs.append(
            Pair(
                id=str(entry).rsplit("#", 1)[-1],
                expected=expected,
                action=local_path(graph.value(entry, MF.action)),
                result=local_path(graph.value(entry, MF.result)),
            )
        )
    return pairs


def parse(path):
    data = path.read_bytes()
    if path.suffix == ".ttl":
        return turtle_parser.parse(data, base=path.as_uri())
    if path.suffix == ".nt":
        return ntriples_parser.parse_string(data)
    if path.suffix == ".nq":
        return nquads_parser.parse_string(data)
    raise ValueError("no parser for %s" % path.name)


def stable_lines(graph, path):
    out = StringIO()
    if path.suffix == ".nq":
        serialize_nquads(graph, out, stable=True)
    else:
        serialize_ntriples(graph, out, stable=True)
    return out.getvalue()


PAIRS = load_pairs()


@pytest.mark.parametrize("pair", PAIRS, ids=[pair.id for pair in PAIRS])
def test_manifest_pair(pair):
    a, b = parse(pair.action), parse(pair.result)
    assert isomorphic(a, b) is pair.expected
    assert isomorphic(b, a) is pair.expected
    if pair.action.suffix != ".nq":
        assert rdflib_isomorphic(to_rdflib(a), to_rdflib(b)) is pair.expected
    if pair.expected:
        assert stable_lines(a, pair.action) == stable_lines(b, pair.result)
    else:
        assert stable_lines(a, pair.action) != stable_lines(b, pair.result)


def test_manifest_covers_every_pair_file():
    """A file in tests/compare that no entry names is a mistake."""
    named = {pair.action.name for pair in PAIRS} | {pair.result.name for pair in PAIRS}
    on_disk = {
        p.name for p in COMPARE_DIR.iterdir() if p.suffix in (".ttl", ".nt", ".nq")
    }
    on_disk.discard(MANIFEST.name)
    assert on_disk == named


def test_near_miss_variants_differ_from_base_in_one_place():
    """Each near-miss file differs from near-miss-base.ttl by exactly the
    line its name promises, so a failing pair test points at the change."""
    base = (COMPARE_DIR / "near-miss-base.ttl").read_text().splitlines()
    for path in sorted(COMPARE_DIR.glob("near-miss-*.ttl")):
        if path.name == "near-miss-base.ttl":
            continue
        lines = path.read_text().splitlines()
        removed = [line for line in base if line not in lines]
        added = [line for line in lines if line not in base]
        assert len(removed) == 1, path.name
        assert len(added) <= 1, path.name
