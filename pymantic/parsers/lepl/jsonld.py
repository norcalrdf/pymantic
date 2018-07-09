import json

from .base import BaseLeplParser


class PyLDLoader(BaseLeplParser):
    class _Loader(object):
        def __init__(self, pyld_loader):
            self.pyld_loader = pyld_loader

        def parse_file(self, f):
            jobj = json.load(f)
            self.pyld_loader.process_jobj(jobj)

        def parse(self, string):
            jobj = json.loads(string)
            self.pyld_loader.process_jobj(jobj)

    def parse_json(self, jobj, sink=None):
        if sink is None:
            sink = self._make_graph()
        self._prepare_parse(sink)
        self.process_jobj(jobj)
        self._cleanup_parse()

        return sink

    def make_quad(self, values):
        quad = self.env.createQuad(*values)
        self._call_state.graph.add(quad)
        return quad

    def _make_graph(self):
        return self.env.createDataset()

    def __init__(self, *args, **kwargs):
        self.document = self._Loader(self)
        super(PyLDLoader, self).__init__(*args, **kwargs)

    def process_triple_fragment(self, triple_fragment):
        if triple_fragment['type'] == 'IRI':
            return self.env.createNamedNode(triple_fragment['value'])
        elif triple_fragment['type'] == 'blank node':
            return self._call_state.bnodes[triple_fragment['value']]
        elif triple_fragment['type'] == 'literal':
            if 'language' in triple_fragment:
                raise NotImplemented('Languages not supported yet')
            return self.env.createLiteral(
                value=triple_fragment['value'],
                datatype=self.env.createNamedNode(triple_fragment['datatype']),
            )

    def process_jobj(self, jobj):
        from pyld.jsonld import to_rdf
        dataset = to_rdf(jobj)
        for graph_name, triples in dataset.items():
            graph_iri = (
                self.env.createNamedNode(graph_name) if
                graph_name != '@default' else
                None
            )
            for triple in triples:
                self.make_quad(
                    (self.process_triple_fragment(triple['subject']),
                     self.process_triple_fragment(triple['predicate']),
                     self.process_triple_fragment(triple['object']),
                     graph_iri,
                     )
                )


jsonld_parser = PyLDLoader()
