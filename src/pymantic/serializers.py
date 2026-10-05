from collections import Counter, OrderedDict
from io import StringIO
import re

from pymantic.util import strips_to_relative_reference


def validate_language(language):
    """Reject language tags that cannot be emitted as an RDF LANGTAG."""
    if not re.fullmatch(r"[A-Za-z]+(?:-[A-Za-z0-9]+)*", language):
        raise ValueError("Invalid RDF language tag")


# Escapes required by canonical N-Triples
# (https://www.w3.org/TR/rdf12-n-triples/#canonical-ntriples): these seven
# characters use ECHAR, the other C0 controls, DEL and code points that are
# not XML 1.1 Chars use \\u with uppercase hex, and everything else is
# written raw.
NT_ECHAR = {
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
    '"': '\\"',
    "\\": "\\\\",
}


# Every character nt_escape changes: those in NT_ECHAR, and as \\u the other
# C0 controls, DEL, surrogates and the non-characters U+FFFE and U+FFFF.
NT_ESCAPED_RE = re.compile('[\x00-\x1f\x7f"\\\\\ud800-\udfff\ufffe\uffff]')


def nt_escape_char(match):
    char = match.group()
    return NT_ECHAR.get(char) or "\\u%04X" % ord(char)


def nt_escape(node_string):
    """Escape a string for canonical N-Triples and N-Quads output."""
    return NT_ESCAPED_RE.sub(nt_escape_char, node_string)


def stable_lines(graph_or_dataset):
    """Return the sorted N-Triples or N-Quads lines of a graph or dataset.

    Blank nodes are named by :func:`pymantic.compare.canonical_labels`, so
    the same content always gives the same lines whatever the labels and
    order it was built with. See :doc:`/graph-comparison`.
    """
    from pymantic.compare import canonical_labels

    labels = canonical_labels(graph_or_dataset)

    def term(node):
        if node.interfaceName == "BlankNode":
            return "_:" + labels[node]
        return node.toNT()

    lines = []
    for item in graph_or_dataset:
        # A quad in the default graph is written as a triple.
        graph = "" if len(item) == 3 or item[3] is None else " " + term(item[3])
        lines.append(f"{term(item[0])} {term(item[1])} {term(item[2])}{graph} .\n")
    return sorted(lines)


def serialize_ntriples(graph, f, stable=False):
    """Serialize some graph to f as ntriples, in graph order. With
    ``stable``, blank nodes get content-derived labels and the lines are
    sorted, so the same graph always produces the same bytes; this raises
    :class:`pymantic.compare.Undecidable` for a graph whose blank nodes
    cannot be told apart within the work budget."""
    if stable:
        f.writelines(stable_lines(graph))
        return
    for triple in graph:
        f.write(str(triple))


def serialize_nquads(dataset, f, stable=False):
    """Serialize some dataset to f as nquads, in dataset order. ``stable``
    works as for :func:`serialize_ntriples`."""
    if stable:
        f.writelines(stable_lines(dataset))
        return
    for quad in dataset:
        f.write(str(quad))


def default_bnode_name_generator():
    i = 0
    while True:
        yield "_:b" + str(i)
        i += 1


# Character classes from the Turtle 1.1 grammar
# (https://www.w3.org/TR/turtle/#sec-grammar-grammar), used to check that an
# escaped local name is a valid PN_LOCAL.
PN_CHARS_BASE = (
    "A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf"
    "\ufdf0-\ufffd\U00010000-\U000effff"
)
PN_CHARS_U = PN_CHARS_BASE + "_"
PN_CHARS = PN_CHARS_U + "\\-0-9\u00b7\u0300-\u036f\u203f-\u2040"
PN_PREFIX_RE = re.compile(
    "[" + PN_CHARS_BASE + "](?:[" + PN_CHARS + ".]*[" + PN_CHARS + "])?"
)
TURTLE_NATIVE_LITERALS = {
    "http://www.w3.org/2001/XMLSchema#" + datatype: re.compile(pattern)
    for datatype, pattern in {
        "integer": r"[+-]?[0-9]+",
        "decimal": r"[+-]?[0-9]*\.[0-9]+",
        "double": r"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)[eE][+-]?[0-9]+",
        "boolean": r"true|false",
    }.items()
}
PN_LOCAL_ESC_CHARS = "_~.-!$&'()*+,;=/?#@%"
PLX = "(?:%[0-9A-Fa-f]{2}|\\\\[" + re.escape(PN_LOCAL_ESC_CHARS) + "])"
PN_LOCAL_RE = re.compile(
    "(?:[" + PN_CHARS_U + ":0-9]|" + PLX + ")"
    "(?:(?:[" + PN_CHARS + ".:]|" + PLX + ")*(?:[" + PN_CHARS + ":]|" + PLX + "))?"
)


