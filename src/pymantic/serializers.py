from collections import OrderedDict


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
        elif char >= "\u007F" and char <= "\uFFFF":
            output_string += "\\u%04X" % ord(char)
        elif char >= "\U00010000" and char <= "\U0010FFFF":
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
        yield "_b" + str(i)
        i += 1


def escape_prefix_local(prefix):
    prefix, colon, local = prefix.partition(":")
    for esc_char in "~.-!$&'()*+,;=:/?#@%_":
        local = local.replace(esc_char, "\\" + esc_char)
    return "".join((prefix, colon, local))


def turtle_string_escape(string):
    """Escape a string appropriately for output in turtle form."""
    from pymantic.util import ECHAR_MAP

    for escaped, value in ECHAR_MAP.items():
        string = string.replace(value, "\\" + escaped)
    return '"' + string + '"'


def turtle_repr(node, profile, name_map, bnode_name_maker, base=None):
    """Turn a node in an RDF graph into its turtle representation."""
    if node.interfaceName == "NamedNode":
        name = profile.prefixes.shrink(node)
        if base and name.startswith(base):
            if base.endswith("#"):
                name = f"<{str(name.replace(base, '#'))}>"
            else:
                name = f"<{str(name.replace(base, ''))}>"
        if name == node:
            name = f"<{str(name)}>"
        else:
            escape_prefix_local(name)
    elif node.interfaceName == "BlankNode":
        if node in name_map:
            name = name_map[node]
        else:
            name = bnode_name_maker.next()
            name_map[node] = name
    elif node.interfaceName == "Literal":
        if node.datatype == profile.resolve("xsd:string"):
            # Simple string.
            name = turtle_string_escape(node.value)
        elif node.datatype is None:
            # String with language?
            name = turtle_string_escape(node.value)
            if node.language:
                name += "@" + node.language
        elif node.datatype == profile.resolve("xsd:integer"):
            name = node.value
        elif node.datatype == profile.resolve("xsd:decimal"):
            name = node.value
        elif node.datatype == profile.resolve("xsd:double"):
            name = node.value
        elif node.datatype == profile.resolve("xsd:boolean"):
            name = node.value
        else:
            # Unrecognized data-type.
            name = turtle_string_escape(node.value)
            name += "^" + turtle_repr(node.datatype, profile, None, None)
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
        f.write("@base <" + base + "> .\n")
    if profile is None:
        from pymantic.primitives import Profile

        profile = Profile()
    for prefix, iri in profile.prefixes.items():
        if prefix != "rdf":
            f.write("@prefix " + prefix + ": <" + iri + "> .\n")

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
