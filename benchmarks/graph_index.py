#!/usr/bin/env python
"""Measure the Graph and Dataset index: load time, memory, GC load, match speed.

Use this to compare two source trees: run it once per tree and compare the
lines. It uses only the public Graph and Dataset API, so it runs unchanged
on the old and the new index.

    python benchmarks/graph_index.py obi --repeat 5
    PYTHONPATH=<other tree>/src python benchmarks/graph_index.py
    python benchmarks/graph_index.py --dataset-per-file

Inputs are names from benchmarks/inputs.py, or the kinds real, synthetic and
rdfc10 (default: fhir-r5-examples obi doid schemaorg-shapes). Every timing is
the best of --repeat runs, with every run shown. Per input:

  parse     inputs.load(name): the input parsed from its file into a
            Graph, as a program loads it
  load      Graph().addAll(triples) from a pre-parsed list of triples,
            then one match with a bound subject, so an index that sorts
            lazily has sorted by the end of the timing
  memory    bytes per triple the graph adds (tracemalloc), not counting the
            triples list or the terms in it, which the caller holds
  gc        objects the collector tracks because of the graph, per triple,
            counted the same way, and the best of 3 full collections
  retained  with --retained: bytes and tracked objects per triple for a
            graph parsed from its file and kept, terms included; the cost
            of a parsed graph as a program holds it
  match     milliseconds per pattern for up to 1000 queries; the pattern names
            the bound positions (s, p, o). The bound values are sampled
            (random.Random(0)) from the distinct values of those positions
            in the graph's own triples, so a pattern with fewer than 1000
            distinct values runs fewer queries, and the count is printed.
            "-" binds nothing and is one full pass. Every query's results
            are consumed.
  iterate   one pass over the graph, and Counter(t.object for t in graph)
  batch k   k adds of new triples then one match on the last one's
            subject, for k in 1, 32, 33 and 1000; milliseconds per batch,
            over about 2000 adds. Each new triple has a new subject and a
            predicate and object taken from the graph, so an index that
            merges adds by bisect inserts them all through its orderings.
  interleave  1000 times: add one new triple, then match a subject from
            the graph; milliseconds for all 1000

The batch and interleave cases add to the loaded graph, so they run last.

--dataset-per-file loads fhir-r5-examples as a Dataset with one named graph
per .ttl file (the graph's name is the file's file:// IRI) and reports load
time (adds, then one match with a bound subject), tracked objects and bytes
per quad. Files pymantic cannot parse are skipped, as in
inputs.parse_directory, and counted.
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

try:
    import tracemalloc
except ImportError:
    # PyPy has no tracemalloc; memory is then reported as unavailable.
    tracemalloc = None

import pymantic
from pymantic.primitives import Dataset, Graph, NamedNode, Quad, Triple

DEFAULT_INPUTS = ["fhir-r5-examples", "obi", "doid", "schemaorg-shapes"]
SAMPLES = 1000
BATCHES = (1, 32, 33, 1000)
BATCH_ADDS = 2000
INTERLEAVED = 1000
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


def best_of(fn, repeat):
    """Time fn() ``repeat`` times after a collection each; returns the
    times and the last result."""
    times, result = [], None
    for _ in range(repeat):
        result = None
        gc.collect()
        t0 = time.perf_counter()
        result = fn()
        times.append(time.perf_counter() - t0)
    return times, result


def runs_text(times, scale=1, digits=3):
    return " ".join(f"{t * scale:.{digits}f}" for t in times)


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


def footprint(build):
    """Bytes and collector-tracked objects held by build(), measured in a
    separate run so tracemalloc does not slow the timed ones. Whatever
    build's arguments hold stays alive and is not counted."""
    gc.collect()
    objects_before = tracked_objects()
    if tracemalloc is None:
        return build(), None, tracked_objects() - objects_before
    tracemalloc.start()
    held = build()
    gc.collect()
    size = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    objects = tracked_objects() - objects_before
    return held, size, objects


