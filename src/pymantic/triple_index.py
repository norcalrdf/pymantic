"""A set of triples of integer term ids, indexed as adjacency rows.

Each triple is one packed int key in a dict, which gives membership and
insertion order, plus one value in each of three orderings (SPO, POS and
OSP). An ordering is a dict from a first-column id to a row: the sorted
packed ``second << 32 | third`` values of the triples with that first id. A
pattern with its first position bound is one dict lookup, and with its
second bound too a bisect within the row.

The index is built to add almost no objects for the cyclic garbage collector
to walk. A row is a tuple, and CPython's collector untracks a tuple holding
only ints, so an ordering costs the collector one dict however many rows it
holds. Adding a value rebuilds the tuple, which costs its length, so a row
longer than `LIST_DEGREE` (rdf:type in POS, say) is a list instead and takes
inserts in place; only those few rows are tracked.

Adds go to a pending list of packed keys, moved into the orderings by the
next query that needs them. A small pending list is inserted value by value.
A larger one (a bulk load, or a big batch) is folded: sorted per ordering
and grouped by first id, so each row it touches is rebuilt once.

Ids must be in ``range(2**32)``. ``None`` is a wildcard in `match`.
"""

from bisect import bisect_left, insort

__all__ = ["FOLD_DIVISOR", "FOLD_MIN", "LIST_DEGREE", "TripleIndex"]

# A row holding more than LIST_DEGREE values is a list rather than a tuple.
LIST_DEGREE = 256

# Pending adds are folded, rather than inserted one by one, when there are
# more than FOLD_MIN of them and more than 1/FOLD_DIVISOR of the index.
FOLD_MIN = 1024
FOLD_DIVISOR = 16

# remove_many filters a row in one pass when it removes more than this many
# of its values; fewer are deleted one by one with bisect.
_FILTER_MIN = 32

_MASK32 = 0xFFFFFFFF
_MASK64 = 0xFFFFFFFFFFFFFFFF
_STEP32 = 1 << 32

_SPO, _POS, _OSP = 0, 1, 2

_RANGE = "TripleIndex ids must be in range(2**32)"
_CHANGED = "TripleIndex changed during iteration"
_DETACHED = "TripleIndex has been detached"
_DISAGREE = "TripleIndex orderings disagree with its keys"


def _changed(index):
    """The error for a generator whose index changed under it."""
    return RuntimeError(_DETACHED if index._detached else _CHANGED)


def _check_range(s, p, o):
    """Raise OverflowError unless s, p and o are all in range(2**32)."""
    if not (0 <= s <= _MASK32 and 0 <= p <= _MASK32 and 0 <= o <= _MASK32):
        raise OverflowError(_RANGE)


def _rotated(keys):
    """The packed SPO keys as packed keys of each ordering, one at a time.

    POS and OSP keys are the SPO key rotated by one and two places.
    """
    yield keys
    yield [(k & _MASK64) << 32 | k >> 64 for k in keys]
    yield [(k & _MASK32) << 64 | k >> 32 for k in keys]


def _row(values):
    """A row for a fresh sorted list of values."""
    return tuple(values) if len(values) <= LIST_DEGREE else values


def _insert(rows, a, v):
    """Insert value `v` into the row of `a`."""
    row = rows.get(a)
    if row is None:
        rows[a] = (v,)
    elif type(row) is tuple:
        i = bisect_left(row, v)
        if len(row) < LIST_DEGREE:
            rows[a] = row[:i] + (v,) + row[i:]
        else:
            row = list(row)
            row.insert(i, v)
            rows[a] = row
    else:
        insort(row, v)


def _delete(rows, a, v):
    """Delete value `v` from the row of `a`, dropping the row if empty."""
    row = rows.get(a)
    # The keys dict says the value is present, so a miss here means the
    # orderings and the keys disagree.
    if row is None:
        raise RuntimeError(_DISAGREE)
    i = bisect_left(row, v)
    if i == len(row) or row[i] != v:
        raise RuntimeError(_DISAGREE)
    if len(row) == 1:
        del rows[a]
    elif type(row) is tuple:
        rows[a] = row[:i] + row[i + 1 :]
    else:
        del row[i]


def _merge_sorted(rows, packed):
    """Merge sorted packed keys of one ordering into its rows."""
    i = 0
    n = len(packed)
    while i < n:
        a = packed[i] >> 64
        j = bisect_left(packed, (a + 1) << 64, i)
        old = rows.get(a)
        if j == i + 1 and old is None:
            rows[a] = (packed[i] & _MASK64,)
        else:
            values = [k & _MASK64 for k in packed[i:j]]
            if old is not None:
                # Two sorted runs, which list.sort merges in linear time.
                values += old
                values.sort()
            rows[a] = _row(values)
        i = j


def _remove_values(rows, a, gone):
    """Remove the set of values `gone` from the row of `a`."""
    if len(gone) <= _FILTER_MIN:
        for v in gone:
            _delete(rows, a, v)
        return
    row = rows.get(a)
    if row is None:
        raise RuntimeError(_DISAGREE)
    kept = [v for v in row if v not in gone]
    if len(kept) != len(row) - len(gone):
        raise RuntimeError(_DISAGREE)
    if kept:
        rows[a] = _row(kept)
    else:
        del rows[a]


