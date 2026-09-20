from collections import Counter, OrderedDict
import re


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


def nt_needs_uchar(char):
    return (
        char <= "\u001f"
        or char == "\u007f"
        or "\ud800" <= char <= "\udfff"
        or char in "\ufffe\uffff"
    )


def nt_escape(node_string):
    """Escape a string for canonical N-Triples and N-Quads output."""
    output_string = ""
    for char in node_string:
        if char in NT_ECHAR:
            output_string += NT_ECHAR[char]
        elif nt_needs_uchar(char):
            output_string += "\\u%04X" % ord(char)
        else:
            output_string += char
    return output_string


def stable_lines(graph_or_dataset):
    """The N-Triples or N-Quads lines of a graph or dataset with blank nodes
    named by :func:`pymantic.compare.canonical_labels`, sorted, so that the
    same content always gives the same lines whatever the labels and order
    it was built with. See docs/graph-comparison.rst."""
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
    "A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF\u0370-\u037D\u037F-\u1FFF"
    "\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF"
    "\uFDF0-\uFFFD\U00010000-\U000EFFFF"
)
PN_CHARS_U = PN_CHARS_BASE + "_"
PN_CHARS = PN_CHARS_U + "\\-0-9\u00B7\u0300-\u036F\u203F-\u2040"
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


# Characters the Turtle IRIREF production forbids raw inside < and >:
# U+0000-U+0020 and <>"{}|^`\ . Everything else, including non-ASCII, is legal.
IRIREF_FORBIDDEN = set(map(chr, range(0x21))) | set('<>"{}|^`\\')


def turtle_iri_escape(iri):
    """Escape an IRI for output between < and > in Turtle by percent-encoding
    the UTF-8 bytes of characters the IRIREF production forbids. All other
    characters, including non-ASCII, pass through unchanged."""
    return "".join(
        "".join("%%%02X" % byte for byte in char.encode("utf-8"))
        if char in IRIREF_FORBIDDEN
        else char
        for char in iri
    )


def turtle_string_escape(string):
    """Escape a string appropriately for output in turtle form."""
    from pymantic.util import ECHAR_MAP

    # Single pass, so a backslash inserted by one escape is never escaped
    # again. An apostrophe needs no escape inside a double-quoted string.
    return (
        '"'
        + "".join(char if char == "'" else ECHAR_MAP.get(char, char) for char in string)
        + '"'
    )


def turtle_repr(node, profile, name_map, bnode_name_maker, base=None):
    """Turn a node in an RDF graph into its turtle representation."""
    if node.interfaceName == "NamedNode":
        name = profile.prefixes.shrink(node)
        if name != node:
            name = escape_prefix_local(name)
        if name is None or name == node:
            iri = str(node)
            if base and iri.startswith(base):
                iri = ("#" if base.endswith("#") else "") + iri[len(base) :]
            name = f"<{turtle_iri_escape(iri)}>"
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
            name += "^^" + turtle_repr(node.datatype, profile, None, None)
    return name


def turtle_sorted_names(nodes, name_maker, tie_break=None):
    """Sort a list of nodes in a graph by turtle name. ``tie_break`` maps a
    node to a secondary key for nodes with the same name, such as two list
    heads that are both written ``(1)``."""
    pairs = ((name_maker(node), node) for node in nodes)
    if tie_break is None:
        return sorted(pairs, key=lambda p: p[0])
    return sorted(pairs, key=lambda p: (p[0], tie_break(p[1])))


RDF_FIRST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#first"
RDF_REST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"
RDF_NIL = "http://www.w3.org/1999/02/22-rdf-syntax-ns#nil"


def plan_collections(graph):
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
    references = Counter(triple.object for triple in graph)

    def cell(node):
        """(first, rest, has_other_predicates) if node looks like a list cell."""
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

    inline, as_subject, consumed = {}, {}, set()
    for node in list(graph.subjects()):
        shape = cell(node)
        if shape is None:
            continue
        _, _, has_others = shape
        if references[node] == 1:
            (reference,) = graph.match(object=node)
            if reference.predicate == RDF_REST and cell(reference.subject):
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
            shape = cell(current)
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


