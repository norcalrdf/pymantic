import gc
import pytest
import random
import sys

from pymantic import adjacency_index
from pymantic.adjacency_index import AdjacencyTripleIndex
from pymantic.triple_index import RESORT_DIVISOR, SMALL_MERGE, TripleIndex

# Every implementation of the triple index interface; the shared tests run
# once per entry.
INDEXES = [
    TripleIndex,
    AdjacencyTripleIndex,
]


@pytest.fixture(params=INDEXES, ids=lambda cls: cls.__name__)
def index_class(request):
    return request.param


IDS = range(16)

# Every combination of bound (True) and wildcard (False) positions.
PATTERNS = [
    (bs, bp, bo) for bs in (False, True) for bp in (False, True) for bo in (False, True)
]


def check_against_reference(index, ref, rng):
    """Compare every read operation of `index` with the ordered set `ref`."""
    assert len(index) == len(ref)
    assert list(index) == list(ref)
    for spo in rng.sample(list(ref), min(3, len(ref))):
        assert spo in index
    for _ in range(3):
        spo = (rng.choice(IDS), rng.choice(IDS), rng.choice(IDS))
        assert (spo in index) == (spo in ref)

    # Sample bound values from a present triple half the time, so bound
    # patterns usually have matches.
    if ref and rng.random() < 0.5:
        s, p, o = rng.choice(list(ref))
    else:
        s, p, o = rng.choice(IDS), rng.choice(IDS), rng.choice(IDS)
    for bs, bp, bo in PATTERNS:
        qs = s if bs else None
        qp = p if bp else None
        qo = o if bo else None
        expected = {
            t
            for t in ref
            if (qs is None or t[0] == qs)
            and (qp is None or t[1] == qp)
            and (qo is None or t[2] == qo)
        }
        got = list(index.match(qs, qp, qo))
        assert len(got) == len(set(got))
        assert set(got) == expected, (qs, qp, qo)

    assert list(index.subjects()) == sorted({t[0] for t in ref})
    assert list(index.predicates()) == sorted({t[1] for t in ref})
    assert list(index.objects()) == sorted({t[2] for t in ref})
    assert index.ids() == {i for t in ref for i in t}


def random_triple(rng):
    return (rng.choice(IDS), rng.choice(IDS), rng.choice(IDS))


def run_model(index_class, seed, operations=2000, max_size=250, check_every=1):
    rng = random.Random(seed)
    index = index_class()
    # A dict used as an ordered set: re-adding after a remove moves to the end.
    ref = {}
    for step in range(operations):
        roll = rng.random()
        # Bias toward removal once the graph is large, to keep it small
        # enough that collisions and empty results stay common.
        shrink = len(ref) > max_size
        if ref and (roll < 0.2 or (shrink and roll < 0.6)):
            spo = rng.choice(list(ref))
            index.remove(*spo)
            del ref[spo]
        elif (ref and roll < 0.25) or (shrink and roll < 0.7):
            subset = rng.sample(list(ref), rng.randint(0, len(ref)))
            index.remove_many(subset)
            for spo in subset:
                del ref[spo]
        elif roll < 0.35:
            # More than SMALL_MERGE adds before the next query.
            for _ in range(rng.randint(SMALL_MERGE + 1, 3 * SMALL_MERGE)):
                spo = random_triple(rng)
                assert index.add(*spo) == (spo not in ref)
                ref[spo] = None
        else:
            spo = random_triple(rng)
            assert index.add(*spo) == (spo not in ref)
            ref[spo] = None
        if step % check_every == 0:
            check_against_reference(index, ref, rng)
    check_against_reference(index, ref, rng)


@pytest.mark.parametrize("seed", range(20))
def test_model(index_class, seed):
    run_model(index_class, seed)


@pytest.mark.parametrize("seed", range(20, 30))
def test_model_with_pending_adds(index_class, seed):
    # Querying only every 7th operation leaves adds pending when removes run,
    # both single adds (merged by bisect) and batches (merged by re-sort).
    run_model(index_class, seed, check_every=7)


