import pytest
import random

from pymantic import btree_index
from pymantic.btree_index import BTreeTripleIndex
from pymantic.triple_index import RESORT_DIVISOR, SMALL_MERGE, TripleIndex

# Every index implementation runs the shared tests below.
IMPLEMENTATIONS = [
    TripleIndex,
    BTreeTripleIndex,
]

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


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda cls: cls.__name__)
def make_index(request):
    return request.param


def run_model(
    make_index, seed, operations=2000, max_size=250, check_every=1, after_check=None
):
    rng = random.Random(seed)
    index = make_index()
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
            if after_check is not None:
                after_check(index)
    check_against_reference(index, ref, rng)
    return index


@pytest.mark.parametrize("seed", range(20))
def test_model(make_index, seed):
    run_model(make_index, seed)


@pytest.mark.parametrize("seed", range(20, 30))
def test_model_with_pending_adds(make_index, seed):
    # Querying only every 7th operation leaves adds pending when removes run,
    # both single adds (merged by bisect) and batches (merged by re-sort).
    run_model(make_index, seed, check_every=7)


def test_readd_moves_to_end(make_index):
    index = make_index()
    index.add(1, 2, 3)
    index.add(4, 5, 6)
    assert not index.add(1, 2, 3)
    assert list(index) == [(1, 2, 3), (4, 5, 6)]
    index.remove(1, 2, 3)
    assert index.add(1, 2, 3)
    assert list(index) == [(4, 5, 6), (1, 2, 3)]


def test_remove_absent_raises_key_error(make_index):
    index = make_index()
    index.add(1, 2, 3)
    with pytest.raises(KeyError):
        index.remove(1, 2, 4)
    assert list(index) == [(1, 2, 3)]


def test_remove_many_with_absent_triple_changes_nothing(make_index):
    index = make_index()
    for i in range(5):
        index.add(i, i, i)
    with pytest.raises(KeyError):
        index.remove_many([(0, 0, 0), (9, 9, 9), (1, 1, 1)])
    assert list(index) == [(i, i, i) for i in range(5)]
    assert sorted(index.match(None, None, 0)) == [(0, 0, 0)]
    assert list(index.subjects()) == [0, 1, 2, 3, 4]


def test_remove_many_tolerates_repeated_triples(make_index):
    index = make_index()
    index.add(1, 2, 3)
    index.add(4, 5, 6)
    index.remove_many([(1, 2, 3), (1, 2, 3)])
    assert list(index) == [(4, 5, 6)]
    assert list(index.match(1, None, None)) == []


def test_zero_ids_are_bound_values(make_index):
    index = make_index()
    index.add(0, 0, 0)
    index.add(1, 1, 1)
    assert list(index.match(0, None, None)) == [(0, 0, 0)]
    assert list(index.match(None, 0, None)) == [(0, 0, 0)]
    assert list(index.match(None, None, 0)) == [(0, 0, 0)]
    assert list(index.match(0, 0, 0)) == [(0, 0, 0)]


def test_largest_id(make_index):
    top = 2**32 - 1
    index = make_index()
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
def test_mutation_during_iteration_raises(make_index, read, mutate):
    index = make_index()
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
def test_mutation_after_last_result_raises(make_index, read, mutate):
    index = make_index()
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


def test_out_of_range_id_leaves_index_unchanged(make_index):
    index = make_index()
    index.add(1, 2, 3)
    for bad in [(2**32, 0, 0), (0, 2**32, 0), (0, 0, 2**32), (0, 0, -1)]:
        with pytest.raises(OverflowError):
            index.add(*bad)
    assert list(index) == [(1, 2, 3)]
    assert len(index) == 1
    index.add(4, 5, 6)
    assert sorted(index.match(None, None, None)) == [(1, 2, 3), (4, 5, 6)]
    assert sorted(index.match(4, None, None)) == [(4, 5, 6)]


def test_out_of_range_id_leaves_buffer_columns_aligned():
    index = TripleIndex()
    index.add(1, 2, 3)
    for bad in [(2**32, 0, 0), (0, 2**32, 0), (0, 0, 2**32), (0, 0, -1)]:
        with pytest.raises(OverflowError):
            index.add(*bad)
    assert all(len(c) == 1 for c in index._columns()[9:])


def test_subjects_drops_subject_after_last_triple_removed(make_index):
    index = make_index()
    index.add(1, 2, 3)
    index.add(1, 2, 4)
    index.add(5, 2, 3)
    index.remove(1, 2, 3)
    assert list(index.subjects()) == [1, 5]
    index.remove(1, 2, 4)
    assert list(index.subjects()) == [5]
    assert list(index.objects()) == [3]
    assert index.ids() == {2, 3, 5}


def test_detach_makes_every_call_raise(make_index):
    index = make_index()
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


