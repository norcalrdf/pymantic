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

nquads_parser = LarkParser(nq_lark)