def escape_prefix_local(name):
    """Escape the local part of a prefixed name (``prefix:local``) so it is a
    valid Turtle PN_LOCAL. Returns None when the local part cannot be expressed
    as a prefixed name even with escapes, in which case the caller should fall
    back to the full <IRI> form."""
    prefix, colon, local = name.partition(":")
    if prefix and not PN_PREFIX_RE.fullmatch(prefix):
        raise ValueError("Invalid Turtle prefix name")
    escaped = ""
    last = len(local) - 1
    for i, char in enumerate(local):
        # "_" and "-" are plain PN_CHARS, and "." is allowed inside a local
        # name, so only escape them where the grammar forbids them raw.
        if char == "_" or (char == "-" and i != 0) or (char == "." and 0 < i < last):
            escaped += char
        elif char in PN_LOCAL_ESC_CHARS:
            escaped += "\\" + char
        else:
            escaped += char
    if escaped and not PN_LOCAL_RE.fullmatch(escaped):
        return None
    return "".join((prefix, colon, escaped))


# Characters the Turtle and N-Triples IRIREF production forbids raw inside
# < and >: U+0000-U+0020 and <>"{}|^`\ . Everything else, including
# non-ASCII, is legal.
IRIREF_FORBIDDEN = set(map(chr, range(0x21))) | set('<>"{}|^`\\')


def iri_escape(iri):
    """Escape an IRI for writing between < and > in Turtle, N-Triples or N-Quads.

    The characters the IRIREF production forbids are percent-encoded as
    UTF-8 bytes; everything else, including % and non-ASCII, is written as
    it is, so two valid IRIs never produce the same text.

    Percent-encoding rather than UCHAR escapes, because Turtle forbids
    those characters in an IRI even when escaped. A term holding one is not
    a valid IRI to begin with, and is written as the valid IRI its
    percent-encoding gives.
    """
    if IRIREF_FORBIDDEN.isdisjoint(iri):
        return iri
    return "".join(
        (
            "".join("%%%02X" % byte for byte in char.encode("utf-8"))
            if char in IRIREF_FORBIDDEN
            else char
        )
        for char in iri
    )


def turtle_string_escapes():
    """Return the :meth:`str.translate` table for Turtle string literals.

    It maps each character with an ECHAR escape to that escape, except the
    apostrophe, which needs none inside the double-quoted strings
    :func:`turtle_string_escape` writes.
    """
    from pymantic.util import ECHAR_MAP

    return {ord(char): escape for char, escape in ECHAR_MAP.items() if char != "'"}


TURTLE_STRING_ESCAPES = turtle_string_escapes()


def turtle_string_escape(string):
    """Escape a string appropriately for output in turtle form."""
    # Single pass, so a backslash inserted by one escape is never escaped
    # again.
    return '"' + string.translate(TURTLE_STRING_ESCAPES) + '"'


