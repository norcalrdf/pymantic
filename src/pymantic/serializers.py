from collections import OrderedDict
import re


def validate_language(language):
    """Reject language tags that cannot be emitted as an RDF LANGTAG."""
    if not re.fullmatch(r"[A-Za-z]+(?:-[A-Za-z0-9]+)*", language):
        raise ValueError("Invalid RDF language tag")


def nt_escape(node_string):
    """Properly escape strings for n-triples and n-quads serialization."""
    output_string = ""
    for char in node_string:
        if char == "\u0009":
            output_string += "\\t"
        elif char == "\u000A":
            output_string += "\\n"
        elif char == "\u000D":
            output_string += "\\r"
        elif char == "\u0022":
            output_string += '\\"'
        elif char == "\u005C":
            output_string += "\\\\"
        elif (
            char >= "\u0020"
            and char <= "\u0021"
            or char >= "\u0023"
            and char <= "\u005B"
            or char >= "\u005D"
            and char <= "\u007E"
        ):
            output_string += char
        elif char <= "\uFFFF":
            output_string += "\\u%04X" % ord(char)
        else:
            output_string += "\\U%08X" % ord(char)
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
    return sorted((name_maker(node), node) for node in nodes)


def serialize_turtle(
    graph, f, base=None, profile=None, bnode_name_generator=default_bnode_name_generator
):
    """Serialize a graph to f as turtle, optionally using base IRI base
    and prefix map from profile. If provided, subject_key will be used to order
    subjects, and predicate_key predicates within a subject."""

    if base is not None:
        f.write("@base <" + turtle_iri_escape(base) + "> .\n")
    if profile is None:
        from pymantic.primitives import Profile

        profile = Profile()
    for prefix, iri in profile.prefixes.items():
        if prefix != "rdf":
            if prefix and not PN_PREFIX_RE.fullmatch(prefix):
                raise ValueError("Invalid Turtle prefix name")
            f.write("@prefix " + prefix + ": <" + turtle_iri_escape(iri) + "> .\n")

    name_map = OrderedDict()
    bnode_name_maker = bnode_name_generator()

    def name_maker(n):
        return turtle_repr(n, profile, name_map, bnode_name_maker, base)

    from pymantic.rdf import List

    subjects = [subj for subj in graph.subjects() if not List.is_list(subj, graph)]

    for subject_name, subject in turtle_sorted_names(subjects, name_maker):
        subj_indent_size = len(subject_name) + 1
        f.write(subject_name + " ")
        predicates = set(t.predicate for t in graph.match(subject=subject))
        sorted_predicates = turtle_sorted_names(predicates, name_maker)
        for i, (predicate_name, predicate) in enumerate(sorted_predicates):
            if i != 0:
                f.write(" " * subj_indent_size)
            pred_indent_size = subj_indent_size + len(predicate_name) + 1
            f.write(predicate_name + " ")
            for j, triple in enumerate(
                graph.match(subject=subject, predicate=predicate)
            ):
                if j != 0:
                    f.write(",\n" + " " * pred_indent_size)
                if List.is_list(triple.object, graph):
                    f.write("(")
                    for k, o in enumerate(List(graph, triple.object)):
                        if k != 0:
                            f.write(" ")
                        f.write(name_maker(o))
                    f.write(")")
                else:
                    f.write(name_maker(triple.object))
            f.write(" ;\n")
        f.write(" " * subj_indent_size + ".\n\n")
