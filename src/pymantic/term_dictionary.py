"""Maps RDF terms to dense integer ids and back.

The graph index stores only ids in int arrays, so the terms themselves are the
only Python objects it keeps alive.
"""

# Ids must fit a 32-bit field of the triple index's packed keys.
MAX_TERMS = 2**32


class TermDictionary:
    __slots__ = ("terms", "_ids", "_free")

    def __init__(self):
        # terms[id] is the term, or None for a freed id. Callers index it
        # directly and must not modify it.
        self.terms = []
        self._ids = {}
        self._free = []

    def intern(self, term):
        """Return the id of term, adding it if it is new."""
        ids = self._ids
        term_id = ids.get(term)
        if term_id is not None:
            return term_id
        if self._free:
            term_id = self._free.pop()
            self.terms[term_id] = term
        else:
            term_id = len(self.terms)
            if term_id >= MAX_TERMS:
                raise OverflowError("term dictionary is full")
            self.terms.append(term)
        ids[term] = term_id
        return term_id

    def lookup(self, term):
        """Return the id of term, or None. Never adds a term."""
        return self._ids.get(term)

    def __len__(self):
        # Live terms, not slots: freed ids still occupy `terms`.
        return len(self._ids)

    def compact(self, live_ids):
        """Free every id not in live_ids and return how many were freed.

        Ids are not renumbered, so ids held by the caller stay valid.
        """
        terms = self.terms
        dead = [
            i for i, term in enumerate(terms) if term is not None and i not in live_ids
        ]
        for term_id in dead:
            del self._ids[terms[term_id]]
            terms[term_id] = None
        self._free.extend(dead)
        return len(dead)