class TripleIndex:
    """Triples of int ids with SPO, POS and OSP adjacency rows."""

    __slots__ = ("_keys", "_orders", "_pending", "_version", "_detached", "folds")

    def __init__(self):
        # Packed key ``s << 64 | p << 32 | o`` to None, in insertion order.
        self._keys = {}
        # SPO, POS and OSP, each a dict from first-column id to its row.
        self._orders = ({}, {}, {})
        # Packed keys of adds not yet in the orderings, in add order.
        self._pending = []
        # Bumped on every change; live generators compare against it.
        self._version = 0
        self._detached = False
        # How many times pending adds were folded into the orderings.
        self.folds = 0

    def __len__(self):
        if self._detached:
            raise RuntimeError(_DETACHED)
        return len(self._keys)

    def __contains__(self, spo):
        if self._detached:
            raise RuntimeError(_DETACHED)
        s, p, o = spo
        # An id out of range packs to some other triple's key.
        if not (0 <= s <= _MASK32 and 0 <= p <= _MASK32 and 0 <= o <= _MASK32):
            return False
        return (s << 64 | p << 32 | o) in self._keys

    def __iter__(self):
        if self._detached:
            raise RuntimeError(_DETACHED)
        return self._walk_keys()

    def add(self, s, p, o):
        """Add a triple; return False if it was already present."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        # An id out of range would pack into some other triple's key, so
        # check before the key is used to look anything up.
        if not (0 <= s <= _MASK32 and 0 <= p <= _MASK32 and 0 <= o <= _MASK32):
            raise OverflowError(_RANGE)
        key = s << 64 | p << 32 | o
        keys = self._keys
        if key in keys:
            return False
        self._pending.append(key)
        keys[key] = None
        self._version += 1
        return True

    def remove(self, s, p, o):
        """Remove a triple; raise KeyError if it is absent."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        _check_range(s, p, o)
        key = s << 64 | p << 32 | o
        if key not in self._keys:
            raise KeyError((s, p, o))
        # Merge first so the triple is in the orderings, not pending.
        if self._pending:
            self._merge()
        del self._keys[key]
        spo, pos, osp = self._orders
        _delete(spo, s, p << 32 | o)
        _delete(pos, p, o << 32 | s)
        _delete(osp, o, s << 32 | p)
        self._version += 1

    def remove_many(self, spos):
        """Remove several triples, rebuilding each row they touch once.

        Raises KeyError, changing nothing, if any triple is absent.
        """
        if self._detached:
            raise RuntimeError(_DETACHED)
        keys = self._keys
        doomed = {}
        for s, p, o in spos:
            _check_range(s, p, o)
            key = s << 64 | p << 32 | o
            if key not in keys:
                raise KeyError((s, p, o))
            doomed[key] = None
        if not doomed:
            return
        if self._pending:
            self._merge()
        for key in doomed:
            del keys[key]
        for rows, packed in zip(self._orders, _rotated(list(doomed))):
            gone = {}
            for k in packed:
                a = k >> 64
                values = gone.get(a)
                if values is None:
                    gone[a] = values = set()
                values.add(k & _MASK64)
            for a, values in gone.items():
                _remove_values(rows, a, values)
        self._version += 1

    def match(self, s, p, o):
        """Yield the (s, p, o) triples matching a pattern; None is a wildcard.

        Fully bound and fully unbound patterns use the keys; unbound yields
        in insertion order. The others read the row of the ordering whose
        first column is bound, in (second, third) id order.
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
        spo, pos, osp = self._orders
        found = set(spo)
        found.update(pos)
        found.update(osp)
        return found

    def detach(self):
        """Free the index; every later call, and every live generator, raises."""
        self._detached = True
        self._version += 1
        self._keys = {}
        self._orders = ({}, {}, {})
        self._pending = []

    def _merge(self):
        """Move the pending adds into the orderings."""
        pending = self._pending
        self._pending = []
        if len(pending) > max(FOLD_MIN, len(self._keys) // FOLD_DIVISOR):
            for rows, packed in zip(self._orders, _rotated(pending)):
                packed.sort()
                _merge_sorted(rows, packed)
            self.folds += 1
            return
        spo, pos, osp = self._orders
        for k in pending:
            s = k >> 64
            o = k & _MASK32
            _insert(spo, s, k & _MASK64)
            _insert(pos, (k >> 32) & _MASK32, o << 32 | s)
            _insert(osp, o, k >> 32)

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
        """Yield the triples in the row of `a` in `order` whose second
        column is `b`, or all of them if `b` is None."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        if self._pending:
            self._merge()
        version = self._version
        row = self._orders[order].get(a)
        if row is None:
            return
        if b is not None:
            lo = b << 32
            row = row[bisect_left(row, lo) : bisect_left(row, lo + _STEP32)]
        # A list row may change in place under a live generator; the version
        # check after each yield stops before reading it again.
        if order == _SPO:
            for v in row:
                yield (a, v >> 32, v & _MASK32)
                if self._version != version:
                    raise _changed(self)
        elif order == _POS:
            for v in row:
                yield (v & _MASK32, a, v >> 32)
                if self._version != version:
                    raise _changed(self)
        else:
            for v in row:
                yield (v >> 32, v & _MASK32, a)
                if self._version != version:
                    raise _changed(self)

    def _distinct(self, order):
        if self._detached:
            raise RuntimeError(_DETACHED)
        if self._pending:
            self._merge()
        version = self._version
        for a in sorted(self._orders[order]):
            yield a
            if self._version != version:
                raise _changed(self)