def bytes_per(size, count, unit):
    if size is None:
        return f"    n/a bytes/{unit} (no tracemalloc)"
    return f"{size / count:7.1f} bytes/{unit}"


def consume(results):
    for _ in results:
        pass


def build_graph(triples):
    graph = Graph().addAll(triples)
    if triples:
        consume(graph.match(subject=triples[0].subject))
    return graph


def build_dataset(quads):
    dataset = Dataset()
    for quad in quads:
        dataset.add(quad)
    if quads:
        # Matches in every graph, so each graph's index is ready.
        consume(dataset.match(subject=quads[0].subject))
    return dataset


def match_queries(triples):
    rng = random.Random(0)
    queries = {}
    for name, bound in PATTERNS.items():
        if name == "-":
            # Binding nothing returns the whole graph, so it runs once.
            queries[name] = [(None, None, None)]
            continue
        distinct = list(
            dict.fromkeys(
                tuple(x if b else None for x, b in zip(t, bound)) for t in triples
            )
        )
        queries[name] = rng.sample(distinct, min(SAMPLES, len(distinct)))
    return queries


def run_queries(graph, queries):
    found = 0
    for terms in queries:
        for _ in graph.match(*terms):
            found += 1
    return found


def new_triples(triples, count, rng, serial):
    """``count`` triples absent from the graph: each a new subject with a
    predicate and an object from a random triple of the graph."""
    made = []
    for _ in range(count):
        _, p, o = rng.choice(triples)
        made.append(
            Triple(NamedNode(f"urn:graph-index-benchmark:{next(serial)}"), p, o)
        )
    return made


