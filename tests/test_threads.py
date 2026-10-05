"""Many threads changing and reading one Graph or Dataset at once.

Each writer thread owns its own triples, so its part of the end state does
not depend on how the threads interleave, but the triples share predicates
and objects, so the threads meet in the same rows, the same dictionary and
the same compactions. On a free-threaded build the threads really run at
once; elsewhere a short switch interval interleaves them finely.
"""

import pytest
import random
import sys
import threading
import time

from pymantic.primitives import (
    Dataset,
    Graph,
    Literal,
    NamedNode,
    Quad,
    Triple,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "emscripten", reason="Pyodide cannot start threads"
)

WRITERS = 4
READERS = 3
SECONDS = 1.0

PREDICATES = [NamedNode(f"http://e/p{i}") for i in range(3)]
OBJECTS = [Literal(f"o{i}") for i in range(5)] + [NamedNode("http://e/shared")]
SHARED_GRAPH = NamedNode("http://e/shared-graph")
SUBJECTS = 40


@pytest.fixture(autouse=True)
def fine_switching():
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(interval)


def subject(writer, i):
    return NamedNode(f"http://e/w{writer}/s{i}")


def possible(triple):
    """Whether a writer could ever add `triple`. Subject i only takes
    predicate i % 3 and two of the objects, so a read that put a term in
    the wrong place would almost always give a triple no writer adds."""
    s, p, o = triple
    writer, i = (int(x[1:]) for x in s.split("/")[-2:])
    return (
        s == subject(writer, i)
        and p == PREDICATES[i % 3]
        and o in (OBJECTS[i % 6], OBJECTS[(i + 1) % 6])
    )


def own_triples(writer, rng, count):
    """Triples only `writer` adds, with fresh subjects, so removing them
    leaves dead terms for compaction to free and other threads to reuse."""
    triples = []
    for _ in range(count):
        i = rng.randrange(SUBJECTS)
        o = OBJECTS[(i + rng.randrange(2)) % 6]
        triples.append(Triple(subject(writer, i), PREDICATES[i % 3], o))
    return triples


def run_threads(targets):
    """Run every target in its own thread until the time is up; return the
    errors they raised, which the test then shows."""
    stop = threading.Event()
    errors = []

    def guarded(target):
        try:
            target(stop)
        except BaseException as e:
            errors.append(e)
            stop.set()

    threads = [threading.Thread(target=guarded, args=(t,)) for t in targets]
    for thread in threads:
        thread.start()
    time.sleep(SECONDS)
    stop.set()
    for thread in threads:
        thread.join()
    return errors


def graph_writer(graph, writer, model, ever):
    def write(stop):
        rng = random.Random(writer)
        present = set()
        while not stop.is_set():
            batch = own_triples(writer, rng, rng.randrange(1, 40))
            choice = rng.random()
            if choice < 0.4:
                ever.update(batch)
                for triple in batch:
                    graph.add(triple)
                present.update(batch)
            elif choice < 0.55:
                ever.update(batch)
                graph.addAll(batch)
                present.update(batch)
            elif choice < 0.85:
                for triple in batch:
                    if triple in present:
                        graph.remove(triple)
                        present.discard(triple)
            else:
                s = batch[0].subject
                graph.removeMatches(s, None, None)
                present = {t for t in present if t.subject != s}
        model.update(present)

    return write


def ended_by_a_change(read):
    """Run `read`, which keeps what it reads as it goes. Another thread's
    change ends a read with RuntimeError, after what it yielded so far, as
    does removing a graph a dataset read has yet to finish; any other error
    is a failure."""
    try:
        read()
    except RuntimeError as e:
        message = str(e)
        assert "changed during iteration" in message or "detached" in message, e


