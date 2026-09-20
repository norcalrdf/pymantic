"""Unit tests for pymantic.compare, following the stages of
docs/graph-comparison.rst. Each bail-out stage has a minimal pair, the
molecule split and Carroll refinement are tested directly, and the work
budget is tested with a blank clique."""

import pytest
import random
import time

from pymantic.compare import (
    Undecidable,
    bail_stage,
    canonical_form,
    canonical_labels,
    isomorphic,
    molecules,
    refine,
    statements,
)
from pymantic.parsers import turtle_parser
from pymantic.primitives import (
    BlankNode,
    Dataset,
    Graph,
    Literal,
    NamedNode,
    Quad,
    Triple,
)

EX = "http://example.org/"
PREFIX = "@prefix : <%s> .\n" % EX


def graph(turtle):
    return turtle_parser.parse(PREFIX + turtle)


def relabelled_and_shuffled(source, seed=0):
    """A copy of ``source`` with fresh blank nodes and its triples (or quads)
    added in a different order."""
    rng = random.Random(seed)
    fresh = {}

    def term(node):
        if isinstance(node, BlankNode):
            if node not in fresh:
                fresh[node] = BlankNode()
            return fresh[node]
        return node

    if isinstance(source, Dataset):
        items = [Quad(term(s), term(p), term(o), term(g)) for s, p, o, g in source]
        rng.shuffle(items)
        copy = Dataset()
    else:
        items = [Triple(term(s), term(p), term(o)) for s, p, o in source]
        rng.shuffle(items)
        copy = Graph()
    copy.addAll(items)
    return copy


def node_with(g, predicate, object):
    """The one subject of ``predicate object`` in g."""
    (triple,) = g.match(predicate=NamedNode(EX + predicate), object=object)
    return triple.subject


# Bail-out stages 1 to 5 -----------------------------------------------------


def test_stage_1_triple_count():
    a = graph(":a :p :b .")
    b = graph(":a :p :b . :a :p :c .")
    assert bail_stage(a, b) == 1
    assert not isomorphic(a, b)


def test_stage_2_ground_triples():
    a = graph(":a :p :b .")
    b = graph(":a :p :c .")
    assert bail_stage(a, b) == 2
    assert not isomorphic(a, b)


def test_stage_3_placeholder_triples():
    a = graph("_:x :p :a .")
    b = graph("_:x :q :a .")
    assert bail_stage(a, b) == 3
    assert not isomorphic(a, b)


def test_stage_4_molecule_signatures():
    # Same placeholder multiset, but two molecules of two nodes against one
    # molecule of three.
    a = graph("_:a :p _:b . _:c :p _:d .")
    b = graph("_:a :p _:b . _:b :p _:c .")
    assert bail_stage(a, b) == 4
    assert not isomorphic(a, b)


def test_stage_5_canonical_forms():
    # One molecule of three nodes with three :p edges on each side; only the
    # shape of the edges differs.
    a = graph("_:a :p _:b . _:b :p _:c . _:c :p _:a .")
    b = graph("_:a :p _:b . _:a :p _:c . _:b :p _:c .")
    assert bail_stage(a, b) == 5
    assert not isomorphic(a, b)


def test_isomorphic_pair_passes_every_stage():
    a = graph("_:a :p _:b . _:b :p _:c . _:c :p _:a . :s :q _:a .")
    b = relabelled_and_shuffled(a)
    assert bail_stage(a, b) is None
    assert isomorphic(a, b)


def test_isomorphic_is_symmetric_and_reflexive():
    a = graph("_:a :p _:b . :s :q _:a .")
    b = relabelled_and_shuffled(a)
    assert isomorphic(a, a)
    assert isomorphic(a, b)
    assert isomorphic(b, a)


def test_empty_graphs_are_isomorphic():
    assert isomorphic(Graph(), Graph())
    assert canonical_labels(Graph()) == {}


# Molecules ------------------------------------------------------------------


def molecule_sizes(g):
    return sorted(len(m.nodes) for m in molecules(statements(g)))


def test_molecules_two_disconnected_groups():
    g = graph("_:a :p :x . _:b :p :x .")
    assert molecule_sizes(g) == [1, 1]


def test_molecules_joined_by_blank_blank_triple():
    g = graph("_:a :p :x . _:b :p :x . _:a :q _:b .")
    assert molecule_sizes(g) == [2]


def test_molecules_include_every_touching_triple():
    g = graph("_:a :p :x . :s :q _:a . :s :q :x .")
    (molecule,) = molecules(statements(g))
    assert len(molecule.statements) == 2