def serialize_turtle(
    graph,
    f,
    base=None,
    profile=None,
    bnode_name_generator=default_bnode_name_generator,
    stable=False,
):
    """Serialize a graph to f as turtle, optionally using base IRI base
    and prefix map from profile. Subjects and predicates are written in
    order of their Turtle names; the objects of one predicate in graph
    order, and blank nodes are named from bnode_name_generator as they are
    met.

    With ``stable``, blank nodes are instead named by
    :func:`pymantic.compare.canonical_labels`, and the objects of one
    predicate are sorted: IRIs and literals by their Turtle name, then blank
    nodes by their molecule's canonical form and their position in it (see
    docs/graph-comparison.rst). The same graph then always produces the
    same bytes, and editing one blank node's content changes only the lines
    of its molecule. Raises :class:`pymantic.compare.Undecidable` for a
    graph whose blank nodes cannot be told apart within the work budget."""

    if base is not None:
        f.write("@base <" + turtle_iri_escape(base) + "> .\n")
    if profile is None:
        from pymantic.primitives import Profile

        profile = Profile()
    for prefix, iri in profile.prefixes.items():
        if prefix and not PN_PREFIX_RE.fullmatch(prefix):
            raise ValueError("Invalid Turtle prefix name")
        f.write("@prefix " + prefix + ": <" + turtle_iri_escape(iri) + "> .\n")

    name_map = OrderedDict()
    bnode_name_maker = bnode_name_generator()
    blank_order = {}
    if stable:
        from pymantic.compare import canonical_labels_and_order

        labels, blank_order = canonical_labels_and_order(graph)
        name_map.update((node, "_:" + label) for node, label in labels.items())

    def name_maker(n):
        return turtle_repr(n, profile, name_map, bnode_name_maker, base)

    def blank_rank(node):
        return blank_order.get(node, -1)

    def object_key(node):
        if node.interfaceName == "BlankNode":
            return (1, blank_order[node], "")
        return (0, 0, name_maker(node))

    inline, as_subject, consumed = plan_collections(graph)
    rendered = set()

    def collection_repr(members):
        return "(" + " ".join(object_repr(member) for member in members) + ")"

    def object_repr(node):
        # An inline head is written where its one reference is; once written
        # it is only ever named again, which is what keeps a list that
        # contains itself from recursing forever.
        if node in inline and node not in rendered:
            rendered.add(node)
            return collection_repr(inline[node])
        return name_maker(node)

    def subject_repr(node):
        if node in as_subject:
            return collection_repr(as_subject[node])
        return name_maker(node)

    def objects_of(subject, predicate):
        objects = [t.object for t in graph.match(subject=subject, predicate=predicate)]
        if stable:
            objects.sort(key=object_key)
        return objects

    def block_predicates(subject, skip=()):
        predicates = set(t.predicate for t in graph.match(subject=subject))
        predicates.difference_update(skip)
        return [
            (
                predicate_name,
                [object_repr(o) for o in objects_of(subject, predicate)],
            )
            for predicate_name, predicate in turtle_sorted_names(predicates, name_maker)
        ]

    def write_block(subject_name, predicates):
        subj_indent_size = len(subject_name) + 1
        f.write(subject_name + " ")
        for i, (predicate_name, object_names) in enumerate(predicates):
            if i != 0:
                f.write(" " * subj_indent_size)
            pred_indent_size = subj_indent_size + len(predicate_name) + 1
            f.write(predicate_name + " ")
            f.write((",\n" + " " * pred_indent_size).join(object_names))
            f.write(" ;\n")
        f.write(" " * subj_indent_size + ".\n\n")

    subjects = [subject for subject in graph.subjects() if subject not in consumed]
    tie_break = blank_rank if stable else None
    for subject_name, subject in turtle_sorted_names(subjects, subject_repr, tie_break):
        skip = (RDF_FIRST, RDF_REST) if subject in as_subject else ()
        write_block(subject_name, block_predicates(subject, skip))

    # A list whose only reference is from inside itself was never reached
    # from a subject block; write its cells as ordinary triples.
    for head in sorted(inline, key=blank_rank) if stable else inline:
        if head in rendered:
            continue
        rendered.add(head)
        node = head
        while node != RDF_NIL:
            write_block(name_maker(node), block_predicates(node))
            (rest,) = graph.match(subject=node, predicate=RDF_REST)
            node = rest.object