def graph_reader(graph, seen, seed):
    """Reads every way a graph can be read, keeping each triple read; the
    lookups that yield single terms are checked as they come."""

    def subjects_ok():
        for s in graph.subjects(PREDICATES[1], OBJECTS[1]):
            assert possible(Triple(s, PREDICATES[1], OBJECTS[1]))

    def read(stop):
        rng = random.Random(seed)
        while not stop.is_set():
            pattern = [
                rng.choice([None, subject(0, 3)]),
                rng.choice([None, PREDICATES[0]]),
                rng.choice([None, OBJECTS[0]]),
            ]
            s = subject(rng.randrange(WRITERS), 3)
            for one_read in [
                lambda: seen.update(graph.match(*pattern)),
                lambda: seen.update(graph),
                lambda: seen.update(
                    Triple(*t) for t in graph.mapped_triples(lambda term: term)
                ),
                lambda: seen.update(
                    Triple(s, p, o) for p, o in graph.predicate_objects(s)
                ),
                lambda: seen.update(
                    Triple(s, PREDICATES[0], o) for o in graph.objects(s, PREDICATES[0])
                ),
                subjects_ok,
            ]:
                ended_by_a_change(one_read)

    return read


def assert_graph_is(graph, triples):
    assert set(graph) == triples
    assert len(graph) == len(triples)
    for s, p, o in list(triples)[:50]:
        for pattern in [(s, None, None), (None, p, None), (None, None, o), (s, p, o)]:
            want = {
                t
                for t in triples
                if all(x is None or x == y for x, y in zip(pattern, t))
            }
            assert set(graph.match(*pattern)) == want
    assert set(graph.subjects()) == {t.subject for t in triples}
    assert set(graph.objects()) == {t.object for t in triples}


def test_threads_changing_and_reading_one_graph():
    graph = Graph()
    models = [set() for _ in range(WRITERS)]
    ever = set()
    seen = set()
    errors = run_threads(
        [graph_writer(graph, w, models[w], ever) for w in range(WRITERS)]
        + [graph_reader(graph, seen, r) for r in range(READERS)]
    )
    assert errors == []
    assert_graph_is(graph, set().union(*models))
    # Nothing read that was never added, and the readers did read while
    # the graph changed: more than the end state holds.
    assert seen <= ever
    assert len(seen - set(graph)) > 0


def dataset_writer(dataset, writer, model, ever):
    own_graph = NamedNode(f"http://e/graph{writer}")

    def write(stop):
        rng = random.Random(writer)
        present = set()
        while not stop.is_set():
            name = rng.choice([None, SHARED_GRAPH, own_graph])
            batch = [
                Quad(*t, name) for t in own_triples(writer, rng, rng.randrange(1, 40))
            ]
            choice = rng.random()
            if choice < 0.35:
                ever.update(batch)
                for quad in batch:
                    dataset.add(quad)
                present.update(batch)
            elif choice < 0.45:
                ever.update(batch)
                dataset.addAll(batch)
                present.update(batch)
            elif choice < 0.55:
                ever.update(batch)
                if name is not None:
                    # Only this thread removes the graph, so it stays.
                    dataset.add_graph(Graph(), named=name)
                (view,) = [g for g in dataset.graphs if g.uri == name]
                view.addAll(Triple(*q[:3]) for q in batch)
                present.update(batch)
            elif choice < 0.8:
                for quad in batch:
                    if quad in present:
                        dataset.remove(quad)
                        present.discard(quad)
            elif choice < 0.95:
                # A graph of None matches every graph.
                s = batch[0].subject
                dataset.removeMatches(s, None, None, name)
                present = {
                    q for q in present if q.subject != s or name not in (None, q.graph)
                }
            elif any(q.graph == own_graph for q in present):
                dataset.remove_graph(own_graph)
                present = {q for q in present if q.graph != own_graph}
        model.update(present)

    return write