def test_molecules_shared_across_dataset_graphs():
    a, b = BlankNode(), BlankNode()
    p = NamedNode(EX + "p")
    g1, g2 = NamedNode(EX + "g1"), NamedNode(EX + "g2")
    dataset = Dataset()
    dataset.add(Quad(a, p, NamedNode(EX + "x"), g1))
    dataset.add(Quad(a, p, b, g2))
    dataset.add(Quad(b, p, NamedNode(EX + "y"), None))
    (molecule,) = molecules(statements(dataset))
    assert set(molecule.nodes) == {a, b}
    assert len(molecule.statements) == 3


def test_dataset_graph_name_is_part_of_the_signature():
    p = NamedNode(EX + "p")
    x = NamedNode(EX + "x")
    one, two = Dataset(), Dataset()
    one.add(Quad(BlankNode(), p, x, NamedNode(EX + "g1")))
    two.add(Quad(BlankNode(), p, x, NamedNode(EX + "g2")))
    assert not isomorphic(one, two)
    assert isomorphic(one, relabelled_and_shuffled(one))


def test_blank_node_as_graph_name():
    p = NamedNode(EX + "p")
    x = NamedNode(EX + "x")
    one = Dataset()
    name = BlankNode()
    one.add(Quad(name, p, x, None))
    one.add(Quad(NamedNode(EX + "s"), p, x, name))
    two = relabelled_and_shuffled(one)
    assert isomorphic(one, two)
    labels_one, labels_two = canonical_labels(one), canonical_labels(two)
    assert set(labels_one.values()) == set(labels_two.values())


def empty_named_graph_dataset(name):
    """A dataset whose only content is one empty graph called ``name``."""
    dataset = Dataset()
    dataset.add_graph(Graph(), named=name)
    return dataset


def test_empty_named_graph_is_part_of_the_dataset():
    name = NamedNode(EX + "g1")
    assert not isomorphic(empty_named_graph_dataset(name), Dataset())
    assert isomorphic(empty_named_graph_dataset(name), empty_named_graph_dataset(name))


def test_empty_graphs_under_different_names_differ():
    one = empty_named_graph_dataset(NamedNode(EX + "g1"))
    two = empty_named_graph_dataset(NamedNode(EX + "g2"))
    assert not isomorphic(one, two)


def test_empty_graph_with_a_blank_name_is_labelled():
    first, second = BlankNode(), BlankNode()
    one, two = empty_named_graph_dataset(first), empty_named_graph_dataset(second)
    assert isomorphic(one, two)
    labels_one, labels_two = canonical_labels(one), canonical_labels(two)
    assert list(labels_one) == [first]
    assert set(labels_one.values()) == set(labels_two.values())


def test_empty_graph_name_shared_with_a_subject_ties_them_together():
    p, x = NamedNode(EX + "p"), NamedNode(EX + "x")
    shared = BlankNode()
    one = empty_named_graph_dataset(shared)
    one.add(Quad(shared, p, x, None))
    # The same content with a fresh blank node is still the same dataset.
    other = BlankNode()
    copy = empty_named_graph_dataset(other)
    copy.add(Quad(other, p, x, None))
    assert isomorphic(one, copy)
    # Two separate blank nodes are not: the empty graph's name is no longer
    # in the same molecule as the subject.
    two = empty_named_graph_dataset(BlankNode())
    two.add(Quad(BlankNode(), p, x, None))
    assert not isomorphic(one, two)


def test_stable_nquads_cannot_write_an_empty_named_graph():
    # N-Quads has no syntax for an empty named graph, so stable output drops
    # a graph that comparison counts; see "Datasets" in the design note.
    from io import StringIO

    from pymantic.serializers import serialize_nquads

    out = StringIO()
    serialize_nquads(empty_named_graph_dataset(NamedNode(EX + "g1")), out, stable=True)
    assert out.getvalue() == ""


# Refinement -----------------------------------------------------------------


def assert_same_label(turtle, predicate, object):
    """The node identified by ``predicate object`` must get the same label in
    the graph and in a relabelled, shuffled copy."""
    a = graph(turtle)
    b = relabelled_and_shuffled(a)
    la, lb = canonical_labels(a), canonical_labels(b)
    assert la[node_with(a, predicate, object)] == lb[node_with(b, predicate, object)]
    assert len(set(la.values())) == len(la)
    return la, lb


def test_refinement_distinguishes_by_predicate():
    x = NamedNode(EX + "x")
    turtle = "_:r :h _:a, _:b . _:a :p :x . _:b :q :x ."
    la, lb = assert_same_label(turtle, "p", x)
    assert_same_label(turtle, "q", x)


def test_refinement_distinguishes_by_role():
    # _:a is subject and object of one triple; _:b and _:c are each subject
    # of one and object of another.
    turtle = "_:r :h _:a, _:b, _:c . _:a :p _:a . _:b :p _:c . _:c :p _:b ."
    a = graph(turtle)
    b = relabelled_and_shuffled(a)
    la, lb = canonical_labels(a), canonical_labels(b)
    (self_loop_a,) = [t.subject for t in a if t.subject is t.object]
    (self_loop_b,) = [t.subject for t in b if t.subject is t.object]
    assert la[self_loop_a] == lb[self_loop_b]
    assert isomorphic(a, b)


