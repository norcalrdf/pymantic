#!/usr/bin/env python
"""Time canonical blank node labels for one in-memory graph in four
implementations, as in the Measurements table of docs/graph-comparison.rst:
pymantic.compare.canonical_labels; pyld's URDNA2015 (RDFC-1.0 in pure
Python); rdf-canonize (the reference RDFC-1.0 implementation, in Node); and
rdflib's canonicalizer (what rdflib.compare.isomorphic computes).

    python benchmarks/compare_implementations.py            # the note's inputs
    python benchmarks/compare_implementations.py doid social-1000

Needs pyld and rdflib installed in the same environment, and for
rdf-canonize, Node with `npm ci` run in benchmarks/rdf-canonize; without
Node that column shows "no node". Parsing is excluded everywhere; Node
parses the N-Quads itself and only its canonicalization is timed.
rdf-canonize's default work factor aborts on some of the RDFC-1.0 suite's
own inputs, so it runs at each of --work-factors and the fastest run that
finishes is shown, with the setting in brackets. Caps: rdflib 60 s, pyld and
rdf-canonize 120 s, pymantic 600 s; a capped run shows "timeout". The
RDFC-1.0 suite inputs other than the clique (test074) are summed into one
row. Prints a Markdown table.
"""

import argparse
import inputs
import io
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time

from pymantic.compare import Undecidable, canonical_labels
from pymantic.primitives import BlankNode, Literal
from pymantic.serializers import serialize_nquads, serialize_ntriples

CAPS = {"pymantic": 600, "pyld": 120, "rdf-canonize": 120, "rdflib": 60}
NODE_DIR = os.path.join(inputs.HERE, "rdf-canonize")
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
RDF_LANGSTRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
DEFAULT_INPUTS = [
    "schemaorg-shapes-100",
    "schemaorg-shapes-400",
    "schemaorg-shapes",
    "social-1000",
    "social-5000",
    "cycle-80",
    "random-3-regular-20",
    "random-3-regular-40",
    "grid-8x8",
    "grid-12x12",
    "hub-40-twins",
    "rdfc10",
]


class Timeout(Exception):
    pass


def alarm(signum, frame):
    raise Timeout()


def timed(fn, cap):
    """Seconds fn took, or why it did not finish."""
    signal.signal(signal.SIGALRM, alarm)
    signal.alarm(cap)
    t0 = time.perf_counter()
    try:
        fn()
        return time.perf_counter() - t0
    except Timeout:
        return "timeout"
    except Undecidable:
        return f"Undecidable in {fmt(time.perf_counter() - t0)}"
    except RecursionError:
        return "recursion error"
    finally:
        signal.alarm(0)


def pyld_dataset(graph):
    """The graph in pyld's internal dataset form."""
    from pyld.canon import (  # noqa: F401  (fail early if pyld is missing)
        URDNA2015,
    )

    def term(node):
        if isinstance(node, BlankNode):
            return {"type": "blank node", "value": "_:" + node.value}
        if isinstance(node, Literal):
            result = {"type": "literal", "value": node.value}
            if node.language:
                result["language"] = node.language
                result["datatype"] = RDF_LANGSTRING
            else:
                result["datatype"] = str(node.datatype or XSD_STRING)
            return result
        return {"type": "IRI", "value": str(node)}

    dataset = {}
    for item in graph:
        name = item[3] if len(item) == 4 else None
        key = "@default" if name is None else term(name)["value"]
        dataset.setdefault(key, []).append(
            {
                "subject": term(item[0]),
                "predicate": term(item[1]),
                "object": term(item[2]),
            }
        )
    return dataset


def time_pyld(graph):
    from pyld.canon import URDNA2015

    dataset = pyld_dataset(graph)
    return timed(
        lambda: URDNA2015().main(dataset, {"format": "application/n-quads"}),
        CAPS["pyld"],
    )


def time_rdflib(graph):
    import rdflib
    from rdflib.compare import _TripleCanonicalizer

    def term(node):
        if isinstance(node, BlankNode):
            return rdflib.BNode(node.value)
        if isinstance(node, Literal):
            if node.language:
                return rdflib.Literal(node.value, lang=node.language)
            return rdflib.Literal(
                node.value, datatype=rdflib.URIRef(str(node.datatype))
            )
        return rdflib.URIRef(str(node))

    if any(len(item) == 4 and item[3] is not None for item in graph):
        return "n/a"
    converted = rdflib.Graph()
    for triple in graph:
        converted.add(tuple(term(t) for t in triple[:3]))
    return timed(lambda: _TripleCanonicalizer(converted).to_hash(), CAPS["rdflib"])