def test_readd_moves_to_end(index_class):
    index = index_class()
    index.add(1, 2, 3)
    index.add(4, 5, 6)
    assert not index.add(1, 2, 3)
    assert list(index) == [(1, 2, 3), (4, 5, 6)]
    index.remove(1, 2, 3)
    assert index.add(1, 2, 3)
    assert list(index) == [(4, 5, 6), (1, 2, 3)]


def test_remove_absent_raises_key_error(index_class):
    index = index_class()
    index.add(1, 2, 3)
    with pytest.raises(KeyError):
        index.remove(1, 2, 4)
    assert list(index) == [(1, 2, 3)]


def test_remove_many_with_absent_triple_changes_nothing(index_class):
    index = index_class()
    for i in range(5):
        index.add(i, i, i)
    with pytest.raises(KeyError):
        index.remove_many([(0, 0, 0), (9, 9, 9), (1, 1, 1)])
    assert list(index) == [(i, i, i) for i in range(5)]
    assert sorted(index.match(None, None, 0)) == [(0, 0, 0)]
    assert list(index.subjects()) == [0, 1, 2, 3, 4]


def test_remove_many_tolerates_repeated_triples(index_class):
    index = index_class()
    index.add(1, 2, 3)
    index.add(4, 5, 6)
    index.remove_many([(1, 2, 3), (1, 2, 3)])
    assert list(index) == [(4, 5, 6)]
    assert list(index.match(1, None, None)) == []


def test_zero_ids_are_bound_values(index_class):
    index = index_class()
    index.add(0, 0, 0)
    index.add(1, 1, 1)
    assert list(index.match(0, None, None)) == [(0, 0, 0)]
    assert list(index.match(None, 0, None)) == [(0, 0, 0)]
    assert list(index.match(None, None, 0)) == [(0, 0, 0)]
    assert list(index.match(0, 0, 0)) == [(0, 0, 0)]


def test_largest_id(index_class):
    top = 2**32 - 1
    index = index_class()
    index.add(top, top, top)
    index.add(top, 0, top)
    assert (top, top, top) in index
    assert sorted(index.match(top, None, top)) == [(top, 0, top), (top, top, top)]
    assert list(index) == [(top, top, top), (top, 0, top)]


def mutating_calls():
    return [
        ("add", lambda index: index.add(9, 9, 9)),
        ("remove", lambda index: index.remove(1, 1, 1)),
        ("remove_many", lambda index: index.remove_many([(1, 1, 1)])),
    ]


def readers():
    return [
        ("iter", iter),
        ("match none", lambda index: index.match(None, None, None)),
        ("match s", lambda index: index.match(0, None, None)),
        ("match p", lambda index: index.match(None, 0, None)),
        ("match o", lambda index: index.match(None, None, 0)),
        ("match s p", lambda index: index.match(0, 0, None)),
        ("match p o", lambda index: index.match(None, 0, 0)),
        ("match s o", lambda index: index.match(0, None, 0)),
        ("subjects", lambda index: index.subjects()),
        ("predicates", lambda index: index.predicates()),
        ("objects", lambda index: index.objects()),
    ]


@pytest.mark.parametrize("mutate", [m for _, m in mutating_calls()])
@pytest.mark.parametrize("read", [r for _, r in readers()])
def test_mutation_during_iteration_raises(index_class, read, mutate):
    index = index_class()
    # Every reader has at least two results, so the second next() would
    # yield if the mutation went unnoticed.
    triples = [(0, 0, 0), (0, 0, 1), (0, 1, 0), (1, 0, 0), (1, 1, 1), (2, 0, 0)]
    for spo in triples:
        index.add(*spo)
    it = read(index)
    next(it)
    mutate(index)
    with pytest.raises(RuntimeError):
        next(it)


