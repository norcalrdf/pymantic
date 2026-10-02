#!/usr/bin/env python
"""Measure the Graph and Dataset index: load time, memory, GC load, match speed.

Use this to compare two source trees: run it once per tree and compare the
lines. It uses only the public Graph and Dataset API, so it runs unchanged
on the old and the new index.

    python benchmarks/graph_index.py obi --repeat 5
    PYTHONPATH=<other tree>/src python benchmarks/graph_index.py
    python benchmarks/graph_index.py --dataset-per-file

Inputs are names from benchmarks/inputs.py, or the kinds real, synthetic and
rdfc10 (default: fhir-r5-examples obi doid schemaorg-shapes). Per input:

  load      best of --repeat times for Graph().addAll(triples) from a
            pre-parsed list of triples, with every run shown
  memory    bytes per triple of the loaded graph (tracemalloc), not
            counting the triples list or the terms in it
  gc        objects the collector tracks because of the graph, per triple,
            and the best of 3 full collections
  match     seconds for 1000 queries per pattern; the bound terms are
            sampled (random.Random(0)) from the graph's own triples, and
            the pattern names the bound positions (s, p, o; "-" binds none,
            run once). Every query's results are consumed.
  iterate   one pass over the graph, and Counter(t.object for t in graph)

--dataset-per-file loads fhir-r5-examples as a Dataset with one named graph
per .ttl file (the graph's name is the file's file:// IRI) and reports load
time, tracked objects and bytes per quad. Files pymantic cannot parse are
skipped, as in inputs.parse_directory.
"""

import argparse
from collections import Counter
import gc
import glob
import inputs
import os
import pathlib
import random
import time
import tracemalloc

import pymantic
from pymantic.primitives import Dataset, Graph, NamedNode, Quad

DEFAULT_INPUTS = ["fhir-r5-examples", "obi", "doid", "schemaorg-shapes"]
SAMPLES = 1000
# Pattern name -> positions (subject, predicate, object) that are bound.
PATTERNS = {
    "s": (1, 0, 0),
    "p": (0, 1, 0),
    "o": (0, 0, 1),
    "sp": (1, 1, 0),
    "so": (1, 0, 1),
    "po": (0, 1, 1),
    "spo": (1, 1, 1),
    "-": (0, 0, 0),
}


def best_load(build, source, repeat):
    """Time build(source) ``repeat`` times; returns the times and the last
    result."""
    times, result = [], None
    for _ in range(repeat):
        result = None
        gc.collect()
        t0 = time.perf_counter()
        result = build(source)
        times.append(time.perf_counter() - t0)
    return times, result


def runs_text(times):
    return " ".join(f"{t:.3f}" for t in times)


def full_collection_ms(repeat=3):
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        gc.collect()
        times.append(time.perf_counter() - t0)
    return min(times) * 1000


def tracked_objects():
    gc.collect()
    return len(gc.get_objects())


def footprint(build, source):
    """Bytes and collector-tracked objects held by build(source), measured
    in a separate load so tracemalloc does not slow the timed ones. The
    source stays alive and is not counted."""
    gc.collect()
    objects_before = tracked_objects()
    tracemalloc.start()
    held = build(source)
    gc.collect()
    size = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    objects = tracked_objects() - objects_before
    return held, size, objects


def build_graph(triples):
    return Graph().addAll(triples)


def build_dataset(quads):
    dataset = Dataset()
    for quad in quads:
        dataset.add(quad)
    return dataset


def match_times(graph, triples):
    rng = random.Random(0)
    sample = rng.sample(triples, min(SAMPLES, len(triples)))
    results = {}
    for name, bound in PATTERNS.items():
        # Binding nothing returns the whole graph, so it runs once.
        queries = [None] if name == "-" else sample
        t0 = time.perf_counter()
        found = 0
        for t in queries:
            terms = (
                (None,) * 3
                if t is None
                else [x if b else None for x, b in zip(t, bound)]
            )
            for _ in graph.match(*terms):
                found += 1
        results[name] = (len(queries), time.perf_counter() - t0, found)
    return results


def report_graph(name, triples, repeat):
    times, graph = best_load(build_graph, triples, repeat)
    count = len(graph)
    print(f"{name}: {len(triples)} triples, {count} in the graph", flush=True)
    print(f"  load     best {min(times):7.3f} s  runs {runs_text(times)}")
    del graph
    graph, size, objects = footprint(build_graph, triples)
    print(f"  memory   {size / count:7.1f} bytes/triple")
    print(
        f"  gc       {objects / count:7.3f} tracked objects/triple  "
        f"full collection {full_collection_ms():.1f} ms"
    )
    for pattern, (queries, seconds, found) in match_times(graph, triples).items():
        print(
            f"  match {pattern:3} {seconds:8.3f} s for {queries:4} queries, "
            f"{found} results"
        )
    t0 = time.perf_counter()
    for _ in graph:
        pass
    iterate = time.perf_counter() - t0
    t0 = time.perf_counter()
    objects_count = Counter(t.object for t in graph)
    counted = time.perf_counter() - t0
    print(
        f"  iterate  {iterate:7.3f} s; Counter of objects {counted:.3f} s "
        f"({len(objects_count)} distinct)"
    )


def fhir_quads():
    """The FHIR R5 examples as quads, one named graph per file."""
    root = inputs.data_path("fhir-r5-examples")
    quads, files = [], 0
    for path in sorted(glob.glob(os.path.join(root, "**", "*.ttl"), recursive=True)):
        try:
            part = inputs.parse_file(path)
        except Exception:
            continue
        files += 1
        name = NamedNode(pathlib.Path(os.path.abspath(path)).as_uri())
        quads.extend(Quad(t.subject, t.predicate, t.object, name) for t in part)
    return quads, files


def report_dataset(repeat):
    quads, files = fhir_quads()
    times, dataset = best_load(build_dataset, quads, repeat)
    count = len(dataset)
    print(
        f"fhir-r5-examples as a dataset: {files} files, {len(quads)} quads, "
        f"{count} in the dataset",
        flush=True,
    )
    print(f"  load     best {min(times):7.3f} s  runs {runs_text(times)}")
    del dataset
    dataset, size, objects = footprint(build_dataset, quads)
    print(f"  memory   {size / count:7.1f} bytes/quad")
    print(
        f"  gc       {objects / count:7.3f} tracked objects/quad  "
        f"full collection {full_collection_ms():.1f} ms"
    )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.splitlines()[2:]),
    )
    ap.add_argument(
        "inputs",
        nargs="*",
        help="input names or kinds (default: " + " ".join(DEFAULT_INPUTS) + ")",
    )
    ap.add_argument(
        "--repeat", type=int, default=3, help="load runs per input (default 3)"
    )
    ap.add_argument(
        "--dataset-per-file",
        action="store_true",
        help="also load fhir-r5-examples as one named graph per file",
    )
    args = ap.parse_args()
    print(f"pymantic from {pymantic.__file__}")
    for name in inputs.select(args.inputs or DEFAULT_INPUTS):
        try:
            triples = list(inputs.load(name))
        except inputs.MissingData as e:
            print(f"{name}: skipped: {e}")
            continue
        report_graph(name, triples, args.repeat)
        del triples
    if args.dataset_per_file:
        try:
            report_dataset(args.repeat)
        except inputs.MissingData as e:
            print(f"fhir-r5-examples as a dataset: skipped: {e}")


if __name__ == "__main__":
    main()