def time_rdf_canonize(graph, work_factors):
    if not shutil.which("node") or not os.path.isdir(
        os.path.join(NODE_DIR, "node_modules")
    ):
        return "no node"
    out = io.StringIO()
    if any(len(item) == 4 and item[3] is not None for item in graph):
        serialize_nquads(graph, out)
    else:
        serialize_ntriples(graph, out)
    with tempfile.NamedTemporaryFile("w", suffix=".nq", delete=False) as f:
        f.write(out.getvalue())
    best, failures = None, []
    try:
        for work_factor in work_factors:
            try:
                result = subprocess.run(
                    ["node", os.path.join(NODE_DIR, "label.js"), f.name, work_factor],
                    capture_output=True,
                    text=True,
                    timeout=CAPS["rdf-canonize"],
                )
                outcome = json.loads(result.stdout.strip().splitlines()[-1])
            except subprocess.TimeoutExpired:
                failures.append("timeout")
                continue
            if "error" in outcome:
                message = outcome["error"].lower()
                failures.append(
                    "aborted"
                    if "deep iterations" in message or "work" in message
                    else "error"
                )
            elif best is None or outcome["canonize"] < best[0]:
                best = (outcome["canonize"], work_factor)
    finally:
        os.unlink(f.name)
    if best is None:
        return failures[-1] if failures else "error"
    return (best[0], best[1])


def fmt(value):
    if isinstance(value, tuple):
        return f"{fmt(value[0])} [wf {value[1]}]"
    if isinstance(value, str):
        return value
    return f"{value:.3f} s" if value < 1 else f"{value:.1f} s"


def blank_count(graph):
    return len({t for item in graph for t in item[:3] if isinstance(t, BlankNode)})


def seconds(value):
    """The time in a measurement, or None when it did not finish."""
    if isinstance(value, tuple):
        return value[0]
    return value if isinstance(value, float) else None


def measure(graph, work_factors):
    """pymantic, pyld, rdf-canonize and rdflib results for one graph."""
    return [
        timed(lambda: canonical_labels(graph), CAPS["pymantic"]),
        time_pyld(graph),
        time_rdf_canonize(graph, work_factors),
        time_rdflib(graph),
    ]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.splitlines()[2:]),
    )
    ap.add_argument(
        "inputs", nargs="*", help="input names or kinds (default: the note's)"
    )
    ap.add_argument(
        "--work-factors",
        default="1,2,3",
        help="rdf-canonize maxWorkFactor settings to try, comma-separated (inf allowed)",
    )
    args = ap.parse_args()
    work_factors = args.work_factors.split(",")
    names = inputs.select(args.inputs or DEFAULT_INPUTS)
    header = [
        "input",
        "triples",
        "blank nodes",
        "pymantic",
        "pyld",
        "rdf-canonize",
        "rdflib",
    ]
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    summed = {"pymantic": 0.0, "pyld": 0.0, "rdf-canonize": 0.0, "count": 0}
    for name in names:
        try:
            graph = inputs.load(name)
        except inputs.MissingData as e:
            print(f"| {name} | skipped: {e} |")
            continue
        results = measure(graph, work_factors)
        if name.startswith("rdfc10-") and not name.startswith("rdfc10-test074"):
            # Summed below; an input where something did not finish is
            # shown on its own row instead.
            times = [seconds(value) for value in results[:3]]
            if None not in times:
                for key, value in zip(("pymantic", "pyld", "rdf-canonize"), times):
                    summed[key] += value
                summed["count"] += 1
                continue
        cells = [name, str(len(graph)), str(blank_count(graph))]
        cells += [fmt(value) for value in results]
        print("| " + " | ".join(cells) + " |", flush=True)
    if summed["count"]:
        print(
            f"| the other {summed['count']} RDFC-1.0 suite inputs, summed | | | "
            f"{fmt(summed['pymantic'])} | {fmt(summed['pyld'])} | "
            f"{fmt(summed['rdf-canonize'])} | n/a |"
        )


if __name__ == "__main__":
    main()
