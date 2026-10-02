"""A set of triples of integer term ids, indexed for pattern matching, with
offsets arrays for constant-time lookup of a leading id.

This is a trial alternative to `pymantic.triple_index.TripleIndex` with the
same interface. Like it, each triple is one packed int key in a dict, which
gives membership and insertion order, plus one row in each of three
orderings (SPO, POS and OSP), and it adds almost no objects for the cyclic
garbage collector to walk.

Each ordering has two parts:

- main: three `array('I')` columns sorted together lexicographically, plus
  `start`, where the rows whose first column is x are
  ``start[x]:start[x + 1]``. Finding the rows of a leading id costs two
  array reads instead of two bisects.
- delta: three columns kept sorted by bisect-insert, holding the rows added
  since main was built.

Removing a main row only marks its key dead, so a remove never shifts the
main columns. When the delta or the dead set outgrows
``max(DELTA_MIN, len(index) // FOLD_DIVISOR)``, the next query folds: main
is rebuilt from the keys and the delta and dead set are emptied. A bulk load
fills the delta past that bound, after which adds skip the delta, since the
fold rebuilds from the keys anyway.

Queries yield the matching main rows, then the matching delta rows, each
part in id order.

Ids must be in ``range(2**32)``. ``None`` is a wildcard in `match`.
"""

from array import array
from bisect import bisect_left, bisect_right
from collections import Counter
from heapq import merge
from itertools import accumulate

__all__ = ["DELTA_MIN", "FOLD_DIVISOR", "OffsetTripleIndex"]

# The delta and the dead set may each hold up to
# max(DELTA_MIN, len(index) // FOLD_DIVISOR) rows before the next query
# folds them into main. Inserting into the delta shifts it, so its cost
# grows with the bound; folding costs a sort of every key.
DELTA_MIN = 1024
FOLD_DIVISOR = 16

# `start` covers first-column ids below START_PER_ROW times the number of
# rows; rows with larger first ids are found by bisect past the covered
# ones. A standalone graph adds at most three terms per triple, so with
# dense ids this covers every id, while a small graph in a large dataset,
# whose ids are spread across the dataset's terms, keeps its offsets in
# proportion to its own rows.
START_PER_ROW = 3

_MASK32 = 0xFFFFFFFF
_MASK64 = 0xFFFFFFFFFFFFFFFF

_SPO, _POS, _OSP = 0, 1, 2

# For each ordering, the positions of its s, p and o columns. The orderings
# are rotations of SPO: POS holds (p, o, s) and OSP holds (o, s, p).
_ROLES = ((0, 1, 2), (2, 0, 1), (1, 2, 0))

_CHANGED = "OffsetTripleIndex changed during iteration"
_DETACHED = "OffsetTripleIndex has been detached"


def _changed(index):
    """The error for a generator whose index changed under it."""
    return RuntimeError(_DETACHED if index._detached else _CHANGED)


def _empty_columns():
    return (array("I"), array("I"), array("I"))


def _empty_main():
    return _empty_columns() + (array("I", [0]),)


def _empty_delta():
    return tuple(_empty_columns() for _ in range(3))


def _build_main(keys):
    """Main for one ordering from its sorted packed keys: three columns and
    the offsets of the covered first-column ids."""
    c0 = array("I", [k >> 64 for k in keys])
    c1 = array("I", [(k >> 32) & _MASK32 for k in keys])
    c2 = array("I", [k & _MASK32 for k in keys])
    covered = min(c0[-1] + 1, START_PER_ROW * len(c0)) if c0 else 0
    # counts[x + 1] is the number of rows with first id x; their running
    # sum is where each id's rows start. The last entry counts every row
    # with a covered id, which is where the uncovered rows start.
    counts = [0] * (covered + 1)
    for x, count in Counter(c0).items():
        if x < covered:
            counts[x + 1] = count
    return (c0, c1, c2, array("I", accumulate(counts)))


def _main_range(main, a):
    """The rows of `main` whose first column is `a`."""
    c0, _, _, start = main
    covered = len(start) - 1
    if a < covered:
        return start[a], start[a + 1]
    lo = bisect_left(c0, a, start[covered])
    return lo, bisect_right(c0, a, lo)