def batch_runs(graph, triples, k, repeat, serial):
    """Milliseconds per batch of k adds and one query, best of repeat."""
    rng = random.Random(k)
    rounds = max(1, BATCH_ADDS // k)
    times = []
    for _ in range(repeat):
        batches = [new_triples(triples, k, rng, serial) for _ in range(rounds)]
        gc.collect()
        t0 = time.perf_counter()
        for batch in batches:
            for triple in batch:
                graph.add(triple)
            consume(graph.match(subject=batch[-1].subject))
        times.append((time.perf_counter() - t0) / rounds)
    return rounds, times


def interleave_runs(graph, triples, repeat, serial):
    """Seconds for INTERLEAVED rounds of one add then one query, best of
    repeat."""
    rng = random.Random(1)
    times = []
    for _ in range(repeat):
        adds = new_triples(triples, INTERLEAVED, rng, serial)
        subjects = [rng.choice(triples).subject for _ in range(INTERLEAVED)]
        gc.collect()
        t0 = time.perf_counter()
        for triple, subject in zip(adds, subjects):
            graph.add(triple)
            consume(graph.match(subject=subject))
        times.append(time.perf_counter() - t0)
    return times


def report_retained(name):
    graph, size, objects = footprint(lambda: inputs.load(name))
    count = len(graph)
    print(
        f"  retained {bytes_per(size, count, 'triple')}, "
        f"{objects / count:.3f} tracked objects/triple "
        "(parsed and kept, terms included)"
    )


def report_graph(name, parse_times, triples, repeat, retained):
    times, graph = best_of(lambda: build_graph(triples), repeat)
    count = len(graph)
    print(f"{name}: {len(triples)} triples, {count} in the graph", flush=True)
    print(f"  parse    best {min(parse_times):7.3f} s  runs {runs_text(parse_times)}")
    print(f"  load     best {min(times):7.3f} s  runs {runs_text(times)}")
    del graph
    graph, size, objects = footprint(lambda: build_graph(triples))
    print(
        f"  memory   {bytes_per(size, count, 'triple')} "
        "(index only: the caller's triples and terms excluded)"
    )
    print(
        f"  gc       {objects / count:7.3f} tracked objects/triple (index only)  "
        f"full collection {full_collection_ms():.1f} ms"
    )
    if retained:
        report_retained(name)
    for pattern, queries in match_queries(triples).items():
        times, found = best_of(lambda: run_queries(graph, queries), repeat)
        print(
            f"  match {pattern:3} best {min(times) * 1000:8.2f} ms for {len(queries):4} "
            f"queries, {found} results"
            + (" (one full pass)" if pattern == "-" else "")
            + f"  runs {runs_text(times, 1000, 2)}"
        )
    times, _ = best_of(lambda: consume(graph), repeat)
    print(
        f"  iterate  best {min(times) * 1000:8.2f} ms  runs {runs_text(times, 1000, 2)}"
    )
    times, objects_count = best_of(lambda: Counter(t.object for t in graph), repeat)
    print(
        f"  Counter of objects best {min(times) * 1000:8.2f} ms "
        f"({len(objects_count)} distinct)  runs {runs_text(times, 1000, 2)}"
    )
    serial = iter(range(10**12))
    for k in BATCHES:
        rounds, times = batch_runs(graph, triples, k, repeat, serial)
        print(
            f"  batch {k:4} best {min(times) * 1000:8.3f} ms per batch "
            f"({rounds} batches)  runs {runs_text(times, 1000)}"
        )
    times = interleave_runs(graph, triples, repeat, serial)
    print(
        f"  interleave best {min(times) * 1000:7.1f} ms for {INTERLEAVED} "
        f"add-then-match rounds  runs {runs_text(times, 1000, 1)}"
    )


def fhir_quads():
    """The FHIR R5 examples as quads, one named graph per file, with the
    counts of files parsed and skipped."""
    root = inputs.data_path("fhir-r5-examples")
    quads, files, skipped = [], 0, 0
    for path in sorted(glob.glob(os.path.join(root, "**", "*.ttl"), recursive=True)):
        try:
            part = inputs.parse_file(path)
        except Exception:
            skipped += 1
            continue
        files += 1
        name = NamedNode(pathlib.Path(os.path.abspath(path)).as_uri())
        quads.extend(Quad(t.subject, t.predicate, t.object, name) for t in part)
    return quads, files, skipped


def report_dataset(repeat):
    quads, files, skipped = fhir_quads()
    times, dataset = best_of(lambda: build_dataset(quads), repeat)
    count = len(dataset)
    print(
        f"fhir-r5-examples as a dataset: {files} files, {skipped} skipped as "
        f"unparsable, {len(quads)} quads, {count} in the dataset",
        flush=True,
    )
    print(f"  load     best {min(times):7.3f} s  runs {runs_text(times)}")
    del dataset
    dataset, size, objects = footprint(lambda: build_dataset(quads))
    print(
        f"  memory   {bytes_per(size, count, 'quad')} "
        "(index only: the caller's quads and terms excluded)"
    )
    print(
        f"  gc       {objects / count:7.3f} tracked objects/quad (index only)  "
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
    ap.add_argument("--repeat", type=int, default=3, help="runs per timing (default 3)")
    ap.add_argument(
        "--dataset-per-file",
        action="store_true",
        help="also load fhir-r5-examples as one named graph per file",
    )
    ap.add_argument(
        "--retained",
        action="store_true",
        help="also measure a parsed-and-kept graph, terms included (slow)",
    )
    args = ap.parse_args()
    print(f"pymantic from {pymantic.__file__}")
    for name in inputs.select(args.inputs or DEFAULT_INPUTS):
        try:
            parse_times, graph = best_of(lambda: inputs.load(name), args.repeat)
        except inputs.MissingData as e:
            print(f"{name}: skipped: {e}")
            continue
        triples = list(graph)
        del graph
        report_graph(name, parse_times, triples, args.repeat, args.retained)
        del triples
    if args.dataset_per_file:
        try:
            report_dataset(args.repeat)
        except inputs.MissingData as e:
            print(f"fhir-r5-examples as a dataset: skipped: {e}")


if __name__ == "__main__":
    main()
