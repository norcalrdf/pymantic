import random

import pytest

from pymantic.triple_index import SMALL_MERGE, TripleIndex

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


def run_model(seed, operations=2000, max_size=250):
    rng = random.Random(seed)
    index = TripleIndex()
    # A dict used as an ordered set: re-adding after a remove moves to the end.
    ref = {}
    for _ in range(operations):
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
        check_against_reference(index, ref, rng)


@pytest.mark.parametrize("seed", range(20))
def test_model(seed):
    run_model(seed)


def test_readd_moves_to_end():
    index = TripleIndex()
    index.add(1, 2, 3)
    index.add(4, 5, 6)
    assert not index.add(1, 2, 3)
    assert list(index) == [(1, 2, 3), (4, 5, 6)]
    index.remove(1, 2, 3)
    assert index.add(1, 2, 3)
    assert list(index) == [(4, 5, 6), (1, 2, 3)]


def test_remove_absent_raises_key_error():
    index = TripleIndex()
    index.add(1, 2, 3)
    with pytest.raises(KeyError):
        index.remove(1, 2, 4)
    assert list(index) == [(1, 2, 3)]


def test_remove_many_with_absent_triple_changes_nothing():
    index = TripleIndex()
    for i in range(5):
        index.add(i, i, i)
    with pytest.raises(KeyError):
        index.remove_many([(0, 0, 0), (9, 9, 9), (1, 1, 1)])
    assert list(index) == [(i, i, i) for i in range(5)]
    assert sorted(index.match(None, None, 0)) == [(0, 0, 0)]
    assert list(index.subjects()) == [0, 1, 2, 3, 4]


def test_remove_many_tolerates_repeated_triples():
    index = TripleIndex()
    index.add(1, 2, 3)
    index.add(4, 5, 6)
    index.remove_many([(1, 2, 3), (1, 2, 3)])
    assert list(index) == [(4, 5, 6)]
    assert list(index.match(1, None, None)) == []


def test_zero_ids_are_bound_values():
    index = TripleIndex()
    index.add(0, 0, 0)
    index.add(1, 1, 1)
    assert list(index.match(0, None, None)) == [(0, 0, 0)]
    assert list(index.match(None, 0, None)) == [(0, 0, 0)]
    assert list(index.match(None, None, 0)) == [(0, 0, 0)]
    assert list(index.match(0, 0, 0)) == [(0, 0, 0)]


def test_largest_id():
    top = 2**32 - 1
    index = TripleIndex()
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
def test_mutation_during_iteration_raises(read, mutate):
    index = TripleIndex()
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


def test_subjects_drops_subject_after_last_triple_removed():
    index = TripleIndex()
    index.add(1, 2, 3)
    index.add(1, 2, 4)
    index.add(5, 2, 3)
    index.remove(1, 2, 3)
    assert list(index.subjects()) == [1, 5]
    index.remove(1, 2, 4)
    assert list(index.subjects()) == [5]
    assert list(index.objects()) == [3]
    assert index.ids() == {2, 3, 5}


def test_detach_makes_every_call_raise():
    index = TripleIndex()
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