def turtle_repr(
    node, profile, name_map, bnode_name_maker, base=None, used_prefixes=None
):
    """Turn a node in an RDF graph into its turtle representation. When
    ``used_prefixes`` is a set, the prefix of every prefixed name written is
    added to it; an IRI that falls back to ``<...>`` adds nothing."""
    if node.interfaceName == "NamedNode":
        name = profile.prefixes.shrink(node)
        if name != node:
            name = escape_prefix_local(name)
        if name is None or name == node:
            iri = str(node)
            if base and strips_to_relative_reference(base, iri):
                iri = ("#" if base.endswith("#") else "") + iri[len(base) :]
            name = f"<{iri_escape(iri)}>"
        elif used_prefixes is not None:
            used_prefixes.add(name.partition(":")[0])
    elif node.interfaceName == "BlankNode":
        if node in name_map:
            name = name_map[node]
        else:
            name = next(bnode_name_maker)
            name_map[node] = name
    elif node.interfaceName == "Literal":
        # A document may bind the xsd prefix to anything, so the datatype is
        # compared with the fixed IRI, never with the profile's xsd:string.
        from pymantic.primitives import XSD_STRING

        if node.language:
            # A language-tagged string is written with its tag alone; its
            # rdf:langString datatype is implicit.
            validate_language(node.language)
            name = turtle_string_escape(node.value) + "@" + node.language
        elif node.datatype == XSD_STRING:
            # Simple string.
            name = turtle_string_escape(node.value)
        elif node.datatype in TURTLE_NATIVE_LITERALS and TURTLE_NATIVE_LITERALS[
            node.datatype
        ].fullmatch(node.value):
            name = node.value
        else:
            # Unrecognized data-type.
            name = turtle_string_escape(node.value)
            name += "^^" + turtle_repr(
                node.datatype, profile, None, None, used_prefixes=used_prefixes
            )
    return name


def turtle_sorted_names(nodes, name_maker, tie_break=None):
    """Sort a list of nodes in a graph by turtle name. ``tie_break`` maps a
    node to a secondary key for nodes with the same name, such as two list
    heads that are both written ``(1)``."""
    pairs = ((name_maker(node), node) for node in nodes)
    if tie_break is None:
        return sorted(pairs, key=lambda p: p[0])
    return sorted(pairs, key=lambda p: (p[0], tie_break(p[1])))


# Deepest [ ... ] and ( ... ) nesting Turtle writes. Planning and rendering an
# inline blank node or a collection each recurse once per level (about three
# frames per level when rendering), and pymantic's own Turtle parser recurses
# about six frames per level and fails near 160 levels under Python's default
# limit of 1000, so a node or list head past this depth keeps its label and
# its own block. Measured, not guessed: 32 levels cost about 100 frames to
# write and 200 to read back.
MAX_INLINE_DEPTH = 32

RDF_FIRST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#first"
RDF_REST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"
RDF_NIL = "http://www.w3.org/1999/02/22-rdf-syntax-ns#nil"


def list_cell_shape(graph, node):
    """(first, rest, has_other_predicates) if node looks like an RDF list
    cell: a blank node with exactly one rdf:first and one rdf:rest."""
    if getattr(node, "interfaceName", None) != "BlankNode":
        return None
    firsts, rests, others = [], [], False
    for triple in graph.match(subject=node):
        if triple.predicate == RDF_FIRST:
            firsts.append(triple.object)
        elif triple.predicate == RDF_REST:
            rests.append(triple.object)
        else:
            others = True
    if len(firsts) != 1 or len(rests) != 1:
        return None
    return firsts[0], rests[0], others


