"""Parse RDF serialized as ntriples files.

Usage::

  from pymantic.parsers.lark import ntriples_parser
  graph = ntriples_parser.parse(io.open('a_file.nt', mode='rt'))
  graph2 = ntriples_parser.parse("<http://a.example/s> <http://a.example/p> <http://a.example/o> .")

If ``.parse()`` is called with a file-like object implementing ``readline``,
it will efficiently parse line by line rather than parsing the entire file.
"""

from lark import Lark, Transformer
import re

from pymantic.parsers.base import BaseParser
from pymantic.primitives import NamedNode, Triple
from pymantic.util import decode_literal

from .base import LarkParser

# The N-Triples 1.1 grammar (https://www.w3.org/TR/n-triples/#n-triples-grammar)
# and the N-Quads 1.1 grammar (https://www.w3.org/TR/n-quads/#sec-grammar),
# which differ only in the optional graph label. Departures from the spec text:
#
# * The document rules are written as ``EOL* (triple EOL+)* triple?`` rather
#   than the spec's ``triple? (EOL triple)* EOL?``. Both accept the same
#   documents once comments and horizontal whitespace are ignored, but a
#   comment-only or whitespace-only line leaves consecutive EOL tokens, which
#   the spec's shape rejects.
# * PN_CHARS_U omits ":" as in the N-Triples 1.2 grammar; the 1.1 REC text
#   includes it by mistake and the W3C suite rejects ``_:a:b``.
# * LANGTAG subtags are limited to 8 characters, the BCP47 well-formedness
#   rule that RDF Concepts requires of language tags.
grammar = r"""triples_start: EOL* (triple EOL+)* triple?
triple: subject predicate object "."

quads_start: EOL* (quad EOL+)* quad?
quad: subject predicate object graph? "."

?subject: iriref
        | BLANK_NODE_LABEL -> blank_node_label
?predicate: iriref
?object: iriref
       | BLANK_NODE_LABEL -> blank_node_label
       | literal
?graph: iriref
      | BLANK_NODE_LABEL -> blank_node_label
literal: STRING_LITERAL_QUOTE ("^^" iriref | LANGTAG)?
iriref: IRIREF

LANGTAG: "@" /[a-zA-Z]{1,8}/ ("-" /[a-zA-Z0-9]{1,8}/)*
EOL: /[\r\n]/+
IRIREF: "<" (/[^\x00-\x20<>"{}|^`\\]/ | UCHAR)* ">"
STRING_LITERAL_QUOTE: "\"" (/[^\x22\\\x0A\x0D]/ | ECHAR | UCHAR)* "\""
BLANK_NODE_LABEL: "_:" (PN_CHARS_U | /[0-9]/) ((PN_CHARS | ".")* PN_CHARS)?
UCHAR: "\\u" HEX~4 | "\\U" HEX~8
ECHAR: "\\" /[tbnrf"'\\]/
PN_CHARS_BASE: /[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD\U00010000-\U000EFFFF]/
PN_CHARS_U: PN_CHARS_BASE | "_"
PN_CHARS: PN_CHARS_U | /[\-0-9\u00B7\u0300-\u036F\u203F-\u2040]/
HEX: /[0-9A-Fa-f]/
COMMENT: /#[^\r\n]*/

%ignore /[ \t]/+
%ignore COMMENT
"""

# N-Triples IRIs "may be written only as absolute IRIs", so they must start
# with a scheme (RFC 3987: ALPHA *( ALPHA / DIGIT / "+" / "-" / "." ) ":").
ABSOLUTE_IRI = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")

# A literal with one of these datatypes must be written with a language tag
# (RDF Concepts, "Literals"); ``"x"^^rdf:langString`` is ill-formed.
LANGUAGE_TAGGED_DATATYPES = {
    NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"),
    NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#dirLangString"),
}


class NTriplesTransformer(BaseParser, Transformer):
    """Transform the tokenized ntriples into RDF primitives."""

    def blank_node_label(self, children):
        (bn_label,) = children
        return self.make_blank_node(bn_label.value)

    def iriref(self, children):
        (token,) = children
        iri = decode_literal(token[1:-1])  # Remove <>s
        if not ABSOLUTE_IRI.match(iri):
            raise ValueError("N-Triples IRIs must be absolute: <%s>" % iri)
        return self.make_named_node(iri)

    def literal(self, children):
        quoted_literal = children[0]

        quoted_literal = quoted_literal[1:-1]  # Remove ""s
        literal = decode_literal(quoted_literal)

        if len(children) == 2 and isinstance(children[1], NamedNode):
            type_ = children[1]
            if type_ in LANGUAGE_TAGGED_DATATYPES:
                raise ValueError(
                    "literal with datatype %s needs a language tag" % type_
                )
            return self.make_datatype_literal(literal, type_)
        elif len(children) == 2 and children[1].type == "LANGTAG":
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
    grammar,
    start="triples_start",
    parser="lalr",
    transformer=NTriplesTransformer(),
)

# A fully-instantiated ntriples parser
ntriples_parser = LarkParser(nt_lark)