def _locate(columns, a, b, c):
    """Return the row where (a, b, c) is or would be inserted."""
    c0, c1, c2 = columns
    lo = bisect_left(c0, a)
    hi = bisect_right(c0, a, lo)
    lo = bisect_left(c1, b, lo, hi)
    hi = bisect_right(c1, b, lo, hi)
    return bisect_left(c2, c, lo, hi)


def _insert(columns, a, b, c):
    i = _locate(columns, a, b, c)
    c0, c1, c2 = columns
    c0.insert(i, a)
    c1.insert(i, b)
    c2.insert(i, c)


def _delete(columns, a, b, c):
    i = _locate(columns, a, b, c)
    c0, c1, c2 = columns
    # The keys and main say the row is in the delta, so a miss here means
    # the delta and the keys disagree.
    if i == len(c0) or c0[i] != a or c1[i] != b or c2[i] != c:
        raise RuntimeError("OffsetTripleIndex delta disagrees with its keys")
    del c0[i]
    del c1[i]
    del c2[i]


class OffsetTripleIndex:
    """Triples of int ids with SPO, POS and OSP orderings, each a main part
    with offsets and a sorted delta."""

    __slots__ = (
        "_keys",
        "_main",
        "_delta",
        "_dead",
        "_stale",
        "_version",
        "_detached",
        "folds",
    )

    def __init__(self):
        # Packed key ``s << 64 | p << 32 | o`` to None, in insertion order.
        self._keys = {}
        # SPO, POS and OSP mains, each (c0, c1, c2, start).
        self._main = tuple(_empty_main() for _ in range(3))
        # SPO, POS and OSP deltas, each three columns in ordering order.
        self._delta = _empty_delta()
        # Packed keys of main rows that were removed.
        self._dead = set()
        # True once the delta or dead set passed its bound: main, delta and
        # dead no longer track the keys, and the next query folds.
        self._stale = False
        # Bumped on every change; live generators compare against it.
        self._version = 0
        self._detached = False
        # How many times main was rebuilt from the keys.
        self.folds = 0

    def __len__(self):
        if self._detached:
            raise RuntimeError(_DETACHED)
        return len(self._keys)

    def __contains__(self, spo):
        if self._detached:
            raise RuntimeError(_DETACHED)
        s, p, o = spo
        return (s << 64 | p << 32 | o) in self._keys

    def __iter__(self):
        if self._detached:
            raise RuntimeError(_DETACHED)
        return self._walk_keys()

    def add(self, s, p, o):
        """Add a triple; return False if it was already present."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        key = s << 64 | p << 32 | o
        keys = self._keys
        if key in keys:
            return False
        # Check the range before any change rather than relying on the
        # arrays to reject it: GraalPy's array.append grows a column with a
        # 0 before raising OverflowError, and a stale index only stores the
        # key, so nothing else would check it.
        if not (0 <= s <= _MASK32 and 0 <= p <= _MASK32 and 0 <= o <= _MASK32):
            raise OverflowError("OffsetTripleIndex ids must be in range(2**32)")
        keys[key] = None
        self._version += 1
        if self._stale:
            return True
        dead = self._dead
        if key in dead:
            # Its main row is still there; it is live again.
            dead.discard(key)
            return True
        spo, pos, osp = self._delta
        _insert(spo, s, p, o)
        _insert(pos, p, o, s)
        _insert(osp, o, s, p)
        if len(spo[0]) > max(DELTA_MIN, len(keys) // FOLD_DIVISOR):
            self._stale = True
        return True

    def remove(self, s, p, o):
        """Remove a triple; raise KeyError if it is absent."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        key = s << 64 | p << 32 | o
        if key not in self._keys:
            raise KeyError((s, p, o))
        self._drop(key)
        self._version += 1

    def remove_many(self, spos):
        """Remove several triples.

        Raises KeyError, changing nothing, if any triple is absent.
        """
        if self._detached:
            raise RuntimeError(_DETACHED)
        keys = self._keys
        doomed = []
        for s, p, o in spos:
            key = s << 64 | p << 32 | o
            if key not in keys:
                raise KeyError((s, p, o))
            doomed.append(key)
        if not doomed:
            return
        for key in doomed:
            # A triple given twice is already gone the second time.
            if key in keys:
                self._drop(key)
        self._version += 1

    def match(self, s, p, o):
        """Yield the (s, p, o) triples matching a pattern; None is a wildcard.

        Fully bound and fully unbound patterns use the keys; unbound yields
        in insertion order. The others take the rows of the ordering whose
        leading columns are bound, from main and then from the delta.
        """
        if self._detached:
            raise RuntimeError(_DETACHED)
        if s is not None:
            if p is not None:
                if o is not None:
                    return self._lookup(s, p, o)
                return self._subject(s, p)
            if o is not None:
                return self._scan(_OSP, o, s)
            return self._subject(s, None)
        if p is not None:
            return self._scan(_POS, p, o)
        if o is not None:
            return self._scan(_OSP, o, None)
        return self._walk_keys()

    def subjects(self):
        """Yield each distinct subject id in id order."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        return self._distinct(_SPO)

    def predicates(self):
        """Yield each distinct predicate id in id order."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        return self._distinct(_POS)

    def objects(self):
        """Yield each distinct object id in id order."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        return self._distinct(_OSP)

    def ids(self):
        """Return the set of every id in any position."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        keys = self._keys
        found = {k >> 64 for k in keys}
        found.update([(k >> 32) & _MASK32 for k in keys])
        found.update([k & _MASK32 for k in keys])
        return found

    def detach(self):
        """Free the index; every later call, and every live generator, raises."""
        self._detached = True
        self._version += 1
        self._keys = {}
        self._main = tuple(_empty_main() for _ in range(3))
        self._delta = _empty_delta()
        self._dead = set()
        self._stale = False

    def _columns(self):
        """The 21 arrays: each main's columns and offsets, then the delta's."""
        return [c for main in self._main for c in main] + self._delta_columns()

    def _delta_columns(self):
        """The nine delta arrays: SPO, POS and OSP columns."""
        return [c for columns in self._delta for c in columns]

    def _drop(self, key):
        """Remove a present key, and its row unless the index is stale."""
        keys = self._keys
        del keys[key]
        if self._stale:
            return
        s, p, o = key >> 64, (key >> 32) & _MASK32, key & _MASK32
        _, c1, c2, _ = main = self._main[_SPO]
        lo, hi = _main_range(main, s)
        lo = bisect_left(c1, p, lo, hi)
        hi = bisect_right(c1, p, lo, hi)
        i = bisect_left(c2, o, lo, hi)
        if i < hi and c2[i] == o:
            dead = self._dead
            dead.add(key)
            if len(dead) > max(DELTA_MIN, len(keys) // FOLD_DIVISOR):
                self._stale = True
            return
        spo, pos, osp = self._delta
        _delete(spo, s, p, o)
        _delete(pos, p, o, s)
        _delete(osp, o, s, p)

    def _fold(self):
        """Rebuild main from the keys and empty the delta and dead set.

        Every part is replaced rather than cleared, so a generator still
        holding the old ones reads a consistent, if outdated, index; it
        raises on its next step anyway, since the change that made the
        index stale bumped the version.
        """
        keys = self._keys
        # POS and OSP keys are the SPO key rotated by one and two places.
        self._main = (
            _build_main(sorted(keys)),
            _build_main(sorted([(k & _MASK64) << 32 | k >> 64 for k in keys])),
            _build_main(sorted([(k & _MASK32) << 64 | k >> 32 for k in keys])),
        )
        self._delta = _empty_delta()
        self._dead = set()
        self._stale = False
        self.folds += 1

    # Each generator checks for detach on its first next(), since it may
    # have been created before the detach. After every yield it checks the
    # version before reading on, so a change is caught even after the last
    # result, as dict iteration does.

    def _lookup(self, s, p, o):
        if self._detached:
            raise RuntimeError(_DETACHED)
        version = self._version
        if (s << 64 | p << 32 | o) in self._keys:
            yield (s, p, o)
            if self._version != version:
                raise _changed(self)

    def _walk_keys(self):
        if self._detached:
            raise RuntimeError(_DETACHED)
        version = self._version
        for key in self._keys:
            yield (key >> 64, (key >> 32) & _MASK32, key & _MASK32)
            if self._version != version:
                raise _changed(self)

    def _subject(self, s, p):
        """Yield the triples with subject `s` and, unless `p` is None,
        predicate `p`.

        The hot path of the Resource layer and the Turtle writer, so the
        SPO ordering is read directly, with the subject taken as given.
        """
        if self._detached:
            raise RuntimeError(_DETACHED)
        if self._stale:
            self._fold()
        version = self._version
        c0, c1, c2, start = self._main[_SPO]
        covered = len(start) - 1
        if s < covered:
            lo = start[s]
            hi = start[s + 1]
        else:
            lo = bisect_left(c0, s, start[covered])
            hi = bisect_right(c0, s, lo)
        if p is not None:
            lo = bisect_left(c1, p, lo, hi)
            hi = bisect_right(c1, p, lo, hi)
        dead = self._dead
        if dead:
            base = s << 64
            for i in range(lo, hi):
                p_i = c1[i]
                o_i = c2[i]
                if (base | p_i << 32 | o_i) in dead:
                    continue
                yield (s, p_i, o_i)
                if self._version != version:
                    raise _changed(self)
        else:
            for i in range(lo, hi):
                yield (s, c1[i], c2[i])
                # A change may have replaced or shortened the columns;
                # stop before reading.
                if self._version != version:
                    raise _changed(self)
        d0, d1, d2 = self._delta[_SPO]
        if d0:
            lo = bisect_left(d0, s)
            hi = bisect_right(d0, s, lo)
            if p is not None:
                lo = bisect_left(d1, p, lo, hi)
                hi = bisect_right(d1, p, lo, hi)
            for i in range(lo, hi):
                yield (s, d1[i], d2[i])
                if self._version != version:
                    raise _changed(self)

    def _scan(self, order, a, b):
        """Yield the rows of `order` whose first column is `a` and, unless
        `b` is None, whose second column is `b`."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        if self._stale:
            self._fold()
        version = self._version
        i_s, i_p, i_o = _ROLES[order]
        main = self._main[order]
        lo, hi = _main_range(main, a)
        if b is not None:
            c1 = main[1]
            lo = bisect_left(c1, b, lo, hi)
            hi = bisect_right(c1, b, lo, hi)
        cs, cp, co = main[i_s], main[i_p], main[i_o]
        dead = self._dead
        for i in range(lo, hi):
            spo = (cs[i], cp[i], co[i])
            if dead and (spo[0] << 64 | spo[1] << 32 | spo[2]) in dead:
                continue
            yield spo
            if self._version != version:
                raise _changed(self)
        delta = self._delta[order]
        d0, d1, _ = delta
        if d0:
            lo = bisect_left(d0, a)
            hi = bisect_right(d0, a, lo)
            if b is not None:
                lo = bisect_left(d1, b, lo, hi)
                hi = bisect_right(d1, b, lo, hi)
            ds, dp, do = delta[i_s], delta[i_p], delta[i_o]
            for i in range(lo, hi):
                yield (ds[i], dp[i], do[i])
                if self._version != version:
                    raise _changed(self)

    def _distinct(self, order):
        if self._detached:
            raise RuntimeError(_DETACHED)
        if self._stale:
            self._fold()
        version = self._version
        last = None
        for value in merge(
            _live_firsts(self._main[order], order, self._dead),
            _firsts(self._delta[order][0]),
        ):
            # A first id with rows in both main and the delta comes twice.
            if value == last:
                continue
            last = value
            yield value
            if self._version != version:
                raise _changed(self)


def _firsts(column):
    """Yield each distinct value of a sorted column."""
    i = 0
    n = len(column)
    while i < n:
        value = column[i]
        yield value
        i = bisect_right(column, value, i)


def _live_firsts(main, order, dead):
    """Yield each distinct first id of `main` that has a row not in `dead`."""
    if not dead:
        yield from _firsts(main[0])
        return
    c0 = main[0]
    i_s, i_p, i_o = _ROLES[order]
    cs, cp, co = main[i_s], main[i_p], main[i_o]
    i = 0
    n = len(c0)
    while i < n:
        value = c0[i]
        end = bisect_right(c0, value, i)
        for j in range(i, end):
            if (cs[j] << 64 | cp[j] << 32 | co[j]) not in dead:
                yield value
                break
        i = end