def plan_collections(graph, references=None):
    """Decide which blank nodes to write with Turtle's ( ... ) syntax.

    Returns (inline, as_subject, consumed). ``inline`` maps a list head that
    is the object of exactly one triple and has no other predicates to its
    members; ``as_subject`` maps a list head that is the object of no triple
    but has other predicates to its members, for ``( ... ) p o .``
    statements; ``consumed`` holds every list cell whose rdf:first/rdf:rest
    triples the collection syntax will express, so they are not written as
    subjects of their own. A node only qualifies when the whole chain from it
    to rdf:nil is made of blank nodes with exactly one rdf:first, exactly one
    rdf:rest, nothing else, and (past the head) exactly one reference; any
    other shape is written as ordinary triples so no information is lost."""
    if references is None:
        references = Counter(triple.object for triple in graph)
    # A node that is not a subject has no rdf:first, so it is no cell.
    shapes = {node: list_cell_shape(graph, node) for node in graph.subjects()}

    inline, as_subject, consumed = {}, {}, set()
    for node in shapes:
        shape = shapes[node]
        if shape is None:
            continue
        _, _, has_others = shape
        if references[node] == 1:
            (reference,) = graph.match(object=node)
            if reference.predicate == RDF_REST and shapes.get(reference.subject):
                # A cell inside another chain; its head decides.
                continue
            if has_others:
                continue
            target = inline
        elif references[node] == 0 and has_others:
            target = as_subject
        else:
            continue
        members, cells = [], []
        current = node
        while current != RDF_NIL:
            shape = shapes.get(current)
            if shape is None or current in cells:
                break
            first, rest, has_others = shape
            if current is not node and (references[current] != 1 or has_others):
                break
            cells.append(current)
            members.append(first)
            current = rest
        else:
            target[node] = members
            consumed.update(cells if target is inline else cells[1:])
    return inline, as_subject, consumed


def list_cells(graph, head):
    """Yield the cells of a list that :func:`plan_collections` accepted.

    The walk starts at ``head`` and follows rdf:rest to rdf:nil.
    """
    node = head
    while node != RDF_NIL:
        yield node
        (rest,) = graph.match(subject=node, predicate=RDF_REST)
        node = rest.object


def inline_candidates(graph, inline, as_subject, consumed, references):
    """Blank nodes that may be written as [ ... ]: the object of exactly one
    triple, no part in a collection (``inline``, ``as_subject`` and
    ``consumed`` are from :func:`plan_collections`), and no rdf:first or
    rdf:rest of their own. ``references`` counts the triples each node is
    the object of."""
    candidates = set()
    for node, count in references.items():
        if count != 1 or getattr(node, "interfaceName", None) != "BlankNode":
            continue
        if node in inline or node in as_subject or node in consumed:
            continue
        if any(t.predicate in (RDF_FIRST, RDF_REST) for t in graph.match(subject=node)):
            continue
        candidates.add(node)
    return candidates


class _InlinePlanner:
    """Walks one graph from its subjects to decide what
    :func:`plan_inline_blank_nodes` returns.

    The walk is recursive per nesting level and shares what it has already
    decided across every subject it starts from, so this object holds that
    state for the length of one plan."""

    def __init__(self, graph, inline, as_subject, candidates):
        self.graph = graph
        self.inline = inline
        self.as_subject = as_subject
        self.candidates = candidates
        self.decided = set()
        self.inlined = set()
        self.heads_seen = set()
        self.labelled_heads = set()
        # Candidates and list heads met past MAX_INLINE_DEPTH; each becomes a
        # labelled subject once the walk that met it has unwound, so the stack
        # never grows with the length of a chain.
        self.too_deep = []

    def visit(self, node, depth):
        if node in self.inline:
            # A list containing itself is only written once.
            if node in self.heads_seen:
                return
            if depth > MAX_INLINE_DEPTH:
                self.too_deep.append(node)
                return
            self.heads_seen.add(node)
            for member in self.inline[node]:
                self.visit(member, depth + 1)
        elif node in self.candidates and node not in self.decided:
            if depth > MAX_INLINE_DEPTH:
                self.too_deep.append(node)
                return
            self.decided.add(node)
            self.inlined.add(node)
            self.walk(node, depth)

    def walk(self, subject, depth):
        if subject in self.as_subject:
            # The "(" that opens subject's own collection is one level of
            # nesting in its own right, on top of the depth subject itself
            # was reached at, so members are one level deeper than an
            # ordinary predicate's objects below.
            for member in self.as_subject[subject]:
                self.visit(member, depth + 2)
        for triple in self.graph.match(subject=subject):
            if subject in self.as_subject and triple.predicate in (RDF_FIRST, RDF_REST):
                continue
            self.visit(triple.object, depth + 1)

    def walk_as_subject(self, node):
        pending = [node]
        while pending:
            subject = pending.pop()
            if subject in self.decided:
                continue
            self.decided.add(subject)
            if subject in self.inline:
                self.labelled_heads.add(subject)
                for cell in list_cells(self.graph, subject):
                    self.walk(cell, 0)
            else:
                self.walk(subject, 0)
            pending.extend(self.too_deep)
            self.too_deep.clear()


