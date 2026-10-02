"""A set of triples of integer term ids, indexed for pattern matching with
nested dicts.

This is a trial alternative to `pymantic.triple_index.TripleIndex` with the
same interface. It re-creates the original Graph index over ids: three
orderings (SPO, POS and OSP), each a dict of first id to a dict of second id
to a set of third ids. A lookup with a bound leading id is a dict read, with
no bisect. The price is memory and garbage collector load: every distinct
(first, second) pair is a dict and every third-id collection a set, and the
collector walks them all.

Each triple is also one packed int key in a dict, which gives membership
and insertion order.

The third level is a set rather than a dict to None: it is smaller, and
nothing needs the order of the third ids. Queries yield in the order the
dicts hold, which is neither id order nor insertion order.

Ids must be in ``range(2**32)``. ``None`` is a wildcard in `match`.
"""

__all__ = ["NestedDictTripleIndex"]

_MASK32 = 0xFFFFFFFF

_CHANGED = "NestedDictTripleIndex changed during iteration"
_DETACHED = "NestedDictTripleIndex has been detached"


def _changed(index):
    """The error for a generator whose index changed under it."""
    return RuntimeError(_DETACHED if index._detached else _CHANGED)


def _insert(root, a, b, c):
    inner = root.get(a)
    if inner is None:
        root[a] = {b: {c}}
        return
    leaf = inner.get(b)
    if leaf is None:
        inner[b] = {c}
    else:
        leaf.add(c)


def _delete(root, a, b, c):
    """Remove (a, b, c), pruning each level that this empties."""
    inner = root[a]
    leaf = inner[b]
    leaf.remove(c)
    if not leaf:
        del inner[b]
        if not inner:
            del root[a]


class NestedDictTripleIndex:
    """Triples of int ids with SPO, POS and OSP orderings, each nested dicts."""

    __slots__ = ("_keys", "_spo", "_pos", "_osp", "_version", "_detached")

    def __init__(self):
        # Packed key ``s << 64 | p << 32 | o`` to None, in insertion order.
        self._keys = {}
        # Plain dicts, never defaultdicts: a read must not create entries.
        self._spo = {}
        self._pos = {}
        self._osp = {}
        # Bumped on every change; live generators compare against it.
        self._version = 0
        self._detached = False

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
        # Check the range before any change, for parity with the array
        # indexes, which cannot store a larger id.
        if not (0 <= s <= _MASK32 and 0 <= p <= _MASK32 and 0 <= o <= _MASK32):
            raise OverflowError("NestedDictTripleIndex ids must be in range(2**32)")
        keys[key] = None
        _insert(self._spo, s, p, o)
        _insert(self._pos, p, o, s)
        _insert(self._osp, o, s, p)
        self._version += 1
        return True

    def remove(self, s, p, o):
        """Remove a triple; raise KeyError if it is absent."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        key = s << 64 | p << 32 | o
        if key not in self._keys:
            raise KeyError((s, p, o))
        self._drop(s, p, o)
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
            if (s << 64 | p << 32 | o) not in keys:
                raise KeyError((s, p, o))
            doomed.append((s, p, o))
        if not doomed:
            return
        for s, p, o in doomed:
            # A triple given twice is already gone the second time.
            if (s << 64 | p << 32 | o) in keys:
                self._drop(s, p, o)
        self._version += 1

    def match(self, s, p, o):
        """Yield the (s, p, o) triples matching a pattern; None is a wildcard.

        Fully unbound yields in insertion order; the others in dict order.
        """
        if self._detached:
            raise RuntimeError(_DETACHED)
        if s is not None:
            if p is not None:
                if o is not None:
                    return self._lookup(s, p, o)
                return self._leaf(self._spo, s, p, _spo_row)
            if o is not None:
                return self._leaf(self._osp, o, s, _osp_row)
            return self._branch(self._spo, s, _spo_row)
        if p is not None:
            if o is not None:
                return self._leaf(self._pos, p, o, _pos_row)
            return self._branch(self._pos, p, _pos_row)
        if o is not None:
            return self._branch(self._osp, o, _osp_row)
        return self._walk_keys()

    def subjects(self):
        """Yield each distinct subject id in id order."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        return self._firsts(self._spo)

    def predicates(self):
        """Yield each distinct predicate id in id order."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        return self._firsts(self._pos)

    def objects(self):
        """Yield each distinct object id in id order."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        return self._firsts(self._osp)

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
        self._spo = {}
        self._pos = {}
        self._osp = {}

    def _drop(self, s, p, o):
        """Remove a present triple from the keys and all three orderings."""
        del self._keys[s << 64 | p << 32 | o]
        _delete(self._spo, s, p, o)
        _delete(self._pos, p, o, s)
        _delete(self._osp, o, s, p)

    # Each generator checks for detach on its first next(), since it may
    # have been created before the detach. After every yield it checks the
    # version before reading on, so a change is caught even after the last
    # result and before a dict is iterated further, as dict iteration's own
    # RuntimeError would not do.

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

    def _leaf(self, root, a, b, row):
        """Yield the triples whose first two ordering columns are `a`, `b`;
        `row` builds a triple from them and a third id."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        version = self._version
        inner = root.get(a)
        leaf = None if inner is None else inner.get(b)
        if leaf:
            for c in leaf:
                yield row(a, b, c)
                if self._version != version:
                    raise _changed(self)

    def _branch(self, root, a, row):
        """Yield the triples whose first ordering column is `a`."""
        if self._detached:
            raise RuntimeError(_DETACHED)
        version = self._version
        inner = root.get(a)
        if inner:
            for b, leaf in inner.items():
                for c in leaf:
                    yield row(a, b, c)
                    if self._version != version:
                        raise _changed(self)

    def _firsts(self, root):
        if self._detached:
            raise RuntimeError(_DETACHED)
        version = self._version
        for value in sorted(root):
            yield value
            if self._version != version:
                raise _changed(self)


# Builders of an (s, p, o) triple from an ordering's columns.
def _spo_row(a, b, c):
    return (a, b, c)


def _pos_row(a, b, c):
    return (c, a, b)


def _osp_row(a, b, c):
    return (b, c, a)
