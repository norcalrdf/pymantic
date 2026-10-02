"""A set of triples of integer term ids in three two-level B+trees.

This has the interface of `pymantic.triple_index.TripleIndex` and is
trialled against it. Each triple is one packed int key in a dict, which
gives membership and insertion order, plus one row in each of three
orderings (SPO, POS and OSP). An ordering is a list of leaves, each three
parallel `array('I')` columns sorted together lexicographically, and an
index list holding each leaf's first row as a packed int. Rows cost about
12 bytes per ordering and the collector never visits them; it sees one
array object per leaf column. An insert or delete shifts rows within one
leaf only, so its cost does not grow with the index.

Adds are pending until the next query that needs them. A few pending adds
are inserted leaf by leaf; many (a bulk load) rebuild every ordering by
sorting the keys and cutting the result into leaves.

Ids must be in ``range(2**32)``. ``None`` is a wildcard in `match`.
"""

from array import array
from bisect import bisect_left, bisect_right
from itertools import islice

__all__ = ["BTreeTripleIndex", "BULK_DIVISOR", "BULK_MIN", "LOAD"]

# A rebuild cuts leaves of LOAD rows; a leaf splits in two when it grows
# past 2 * LOAD rows.
LOAD = 512

# Pending adds are inserted leaf by leaf unless there are more than BULK_MIN
# of them and more than 1/BULK_DIVISOR of the index, in which case every
# ordering is rebuilt. remove_many uses the same bound. On 3.14 a leaf
# insert costs 2-4 us per row in all three orderings and a rebuild 0.6-0.9
# us per key in the index, so they break even at a batch of a third to a
# quarter of the index.
BULK_MIN = 32
BULK_DIVISOR = 4

_MASK32 = 0xFFFFFFFF
_MASK64 = 0xFFFFFFFFFFFFFFFF

_SPO, _POS, _OSP = 0, 1, 2

# For each ordering, the positions of its s, p and o columns. The orderings
# are rotations of SPO: POS holds (p, o, s) and OSP holds (o, s, p).
_ROLES = ((0, 1, 2), (2, 0, 1), (1, 2, 0))

_CHANGED = "BTreeTripleIndex changed during iteration"
_DETACHED = "BTreeTripleIndex has been detached"
_DISAGREE = "BTreeTripleIndex orderings disagree with its keys"


def _changed(index):
    """The error for a generator whose index changed under it."""
    return RuntimeError(_DETACHED if index._detached else _CHANGED)


def _empty_ordering():
    """An ordering: the packed first row of each leaf, then the leaves'
    first, second and third columns, one list per column."""
    return ([], [], [], [])


def _build(keys):
    """An ordering holding the packed rows `keys`, which must be sorted."""
    load = LOAD
    firsts, col0s, col1s, col2s = ordering = _empty_ordering()
    for start in range(0, len(keys), load):
        chunk = keys[start : start + load]
        firsts.append(chunk[0])
        col0s.append(array("I", [k >> 64 for k in chunk]))
        col1s.append(array("I", [(k >> 32) & _MASK32 for k in chunk]))
        col2s.append(array("I", [k & _MASK32 for k in chunk]))
    return ordering


def _locate(c0, c1, c2, a, b, c):
    """Return the row of a leaf where (a, b, c) is or would be inserted."""
    lo = bisect_left(c0, a)
    hi = bisect_right(c0, a, lo)
    lo = bisect_left(c1, b, lo, hi)
    hi = bisect_right(c1, b, lo, hi)
    return bisect_left(c2, c, lo, hi)


