#!/usr/bin/env python
"""Describe inputs by their blank node structure, to judge whether a dataset
exercises pymantic.compare: how many triples touch a blank node, and how big
the molecules (connected groups of blank nodes) are.

    python benchmarks/census.py                 # every real input
    python benchmarks/census.py fhir-r5-examples doid

Inputs are names from benchmarks/inputs.py, or the kinds real, synthetic and
rdfc10 (default: real). Prints parse time, triples, blank nodes, the share of
triples touching a blank node, and molecule count and sizes. Time it with
timing.py.
"""

import argparse
import inputs
import statistics
import time

from pymantic.compare import molecules, statements
from pymantic.primitives import BlankNode


def census(name):
    t0 = time.perf_counter()
    try:
        graph = inputs.load(name)
    except inputs.MissingData as e:
        print(f"\n=== {name}: skipped: {e}")
        return
    parse = time.perf_counter() - t0
    triples = list(graph)
    blanks = {t for s in triples for t in s[:3] if isinstance(t, BlankNode)}
    touching = sum(1 for s in triples if any(isinstance(t, BlankNode) for t in s))
    sizes = sorted(len(m.nodes) for m in molecules(statements(graph)))
    print(f"\n=== {name}  (loaded in {parse:.2f} s)")
    print(
        f"  triples {len(triples)}  blank nodes {len(blanks)}  touching a blank "
        f"node {touching} ({100 * touching / max(1, len(triples)):.0f}%)"
    )
    if sizes:
        print(
            f"  molecules {len(sizes)}  nodes per molecule: median "
            f"{statistics.median(sizes)}  p90 {sizes[int(len(sizes) * 0.9)]}  "
            f"max {sizes[-1]}  (largest five: {sizes[-5:]})"
        )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.splitlines()[2:]),
    )
    ap.add_argument("inputs", nargs="*", help="input names or kinds (default: real)")
    args = ap.parse_args()
    for name in inputs.select(args.inputs):
        census(name)


if __name__ == "__main__":
    main()
