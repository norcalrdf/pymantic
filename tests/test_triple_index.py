import pytest
import random

from pymantic import offset_index
from pymantic.offset_index import DELTA_MIN, FOLD_DIVISOR, OffsetTripleIndex
from pymantic.triple_index import RESORT_DIVISOR, SMALL_MERGE, TripleIndex

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


@pytest.fixture(params=["sorted", "offsets", "offsets-small-folds"])
def index_class(request, monkeypatch):
    """Each index implementation. The small-folds variant lowers DELTA_MIN
    so the small graphs in these tests fold, leaving rows in main, dead
    rows and delta rows all in play."""
    if request.param == "sorted":
        return TripleIndex
    if request.param == "offsets-small-folds":
        monkeypatch.setattr(offset_index, "DELTA_MIN", 4)
    return OffsetTripleIndex


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


def pending_columns(index):
    """The columns an add appends to before any query."""
    if isinstance(index, TripleIndex):
        return index._columns()[9:]
    return index._delta_columns()


def test_out_of_range_id_leaves_index_unchanged(index_class):
    index = index_class()
    index.add(1, 2, 3)
    for bad in [(2**32, 0, 0), (0, 2**32, 0), (0, 0, 2**32), (0, 0, -1)]:
        with pytest.raises(OverflowError):
            index.add(*bad)
    assert list(index) == [(1, 2, 3)]
    assert all(len(c) == 1 for c in pending_columns(index))
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


# OffsetTripleIndex: the delta, dead rows and folds.


def folded_offset_index(count):
    """An OffsetTripleIndex of (i, 0, i) for i in range(count), folded."""
    index = OffsetTripleIndex()
    for i in range(count):
        index.add(i, 0, i)
    list(index.match(0, None, None))
    return index


def test_offsets_small_fresh_index_is_queried_without_a_fold():
    index = OffsetTripleIndex()
    for i in range(DELTA_MIN):
        index.add(i, 0, i)
    assert list(index.match(5, None, None)) == [(5, 0, 5)]
    assert list(index.subjects()) == list(range(DELTA_MIN))
    assert index.folds == 0


def test_offsets_delta_below_threshold_is_queried_without_a_fold():
    index = folded_offset_index(DELTA_MIN + 1)
    assert index.folds == 1
    for i in range(DELTA_MIN):
        index.add(i, 1, i)
    assert sorted(index.match(None, 1, None)) == [(i, 1, i) for i in range(DELTA_MIN)]
    assert list(index.match(3, None, None)) == [(3, 0, 3), (3, 1, 3)]
    assert index.folds == 1

    # One more row crosses the threshold: the next query folds, once.
    index.add(0, 2, 0)
    assert list(index.match(None, 2, None)) == [(0, 2, 0)]
    assert list(index.match(None, 1, None))[:2] == [(0, 1, 0), (1, 1, 1)]
    assert index.folds == 2
    assert all(len(c) == 0 for c in index._delta_columns())


def test_offsets_removed_main_row_is_skipped_and_revived_by_readd():
    index = folded_offset_index(DELTA_MIN + 1)
    index.add(3, 1, 4)
    index.remove(3, 0, 3)
    assert (3, 0, 3) not in index
    assert list(index.match(3, None, None)) == [(3, 1, 4)]
    assert list(index.match(None, None, 3)) == []
    assert (3, 0, 3) not in set(index.match(None, 0, None))
    assert list(index.objects())[:5] == [0, 1, 2, 4, 5]

    # Removing the delta row as well leaves subject 3 with no live rows.
    index.remove(3, 1, 4)
    assert 3 not in list(index.subjects())
    assert all(len(c) == 0 for c in index._delta_columns())

    assert index.add(3, 0, 3)
    assert all(len(c) == 0 for c in index._delta_columns())
    assert list(index.match(3, None, None)) == [(3, 0, 3)]
    assert list(index)[-1] == (3, 0, 3)
    assert 3 in list(index.subjects())
    assert index.folds == 1


def test_offsets_dead_rows_past_threshold_fold():
    index = folded_offset_index(2 * DELTA_MIN)
    for i in range(DELTA_MIN):
        index.remove(i, 0, i)
    assert list(index.match(None, 0, None))[0] == (DELTA_MIN, 0, DELTA_MIN)
    assert index.folds == 1

    index.remove(DELTA_MIN, 0, DELTA_MIN)
    assert list(index.subjects())[0] == DELTA_MIN + 1
    assert index.folds == 2
    assert list(index.match(DELTA_MIN + 1, None, None)) == [
        (DELTA_MIN + 1, 0, DELTA_MIN + 1)
    ]
    assert len(index) == DELTA_MIN - 1