def one_result_readers():
    return [
        ("iter", iter),
        ("match s", lambda index: index.match(1, None, None)),
        ("match o", lambda index: index.match(None, None, 3)),
        ("match s p o", lambda index: index.match(1, 2, 3)),
        ("subjects", lambda index: index.subjects()),
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda index: index.remove(1, 2, 3),
        lambda index: index.add(7, 7, 7),
        lambda index: index.detach(),
    ],
    ids=["remove", "add", "detach"],
)
@pytest.mark.parametrize(
    "read",
    [r for _, r in one_result_readers()],
    ids=[name for name, _ in one_result_readers()],
)
def test_mutation_after_last_result_raises(index_class, read, mutate):
    index = index_class()
    index.add(1, 2, 3)
    it = read(index)
    assert next(it) in [(1, 2, 3), 1]
    mutate(index)
    with pytest.raises(RuntimeError):
        next(it)


def test_query_merges_single_adds_without_resorting():
    rng = random.Random(6)
    index = TripleIndex()
    for i in range(20000):
        s, p, o = rng.randrange(5000), rng.randrange(50), rng.randrange(5000)
        index.add(s, p, o)
        assert (s, p, o) in set(index.match(s, None, None))
    assert index.resorts == 0
    assert len(index) == len(set(index))


def test_large_batch_of_adds_resorts():
    index = TripleIndex()
    for i in range(SMALL_MERGE + 1):
        index.add(i, i, i)
    assert index.resorts == 0
    assert list(index.match(None, 3, None)) == [(3, 3, 3)]
    assert index.resorts == 1


def test_resort_threshold_grows_with_index():
    index = TripleIndex()
    loaded = 64 * RESORT_DIVISOR
    for i in range(loaded):
        index.add(i, 0, i)
    list(index.match(0, None, None))
    assert index.resorts == 1

    # More than SMALL_MERGE rows, but at most 1/RESORT_DIVISOR of the index:
    # merged by bisect.
    batch = (loaded + 64) // RESORT_DIVISOR
    assert SMALL_MERGE < batch
    for i in range(batch):
        index.add(i, 1, i)
    assert sorted(index.match(None, 1, None)) == [(i, 1, i) for i in range(batch)]
    assert index.resorts == 1

    # A batch above the relative bound re-sorts.
    batch = len(index) // RESORT_DIVISOR + 10
    for i in range(batch):
        index.add(i, 2, i)
    assert sorted(index.match(None, 2, None)) == [(i, 2, i) for i in range(batch)]
    assert index.resorts == 2
    assert list(index.subjects()) == list(range(loaded))


def test_out_of_range_id_leaves_index_unchanged(index_class):
    index = index_class()
    index.add(1, 2, 3)
    for bad in [(2**32, 0, 0), (0, 2**32, 0), (0, 0, 2**32), (0, 0, -1)]:
        with pytest.raises(OverflowError):
            index.add(*bad)
    assert list(index) == [(1, 2, 3)]
    if index_class is TripleIndex:
        assert all(len(c) == 1 for c in index._columns()[9:])
    else:
        assert index._pending == [1 << 64 | 2 << 32 | 3]
    index.add(4, 5, 6)
    assert sorted(index.match(None, None, None)) == [(1, 2, 3), (4, 5, 6)]
    assert sorted(index.match(4, None, None)) == [(4, 5, 6)]


def test_subjects_drops_subject_after_last_triple_removed(index_class):
    index = index_class()
    index.add(1, 2, 3)
    index.add(1, 2, 4)
    index.add(5, 2, 3)
    index.remove(1, 2, 3)
    assert list(index.subjects()) == [1, 5]
    index.remove(1, 2, 4)
    assert list(index.subjects()) == [5]
    assert list(index.objects()) == [3]
    assert index.ids() == {2, 3, 5}


