"""Graph isomorphism and content-derived blank node labels.

This module implements the algorithm described in docs/graph-comparison.rst;
read that note first. The functions here carry the names used there:
:func:`statements` prepares a graph or dataset, :func:`bail_stage` runs the
five comparison stages, :func:`molecules` splits the blank nodes into
connected groups, :func:`refine` is Carroll's hash-code vertex
classification, :func:`individualize` is the backtracking search around it,
and :func:`canonical_form` ties the last two together under a work budget.

The public API is :func:`isomorphic`, :func:`canonical_labels` and
:class:`Undecidable`. :func:`canonical_labels_and_order` exists for the
serializers, which need both a label and a sort key for every blank node.
"""

__all__ = [
    "Undecidable",
    "isomorphic",
    "canonical_labels",
    "canonical_labels_and_order",
]

from collections import Counter
import functools
import hashlib

from pymantic.primitives import XSD_STRING, BlankNode, Literal, NamedNode
from pymantic.serializers import nt_escape

# Work allowed for one molecule of n blank nodes, counted in node visits: a
# refinement round over the molecule costs n, and so does opening a branch.
# The allowance is n * n * (WORK_PER_NODE + n), a polynomial in the size of
# the molecule, so the time a molecule can consume is bounded by its size: a
# small molecule cannot eat much, whatever its shape. Symmetric shapes that
# are honest but slow, cycles and ring lattices, need about n cubed over two
# and fit; a clique needs factorial work and trips at once (see "Work
# budget" in the design note).
WORK_PER_NODE = 64

# Every hash in this module is a 64-bit integer built with a fixed mixing
# function, so canonical forms, and therefore labels and stable output, are
# the same in every process and on every platform. Python's own hash() is
# seeded per process for strings, which would break that.
MASK = (1 << 64) - 1
SELF = 0x9E3779B97F4A7C15  # stands for "the node being coded" in a triple
INDIVIDUAL = 0x2545F4914F6CDD1D  # mixed in when a node is individualized


class Undecidable(Exception):
    """Raised when a molecule exhausts its work budget before reaching a
    canonical form. The message names the molecule by size and attachments."""


def mix(*parts):
    """Deterministic 64-bit hash of a sequence of integers (FNV-1a over
    whole words). Collisions only merge refinement classes and cost work;
    they never make different molecules compare equal."""
    h = 0xCBF29CE484222325
    for part in parts:
        h = ((h ^ part) * 0x100000001B3) & MASK
    return h


@functools.lru_cache(maxsize=65536)
def term_code(key):
    """Deterministic 64-bit code of an IRI or literal key."""
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def term_key(term):
    """A string that identifies an IRI or literal as an RDF term: two terms
    get the same key exactly when RDF says they are the same term. A
    :class:`~pymantic.primitives.Literal` is already canonical -- it carries
    a datatype whether or not one was written -- so its three fields decide
    the key, written the way N-Triples writes them."""
    if isinstance(term, NamedNode):
        return "<%s>" % term
    if isinstance(term, Literal):
        key = '"' + nt_escape(term.value) + '"'
        if term.language:
            return key + "@" + term.language
        if term.datatype != XSD_STRING:
            return key + "^^<" + term.datatype + ">"
        return key
    raise TypeError("%r is not an RDF term" % (term,))


def statements(graph_or_dataset):
    """The content of a graph or dataset as a list of distinct
    (subject, predicate, object, graph) tuples. IRIs and literals become
    their :func:`term_key`; blank nodes stay as themselves. The graph
    position is "" for a triple and for a quad in the default graph."""
    keys = {}

    def key(term):
        if isinstance(term, BlankNode):
            return term
        try:
            return keys[term]
        except KeyError:
            keys[term] = term_key(term)
            return keys[term]

    # A Dataset yields quads, and so does a Graph filled by the N-Quads
    # parser; a Graph of triples yields triples.
    items = []
    for item in graph_or_dataset:
        graph = "" if len(item) == 3 or item[3] is None else key(item[3])
        items.append((key(item[0]), key(item[1]), key(item[2]), graph))
    return list(dict.fromkeys(items))


def is_ground(statement):
    return not any(isinstance(term, BlankNode) for term in statement)


def placeholder(statement):
    """The statement with every blank node replaced by a placeholder."""
    return tuple("_" if isinstance(term, BlankNode) else term for term in statement)