def dataset_reader(dataset, seen, seed):
    def views():
        # The default and shared graphs are never removed, so their views
        # stay readable.
        for view in dataset.graphs:
            if view.uri in (None, SHARED_GRAPH):
                pattern = rng.choice([(None, None), (PREDICATES[0], None)])
                seen.update(Quad(*t, view.uri) for t in view.match(None, *pattern))

    def read(stop):
        nonlocal rng
        rng = random.Random(seed)
        while not stop.is_set():
            graph = rng.choice([None, SHARED_GRAPH])
            for one_read in [
                lambda: seen.update(dataset.match(None, PREDICATES[0], None, graph)),
                lambda: seen.update(dataset),
                lambda: seen.update(
                    Quad(*q) for q in dataset.mapped_quads(lambda term: term)
                ),
                views,
            ]:
                ended_by_a_change(one_read)

    rng = None
    return read


def test_threads_changing_and_reading_one_dataset():
    dataset = Dataset()
    models = [set() for _ in range(WRITERS)]
    ever = set()
    seen = set()
    errors = run_threads(
        [dataset_writer(dataset, w, models[w], ever) for w in range(WRITERS)]
        + [dataset_reader(dataset, seen, r) for r in range(READERS)]
    )
    assert errors == []
    quads = set().union(*models)
    assert set(dataset) == quads
    assert len(dataset) == len(quads)
    for name in {None, SHARED_GRAPH} | {q.graph for q in quads}:
        (view,) = [g for g in dataset.graphs if g.uri == name]
        assert_graph_is(view, {Triple(*q[:3]) for q in quads if q.graph == name})
    assert seen <= ever
    assert len(seen - set(dataset)) > 0


PAIRED_GRAPHS = [NamedNode("http://e/pairs0"), NamedNode("http://e/pairs1")]
STILL_GRAPH = NamedNode("http://e/still")
STILL = {
    Quad(NamedNode(f"http://e/still/s{i}"), PREDICATES[0], OBJECTS[i % 6], STILL_GRAPH)
    for i in range(10)
}


def pair(writer, i):
    """A quad in each paired graph, which a writer only ever adds and
    removes together, so a read of one state has both or neither."""
    s = subject(writer, i)
    return [Quad(s, PREDICATES[0], OBJECTS[0], name) for name in PAIRED_GRAPHS]


def pair_writer(dataset, writer, ever):
    """Adds and removes whole pairs, each in one call that changes both
    paired graphs."""

    def write(stop):
        rng = random.Random(writer)
        while not stop.is_set():
            i = rng.randrange(SUBJECTS)
            if rng.random() < 0.5:
                quads = pair(writer, i)
                ever.update(quads)
                dataset.addAll(quads)
            else:
                # A graph of None matches every graph.
                dataset.removeMatches(subject(writer, i), None, None, None)

    return write


def whole_pairs_reader(dataset, finished):
    """Reads the whole dataset: a read that finishes saw one state, so it
    holds each pair whole and every quad of the graph nobody changes. Reads
    of the unchanged graph alone must never be ended by changes to the
    others."""

    def read(stop):
        (still,) = [g for g in dataset.graphs if g.uri == STILL_GRAPH]
        while not stop.is_set():
            assert set(dataset.match(graph=STILL_GRAPH)) == STILL
            assert {Quad(*t, STILL_GRAPH) for t in still} == STILL
            quads = []
            try:
                quads.extend(dataset)
            except RuntimeError as e:
                # The walked graph's own index may notice first.
                assert "changed during iteration" in str(e), e
                continue
            finished.append(len(quads))
            got = set(quads)
            assert STILL <= got
            for q in got - STILL:
                writer, i = (int(x[1:]) for x in q.subject.split("/")[-2:])
                assert set(pair(writer, i)) <= got, q

    return read


def test_dataset_reads_while_two_graphs_change_together():
    dataset = Dataset()
    dataset.addAll(STILL)
    for name in PAIRED_GRAPHS:
        dataset.add_graph(Graph(), named=name)
    ever = set()
    finished = []
    errors = run_threads(
        [pair_writer(dataset, w, ever) for w in range(WRITERS)]
        + [whole_pairs_reader(dataset, finished) for _ in range(READERS)]
    )
    assert errors == []
    assert set(dataset) - STILL <= ever
    # Some reads finished while the graphs changed.
    assert finished