def btree_leaf_counts(index):
    """Check the shape of every BTreeTripleIndex ordering and return its leaf
    counts: leaves are non-empty, hold at most 2 * LOAD rows, are sorted
    within and across leaves, and `_firsts` holds each leaf's first row."""
    counts = []
    for firsts, col0s, col1s, col2s in index._orders:
        assert len(firsts) == len(col0s) == len(col1s) == len(col2s)
        rows = []
        for first, c0, c1, c2 in zip(firsts, col0s, col1s, col2s):
            assert 0 < len(c0) <= 2 * btree_index.LOAD
            assert len(c0) == len(c1) == len(c2)
            assert all(c.typecode == "I" for c in (c0, c1, c2))
            assert first == c0[0] << 64 | c1[0] << 32 | c2[0]
            rows.extend(a << 64 | b << 32 | c for a, b, c in zip(c0, c1, c2))
        assert rows == sorted(set(rows))
        assert len(rows) == len(index)
        counts.append(len(firsts))
    return counts


@pytest.mark.parametrize("seed", range(10))
def test_btree_model_with_small_leaves(monkeypatch, seed):
    # Small leaves give many of them, so inserts split leaves and removes
    # empty them.
    monkeypatch.setattr(btree_index, "LOAD", 4)
    history = []

    def record(index):
        history.append((index.rebuilds, btree_leaf_counts(index)))

    run_model(BTreeTripleIndex, seed, check_every=1, after_check=record)
    steps = list(zip(history, history[1:]))
    # Between two checks without a rebuild, the leaf count changes only by
    # splits and drops; see both happen.
    unbuilt = [(a, b) for (ra, a), (rb, b) in steps if ra == rb]
    assert any(after[0] > before[0] for before, after in unbuilt)
    assert any(after[0] < before[0] for before, after in unbuilt)
    assert max(counts[0] for _, counts in history) > 20


def test_btree_single_adds_merge_without_rebuilding():
    rng = random.Random(6)
    index = BTreeTripleIndex()
    for i in range(20000):
        s, p, o = rng.randrange(5000), rng.randrange(50), rng.randrange(5000)
        index.add(s, p, o)
        assert (s, p, o) in set(index.match(s, None, None))
    assert index.rebuilds == 0
    assert len(index) == len(set(index))
    btree_leaf_counts(index)


def test_btree_bulk_adds_rebuild_into_full_leaves(monkeypatch):
    monkeypatch.setattr(btree_index, "LOAD", 8)
    index = BTreeTripleIndex()
    count = btree_index.BULK_MIN + 50
    for i in range(count):
        index.add(i, i % 3, i)
    assert sorted(index.match(None, 1, None)) == [(i, 1, i) for i in range(1, count, 3)]
    assert index.rebuilds == 1
    # Cut into leaves of LOAD rows, the last one holding the rest.
    sizes = [8] * (count // 8) + ([count % 8] if count % 8 else [])
    for _, col0s, _, _ in index._orders:
        assert [len(c) for c in col0s] == sizes


def test_btree_rebuild_threshold_grows_with_index():
    index = BTreeTripleIndex()
    loaded = 2 * (btree_index.BULK_MIN + 1) * btree_index.BULK_DIVISOR
    for i in range(loaded):
        index.add(i, 0, i)
    list(index.match(0, None, None))
    assert index.rebuilds == 1

    # More than BULK_MIN rows, but at most 1/BULK_DIVISOR of the index:
    # inserted leaf by leaf.
    batch = len(index) // btree_index.BULK_DIVISOR
    assert btree_index.BULK_MIN < batch
    for i in range(batch):
        index.add(i, 1, i)
    assert sorted(index.match(None, 1, None)) == [(i, 1, i) for i in range(batch)]
    assert index.rebuilds == 1

    # A batch above the relative bound rebuilds.
    batch = 2 * len(index) // btree_index.BULK_DIVISOR
    for i in range(batch):
        index.add(i, 2, i)
    assert sorted(index.match(None, 2, None)) == [(i, 2, i) for i in range(batch)]
    assert index.rebuilds == 2
    assert list(index.subjects()) == list(range(loaded))
    btree_leaf_counts(index)


def test_btree_remove_many_rebuilds_only_for_large_batches():
    index = BTreeTripleIndex()
    loaded = 2 * (btree_index.BULK_MIN + 1) * btree_index.BULK_DIVISOR
    for i in range(loaded):
        index.add(i, 0, i)
    list(index.match(0, None, None))
    assert index.rebuilds == 1
    index.remove_many([(i, 0, i) for i in range(btree_index.BULK_MIN)])
    assert index.rebuilds == 1
    index.remove_many([(i, 0, i) for i in range(btree_index.BULK_MIN, loaded // 2)])
    assert index.rebuilds == 2
    assert list(index.subjects()) == list(range(loaded // 2, loaded))
    btree_leaf_counts(index)


def test_btree_remove_detects_orderings_out_of_step_with_keys():
    index = BTreeTripleIndex()
    index.add(1, 2, 3)
    index.add(4, 5, 6)
    list(index.match(1, None, None))
    # Corrupt the POS ordering so it no longer holds a triple the keys hold.
    for column in index._orders[1][1:]:
        column[0].pop()
    with pytest.raises(RuntimeError, match="disagree"):
        index.remove(4, 5, 6)