def test_detach_makes_every_call_raise(index_class):
    index = index_class()
    index.add(1, 2, 3)
    index.add(1, 2, 4)
    # Two results each, so a second next() would yield if detach went
    # unnoticed.
    started = [iter(index), index.match(1, None, None), index.objects()]
    for it in started:
        next(it)
    unstarted = [
        index.match(1, 2, 3),
        index.match(1, None, None),
        index.match(None, None, None),
        index.subjects(),
    ]
    index.detach()
    calls = [
        lambda: index.add(4, 5, 6),
        lambda: index.remove(1, 2, 3),
        lambda: index.remove_many([(1, 2, 3)]),
        lambda: index.match(1, None, None),
        lambda: index.match(None, None, None),
        lambda: iter(index),
        lambda: len(index),
        lambda: (1, 2, 3) in index,
        lambda: index.subjects(),
        lambda: index.predicates(),
        lambda: index.objects(),
        lambda: index.ids(),
    ] + [lambda it=it: next(it) for it in started + unstarted]
    for call in calls:
        with pytest.raises(RuntimeError):
            call()


def test_columns_are_unsigned_int_arrays():
    index = TripleIndex()
    for i in range(SMALL_MERGE + 5):
        index.add(i, i + 1, i + 2)
    list(index.match(1, None, None))
    index.add(100, 100, 100)
    columns = index._columns()
    assert len(columns) == 12
    assert len({id(c) for c in columns}) == 12
    assert all(c.typecode == "I" for c in columns)


def test_remove_detects_orderings_out_of_step_with_keys():
    index = TripleIndex()
    index.add(1, 2, 3)
    index.add(4, 5, 6)
    list(index.match(1, None, None))
    # Corrupt one ordering so it no longer holds a triple the keys hold.
    for column in index._columns()[3:6]:
        column.pop()
    with pytest.raises(RuntimeError, match="disagree"):
        index.remove(4, 5, 6)


# AdjacencyTripleIndex


def adjacency_rows(index):
    """Every row value of the three orderings."""
    return [row for rows in index._orders for row in rows.values()]


@pytest.fixture
def small_adjacency(monkeypatch):
    """Constants small enough that the model tests fold pending adds, turn
    rows into lists and filter rows in remove_many."""
    monkeypatch.setattr(adjacency_index, "FOLD_MIN", 8)
    monkeypatch.setattr(adjacency_index, "LIST_DEGREE", 4)
    monkeypatch.setattr(adjacency_index, "_FILTER_MIN", 2)


@pytest.mark.parametrize("seed", range(30, 40))
def test_adjacency_model_with_small_constants(small_adjacency, seed):
    run_model(AdjacencyTripleIndex, seed)
    run_model(AdjacencyTripleIndex, seed, check_every=7)


@pytest.mark.parametrize("mutate", [m for _, m in mutating_calls()])
@pytest.mark.parametrize("read", [r for _, r in readers()])
def test_adjacency_mutation_of_list_rows_raises(monkeypatch, read, mutate):
    # Every row with more than one value is a list, mutated in place.
    monkeypatch.setattr(adjacency_index, "LIST_DEGREE", 1)
    test_mutation_during_iteration_raises(AdjacencyTripleIndex, read, mutate)


def test_adjacency_small_pending_is_inserted_without_folding():
    index = AdjacencyTripleIndex()
    for i in range(adjacency_index.FOLD_MIN):
        index.add(i % 7, 0, i)
    assert sorted(index.match(3, None, None)) == [
        (3, 0, i) for i in range(adjacency_index.FOLD_MIN) if i % 7 == 3
    ]
    assert index.folds == 0
    assert index._pending == []


def test_adjacency_large_pending_folds_once():
    index = AdjacencyTripleIndex()
    count = adjacency_index.FOLD_MIN + 1
    for i in range(count):
        index.add(i % 7, i % 3, i)
    assert list(index.match(None, 2, None)) == sorted(
        [(i % 7, 2, i) for i in range(count) if i % 3 == 2],
        key=lambda t: (t[2], t[0]),
    )
    assert index.folds == 1
    assert list(index.match(None, 1, None))
    assert index.folds == 1