def test_offsets_ids_beyond_the_offsets_are_found_in_the_delta():
    count = DELTA_MIN + 1
    index = folded_offset_index(count)
    late = [(count + 5, 0, count + 6), (0, count + 7, 1), (2, 0, count + 8)]
    for spo in late:
        index.add(*spo)
    assert list(index.match(count + 5, None, None)) == [late[0]]
    assert list(index.match(None, None, count + 6)) == [late[0]]
    assert list(index.match(None, count + 7, None)) == [late[1]]
    assert list(index.match(0, count + 7, None)) == [late[1]]
    assert list(index.match(2, None, count + 8)) == [late[2]]
    assert list(index.subjects()) == list(range(count)) + [count + 5]
    assert list(index.predicates()) == [0, count + 7]
    assert index.folds == 1


def test_offsets_sparse_high_ids_need_no_offset_per_id():
    # A small graph in a large dataset has ids spread up to the dataset's
    # term count; its offsets arrays must stay proportional to its rows.
    top = 2**32 - 1
    count = DELTA_MIN + 1
    index = OffsetTripleIndex()
    triples = [(top - i, i % 3, top - 2 * i) for i in range(count)]
    triples.append((1, 1, 1))
    for spo in triples:
        index.add(*spo)
    assert list(index.match(top - 7, None, None)) == [triples[7]]
    assert index.folds == 1
    assert sum(len(c) for c in index._columns()) < 30 * len(triples)
    assert list(index.match(1, None, None)) == [(1, 1, 1)]
    assert list(index.match(top - 9, 0, None)) == [triples[9]]
    assert list(index.match(None, None, top - 8)) == [triples[4]]
    assert list(index.subjects()) == sorted({s for s, _, _ in triples})
    assert list(index.predicates()) == [0, 1, 2]
    index.remove(*triples[7])
    assert list(index.match(top - 7, None, None)) == []
    assert list(index.match(top - 6, None, None)) == [triples[6]]


def test_offsets_one_add_then_match_folds_rarely():
    rng = random.Random(10)
    index = OffsetTripleIndex()
    n = 100_000
    while len(index) < n:
        index.add(rng.randrange(20000), rng.randrange(50), rng.randrange(20000))
    list(index.match(0, None, None))
    folds = index.folds
    rounds = 20_000
    for _ in range(rounds):
        s, p, o = rng.randrange(25000), rng.randrange(50), rng.randrange(25000)
        index.add(s, p, o)
        assert (s, p, o) in set(index.match(s, None, None))
    assert index.folds - folds <= rounds // max(DELTA_MIN, n // FOLD_DIVISOR) + 1
    assert len(index) == len(set(index))


def test_offsets_columns_are_unsigned_int_arrays():
    index = folded_offset_index(DELTA_MIN + 5)
    index.add(100, 100, 100)
    columns = index._columns()
    # Three orderings of three columns and offsets in main, and three
    # columns each in the delta.
    assert len(columns) == 21
    assert len({id(c) for c in columns}) == 21
    assert all(c.typecode == "I" for c in columns)


def test_offsets_remove_detects_delta_out_of_step_with_keys():
    index = OffsetTripleIndex()
    index.add(1, 2, 3)
    index.add(4, 5, 6)
    for column in index._delta_columns()[:3]:
        column.pop()
    with pytest.raises(RuntimeError, match="disagree"):
        index.remove(4, 5, 6)


@pytest.mark.parametrize(
    "read",
    [
        lambda index: index.match(1, None, None),
        lambda index: index.match(1, 0, None),
        lambda index: index.match(None, None, 1),
    ],
    ids=["s", "s p", "o"],
)
def test_offsets_change_between_main_and_delta_raises(read):
    index = folded_offset_index(DELTA_MIN + 1)
    # A dead row in main, so the dead-row path runs too.
    index.remove(DELTA_MIN, 0, DELTA_MIN)
    index.add(1, 0, 0)
    index.add(0, 0, 1)
    it = read(index)
    # The one main match; the delta match is next.
    assert next(it) == (1, 0, 1)
    index.remove(1, 0, 0)
    with pytest.raises(RuntimeError):
        next(it)