def plan_inline_blank_nodes(
    graph, inline, as_subject, consumed, rank, references, blank_nodes=True
):
    """Decide which blank nodes to write with Turtle's [ ... ] syntax, and
    which collections are nested too deep to write with ( ... ).

    A blank node qualifies when it is the object of exactly one triple, takes
    no part in a collection (``inline``, ``as_subject`` and ``consumed`` are
    from :func:`plan_collections`) and has no rdf:first or rdf:rest of its
    own. It is written where its one reference is, so that reference must
    itself be written: walking the objects of every other subject, through
    collections, claims each qualifying node the walk meets and then walks
    on from it. A qualifying node the walk never reaches is in a cycle whose
    members are referenced only from within the cycle. The lowest-ranked
    such node keeps its label and is written as a subject, and the walk
    resumes from it so the rest of the cycle is inlined beneath it; ``rank``
    is the canonical blank node order, which makes that choice stable.
    ``references`` counts the triples each node is the object of.

    Each [ and each ( counts one level of depth. A qualifying node or an
    ``inline`` list head the walk meets more than ``MAX_INLINE_DEPTH`` levels
    down likewise keeps its label, and the walk resumes from it at depth
    zero; such a head and its cells are written as ordinary subjects with
    their rdf:first and rdf:rest triples. With ``blank_nodes`` False no
    blank node is inlined and only collection depth is planned, as default
    (non-stable) output needs. Returns (nodes to inline, list heads to write
    with labels)."""
    candidates = (
        inline_candidates(graph, inline, as_subject, consumed, references)
        if blank_nodes
        else set()
    )
    planner = _InlinePlanner(graph, inline, as_subject, candidates)
    for subject in graph.subjects():
        if subject not in candidates and subject not in consumed:
            planner.walk_as_subject(subject)
    for node in sorted(candidates, key=rank):
        if node not in planner.decided:
            planner.walk_as_subject(node)
    return planner.inlined, planner.labelled_heads


# Turtle layout. A subject block lines its predicates up after the subject
# while the subject is at most MAX_ALIGNED_SUBJECT columns wide; a wider or
# multi-line subject goes on a line of its own and its predicates are
# indented INDENT. A multi-line [ ... ] or ( ... ) puts its contents INDENT
# columns in from the line it opens on and its closing bracket back at that
# line's indentation, so indentation grows with nesting depth alone, never
# with the length of the names or literals written before it.
MAX_ALIGNED_SUBJECT = 40
INDENT = 4


def indented(text, column):
    """Shift the continuation lines of a multi-line object, which carry their
    own indentation relative to the line it starts on, to that line's
    indentation."""
    return text.replace("\n", "\n" + " " * column)


def object_list(object_names, indent, column):
    """The objects of one predicate, written after it on a line indented
    ``indent``. One-line objects go one per line at ``column``; if any object
    spans lines they are joined with ", " instead, so each opens where the
    one before it closed and every body sits INDENT in from ``indent``."""
    if any("\n" in name for name in object_names):
        return ", ".join(indented(name, indent) for name in object_names)
    return (",\n" + " " * column).join(object_names)


