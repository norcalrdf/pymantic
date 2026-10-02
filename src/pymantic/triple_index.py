"""A set of triples of integer term ids, indexed for pattern matching.

The index is built to add almost no objects for the cyclic garbage collector
to walk. Each triple is one packed int key in a dict, which gives
membership and insertion order, plus one row in each of three orderings
(SPO, POS and OSP). An ordering is three parallel `array('I')` columns
sorted together lexicographically, so a pattern with its leading positions
bound is a bisect range.

Adds go to a pending buffer and are merged into the orderings by the next
query that needs them. A small buffer is inserted row by row with bisect; a
larger one (a bulk load) re-sorts every ordering from the keys.

Ids must be in ``range(2**32)``. ``None`` is a wildcard in `match`.
"""

from array import array
from bisect import bisect_left, bisect_right

__all__ = ["SMALL_MERGE", "TripleIndex"]

# Buffers up to this size are inserted by bisect; larger ones trigger a
# re-sort. Tuned in Task 9.
SMALL_MERGE = 32

_MASK32 = 0xFFFFFFFF
_MASK64 = 0xFFFFFFFFFFFFFFFF

_SPO, _POS, _OSP = 0, 1, 2

# For each ordering, the positions of its s, p and o columns. The orderings
# are rotations of SPO: POS holds (p, o, s) and OSP holds (o, s, p).
_ROLES = ((0, 1, 2), (2, 0, 1), (1, 2, 0))

_CHANGED = "TripleIndex changed during iteration"
_DETACHED = "TripleIndex has been detached"


def _empty_columns():
    return (array("I"), array("I"), array("I"))


def _unpack(keys):
    """Split sorted packed keys into three fresh columns."""
    return (
        array("I", [k >> 64 for k in keys]),
        array("I", [(k >> 32) & _MASK32 for k in keys]),
        array("I", [k & _MASK32 for k in keys]),
    )


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
    # The keys dict says the row is present, so a miss here means the
    # orderings and the keys disagree.
    assert c0[i] == a and c1[i] == b and c2[i] == c
    del c0[i]
    del c1[i]
    del c2[i]


class TripleIndex:
    """Triples of int ids with SPO, POS and OSP orderings."""

    __slots__ = (
        "_keys",
        "_orders",
        "_buffer",
        "_version",
        "_detached",
        "resorts",
    )

    def __init__(self):
        # Packed key ``s << 64 | p << 32 | o`` to None, in insertion order.
        self._keys = {}
        # SPO, POS and OSP, each a tuple of three columns in ordering order.
        self._orders = tuple(_empty_columns() for _ in range(3))
        # s, p and o columns of adds not yet merged into the orderings.
        self._buffer = _empty_columns()
        # Bumped on every change; live generators compare against it.
        self._version = 0
        self._detached = False
        # How many times every ordering was rebuilt from the keys.
        self.resorts = 0

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
        keys[key] = None
        bs, bp, bo = self._buffer
        bs.append(s)
        bp.append(p)
        bo.append(o)
        self._version += 1
        return True

    def remove(self, s, p, o):
        """Remove a triple; raise KeyError if it is absent."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        key = s << 64 | p << 32 | o
        if key not in self._keys:
            raise KeyError((s, p, o))
        # Merge first so the triple is in the orderings, not the buffer.
        self._merge()
        del self._keys[key]
        spo, pos, osp = self._orders
        _delete(spo, s, p, o)
        _delete(pos, p, o, s)
        _delete(osp, o, s, p)
        self._version += 1

    def remove_many(self, spos):
        """Remove several triples with one re-sort.

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
            keys.pop(key, None)
        self._resort()
        self._version += 1

    def match(self, s, p, o):
        """Yield the (s, p, o) triples matching a pattern; None is a wildcard.

        Fully bound and fully unbound patterns use the keys; unbound yields
        in insertion order. The others take a bisect range in the ordering
        whose leading columns are bound and yield in id order.
        """
        if self._detached:
            raise RuntimeError(_DETACHED)
        if s is not None:
            if p is not None:
                if o is not None:
                    return self._lookup(s, p, o)
                return self._scan(_SPO, s, p)
            if o is not None:
                return self._scan(_OSP, o, s)
            return self._scan(_SPO, s, None)
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
        self._merge()
        found = set()
        for column in self._orders[_SPO]:
            found.update(column)
        return found

    def detach(self):
        """Free the index; every later call, and every live generator, raises."""
        self._detached = True
        self._version += 1
        self._keys = {}
        self._orders = tuple(_empty_columns() for _ in range(3))
        self._buffer = _empty_columns()

    def _columns(self):
        """The twelve arrays: SPO, POS and OSP columns, then the buffer."""
        return [c for columns in self._orders for c in columns] + list(self._buffer)

    def _merge(self):
        """Move the pending buffer into the orderings."""
        bs, bp, bo = self._buffer
        if not bs:
            return
        if len(bs) > SMALL_MERGE:
            self._resort()
            return
        spo, pos, osp = self._orders
        for s, p, o in zip(bs, bp, bo):
            _insert(spo, s, p, o)
            _insert(pos, p, o, s)
            _insert(osp, o, s, p)
        del bs[:]
        del bp[:]
        del bo[:]

    def _resort(self):
        """Rebuild every ordering from the keys and empty the buffer."""
        keys = self._keys
        # POS and OSP keys are the SPO key rotated by one and two places.
        self._orders = (
            _unpack(sorted(keys)),
            _unpack(sorted([(k & _MASK64) << 32 | k >> 64 for k in keys])),
            _unpack(sorted([(k & _MASK32) << 64 | k >> 32 for k in keys])),
        )
        self._buffer = _empty_columns()
        self.resorts += 1

    # Each generator checks for detach on its first next(), since it may
    # have been created before the detach.

    def _lookup(self, s, p, o):
        if self._detached:
            raise RuntimeError(_DETACHED)
        if (s << 64 | p << 32 | o) in self._keys:
            yield (s, p, o)

    def _walk_keys(self):
        if self._detached:
            raise RuntimeError(_DETACHED)
        version = self._version
        for key in self._keys:
            if self._version != version:
                raise RuntimeError(_CHANGED)
            yield (key >> 64, (key >> 32) & _MASK32, key & _MASK32)

    def _scan(self, order, a, b):
        """Yield the rows of `order` whose first column is `a` and, unless
        `b` is None, whose second column is `b`."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        self._merge()
        version = self._version
        columns = self._orders[order]
        c0, c1, _ = columns
        lo = bisect_left(c0, a)
        hi = bisect_right(c0, a, lo)
        if b is not None:
            lo = bisect_left(c1, b, lo, hi)
            hi = bisect_right(c1, b, lo, hi)
        i_s, i_p, i_o = _ROLES[order]
        cs, cp, co = columns[i_s], columns[i_p], columns[i_o]
        for i in range(lo, hi):
            # Check before reading: a change may have shortened the columns.
            if self._version != version:
                raise RuntimeError(_CHANGED)
            yield (cs[i], cp[i], co[i])

    def _distinct(self, order):
        if self._detached:
            raise RuntimeError(_DETACHED)
        self._merge()
        version = self._version
        column = self._orders[order][0]
        i = 0
        n = len(column)
        while i < n:
            if self._version != version:
                raise RuntimeError(_CHANGED)
            value = column[i]
            yield value
            i = bisect_right(column, value, i)
