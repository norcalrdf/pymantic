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
READERS = 2
SECONDS = 1.0

PREDICATES = [NamedNode(f"http://e/p{i}") for i in range(3)]
OBJECTS = [Literal(f"o{i}") for i in range(5)] + [NamedNode("http://e/shared")]
SHARED_GRAPH = NamedNode("http://e/shared-graph")


@pytest.fixture(autouse=True)
def fine_switching():
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(interval)


def own_triples(writer, rng, count):
    """Triples only `writer` adds, with fresh subjects, so removing them
    leaves dead terms for compaction to free and other threads to reuse."""
    return [
        Triple(
            NamedNode(f"http://e/w{writer}/s{rng.randrange(40)}"),
            rng.choice(PREDICATES),
            rng.choice(OBJECTS),
        )
        for _ in range(count)
    ]


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


def graph_writer(graph, writer, model):
    def write(stop):
        rng = random.Random(writer)
        present = set()
        while not stop.is_set():
            batch = own_triples(writer, rng, rng.randrange(1, 40))
            choice = rng.random()
            if choice < 0.4:
                for triple in batch:
                    graph.add(triple)
                present.update(batch)
            elif choice < 0.55:
                graph.addAll(batch)
                present.update(batch)
            elif choice < 0.85:
                for triple in batch:
                    if triple in present:
                        graph.remove(triple)
                        present.discard(triple)
            else:
                subject = batch[0].subject
                graph.removeMatches(subject, None, None)
                present = {t for t in present if t.subject != subject}
        model.update(present)

    return write


def graph_reader(graph, seen):
    def read(stop):
        rng = random.Random(len(seen))
        while not stop.is_set():
            pattern = [
                rng.choice([None, PREDICATES[0]]),
                None,
                rng.choice([None, OBJECTS[0]]),
            ]
            try:
                seen.update(graph.match(*pattern))
                seen.update(graph.objects(None, PREDICATES[1]))
            except RuntimeError as e:
                # Until reads see a snapshot, a change ends them.
                assert "changed" in str(e)

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
    seen = set()
    errors = run_threads(
        [graph_writer(graph, w, models[w]) for w in range(WRITERS)]
        + [graph_reader(graph, seen) for _ in range(READERS)]
    )
    assert errors == []
    assert_graph_is(graph, set().union(*models))


def dataset_writer(dataset, writer, model):
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
                for quad in batch:
                    dataset.add(quad)
                present.update(batch)
            elif choice < 0.45:
                dataset.addAll(batch)
                present.update(batch)
            elif choice < 0.55:
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
                subject = batch[0].subject
                dataset.removeMatches(subject, None, None, name)
                present = {
                    q
                    for q in present
                    if q.subject != subject or name not in (None, q.graph)
                }
            elif any(q.graph == own_graph for q in present):
                dataset.remove_graph(own_graph)
                present = {q for q in present if q.graph != own_graph}
        model.update(present)

    return write


def dataset_reader(dataset, seen):
    def read(stop):
        rng = random.Random(len(seen))
        while not stop.is_set():
            try:
                if rng.random() < 0.5:
                    seen.update(dataset.match(predicate=PREDICATES[0]))
                else:
                    seen.update(dataset)
            except RuntimeError as e:
                # Until reads see a snapshot, a change ends them.
                assert "changed" in str(e) or "detached" in str(e)

    return read


def test_threads_changing_and_reading_one_dataset():
    dataset = Dataset()
    models = [set() for _ in range(WRITERS)]
    seen = set()
    errors = run_threads(
        [dataset_writer(dataset, w, models[w]) for w in range(WRITERS)]
        + [dataset_reader(dataset, seen) for _ in range(READERS)]
    )
    assert errors == []
    quads = set().union(*models)
    assert set(dataset) == quads
    assert len(dataset) == len(quads)
    for name in {None, SHARED_GRAPH} | {q.graph for q in quads}:
        (view,) = [g for g in dataset.graphs if g.uri == name]
        assert_graph_is(view, {Triple(*q[:3]) for q in quads if q.graph == name})
