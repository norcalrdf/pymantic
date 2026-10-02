#!/usr/bin/env python
"""Time canonical_labels and Turtle output on named inputs, and print a
digest of each result so two source trees can be compared for speed and for
identical output.

Use this to check that a change to pymantic.compare or the serializers is
faster and changes nothing: run it once per tree and compare the lines.

    python benchmarks/timing.py fhir-r5-examples schemaorg-shapes
    PYTHONPATH=<other tree>/src python benchmarks/timing.py fhir-r5-examples
    python benchmarks/timing.py synthetic --repeat 5 --what labels
    python benchmarks/timing.py obi --what turtle --index offsets

Inputs are names from benchmarks/inputs.py, or the kinds real, synthetic and
rdfc10 (default: real). --what picks labels, turtle (default output) and
stable (stable=True Turtle). Each time is the best of --repeat runs with the
garbage collector on; --gc-off adds a run set with it disabled. Every line
shows all run times, so the spread is visible: on a busy machine runs of a
few seconds vary by 10% or more. --index offsets loads the graphs into
pymantic.offset_index's OffsetTripleIndex instead of the default sorted
TripleIndex; --index dict loads them into pymantic.dict_index's
NestedDictTripleIndex.
"""

import argparse
import gc
import hashlib
import inputs
import io
import time

import pymantic
from pymantic.compare import Undecidable, canonical_labels
from pymantic.primitives import Profile
from pymantic.serializers import serialize_turtle

# Prefixes for the real inputs' Turtle, so the timed output is the readable
# document a user would write rather than one of full IRIs.
PREFIXES = {
    "schemaorg": {"sh": "http://www.w3.org/ns/shacl#", "schema": "http://schema.org/"},
    "fhir": {"fhir": "http://hl7.org/fhir/"},
    "doid": {
        "obo": "http://purl.obolibrary.org/obo/",
        "owl": "http://www.w3.org/2002/07/owl#",
    },
    "obi": {
        "obo": "http://purl.obolibrary.org/obo/",
        "owl": "http://www.w3.org/2002/07/owl#",
    },
}


def profile_for(name):
    profile = Profile()
    for start, prefixes in PREFIXES.items():
        if name.startswith(start):
            for prefix, iri in prefixes.items():
                profile.setPrefix(prefix, iri)
    return profile


def labels_digest(labels):
    # Labels are derived from content alone, so their multiset identifies
    # the result independently of the BlankNode objects in this process.
    return hashlib.sha256("\n".join(sorted(labels.values())).encode()).hexdigest()


def turtle(graph, name, stable):
    f = io.StringIO()
    serialize_turtle(graph, f, profile=profile_for(name), stable=stable)
    return f.getvalue()


def timed_runs(fn, repeat, gc_enabled):
    times, result = [], None
    for _ in range(repeat):
        gc.collect()
        if not gc_enabled:
            gc.disable()
        try:
            t0 = time.perf_counter()
            result = fn()
            times.append(time.perf_counter() - t0)
        finally:
            gc.enable()
    return times, result


def report(name, what, gc_enabled, times, digest):
    runs = " ".join(f"{t:.3f}" for t in times)
    gc_note = "" if gc_enabled else " gc-off"
    print(
        f"{name:24} {what + gc_note:14} best {min(times):8.3f} s  "
        f"{digest[:12]}  runs {runs}",
        flush=True,
    )


def use_index(name):
    """Make Graph and Dataset build the named index. "sorted" leaves the
    tree's own index in place, so the default runs on trees without
    pymantic.offset_index or pymantic.dict_index."""
    if name == "offsets":
        from pymantic import primitives
        from pymantic.offset_index import OffsetTripleIndex

        primitives.TripleIndex = OffsetTripleIndex
    elif name == "dict":
        from pymantic import primitives
        from pymantic.dict_index import NestedDictTripleIndex

        primitives.TripleIndex = NestedDictTripleIndex
    print(f"index: {name}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.splitlines()[2:]),
    )
    ap.add_argument("inputs", nargs="*", help="input names or kinds (default: real)")
    ap.add_argument(
        "--repeat", type=int, default=3, help="runs per measurement (default 3)"
    )
    ap.add_argument(
        "--what",
        default="labels,turtle,stable",
        help="comma-separated: labels, turtle, stable (default: all three)",
    )
    ap.add_argument(
        "--index",
        choices=["sorted", "offsets", "dict"],
        default="sorted",
        help="triple index for Graph and Dataset (default sorted)",
    )
    ap.add_argument(
        "--gc-off", action="store_true", help="also time with the collector off"
    )
    args = ap.parse_args()
    what = args.what.split(",")
    print(f"pymantic from {pymantic.__file__}")
    use_index(args.index)
    for name in inputs.select(args.inputs):
        try:
            graph = inputs.load(name)
        except inputs.MissingData as e:
            print(f"{name:24} skipped: {e}")
            continue
        measurements = {
            "labels": (
                lambda: canonical_labels(graph),
                labels_digest,
            ),
            "turtle": (
                lambda: turtle(graph, name, False),
                lambda text: hashlib.sha256(text.encode()).hexdigest(),
            ),
            "stable": (
                lambda: turtle(graph, name, True),
                lambda text: hashlib.sha256(text.encode()).hexdigest(),
            ),
        }
        for gc_enabled in (True, False) if args.gc_off else (True,):
            for kind in ("labels", "turtle", "stable"):
                if kind not in what:
                    continue
                run, digest = measurements[kind]
                try:
                    times, result = timed_runs(run, args.repeat, gc_enabled)
                except Undecidable:
                    print(f"{name:24} {kind:14} Undecidable", flush=True)
                    continue
                report(name, kind, gc_enabled, times, digest(result))


if __name__ == "__main__":
    main()
