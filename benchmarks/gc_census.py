#!/usr/bin/env python
"""Show what Python's cyclic garbage collector costs for an input: how many
objects the loaded graph makes it track, by type, how long one full
collection takes with the graph loaded, and how many collections of each
generation run during canonical_labels and how long they take.

    python benchmarks/gc_census.py fhir-r5-examples
    python benchmarks/gc_census.py fhir-r5-examples --freeze

Young collections are cheap; a full (generation 2) collection walks every
tracked object, the input graph included, so its cost is paid by any
long-lived program holding the graph. --freeze calls gc.freeze() after
loading, which takes the graph out of the collector's reach and shows how
much of the full collections' cost is pymantic.compare's own objects.
"""

import argparse
from collections import Counter, defaultdict
import gc
import inputs
import time

import pymantic
from pymantic.compare import canonical_labels


def full_collection_time(repeat=3):
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        gc.collect()
        times.append(time.perf_counter() - t0)
    return min(times)


def collections_during(fn):
    counts, spent, started = defaultdict(int), defaultdict(float), {}

    def callback(phase, info):
        if phase == "start":
            started["at"] = time.perf_counter()
        else:
            counts[info["generation"]] += 1
            spent[info["generation"]] += time.perf_counter() - started["at"]

    gc.callbacks.append(callback)
    try:
        t0 = time.perf_counter()
        fn()
        total = time.perf_counter() - t0
    finally:
        gc.callbacks.remove(callback)
    return total, counts, spent


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.splitlines()[2:]),
    )
    ap.add_argument("input", help="one input name from benchmarks/inputs.py")
    ap.add_argument("--freeze", action="store_true", help="gc.freeze() after loading")
    ap.add_argument("--types", type=int, default=8, help="tracked types to list")
    args = ap.parse_args()
    print(f"pymantic from {pymantic.__file__}")

    gc.collect()
    before = len(gc.get_objects())
    empty = full_collection_time()
    graph = inputs.load(args.input)
    gc.collect()
    by_type = Counter(type(o).__qualname__ for o in gc.get_objects())
    print(
        f"{args.input}: {len(graph)} triples; the collector tracks "
        f"{sum(by_type.values()) - before} more objects than before loading"
    )
    for name, count in by_type.most_common(args.types):
        print(f"  {count:9}  {name}")
    print(
        f"one full collection: {empty * 1000:.1f} ms before loading, "
        f"{full_collection_time() * 1000:.1f} ms with the graph"
    )

    if args.freeze:
        gc.freeze()
    total, counts, spent = collections_during(lambda: canonical_labels(graph))
    print(f"canonical_labels {total:.2f} s{' (graph frozen)' if args.freeze else ''}:")
    for generation in sorted(counts):
        print(
            f"  generation {generation}: {counts[generation]:5} collections, "
            f"{spent[generation]:.2f} s"
        )


if __name__ == "__main__":
    main()
