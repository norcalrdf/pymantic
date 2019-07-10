"""Parse RDF serialized as ntriples files.

Usage::

  from pymantic.parsers.lark import ntriples_parser
  graph = ntriples_parser.parse(io.open('a_file.nt', mode='rt'))
  graph2 = ntriples_parser.parse("<http://a.example/s> <http://a.example/p> <http://a.example/o> .")

If ``.parse()`` is called with a file-like object implementing ``readline``,
it will efficiently parse line by line rather than parsing the entire file.
"""

from lark import (
    Lark,
    Transformer,
)

from pymantic.primitives import (
    NamedNode,
    Triple,
)
from pymantic.util import (
    decode_literal,
)

from pymantic.parsers.base import (
    BaseParser,
)
from .base import (
    LarkParser,
)


grammar = r"""triples_start: triple? (EOL triple)* EOL?
triple: subject predicate object "."

quads_start: quad? (EOL quad)* EOL?
quad: subject predicate object graph "."

?subject: iriref
        | BLANK_NODE_LABEL -> blank_node_label
?predicate: iriref
?object: iriref
       | BLANK_NODE_LABEL -> blank_node_label
       | literal
?graph: iriref
literal: STRING_LITERAL_QUOTE ("^^" iriref | LANGTAG)?

LANGTAG: "@" /[a-zA-Z]/+ ("-" /[a-zA-Z0_9]/+)*
EOL: /[\r\n]/+
iriref: "<" (/[^\x00-\x20<>"{}|^`\\]/ | UCHAR)* ">"
STRING_LITERAL_QUOTE: "\"" (/[^\x22\\\x0A\x0D]/ | ECHAR | UCHAR)* "\""
BLANK_NODE_LABEL: "_:" (PN_CHARS_U | "0".."9") ((PN_CHARS | ".")* PN_CHARS)?
UCHAR: "\\u" HEX~4 | "\\U" HEX~8
ECHAR: "\\" /[tbnrf"'\\]/
PN_CHARS_BASE: /[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD\u10000-\uEFFFF]/
PN_CHARS_U: PN_CHARS_BASE | "_" | ":"
PN_CHARS: PN_CHARS_U | /[\-0-9\u00B7\u0300-\u036F\u203F-\u2040]/
HEX: /[0-9A-Fa-f]/

%ignore /[ \t]/+
"""


class NTriplesTransformer(Transformer, BaseParser):
    """Transform the tokenized ntriples into RDF primitives.
    """
    def blank_node_label(self, children):
        bn_label, = children
        return self.make_blank_node(bn_label.value)

    def iriref(self, children):
        iri = ''.join(children)
        iri = decode_literal(iri)
        return self.make_named_node(iri)

    def literal(self, children):
        quoted_literal = children[0]

        quoted_literal = quoted_literal[1:-1]  # Remove ""s
        literal = decode_literal(quoted_literal)

        if len(children) == 2 and isinstance(children[1], NamedNode):
            type_ = children[1]
            return self.make_datatype_literal(literal, type_)
        elif len(children) == 2 and children[1].type == 'LANGTAG':
            lang = children[1][1:]  # Remove @
            return self.make_language_literal(literal, lang)
        else:
            return self.make_language_literal(literal)

    def triple(self, children):
        subject, predicate, object_ = children
        return self.make_triple(subject, predicate, object_)

    def triples_start(self, children):
        for child in children:
            if isinstance(child, Triple):
                yield child


nt_lark = Lark(
    grammar, start='triples_start', parser='lalr',
    transformer=NTriplesTransformer(),
)

#! A fully-instantiated ntriples parser
ntriples_parser = LarkParser(nt_lark)
