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


def serialize_ntriples(graph, f):
    """Serialize some graph to f as ntriples."""
    for triple in graph:
        f.write(str(triple))


def serialize_nquads(dataset, f):
    """Serialize some graph to f as nquads."""
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
        if node.datatype == profile.resolve("xsd:string"):
            # Simple string.
            name = turtle_string_escape(node.value)
        elif node.datatype is None:
            # String with language?
            name = turtle_string_escape(node.value)
            if node.language:
                validate_language(node.language)
                name += "@" + node.language
        elif node.datatype in TURTLE_NATIVE_LITERALS and TURTLE_NATIVE_LITERALS[
            node.datatype
        ].fullmatch(node.value):
            name = node.value
        else:
            # Unrecognized data-type.
            name = turtle_string_escape(node.value)
            name += "^^" + turtle_repr(node.datatype, profile, None, None)
    return name


def turtle_sorted_names(nodes, name_maker):
    """Sort a list of nodes in a graph by turtle name."""
    return sorted(((name_maker(node), node) for node in nodes), key=lambda p: p[0])


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

    inline, as_subject, consumed = {}, {}, set()
    for node in list(graph.subjects()):
        shape = list_cell_shape(graph, node)
        if shape is None:
            continue
        _, _, has_others = shape
        if references[node] == 1:
            (reference,) = graph.match(object=node)
            if reference.predicate == RDF_REST and list_cell_shape(
                graph, reference.subject
            ):
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
            shape = list_cell_shape(graph, current)
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


class _TurtleWriter:
    """Writes one graph to a stream as Turtle.

    The parts of the output share state: blank node labels are handed out
    as nodes are first named, and an inline collection is written once, at
    its one reference, after which it is only named. This object holds that
    state for the length of one serialization."""

    def __init__(self, graph, f, base, profile, bnode_name_generator):
        self.graph = graph
        self.f = f
        self.base = base
        self.profile = profile
        self.name_map = OrderedDict()
        self.bnode_name_maker = bnode_name_generator()
        self.inline, self.as_subject, self.consumed = plan_collections(graph)
        self.rendered = set()

    def write(self):
        if self.base is not None:
            self.f.write("@base <" + turtle_iri_escape(self.base) + "> .\n")
        for prefix, iri in self.profile.prefixes.items():
            if prefix and not PN_PREFIX_RE.fullmatch(prefix):
                raise ValueError("Invalid Turtle prefix name")
            self.f.write("@prefix " + prefix + ": <" + turtle_iri_escape(iri) + "> .\n")

        subjects = [s for s in self.graph.subjects() if s not in self.consumed]
        for subject_name, subject in turtle_sorted_names(subjects, self.subject_repr):
            skip = (RDF_FIRST, RDF_REST) if subject in self.as_subject else ()
            self.write_block(subject_name, self.block_predicates(subject, skip))

        # A list whose only reference is from inside itself was never reached
        # from a subject block; write its cells as ordinary triples.
        for head in self.inline:
            if head in self.rendered:
                continue
            self.rendered.add(head)
            node = head
            while node != RDF_NIL:
                self.write_block(self.name(node), self.block_predicates(node))
                (rest,) = self.graph.match(subject=node, predicate=RDF_REST)
                node = rest.object

    def name(self, node):
        return turtle_repr(
            node, self.profile, self.name_map, self.bnode_name_maker, self.base
        )

    def collection_repr(self, members):
        return "(" + " ".join(self.object_repr(member) for member in members) + ")"

    def object_repr(self, node):
        # An inline head is written where its one reference is; once written
        # it is only ever named again, which is what keeps a list that
        # contains itself from recursing forever.
        if node in self.inline and node not in self.rendered:
            self.rendered.add(node)
            return self.collection_repr(self.inline[node])
        return self.name(node)

    def subject_repr(self, node):
        if node in self.as_subject:
            return self.collection_repr(self.as_subject[node])
        return self.name(node)

    def block_predicates(self, subject, skip=()):
        predicates = set(t.predicate for t in self.graph.match(subject=subject))
        predicates.difference_update(skip)
        return [
            (
                predicate_name,
                [
                    self.object_repr(t.object)
                    for t in self.graph.match(subject=subject, predicate=predicate)
                ],
            )
            for predicate_name, predicate in turtle_sorted_names(predicates, self.name)
        ]

    def write_block(self, subject_name, predicates):
        subj_indent_size = len(subject_name) + 1
        self.f.write(subject_name + " ")
        for i, (predicate_name, object_names) in enumerate(predicates):
            if i != 0:
                self.f.write(" " * subj_indent_size)
            pred_indent_size = subj_indent_size + len(predicate_name) + 1
            self.f.write(predicate_name + " ")
            self.f.write((",\n" + " " * pred_indent_size).join(object_names))
            self.f.write(" ;\n")
        self.f.write(" " * subj_indent_size + ".\n\n")


def serialize_turtle(
    graph, f, base=None, profile=None, bnode_name_generator=default_bnode_name_generator
):
    """Serialize a graph to f as Turtle.

    If base is given it is written as @base and IRIs that start with it are
    written relative to it. The prefixes in profile are declared and used to
    abbreviate IRIs. bnode_name_generator is called once to get an iterator
    of blank node labels. Subjects, and predicates within a subject, are
    ordered by their written form."""
    if profile is None:
        from pymantic.primitives import Profile

        profile = Profile()
    _TurtleWriter(graph, f, base, profile, bnode_name_generator).write()