class _TurtleWriter:
    """Writes one graph to a stream as Turtle.

    The parts of the output share state: blank node labels are handed out
    as nodes are first named, and an inline collection is written once, at
    its one reference, after which it is only named. This object holds that
    state for the length of one serialization."""

    def __init__(self, graph, f, base, profile, bnode_name_generator, stable):
        self.graph = graph
        self.f = f
        self.base = base
        self.profile = profile
        self.stable = stable
        self.out = f
        self.used_prefixes = None
        self.name_map = OrderedDict()
        # Every term's written name, so a term named again, such as a
        # predicate on many subjects, is not shrunk and escaped again.
        self.names = {}
        self.bnode_name_maker = bnode_name_generator()
        self.blank_order = {}
        if stable:
            from pymantic.compare import canonical_labels_and_order

            # Stable output declares only the prefixes it uses, which are
            # not known until the statements are written, so those go to a
            # buffer first.
            self.out = StringIO()
            self.used_prefixes = set()
            # Blank nodes take their canonical labels, and blank_order ranks
            # them for sorting.
            labels, self.blank_order = canonical_labels_and_order(graph)
            self.name_map.update((node, "_:" + label) for node, label in labels.items())
        # How many triples have each node as their object, which both
        # planners need; counted once here.
        references = Counter(triple.object for triple in graph)
        self.inline, self.as_subject, self.consumed = plan_collections(
            graph, references
        )
        self.inlined, labelled_heads = plan_inline_blank_nodes(
            graph,
            self.inline,
            self.as_subject,
            self.consumed,
            self.blank_rank,
            references,
            blank_nodes=stable,
        )
        # A list nested past MAX_INLINE_DEPTH is written as rdf:first/rdf:rest
        # triples from a labelled head, so its cells are subjects again.
        for head in labelled_heads:
            del self.inline[head]
            self.consumed.difference_update(list_cells(graph, head))
        self.rendered = set()

    def write(self):
        if not self.stable:
            self.write_directives()

        subjects = [
            s
            for s in self.graph.subjects()
            if s not in self.consumed and s not in self.inlined
        ]
        tie_break = self.blank_rank if self.stable else None
        for subject_name, subject in turtle_sorted_names(
            subjects, self.subject_repr, tie_break
        ):
            skip = (RDF_FIRST, RDF_REST) if subject in self.as_subject else ()
            self.write_block(subject_name, self.block_predicates(subject, skip))

        # A list whose only reference is from inside itself was never reached
        # from a subject block; write its cells as ordinary triples.
        heads = sorted(self.inline, key=self.blank_rank) if self.stable else self.inline
        for head in heads:
            if head in self.rendered:
                continue
            self.rendered.add(head)
            for node in list_cells(self.graph, head):
                self.write_block(self.name(node), self.block_predicates(node))

        if self.stable:
            self.write_directives(self.used_prefixes)
            self.f.write(self.out.getvalue())

    def write_directives(self, used=None):
        if self.base is not None:
            self.f.write("@base <" + iri_escape(self.base) + "> .\n")
        for prefix, iri in self.profile.prefixes.items():
            if prefix and not PN_PREFIX_RE.fullmatch(prefix):
                raise ValueError("Invalid Turtle prefix name")
            if used is None or prefix in used:
                self.f.write("@prefix " + prefix + ": <" + iri_escape(iri) + "> .\n")

    def name(self, node):
        name = self.names.get(node)
        if name is None:
            name = self.names[node] = turtle_repr(
                node,
                self.profile,
                self.name_map,
                self.bnode_name_maker,
                self.base,
                used_prefixes=self.used_prefixes,
            )
        return name

    def blank_rank(self, node):
        return self.blank_order.get(node, -1)

    def object_key(self, node):
        if node.interfaceName == "BlankNode":
            return (1, self.blank_order[node], "")
        return (0, 0, self.name(node))

    def collection_repr(self, members):
        names = [self.object_repr(member) for member in members]
        if not any("\n" in name for name in names):
            return "(" + " ".join(names) + ")"
        # Some member spans lines, so every member gets a line of its own.
        return (
            "(\n"
            + "".join(" " * INDENT + indented(name, INDENT) + "\n" for name in names)
            + ")"
        )

    def inline_repr(self, node):
        predicates = self.block_predicates(node)
        if not predicates:
            return "[]"
        if len(predicates) == 1 and len(predicates[0][1]) == 1:
            predicate_name, (object_name,) = predicates[0]
            if "\n" not in object_name:
                return "[ " + predicate_name + " " + object_name + " ]"
        # One predicate per line, INDENT in; one-line later objects each on
        # a line of their own, INDENT further in.
        lines = [
            " " * INDENT
            + predicate_name
            + " "
            + object_list(object_names, INDENT, 2 * INDENT)
            for predicate_name, object_names in predicates
        ]
        return "[\n" + " ;\n".join(lines) + "\n]"

    def object_repr(self, node):
        # An inline head is written where its one reference is; once written
        # it is only ever named again, which is what keeps a list that
        # contains itself from recursing forever.
        if node in self.inline and node not in self.rendered:
            self.rendered.add(node)
            return self.collection_repr(self.inline[node])
        if node in self.inlined:
            return self.inline_repr(node)
        return self.name(node)

    def subject_repr(self, node):
        if node in self.as_subject:
            return self.collection_repr(self.as_subject[node])
        return self.name(node)

    def block_predicates(self, subject, skip=()):
        # Objects keep the graph's order for their predicate. A term written
        # in both literal forms is one triple in the graph, so no dedup is
        # needed here. Blank nodes are never deduplicated: two distinct
        # blank nodes are two RDF terms even when both are written as [].
        objects_by_predicate = {}
        for triple in self.graph.match(subject=subject):
            if triple.predicate not in skip:
                group = objects_by_predicate.get(triple.predicate)
                if group is None:
                    group = objects_by_predicate[triple.predicate] = []
                group.append(triple.object)
        blocks = []
        for predicate_name, predicate in turtle_sorted_names(
            objects_by_predicate, self.name
        ):
            objects = objects_by_predicate[predicate]
            if self.stable:
                objects.sort(key=self.object_key)
            blocks.append((predicate_name, [self.object_repr(o) for o in objects]))
        return blocks

    def write_block(self, subject_name, predicates):
        if len(subject_name) > MAX_ALIGNED_SUBJECT or "\n" in subject_name:
            self.out.write(subject_name + "\n")
            indent, first_indent = INDENT, INDENT
        else:
            self.out.write(subject_name + " ")
            indent, first_indent = len(subject_name) + 1, 0
        for i, (predicate_name, object_names) in enumerate(predicates):
            self.out.write(" " * (indent if i else first_indent))
            # One-line later objects line up under the first.
            column = indent + len(predicate_name) + 1
            self.out.write(
                predicate_name + " " + object_list(object_names, indent, column)
            )
            self.out.write(" ;\n")
        self.out.write(" " * indent + ".\n\n")


