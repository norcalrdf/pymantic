import pytest

from pymantic import term_dictionary
from pymantic.primitives import BlankNode, Literal, NamedNode
from pymantic.term_dictionary import TermDictionary


class TripleTermStandIn(tuple):
    """Meets the spec's requirement for the 2.0 triple-term type: never
    equal to a Literal or a plain tuple."""

    __slots__ = ()

    def __eq__(self, other):
        return type(other) is type(self) and tuple.__eq__(self, other)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash((TripleTermStandIn, tuple(self)))


def test_equal_terms_get_one_id():
    d = TermDictionary()
    assert d.intern(NamedNode("http://a")) == d.intern(NamedNode("http://a"))
    assert len(d) == 1


def test_plain_str_looks_up_the_named_node_with_the_same_text():
    d = TermDictionary()
    i = d.intern(NamedNode("http://a"))
    assert d.lookup("http://a") == i


def test_two_blank_nodes_get_two_ids():
    d = TermDictionary()
    assert d.intern(BlankNode()) != d.intern(BlankNode())
    assert len(d) == 2


def test_lookup_of_unknown_term_returns_none_and_allocates_nothing():
    d = TermDictionary()
    d.intern(NamedNode("http://a"))
    assert d.lookup(NamedNode("http://b")) is None
    assert len(d) == 1
    assert len(d.terms) == 1


def test_terms_maps_id_back_to_term():
    d = TermDictionary()
    node = NamedNode("http://a")
    assert d.terms[d.intern(node)] == node


def test_compact_frees_dead_ids_and_reuses_them():
    d = TermDictionary()
    nodes = [NamedNode("http://e/%d" % n) for n in range(4)]
    ids = [d.intern(n) for n in nodes]
    assert d.compact({ids[0], ids[2]}) == 2
    assert d.terms[ids[1]] is None
    assert d.terms[ids[3]] is None
    assert d.lookup(nodes[1]) is None
    assert d.lookup(nodes[3]) is None
    assert d.lookup(nodes[0]) == ids[0]
    assert len(d) == 2
    new_id = d.intern(NamedNode("http://e/new"))
    assert new_id in (ids[1], ids[3])
    assert len(d.terms) == 4
    assert d.terms[new_id] == NamedNode("http://e/new")


def test_compact_with_every_id_live_frees_nothing():
    d = TermDictionary()
    ids = {d.intern(NamedNode("http://e/%d" % n)) for n in range(3)}
    assert d.compact(ids) == 0
    assert len(d) == 3


def test_compacting_twice_frees_nothing_the_second_time():
    d = TermDictionary()
    ids = [d.intern(NamedNode("http://e/%d" % n)) for n in range(4)]
    assert d.compact({ids[0]}) == 3
    assert d.compact({ids[0]}) == 0
    # Each freed id is reusable once: no id was listed free twice.
    reused = [d.intern(NamedNode("http://e/new%d" % n)) for n in range(3)]
    assert sorted(reused) == ids[1:]
    assert d.intern(NamedNode("http://e/last")) == 4
    assert len(d.terms) == 5


def test_compacting_after_the_free_list_was_reused_frees_each_id_once():
    d = TermDictionary()
    ids = [d.intern(NamedNode("http://e/%d" % n)) for n in range(4)]
    d.compact({ids[0]})
    reused = [d.intern(NamedNode("http://e/new%d" % n)) for n in range(3)]
    assert d.compact({ids[0]}) == 3
    assert d.compact({ids[0]}) == 0
    again = [d.intern(NamedNode("http://e/more%d" % n)) for n in range(3)]
    assert sorted(again) == sorted(reused)
    assert len(d.terms) == 4


def test_intern_raises_overflow_error_at_max_terms(monkeypatch):
    monkeypatch.setattr(term_dictionary, "MAX_TERMS", 3)
    d = TermDictionary()
    for n in range(3):
        d.intern(NamedNode("http://e/%d" % n))
    with pytest.raises(OverflowError):
        d.intern(NamedNode("http://e/overflow"))
    assert len(d) == 3
    assert d.intern(NamedNode("http://e/0")) == 0


def test_freed_ids_are_reusable_at_the_limit(monkeypatch):
    monkeypatch.setattr(term_dictionary, "MAX_TERMS", 3)
    d = TermDictionary()
    ids = [d.intern(NamedNode("http://e/%d" % n)) for n in range(3)]
    d.compact({ids[0], ids[1]})
    assert d.intern(NamedNode("http://e/again")) == ids[2]


def test_literal_and_triple_term_with_equal_parts_get_distinct_ids():
    d = TermDictionary()
    parts = ("x", None, NamedNode("http://e/dt"))
    assert d.intern(Literal(*parts)) != d.intern(TripleTermStandIn(parts))
