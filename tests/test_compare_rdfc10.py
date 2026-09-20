"""The RDFC-1.0 test suite inputs as adversarial fixtures for
pymantic.compare (see tests/compare/rdfc10-inputs/README.md).

For every input: a relabelled, shuffled copy must be isomorphic to the
original and both must serialize to the same bytes with stable=True; a copy
with one quad removed, or with one blank node edge redirected to a fresh
blank node, must not be isomorphic. The poison inputs listed in POISON must
raise Undecidable quickly on the first check; the altered copies are still
told apart, because the comparison bails before any refinement.
"""

from io import StringIO
import pathlib
import pytest
import random
import time

from pymantic.compare import Undecidable, isomorphic
from pymantic.parsers import nquads_parser
from pymantic.primitives import BlankNode, Graph, Quad
from pymantic.serializers import serialize_nquads

INPUTS_DIR = pathlib.Path(__file__).parent / "compare" / "rdfc10-inputs"
INPUTS = sorted(INPUTS_DIR.glob("*-in.nq"))
assert len(INPUTS) == 65, "expected the 65 vendored RDFC-1.0 inputs"

# Inputs whose blank nodes no content can tell apart, so that only the
# individualization search could label them, and it exceeds the work
# budget. test074 is a 10-node clique of blank nodes (100 triples, one
# predicate). The suite's other "poison" graphs, test044 to test046 (two
# 6-node 3-regular components), refine within the budget and are not
# listed: they are handled like any other input.
POISON = {"test074-in.nq"}

# Well under a second, so a caller that hits the budget notices at once
# instead of waiting for an exponential search.
POISON_SECONDS = 1.0


def parse(path):
    return nquads_parser.parse_string(path.read_bytes())


def relabelled_and_shuffled(graph, seed):
    rng = random.Random(seed)
    fresh = {}

    def term(node):
        if isinstance(node, BlankNode):
            return fresh.setdefault(node, BlankNode())
        return node

    quads = [Quad(term(s), term(p), term(o), term(g)) for s, p, o, g in graph]
    rng.shuffle(quads)
    return Graph().addAll(quads)


def with_one_quad_removed(graph):
    quads = list(graph)
    quads.pop(len(quads) // 2)
    return Graph().addAll(quads)


def with_one_edge_redirected(graph):
    """Point one quad's blank node object at a fresh blank node instead. The
    original object must occur elsewhere too, so the copy has one more blank
    node than the original and cannot be isomorphic to it. Returns None when
    the input has no such quad."""
    occurrences = {}
    for quad in graph:
        for term in quad:
            if isinstance(term, BlankNode):
                occurrences[term] = occurrences.get(term, 0) + 1
    for quad in graph:
        if isinstance(quad.object, BlankNode) and occurrences[quad.object] > 1:
            quads = [q for q in graph if q is not quad]
            quads.append(Quad(quad.subject, quad.predicate, BlankNode(), quad.graph))
            return Graph().addAll(quads)
    return None


def stable_nquads(graph):
    out = StringIO()
    serialize_nquads(graph, out, stable=True)
    return out.getvalue()


def ids(paths):
    return [path.name.replace("-in.nq", "") for path in paths]


REGULAR = [path for path in INPUTS if path.name not in POISON]
POISONOUS = [path for path in INPUTS if path.name in POISON]
NON_EMPTY = [path for path in INPUTS if len(parse(path)) > 0]
REDIRECTABLE = [
    path for path in INPUTS if with_one_edge_redirected(parse(path)) is not None
]


@pytest.mark.parametrize("path", REGULAR, ids=ids(REGULAR))
def test_relabelled_copy_is_isomorphic_and_serializes_identically(path):
    graph = parse(path)
    copy = relabelled_and_shuffled(graph, seed=len(path.name))
    assert isomorphic(graph, copy)
    assert isomorphic(copy, graph)
    assert stable_nquads(graph) == stable_nquads(copy)


@pytest.mark.parametrize("path", POISONOUS, ids=ids(POISONOUS))
def test_poison_input_is_undecidable_quickly(path):
    graph = parse(path)
    copy = relabelled_and_shuffled(graph, seed=1)
    started = time.perf_counter()
    with pytest.raises(Undecidable):
        isomorphic(graph, copy)
    with pytest.raises(Undecidable):
        stable_nquads(graph)
    assert time.perf_counter() - started < POISON_SECONDS


@pytest.mark.parametrize("path", NON_EMPTY, ids=ids(NON_EMPTY))
def test_copy_with_one_quad_removed_is_not_isomorphic(path):
    graph = parse(path)
    altered = with_one_quad_removed(relabelled_and_shuffled(graph, seed=2))
    assert not isomorphic(graph, altered)
    assert not isomorphic(altered, graph)


@pytest.mark.parametrize("path", REDIRECTABLE, ids=ids(REDIRECTABLE))
def test_copy_with_one_edge_redirected_is_not_isomorphic(path):
    graph = parse(path)
    altered = with_one_edge_redirected(relabelled_and_shuffled(graph, seed=3))
    assert not isomorphic(graph, altered)
    assert not isomorphic(altered, graph)


def test_fixture_lists_cover_the_inputs():
    """The lists above are computed from the files; pin their sizes so a
    change to the vendored inputs is noticed."""
    assert POISON <= {path.name for path in INPUTS}
    assert len(NON_EMPTY) == 64
    assert len(REDIRECTABLE) == 43