def _insert(ordering, key, a, b, c):
    """Insert the row (a, b, c), packed as `key`, into its leaf."""
    firsts, col0s, col1s, col2s = ordering
    if not firsts:
        firsts.append(key)
        col0s.append(array("I", [a]))
        col1s.append(array("I", [b]))
        col2s.append(array("I", [c]))
        return
    j = bisect_right(firsts, key) - 1
    if j < 0:
        # Below every row: it becomes the first row of the first leaf.
        j = 0
        firsts[0] = key
    c0, c1, c2 = col0s[j], col1s[j], col2s[j]
    i = _locate(c0, c1, c2, a, b, c)
    c0.insert(i, a)
    c1.insert(i, b)
    c2.insert(i, c)
    if len(c0) > 2 * LOAD:
        half = len(c0) >> 1
        n0, n1, n2 = c0[half:], c1[half:], c2[half:]
        del c0[half:]
        del c1[half:]
        del c2[half:]
        firsts.insert(j + 1, n0[0] << 64 | n1[0] << 32 | n2[0])
        col0s.insert(j + 1, n0)
        col1s.insert(j + 1, n1)
        col2s.insert(j + 1, n2)


def _delete(ordering, key, a, b, c):
    """Delete the row (a, b, c), packed as `key`, from its leaf."""
    firsts, col0s, col1s, col2s = ordering
    j = bisect_right(firsts, key) - 1
    # The keys dict says the row is present, so a miss here means the
    # orderings and the keys disagree.
    if j < 0:
        raise RuntimeError(_DISAGREE)
    c0, c1, c2 = col0s[j], col1s[j], col2s[j]
    i = _locate(c0, c1, c2, a, b, c)
    if i == len(c0) or c0[i] != a or c1[i] != b or c2[i] != c:
        raise RuntimeError(_DISAGREE)
    del c0[i]
    del c1[i]
    del c2[i]
    if not c0:
        del firsts[j]
        del col0s[j]
        del col1s[j]
        del col2s[j]
    elif i == 0:
        firsts[j] = c0[0] << 64 | c1[0] << 32 | c2[0]


def _is_bulk(count, size):
    """Whether `count` rows changing in an index of `size` rows is cheaper
    as a rebuild than leaf by leaf."""
    return count > BULK_MIN and count > size // BULK_DIVISOR