def serialize_turtle(
    graph,
    f,
    base=None,
    profile=None,
    bnode_name_generator=default_bnode_name_generator,
    stable=False,
):
    """Serialize a graph to f as Turtle.

    If base is given it is written as @base and IRIs that start with it are
    written relative to it. The prefixes in profile are declared and used to
    abbreviate IRIs. bnode_name_generator is called once to get an iterator
    of blank node labels. Subjects, and predicates within a subject, are
    ordered by their written form; the objects of one predicate are in graph
    order, and blank nodes are labelled as they are met.

    With ``stable``, blank nodes are instead named by
    :func:`pymantic.compare.canonical_labels`, and the objects of one
    predicate are sorted: IRIs and literals by their Turtle name, then blank
    nodes by their molecule's canonical form and their position in it (see
    :doc:`/graph-comparison`). A blank node referenced exactly once is
    written inline as ``[ ... ]`` at that reference (see
    :func:`plan_inline_blank_nodes`), and only the prefixes the output uses
    are declared. The same graph then always produces the same bytes, and
    editing one blank node's content changes only the lines of its molecule.
    Raises :class:`pymantic.compare.Undecidable` for a graph whose blank
    nodes cannot be told apart within the work budget."""
    if profile is None:
        from pymantic.primitives import Profile

        profile = Profile()
    _TurtleWriter(graph, f, base, profile, bnode_name_generator, stable).write()