class Molecule:
    """A maximal set of blank nodes connected by blank-to-blank statements,
    with every statement that touches one of them.

    ``nodes`` and ``statements`` are in first-encounter order. ``incident``
    maps each node to its statements with IRIs and literals replaced by
    their :func:`term_code`, which is what :func:`refine` reads."""

    def __init__(self):
        self.nodes = []
        self.statements = []
        self.incident = {}

    def prepare(self):
        seen = {}
        for statement in self.statements:
            for term in statement:
                if isinstance(term, BlankNode) and term not in seen:
                    seen[term] = None
        self.nodes = list(seen)
        self.incident = {node: [] for node in self.nodes}
        for statement in self.statements:
            coded = tuple(
                term if isinstance(term, BlankNode) else term_code(term)
                for term in statement
            )
            for node in seen.fromkeys(t for t in statement if isinstance(t, BlankNode)):
                self.incident[node].append(coded)

    def attachments(self):
        return sorted(
            {t for s in self.statements for t in s if not isinstance(t, BlankNode)}
        )

    def describe(self):
        attachments = self.attachments()
        shown = ", ".join(attachments[:8])
        if len(attachments) > 8:
            shown += ", ... (%d in all)" % len(attachments)
        return "molecule of %d blank nodes and %d triples with attachments %s" % (
            len(self.nodes),
            len(self.statements),
            shown or "(none)",
        )


def molecules(statements):
    """Split the non-ground statements into molecules, in the order their
    first statement appears."""
    parent = {}

    def find(node):
        while parent[node] is not node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for statement in statements:
        blanks = [term for term in statement if isinstance(term, BlankNode)]
        for node in blanks:
            parent.setdefault(node, node)
        for node in blanks[1:]:
            parent[find(node)] = find(blanks[0])

    by_root = {}
    for statement in statements:
        for term in statement:
            if isinstance(term, BlankNode):
                by_root.setdefault(find(term), Molecule()).statements.append(statement)
                break
    for molecule in by_root.values():
        molecule.prepare()
    return list(by_root.values())


def signature(molecule):
    """Size and placeholder multiset; molecules that can be isomorphic have
    equal signatures."""
    return (
        len(molecule.nodes),
        tuple(sorted(placeholder(s) for s in molecule.statements)),
    )


class Budget:
    """Work allowed for one molecule, in node visits; see WORK_PER_NODE."""

    def __init__(self, molecule, work_limit=None):
        self.molecule = molecule
        size = len(molecule.nodes)
        self.total = size * size * (WORK_PER_NODE + size)
        if work_limit is not None:
            # A caller may tighten the allowance, never loosen it.
            self.total = min(self.total, work_limit)
        self.left = self.total

    def spend(self, units):
        self.left -= units
        if self.left < 0:
            raise Undecidable(
                "%s needs more than %d node visits of refinement"
                % (self.molecule.describe(), self.total)
            )


def refine(molecule, codes, budget=None):
    """Carroll's iterative vertex classification. ``codes`` maps every node
    of the molecule to its current class code; the result maps each node to
    a code that combines its previous code with the multiset of its
    incident statements, iterated until the partition into classes stops
    changing. Nodes with equal codes are in the same class."""
    incident = molecule.incident
    classes = len(set(codes.values()))
    while True:
        if budget is not None:
            budget.spend(len(molecule.nodes))
        new = {}
        for node in molecule.nodes:
            total = 0
            for statement in incident[node]:
                total += mix(
                    *(
                        SELF
                        if term is node
                        else (term if type(term) is int else codes[term])
                        for term in statement
                    )
                )
            new[node] = mix(codes[node], total & MASK)
        new_classes = len(set(new.values()))
        if new_classes == classes:
            return new
        codes, classes = new, new_classes


def labelled_form(molecule, codes):
    """The canonical form for a partition of singletons: nodes are numbered
    in code order and the statements written with those numbers, sorted.
    Returns (form, positions)."""
    ordered = sorted(molecule.nodes, key=codes.__getitem__)
    positions = {node: i for i, node in enumerate(ordered)}
    width = len(str(len(ordered) - 1))
    form = tuple(
        sorted(
            tuple(
                "_:%0*d" % (width, positions[t]) if isinstance(t, BlankNode) else t
                for t in statement
            )
            for statement in molecule.statements
        )
    )
    return form, positions


def twins(molecule, nodes):
    """One representative from each set of ``nodes`` (all in one class)
    that are twins: nodes whose incident statements are identical once the
    node itself is masked. Swapping two twins is an automorphism, so
    individualizing either gives the same canonical form and only one
    branch needs searching. Identical anonymous siblings under a blank node
    are the common case in documents, and without this they cost k! work."""
    representatives = {}
    for node in nodes:
        key = tuple(
            sorted(
                tuple(
                    (2,) if t is node else ((0, t) if type(t) is int else (1, id(t)))
                    for t in statement
                )
                for statement in molecule.incident[node]
            )
        )
        representatives.setdefault(key, node)
    return list(representatives.values())


def individualize(molecule, codes, budget):
    """Depth-first search over individualization choices. Whenever a
    refined partition still has a class of several nodes, the smallest such
    class is picked and each of its nodes is tried as the one to
    individualize. The lexicographically smallest canonical form over all
    leaves wins. Returns (form, positions)."""
    best = None
    pending = [codes]
    while pending:
        codes = refine(molecule, pending.pop(), budget)
        classes = {}
        for node in molecule.nodes:
            classes.setdefault(codes[node], []).append(node)
        if len(classes) == len(molecule.nodes):
            leaf = labelled_form(molecule, codes)
            if best is None or leaf[0] < best[0]:
                best = leaf
            continue
        target = min(
            (nodes for nodes in classes.values() if len(nodes) > 1),
            key=lambda nodes: (len(nodes), codes[nodes[0]]),
        )
        for node in twins(molecule, target):
            budget.spend(len(molecule.nodes))
            split = dict(codes)
            split[node] = mix(codes[node], INDIVIDUAL)
            pending.append(split)
    return best


