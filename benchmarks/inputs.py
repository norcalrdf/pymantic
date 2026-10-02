"""Named benchmark inputs: real-world graphs fetched by fetch_data.py, the
vendored RDFC-1.0 test inputs, and synthetic blank-node graphs.

Every benchmark script takes input names from here, so a name means the same
graph everywhere. ``load(name)`` returns a pymantic Graph; ``names(kind)``
lists the names of one kind ("real", "synthetic" or "rdfc10"), or all.
"""

import glob
import os
import random

from pymantic.parsers import nquads_parser, ntriples_parser, turtle_parser
from pymantic.primitives import BlankNode, Graph, Literal, NamedNode, Triple

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
RDFC10 = os.path.join(HERE, os.pardir, "tests", "compare", "rdfc10-inputs")
P = NamedNode("http://example/p")
KNOWS = NamedNode("http://xmlns.com/foaf/0.1/knows")


class MissingData(Exception):
    """A real-world input whose data has not been fetched yet."""


def data_path(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        raise MissingData(f"{path} is missing; run benchmarks/fetch_data.py first")
    return path


def parse_file(path, base=None):
    data = open(path, "rb").read()
    if path.endswith(".nt"):
        return ntriples_parser.parse_string(data)
    if path.endswith(".nq"):
        return nquads_parser.parse_string(data)
    return turtle_parser.parse(data, base=base)


def parse_directory(path):
    """Every .ttl file under path merged into one graph. Files pymantic
    cannot parse are skipped: six of the FHIR R5 examples are not valid
    Turtle (an IRI containing "|", a prefixed name with spaces) or start
    with a byte order mark."""
    graph = Graph()
    for file in sorted(glob.glob(os.path.join(path, "**", "*.ttl"), recursive=True)):
        try:
            part = parse_file(file)
        except Exception:
            continue
        for triple in part:
            graph.add(triple)
    return graph


def schemaorg_shapes():
    return parse_file(data_path("schemaorg-shapes.shacl"), base="https://schema.org/")


def schemaorg_subset(count):
    """The first ``count`` named shapes of the schema.org SHACL shapes, with
    every blank node reachable from them."""
    full = schemaorg_shapes()
    subjects = [s for s in full.subjects() if isinstance(s, NamedNode)][:count]
    graph, todo, seen = Graph(), list(subjects), set()
    while todo:
        subject = todo.pop()
        if subject in seen:
            continue
        seen.add(subject)
        for triple in full.match(subject=subject):
            graph.add(triple)
            if isinstance(triple.object, BlankNode):
                todo.append(triple.object)
    return graph


def graph_of(triples):
    graph = Graph()
    for triple in triples:
        graph.add(triple)
    return graph


def cycle(n):
    nodes = [BlankNode() for _ in range(n)]
    return graph_of(Triple(nodes[i], P, nodes[(i + 1) % n]) for i in range(n))


def ring_lattice(n):
    """Each node linked to the next two around a ring: the slowest honest
    shape the design note names."""
    nodes = [BlankNode() for _ in range(n)]
    return graph_of(
        Triple(nodes[i], P, nodes[(i + step) % n]) for i in range(n) for step in (1, 2)
    )


def random_3_regular(n, seed=1):
    """A random simple graph where every node has three neighbours, each
    edge written in both directions."""
    rng = random.Random(seed)
    while True:
        stubs = [i for i in range(n) for _ in range(3)]
        rng.shuffle(stubs)
        edges = set()
        for a, b in zip(stubs[::2], stubs[1::2]):
            if a == b or (a, b) in edges or (b, a) in edges:
                break
            edges.add((a, b))
        else:
            nodes = [BlankNode() for _ in range(n)]
            return graph_of(
                Triple(nodes[x], P, nodes[y])
                for a, b in edges
                for x, y in ((a, b), (b, a))
            )


def grid(n):
    nodes = {(i, j): BlankNode() for i in range(n) for j in range(n)}
    triples = []
    for (i, j), node in nodes.items():
        if i + 1 < n:
            triples.append(Triple(node, P, nodes[(i + 1, j)]))
        if j + 1 < n:
            triples.append(Triple(node, P, nodes[(i, j + 1)]))
    return graph_of(triples)


def hub_with_twins(k):
    """A blank node with k identical blank children."""
    hub, triples = BlankNode(), []
    for _ in range(k):
        child = BlankNode()
        triples.append(Triple(hub, P, child))
        triples.append(Triple(child, P, Literal("x")))
    return graph_of(triples)


def social(n, seed=3):
    """A preferential-attachment graph of n blank people who foaf:know each
    other in both directions, two links per newcomer, with no attributes."""
    rng = random.Random(seed)
    m, edges, repeated = 2, [], []
    for v in range(m, n):
        targets = set(range(m)) if v == m else set(rng.sample(repeated, m))
        edges.extend((v, t) for t in targets)
        repeated.extend([v] * m + [t for _, t in edges[-m:]])
    nodes = [BlankNode() for _ in range(n)]
    return graph_of(
        Triple(nodes[x], KNOWS, nodes[y]) for a, b in edges for x, y in ((a, b), (b, a))
    )


REAL = {
    "schemaorg-shapes": schemaorg_shapes,
    "schemaorg-shapes-100": lambda: schemaorg_subset(100),
    "schemaorg-shapes-400": lambda: schemaorg_subset(400),
    "fhir-r5-examples": lambda: parse_directory(data_path("fhir-r5-examples")),
    "fhir-r5-ontology": lambda: parse_file(data_path("fhir-r5.ttl")),
    "brick": lambda: parse_file(data_path("brick.ttl")),
    "obi": lambda: parse_file(data_path("obi.nt")),
    "doid": lambda: parse_file(data_path("doid.nt")),
    "dash": lambda: parse_file(data_path("dash.ttl")),
    "wot-td-validation": lambda: parse_file(data_path("wot-td-validation.ttl")),
}

SYNTHETIC = {
    "cycle-80": lambda: cycle(80),
    "ring-lattice-100": lambda: ring_lattice(100),
    "random-3-regular-20": lambda: random_3_regular(20),
    "random-3-regular-40": lambda: random_3_regular(40),
    "grid-8x8": lambda: grid(8),
    "grid-12x12": lambda: grid(12),
    "hub-40-twins": lambda: hub_with_twins(40),
    "social-1000": lambda: social(1000),
    "social-5000": lambda: social(5000),
}


def rdfc10_inputs():
    return {
        "rdfc10-"
        + os.path.basename(path)[: -len("-in.nq")]: (lambda p=path: parse_file(p))
        for path in sorted(glob.glob(os.path.join(RDFC10, "*-in.nq")))
    }


def loaders(kind=None):
    groups = {"real": REAL, "synthetic": SYNTHETIC, "rdfc10": rdfc10_inputs()}
    if kind is not None:
        return dict(groups[kind])
    return {name: load for group in groups.values() for name, load in group.items()}


def names(kind=None):
    return list(loaders(kind))


def load(name):
    try:
        return loaders()[name]()
    except KeyError:
        raise SystemExit(f"unknown input {name!r}; see benchmarks/README.rst") from None


def select(arguments, default_kind="real"):
    """Input names from command-line arguments: exact names, or the kinds
    "real", "synthetic" and "rdfc10"; with none, every input of
    ``default_kind``."""
    if not arguments:
        return names(default_kind)
    selected = []
    for argument in arguments:
        if argument in ("real", "synthetic", "rdfc10"):
            selected.extend(names(argument))
        elif argument in loaders():
            selected.append(argument)
        else:
            raise SystemExit(
                f"unknown input {argument!r}; choose from: "
                + ", ".join(
                    ["real", "synthetic", "rdfc10"] + names("real") + names("synthetic")
                )
            )
    return selected
