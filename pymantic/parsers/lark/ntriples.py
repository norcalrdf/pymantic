import codecs
from collections import defaultdict

from lark import (
    Lark,
    Transformer,
)

from pymantic.compat import (
    binary_type,
)
from pymantic.primitives import (
    BlankNode,
    Graph,
    Literal,
    NamedNode,
    Triple,
)


grammar = r"""start: triple? (EOL triple)* EOL?
triple: subject predicate object "."
?subject: iriref
        | BLANK_NODE_LABEL -> blank_node_label
?predicate: iriref
?object: iriref
       | BLANK_NODE_LABEL -> blank_node_label
       | literal
literal: STRING_LITERAL_QUOTE ("^^" iriref | LANGTAG)?

LANGTAG: "@" /[a-zA-Z]/+ ("-" /[a-zA-Z0_9]/+)*
EOL: /[\r\n]/+
iriref: "<" (/[^\x00-\x20<>"{}|^`\\]/ | UCHAR)* ">"
STRING_LITERAL_QUOTE: "\"" (/[^\x22\x5C\x0A\x0D]/ | ECHAR | UCHAR)* "\""
BLANK_NODE_LABEL: "_:" (PN_CHARS_U | "0".."9") ((PN_CHARS | ".")* PN_CHARS)?
UCHAR: "\\u" HEX~4 | "\\U" HEX~8
ECHAR: "\\" /[tbnrf"'\\]/
PN_CHARS_BASE: /[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD\u10000-\uEFFFF]/
PN_CHARS_U: PN_CHARS_BASE | "_" | ":"
PN_CHARS: PN_CHARS_U | /[\-0-9\u00B7\u0300-\u036F\u203F-\u2040]/
HEX: /[0-9A-Fa-f]/

%ignore /[ \t]/+
"""


class NTriplesTransformer(Transformer):
    def __init__(self):
        self.blank_node_labels = defaultdict(BlankNode)

    def blank_node_label(self, children):
        bn_label, = children
        return self.blank_node_labels[bn_label.value]

    def iriref(self, children):
        iri = ''.join(children)
        iri = codecs.decode(iri, 'unicode-escape')
        return NamedNode(iri)

    def literal(self, children):
        quoted_literal = children[0]
        lang = None
        type_ = None

        quoted_literal = quoted_literal[1:-1]  # Remove ""s
        literal = codecs.decode(quoted_literal, 'unicode-escape')

        if len(children) == 2 and isinstance(children[1], NamedNode):
            type_ = children[1]
        elif len(children) == 2 and children[1].type == 'LANGTAG':
            lang = children[1][1:]  # Remove @

        return Literal(literal, language=lang, datatype=type_)

    def triple(self, children):
        subject, predicate, object_ = children
        t = Triple(subject, predicate, object_)
        return t

    def start(self, children):
        for child in children:
            if isinstance(child, Triple):
                yield child

    def reset(self):
        self.blank_node_labels = defaultdict(BlankNode)


nt_lark = Lark(grammar, parser='lalr', transformer=NTriplesTransformer())


def triple_producer(stream):
    for line in stream:  # Equivalent to readline
        if line:
            yield next(nt_lark.parse(line))


def parse(string_or_stream, graph=None):
    if graph is None:
        graph = Graph()

    try:
        if hasattr(string_or_stream, 'readline'):
            triples = triple_producer(string_or_stream)
        else:
            # Presume string.
            triples = nt_lark.parse(string_or_stream)

        graph.addAll(triples)
    finally:
        nt_lark.options.transformer.reset()

    return graph


def parse_string(string_or_bytes, graph=None):
    if isinstance(string_or_bytes, binary_type):
        string = string_or_bytes.decode('utf-8')
    else:
        string = string_or_bytes

    return parse(string, graph)