def canonical_form(molecule, work_limit=None):
    """(form, positions) for a molecule: ``form`` is a sorted tuple of its
    statements with blank nodes replaced by canonical positions, equal for
    isomorphic molecules; ``positions`` maps each node to its position.
    Raises :class:`Undecidable` when the molecule's work budget runs out;
    ``work_limit`` caps that budget in node visits (it cannot raise it)."""
    budget = Budget(molecule, work_limit)
    codes = dict.fromkeys(molecule.nodes, 0)
    return individualize(molecule, codes, budget)


def form_digest(form):
    lines = "\n".join(" ".join(statement) for statement in form)
    return hashlib.blake2b(lines.encode("utf-8"), digest_size=6).hexdigest()


def bail_stage(a, b, work_limit=None):
    """The number of the first stage of the design note that shows the two
    graphs (or datasets) differ, or None when they are isomorphic."""
    statements_a, statements_b = statements(a), statements(b)
    if len(statements_a) != len(statements_b):
        return 1
    ground_a = {s for s in statements_a if is_ground(s)}
    ground_b = {s for s in statements_b if is_ground(s)}
    if ground_a != ground_b:
        return 2
    blank_a = [s for s in statements_a if not is_ground(s)]
    blank_b = [s for s in statements_b if not is_ground(s)]
    if Counter(map(placeholder, blank_a)) != Counter(map(placeholder, blank_b)):
        return 3
    groups_a, groups_b = {}, {}
    for groups, molecule_list in (
        (groups_a, molecules(blank_a)),
        (groups_b, molecules(blank_b)),
    ):
        for molecule in molecule_list:
            groups.setdefault(signature(molecule), []).append(molecule)
    if {k: len(v) for k, v in groups_a.items()} != {
        k: len(v) for k, v in groups_b.items()
    }:
        return 4
    for key, group_a in groups_a.items():
        forms_a = Counter(canonical_form(m, work_limit)[0] for m in group_a)
        forms_b = Counter(canonical_form(m, work_limit)[0] for m in groups_b[key])
        if forms_a != forms_b:
            return 5
    return None


def isomorphic(a, b, work_limit=None):
    """Whether two graphs, or two datasets, are isomorphic: equal up to
    renaming of blank nodes. Raises :class:`Undecidable` if a molecule's
    work budget runs out. ``work_limit`` lowers that budget to at most the
    given number of node visits per molecule; it can never raise it. See
    docs/graph-comparison.rst."""
    return bail_stage(a, b, work_limit) is None


def canonical_labels_and_order(graph_or_dataset, work_limit=None):
    """Returns (labels, order). ``labels`` maps every blank node to its
    canonical label; ``order`` maps it to its rank when molecules are sorted
    by canonical form and nodes within a molecule by position, which is the
    order the stable serializers write sibling blank nodes in.

    A label is ``b`` followed by a 12-hex-digit digest of the molecule's
    canonical form, then ``m<i>`` when several molecules share that digest
    (they are numbered in canonical form order, identical ones in encounter
    order) and ``n<position>`` when the molecule has several nodes. Deriving
    the label from a digest rather than a rank keeps the labels of every
    other molecule unchanged when one molecule is edited."""
    placed = [
        (molecule, *canonical_form(molecule, work_limit))
        for molecule in molecules(statements(graph_or_dataset))
    ]
    by_digest = {}
    for index, (_, form, _) in enumerate(placed):
        by_digest.setdefault(form_digest(form), []).append(index)
    labels = {}
    for digest, indexes in by_digest.items():
        indexes.sort(key=lambda i: placed[i][1])
        for duplicate, index in enumerate(indexes):
            molecule, _, positions = placed[index]
            label = "b" + digest
            if len(indexes) > 1:
                label += "m%d" % duplicate
            for node, position in positions.items():
                if len(molecule.nodes) > 1:
                    labels[node] = label + "n%d" % position
                else:
                    labels[node] = label
    order = {}
    for _, _, positions in sorted(placed, key=lambda p: p[1]):
        for node in sorted(positions, key=positions.__getitem__):
            order[node] = len(order)
    return labels, order


def canonical_labels(graph_or_dataset, work_limit=None):
    """Map every blank node of a graph or dataset to a label derived only
    from its content, so that a relabelled or reordered copy gets the same
    labels. Raises :class:`Undecidable` if a molecule's work budget runs
    out. ``work_limit`` lowers that budget to at most the given number of
    node visits per molecule; it can never raise it. See
    docs/graph-comparison.rst."""
    return canonical_labels_and_order(graph_or_dataset, work_limit)[0]