def test_role_alone_separates_non_isomorphic_graphs():
    both = graph("_:r :h _:a, _:b . _:a :p _:a . _:b :p _:b .")
    swapped = graph("_:r :h _:a, _:b . _:a :p _:b . _:b :p _:a .")
    assert bail_stage(both, swapped) == 5
    assert not isomorphic(both, swapped)


def test_refinement_distinguishes_by_attachment():
    turtle = '_:r :h _:a, _:b . _:a :v "1" . _:b :v "2" .'
    assert_same_label(turtle, "v", graph('_:x :v "1" .').match().__next__().object)
    a = graph(turtle)
    b = graph('_:r :h _:a, _:b . _:a :v "1" . _:b :v "3" .')
    assert not isomorphic(a, b)


def undirected_square_with_literal():
    """A 4-cycle with edges in both directions and a literal on one corner.
    The two neighbours of that corner are symmetric, so refinement alone
    cannot separate them."""
    return graph(
        "_:a :p _:b . _:b :p _:a ."
        "_:b :p _:c . _:c :p _:b ."
        "_:c :p _:d . _:d :p _:c ."
        "_:d :p _:a . _:a :p _:d ."
        '_:a :v "corner" .'
    )


def test_refinement_alone_leaves_symmetric_nodes_together():
    (molecule,) = molecules(statements(undirected_square_with_literal()))
    codes = refine(molecule, {node: 0 for node in molecule.nodes})
    classes = {}
    for node, code in codes.items():
        classes.setdefault(code, []).append(node)
    assert sorted(len(c) for c in classes.values()) == [1, 1, 2]


def test_individualization_succeeds_on_symmetric_pair():
    a = undirected_square_with_literal()
    b = relabelled_and_shuffled(a, seed=3)
    assert isomorphic(a, b)
    form_a, _ = canonical_form(molecules(statements(a))[0])
    form_b, _ = canonical_form(molecules(statements(b))[0])
    assert form_a == form_b
    assert canonical_labels(a).values() != {}
    assert set(canonical_labels(a).values()) == set(canonical_labels(b).values())


def test_individualization_separates_near_miss():
    a = undirected_square_with_literal()
    # Same square, but the literal's neighbour on one side also has one.
    b = graph(
        "_:a :p _:b . _:b :p _:a ."
        "_:b :p _:c . _:c :p _:b ."
        "_:c :p _:d . _:d :p _:c ."
        "_:d :p _:a . _:a :p _:d ."
        '_:b :v "corner" .'
    )
    assert isomorphic(a, b)  # rotating the square maps _:a to _:b
    c = graph(
        "_:a :p _:b . _:b :p _:a ."
        "_:b :p _:c . _:c :p _:b ."
        "_:c :p _:d . _:d :p _:c ."
        "_:d :p _:b . _:b :p _:d ."
        '_:a :v "corner" .'
    )
    assert not isomorphic(a, c)


# Work budget ----------------------------------------------------------------


def blank_clique(size):
    p = NamedNode(EX + "p")
    nodes = [BlankNode() for _ in range(size)]
    g = Graph()
    for s in nodes:
        for o in nodes:
            g.add(Triple(s, p, o))
    return g


def test_budget_exhaustion_raises_undecidable_quickly():
    g = blank_clique(10)
    started = time.perf_counter()
    with pytest.raises(Undecidable) as info:
        isomorphic(g, relabelled_and_shuffled(g))
    assert time.perf_counter() - started < 1.0
    assert "10 blank nodes" in str(info.value)
    assert EX + "p" in str(info.value)
    with pytest.raises(Undecidable):
        canonical_labels(g)


def test_budget_is_per_molecule():
    # A graph that is mostly ordinary must still be undecidable if one of
    # its molecules is.
    g = blank_clique(10)
    g.add(Triple(NamedNode(EX + "s"), NamedNode(EX + "p"), BlankNode()))
    with pytest.raises(Undecidable):
        canonical_labels(g)


