from lepl import (
    Literal,
    Optional,
    Plus,
    Space,
    Star,
)

from .ntriples import BaseNParser


class NQuadsParser(BaseNParser):
    def make_quad(self, values):
        quad = self.env.createQuad(*values)
        self._call_state.graph.add(quad)
        return quad

    def __init__(self, environment=None):
        super(NQuadsParser, self).__init__(environment)
        self.graph_name = self.uriref
        self.quad = self.subject & ~Plus(Space()) & self.predicate \
            & ~Plus(Space()) & self.object_ & ~Plus(Space()) & \
            self.graph_name & ~Star(Space()) & ~Literal('.') & \
            ~Star(Space()) >= self.make_quad
        self.line = Star(Space()) & Optional(~self.quad | ~self.comment) \
            & ~Literal('\n')
        self.document = Star(self.line)

    def _make_graph(self):
        return self.env.createDataset()

    def parse(self, f, dataset=None):
        return super(NQuadsParser, self).parse(f, dataset)


nquads_parser = NQuadsParser()