class BTreeTripleIndex:
    """Triples of int ids with SPO, POS and OSP orderings in B+trees."""

    __slots__ = (
        "_keys",
        "_orders",
        "_pending",
        "_version",
        "_detached",
        "rebuilds",
    )

    def __init__(self):
        # Packed key ``s << 64 | p << 32 | o`` to None, in insertion order.
        self._keys = {}
        # SPO, POS and OSP, each an ordering as `_empty_ordering` makes.
        self._orders = tuple(_empty_ordering() for _ in range(3))
        # How many of the last keys are not yet in the orderings. Every
        # remove merges first, so the pending adds are always the last
        # keys in insertion order.
        self._pending = 0
        # Bumped on every change; live generators compare against it.
        self._version = 0
        self._detached = False
        # How many times every ordering was rebuilt from the keys.
        self.rebuilds = 0

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
        # Check the range before packing: an out-of-range id would pack
        # into a key for a different triple.
        if not (0 <= s <= _MASK32 and 0 <= p <= _MASK32 and 0 <= o <= _MASK32):
            raise OverflowError("BTreeTripleIndex ids must be in range(2**32)")
        key = s << 64 | p << 32 | o
        keys = self._keys
        if key in keys:
            return False
        keys[key] = None
        self._pending += 1
        self._version += 1
        return True

    def remove(self, s, p, o):
        """Remove a triple; raise KeyError if it is absent."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        key = s << 64 | p << 32 | o
        if key not in self._keys:
            raise KeyError((s, p, o))
        # Merge first so the triple is in the orderings and the pending
        # adds stay the last keys.
        if self._pending:
            self._merge()
        del self._keys[key]
        self._delete_rows(key)
        self._version += 1

    def remove_many(self, spos):
        """Remove several triples, rebuilding if they are many.

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
        if _is_bulk(len(doomed), len(keys)):
            for key in doomed:
                keys.pop(key, None)
            self._rebuild()
        else:
            if self._pending:
                self._merge()
            for key in doomed:
                # A triple listed twice is deleted once.
                if keys.pop(key, False) is None:
                    self._delete_rows(key)
        self._version += 1

    def match(self, s, p, o):
        """Yield the (s, p, o) triples matching a pattern; None is a wildcard.

        Fully bound and fully unbound patterns use the keys; unbound yields
        in insertion order. The others take a range in the ordering whose
        leading columns are bound and yield in id order.
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
        if self._pending:
            self._merge()
        found = set()
        for columns in self._orders[_SPO][1:]:
            for column in columns:
                found.update(column)
        return found

    def detach(self):
        """Free the index; every later call, and every live generator, raises."""
        self._detached = True
        self._version += 1
        self._keys = {}
        self._orders = tuple(_empty_ordering() for _ in range(3))
        self._pending = 0

    def _delete_rows(self, key):
        s, p, o = key >> 64, (key >> 32) & _MASK32, key & _MASK32
        spo, pos, osp = self._orders
        _delete(spo, key, s, p, o)
        _delete(pos, (key & _MASK64) << 32 | s, p, o, s)
        _delete(osp, (key & _MASK32) << 64 | key >> 32, o, s, p)

    def _merge(self):
        """Move the pending adds into the orderings."""
        pending = self._pending
        keys = self._keys
        if _is_bulk(pending, len(keys)):
            self._rebuild()
            return
        spo, pos, osp = self._orders
        for key in islice(reversed(keys), pending):
            s, p, o = key >> 64, (key >> 32) & _MASK32, key & _MASK32
            _insert(spo, key, s, p, o)
            _insert(pos, (key & _MASK64) << 32 | s, p, o, s)
            _insert(osp, (key & _MASK32) << 64 | key >> 32, o, s, p)
        self._pending = 0

    def _rebuild(self):
        """Rebuild every ordering from the keys and clear the pending adds."""
        keys = self._keys
        # POS and OSP keys are the SPO key rotated by one and two places.
        self._orders = (
            _build(sorted(keys)),
            _build(sorted([(k & _MASK64) << 32 | k >> 64 for k in keys])),
            _build(sorted([(k & _MASK32) << 64 | k >> 32 for k in keys])),
        )
        self._pending = 0
        self.rebuilds += 1

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

    def _scan(self, order, a, b):
        """Yield the rows of `order` whose first column is `a` and, unless
        `b` is None, whose second column is `b`."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        if self._pending:
            self._merge()
        version = self._version
        firsts, col0s, col1s, col2s = self._orders[order]
        # The matching rows are the packed keys in [low, high).
        if b is None:
            low = a << 64
            high = low + (1 << 64)
        else:
            low = a << 64 | b << 32
            high = low + (1 << 32)
        # The last leaf starting at or below `low` holds the first match,
        # unless every one of its rows is below `low`; the matches then
        # start the next leaf.
        j = bisect_right(firsts, low) - 1
        if j < 0:
            j = 0
        n = len(firsts)
        i_s, i_p, i_o = _ROLES[order]
        lists = (col0s, col1s, col2s)
        ss, ps, os_ = lists[i_s], lists[i_p], lists[i_o]
        while j < n:
            c0 = col0s[j]
            lo = bisect_left(c0, a)
            hi = bisect_right(c0, a, lo)
            if b is not None:
                c1 = col1s[j]
                lo = bisect_left(c1, b, lo, hi)
                hi = bisect_right(c1, b, lo, hi)
            if lo < hi:
                cs, cp, co = ss[j], ps[j], os_[j]
                for i in range(lo, hi):
                    yield (cs[i], cp[i], co[i])
                    # A change may have shortened the leaf; stop before
                    # reading.
                    if self._version != version:
                        raise _changed(self)
            j += 1
            if j == n or firsts[j] >= high:
                return

    def _distinct(self, order):
        if self._detached:
            raise RuntimeError(_DETACHED)
        if self._pending:
            self._merge()
        version = self._version
        col0s = self._orders[order][1]
        last = None
        for column in col0s:
            i = 0
            n = len(column)
            while i < n:
                value = column[i]
                # A value whose rows span two leaves starts the second one.
                if value != last:
                    yield value
                    if self._version != version:
                        raise _changed(self)
                    last = value
                i = bisect_right(column, value, i)