def blank_ring_lattice(size, degree=4):
    """Every node linked both ways to its ``degree // 2`` nearest neighbours
    on a ring: perfectly regular, so no content distinguishes any node."""
    p = NamedNode(EX + "knows")
    nodes = [BlankNode() for _ in range(size)]
    g = Graph()
    for i in range(size):
        for j in range(1, degree // 2 + 1):
            g.add(Triple(nodes[i], p, nodes[(i + j) % size]))
            g.add(Triple(nodes[(i + j) % size], p, nodes[i]))
    return g


def test_symmetric_but_polynomial_molecules_are_within_budget():
    # A ring of blank nodes needs about n cubed over two node visits (n
    # choices at the top, n/2 rounds each) and must succeed: it is slow, not
    # poison.
    for size in (20, 60):
        g = blank_ring_lattice(size)
        assert len(set(canonical_labels(g).values())) == size
        assert isomorphic(g, relabelled_and_shuffled(g))


def test_budget_bounds_time_by_molecule_size():
    # The budget is a polynomial in the molecule's size, so a small poison
    # molecule cannot consume much time whatever its shape: the 10-node
    # clique trips in milliseconds, and a 20-node one still within a second.
    for size, limit in ((10, 0.1), (20, 1.0)):
        g = blank_clique(size)
        started = time.perf_counter()
        with pytest.raises(Undecidable):
            canonical_labels(g)
        assert time.perf_counter() - started < limit


def test_long_chain_of_identical_blank_members_is_within_budget():
    # An RDF list of 300 identical anonymous members refines one cell per
    # round from the rdf:nil end, so it needs about 300 rounds over a
    # 600-node molecule. That is a document, not a poison graph, and must
    # stay well inside the budget.
    first = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#first")
    rest = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#rest")
    nil = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#nil")
    p = NamedNode(EX + "p")
    g = Graph()
    cells = [BlankNode() for _ in range(300)]
    for i, cell in enumerate(cells):
        item = BlankNode()
        g.add(Triple(cell, first, item))
        g.add(Triple(item, p, Literal("same")))
        g.add(Triple(cell, rest, cells[i + 1] if i + 1 < len(cells) else nil))
    g.add(Triple(NamedNode(EX + "s"), p, cells[0]))
    labels = canonical_labels(g)
    assert len(set(labels.values())) == 600
    assert isomorphic(g, relabelled_and_shuffled(g))


def test_work_limit_can_only_lower_the_budget():
    # A 40-node ring needs tens of thousands of node visits; a caller can
    # refuse to spend them.
    g = blank_ring_lattice(40, degree=2)
    assert len(set(canonical_labels(g).values())) == 40
    with pytest.raises(Undecidable):
        canonical_labels(g, work_limit=1000)
    with pytest.raises(Undecidable):
        isomorphic(g, relabelled_and_shuffled(g), work_limit=1000)
    # A huge limit does not lift the built-in allowance: the clique still
    # trips quickly.
    started = time.perf_counter()
    with pytest.raises(Undecidable):
        canonical_labels(blank_clique(10), work_limit=10**12)
    assert time.perf_counter() - started < 0.5


# Canonical labels -----------------------------------------------------------


SHAPES = """
:Shape :property _:p1, _:p2, _:p3 .
_:p1 :path :name ; :minCount 1 ; :in _:l1 .
_:l1 :first "a" ; :rest _:l2 .
_:l2 :first "b" ; :rest :nil .
_:p2 :path :age ; :datatype :integer .
_:p3 :path :age ; :maxCount 5 .
:Other :property _:p4 .
_:p4 :path :name ; :minCount 1 .
"""


def test_canonical_labels_are_stable_under_relabelling_and_shuffling():
    a = graph(SHAPES)
    for seed in range(5):
        b = relabelled_and_shuffled(a, seed=seed)
        la, lb = canonical_labels(a), canonical_labels(b)
        assert sorted(la.values()) == sorted(lb.values())
        integer = NamedNode(EX + "integer")
        assert (
            la[node_with(a, "datatype", integer)]
            == lb[node_with(b, "datatype", integer)]
        )


def test_canonical_labels_cover_every_blank_node_once():
    g = graph(SHAPES)
    labels = canonical_labels(g)
    blanks = {t.subject for t in g if isinstance(t.subject, BlankNode)}
    blanks |= {t.object for t in g if isinstance(t.object, BlankNode)}
    assert set(labels) == blanks
    assert len(set(labels.values())) == len(labels)


def test_canonical_labels_are_valid_blank_node_labels():
    for label in canonical_labels(graph(SHAPES)).values():
        assert label[0].isalpha()
        assert all(c.isalnum() or c == "_" for c in label)


def test_identical_molecules_get_interchangeable_deterministic_labels():
    g = graph(':s :h _:a, _:b . _:a :v "1" . _:b :v "1" .')
    labels = canonical_labels(g)
    assert len(set(labels.values())) == 2
    # The two nodes cannot be told apart, so a relabelled copy gets the same
    # pair of labels, in some order.
    copy = relabelled_and_shuffled(g, seed=7)
    assert set(canonical_labels(copy).values()) == set(labels.values())
    assert canonical_labels(g) == labels


def test_undecidable_names_the_molecule():
    g = blank_clique(10)
    with pytest.raises(Undecidable) as info:
        canonical_labels(g)
    message = str(info.value)
    assert "10 blank nodes" in message
    assert "100 triples" in message
