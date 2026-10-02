#!/usr/bin/env python
"""Profile canonical_labels and Turtle output on named inputs with cProfile,
to find where the time goes before changing anything.

    python benchmarks/profiling.py fhir-r5-examples
    python benchmarks/profiling.py ring-lattice-100 --what labels --rows 25
    python benchmarks/profiling.py schemaorg-shapes --sort cumulative --filter serializers

Inputs are names from benchmarks/inputs.py, or the kinds real, synthetic and
rdfc10 (default: real). --what picks labels, turtle and stable as in
timing.py. Prints the top --rows functions per profile and saves each full
profile to benchmarks/out/<input>.<what>.prof for pstats or snakeviz.
cProfile counts every resumption of a generator as a call, so a generator's
ncalls is the number of items it yielded, not how often it was started.
"""

import argparse
import cProfile
import inputs
import io
import os
import pstats
import time
from timing import turtle

from pymantic.compare import Undecidable, canonical_labels

OUT = os.path.join(inputs.HERE, "out")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.splitlines()[2:]),
    )
    ap.add_argument("inputs", nargs="*", help="input names or kinds (default: real)")
    ap.add_argument("--what", default="labels,stable", help="labels, turtle, stable")
    ap.add_argument("--rows", type=int, default=20, help="functions shown per profile")
    ap.add_argument(
        "--sort", default="tottime", help="pstats sort key (default tottime)"
    )
    ap.add_argument(
        "--filter", default=None, help="regex on file:line(function) to show"
    )
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    for name in inputs.select(args.inputs):
        try:
            graph = inputs.load(name)
        except inputs.MissingData as e:
            print(f"=== {name}: skipped: {e}")
            continue
        runs = {
            "labels": lambda: canonical_labels(graph),
            "turtle": lambda: turtle(graph, name, False),
            "stable": lambda: turtle(graph, name, True),
        }
        for what in args.what.split(","):
            profiler = cProfile.Profile()
            t0 = time.perf_counter()
            try:
                profiler.runcall(runs[what])
            except Undecidable as e:
                print(f"\n=== {name} {what}: Undecidable ({e})")
                continue
            wall = time.perf_counter() - t0
            path = os.path.join(OUT, f"{name}.{what}.prof")
            profiler.dump_stats(path)
            stream = io.StringIO()
            stats = pstats.Stats(profiler, stream=stream).strip_dirs()
            restrictions = [args.filter, args.rows] if args.filter else [args.rows]
            stats.sort_stats(args.sort).print_stats(*restrictions)
            text = stream.getvalue()
            print(f"\n=== {name} {what}: {wall:.3f} s under cProfile, saved {path}")
            print(text[text.index("   ncalls") :].rstrip())


if __name__ == "__main__":
    main()