def test_adjacency_fold_threshold_grows_with_index():
    index = AdjacencyTripleIndex()
    loaded = 2 * adjacency_index.FOLD_MIN * adjacency_index.FOLD_DIVISOR
    for i in range(loaded):
        index.add(i, 0, i)
    list(index.match(0, None, None))
    assert index.folds == 1

    # More than FOLD_MIN pending adds, but at most 1/FOLD_DIVISOR of the
    # index: inserted one by one.
    batch = (loaded + adjacency_index.FOLD_MIN) // adjacency_index.FOLD_DIVISOR
    assert adjacency_index.FOLD_MIN < batch
    for i in range(batch):
        index.add(i, 1, i)
    assert list(index.match(None, 1, None)) == [(i, 1, i) for i in range(batch)]
    assert index.folds == 1

    # A batch above the relative bound folds, merging into existing rows.
    # The bound counts the batch too.
    batch = 2 * len(index) // adjacency_index.FOLD_DIVISOR
    for i in range(batch):
        index.add(i, 2, i)
    assert list(index.match(None, 2, None)) == [(i, 2, i) for i in range(batch)]
    assert list(index.match(5, None, None)) == [(5, 0, 5), (5, 1, 5), (5, 2, 5)]
    assert index.folds == 2
    assert list(index.subjects()) == list(range(loaded))


def test_adjacency_results_within_a_key_are_sorted():
    index = AdjacencyTripleIndex()
    triples = [(1, p, o) for p in (5, 3, 9) for o in (8, 2, 6)]
    for spo in triples:
        index.add(*spo)
    assert list(index.match(1, None, None)) == sorted(triples)
    assert list(index.match(1, 3, None)) == [(1, 3, 2), (1, 3, 6), (1, 3, 8)]
    assert list(index.match(1, None, 6)) == [(1, 3, 6), (1, 5, 6), (1, 9, 6)]


@pytest.mark.parametrize("bulk", [False, True], ids=["inserted", "folded"])
def test_adjacency_row_crossing_list_degree_becomes_a_list(monkeypatch, bulk):
    degree = adjacency_index.LIST_DEGREE
    # Low enough that the adds below fold when queried together.
    monkeypatch.setattr(adjacency_index, "FOLD_MIN", degree)
    index = AdjacencyTripleIndex()
    # Odd objects first and even ones after, so later inserts land between
    # existing values rather than only at the end.
    order = list(range(1, 2 * degree, 2)) + list(range(0, 2 * degree + 2, 2))
    for count, o in enumerate(order, 1):
        index.add(7, 1, o)
        if not bulk:
            list(index.match(7, None, None))
            row = index._orders[0][7]
            assert type(row) is (tuple if count <= degree else list)
    list(index.match(7, None, None))
    assert index.folds == (1 if bulk else 0)
    assert type(index._orders[0][7]) is list
    assert type(index._orders[1][1]) is list
    assert list(index.match(7, None, None)) == [(7, 1, o) for o in sorted(order)]
    assert list(index.match(None, 1, None)) == [(7, 1, o) for o in sorted(order)]
    assert list(index.match(7, 1, None)) == [(7, 1, o) for o in sorted(order)]
    assert list(index.match(7, None, 4)) == [(7, 1, 4)]

    # Removes keep it a list and stay correct, down to the last value.
    for o in order[:-1]:
        index.remove(7, 1, o)
    assert type(index._orders[0][7]) is list
    assert list(index.match(7, None, None)) == [(7, 1, order[-1])]
    index.remove(7, 1, order[-1])
    assert index._orders == ({}, {}, {})
    assert list(index.subjects()) == []


