"""Independent isomorphism checks for tests, so pymantic.compare is never
the judge of its own output.

rdflib judges graphs that hold only RDF 1.1 terms. rdflib cannot represent
RDF 1.2 triple terms or base directions, so a graph or dataset holding
either is judged by pyoxigraph: both sides are written as N-Quads, loaded
into pyoxigraph Datasets, canonicalized and compared. pyoxigraph has wheels
for CPython only; elsewhere :func:`require_oracle` skips the test.
"""

from io import StringIO
import pytest
import rdflib
from rdflib.compare import isomorphic as rdflib_isomorphic

from pymantic.primitives import BlankNode, Dataset, Literal, NamedNode, Triple
from pymantic.serializers import serialize_nquads, serialize_ntriples

try:
    import pyoxigraph
except ImportError:
    pyoxigraph = None


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


def has_rdf12_terms(graph_or_dataset):
    """Whether a graph or dataset holds a triple term or a literal with a
    base direction. Both can only be objects, and a directional literal
    inside a triple term needs no separate look: the triple term counts."""
    for statement in graph_or_dataset:
        object = statement[2]
        if isinstance(object, Triple):
            return True
        if isinstance(object, Literal) and object.direction:
            return True
    return False


def require_oracle():
    if pyoxigraph is None:
        pytest.skip(
            "pyoxigraph, the RDF 1.2 oracle, is not available on this interpreter"
        )


def to_pyoxigraph(graph_or_dataset):
    out = StringIO()
    if isinstance(graph_or_dataset, Dataset):
        serialize_nquads(graph_or_dataset, out)
    else:
        serialize_ntriples(graph_or_dataset, out)
    dataset = pyoxigraph.Dataset(
        pyoxigraph.parse(out.getvalue(), format=pyoxigraph.RdfFormat.N_QUADS)
    )
    dataset.canonicalize(pyoxigraph.CanonicalizationAlgorithm.UNSTABLE)
    return dataset


def isomorphic(a, b):
    """Whether two pymantic graphs, or two datasets, are isomorphic, by
    pyoxigraph when either holds RDF 1.2 terms and by rdflib otherwise. The
    rdflib path compares graphs only; a caller holding RDF 1.2 terms calls
    :func:`require_oracle` first."""
    if has_rdf12_terms(a) or has_rdf12_terms(b):
        return to_pyoxigraph(a) == to_pyoxigraph(b)
    if isinstance(a, Dataset) or isinstance(b, Dataset):
        raise TypeError("the rdflib oracle compares graphs, not datasets")
    return rdflib_isomorphic(to_rdflib(a), to_rdflib(b))
