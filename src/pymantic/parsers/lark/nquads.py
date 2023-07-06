"""Parse RDF serialized as nquads files.

Usage::

  from pymantic.parsers.lark import nquads_parser
  graph = nquads_parser.parse(io.open('a_file.nq', mode='rt'))
  graph2 = nquads_parser.parse("<http://a.example/s> <http://a.example/p> <http://a.example/o> <http://a.example/g> .")

If ``.parse()`` is called with a file-like object implementing ``readline``,
it will efficiently parse line by line rather than parsing the entire file.
"""

from lark import Lark

from pymantic.primitives import (
    Quad,
)

from .base import (
    LarkParser,
)
from .ntriples import (
    grammar,
    NTriplesTransformer,
)


class NQuadsTransformer(NTriplesTransformer):
    """Transform the tokenized nquads into RDF primitives.
    """
    def quad(self, children):
        subject, predicate, object_, graph = children
        return self.make_quad(subject, predicate, object_, graph)

    def quads_start(self, children):
        for child in children:
            if isinstance(child, Quad):
                yield child


nq_lark = Lark(
    grammar, start='quads_start', parser='lalr',
    transformer=NQuadsTransformer(),
)

#! A fully-instantiated nquads parser
nquads_parser = LarkParser(nq_lark)