def test_adjacency_remove_many_of_a_list_row():
    degree = adjacency_index.LIST_DEGREE
    index = AdjacencyTripleIndex()
    for o in range(3 * degree):
        index.add(1, 2, o)
    index.add(5, 2, 0)
    list(index.match(1, None, None))
    index.remove_many([(1, 2, o) for o in range(0, 3 * degree, 3)])
    kept = [(1, 2, o) for o in range(3 * degree) if o % 3]
    assert list(index.match(1, None, None)) == kept
    assert list(index.match(None, 2, 0)) == [(5, 2, 0)]
    assert sorted(index.match(None, 2, None)) == sorted(kept + [(5, 2, 0)])
    index.remove_many(kept)
    assert list(index.subjects()) == [5]
    assert list(index.match(None, 2, None)) == [(5, 2, 0)]


def test_adjacency_remove_many_with_pending_adds():
    index = AdjacencyTripleIndex()
    index.add(1, 2, 3)
    list(index.match(1, None, None))
    index.add(1, 2, 4)
    index.add(1, 2, 5)
    index.remove_many([(1, 2, 3), (1, 2, 4)])
    assert list(index.match(1, None, None)) == [(1, 2, 5)]
    assert list(index.match(None, None, 4)) == []
    assert index.ids() == {1, 2, 5}
    index.add(7, 8, 9)
    assert index.ids() == {1, 2, 5, 7, 8, 9}


def test_adjacency_one_add_then_match_never_folds():
    rng = random.Random(11)
    index = AdjacencyTripleIndex()
    for i in range(100_000):
        index.add(rng.randrange(20_000), rng.randrange(50), rng.randrange(20_000))
    list(index.match(0, None, None))
    assert index.folds == 1
    for i in range(20_000):
        s, p, o = rng.randrange(20_000), rng.randrange(50), rng.randrange(20_000)
        index.add(s, p, o)
        assert (s, p, o) in set(index.match(s, None, None))
    assert index.folds == 1


def corrupt_drop_row(index):
    del index._orders[1][5]


def corrupt_drop_value(index):
    index._orders[1][5] = index._orders[1][5][1:]


@pytest.mark.parametrize("corrupt", [corrupt_drop_row, corrupt_drop_value])
@pytest.mark.parametrize(
    "remove",
    [
        lambda index: index.remove(4, 5, 6),
        # Many values from one row, so the row is filtered in one pass.
        lambda index: index.remove_many([(4, 5, 6)] + [(s, 5, 7) for s in range(100)]),
    ],
    ids=["remove", "remove_many"],
)
def test_adjacency_remove_detects_orderings_out_of_step_with_keys(corrupt, remove):
    index = AdjacencyTripleIndex()
    index.add(1, 2, 3)
    index.add(4, 5, 6)
    for s in range(100):
        index.add(s, 5, 7)
    list(index.match(1, None, None))
    # Corrupt one ordering so it no longer holds a triple the keys hold.
    corrupt(index)
    with pytest.raises(RuntimeError, match="disagree"):
        remove(index)


@pytest.mark.skipif(
    sys.implementation.name != "cpython",
    reason="checks tracking by CPython's cyclic garbage collector",
)
def test_adjacency_tuple_rows_are_untracked_after_a_collection():
    rng = random.Random(3)
    index = AdjacencyTripleIndex()
    for i in range(50_000):
        index.add(rng.randrange(5000), rng.randrange(20), rng.randrange(5000))
    list(index.match(0, None, None))
    # Single inserts as well as the fold.
    for i in range(500):
        index.add(rng.randrange(5000), rng.randrange(20), rng.randrange(5000))
        list(index.match(0, None, None))
    gc.collect()
    rows = adjacency_rows(index)
    tuples = [row for row in rows if type(row) is tuple]
    lists = [row for row in rows if type(row) is list]
    assert tuples and lists
    assert not any(gc.is_tracked(row) for row in tuples)
    # Only the rows past LIST_DEGREE are lists: here the 20 predicates.
    assert len(lists) == 20
