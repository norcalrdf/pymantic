"""Parse RDF serialized as jsonld

Usage::

  from pymantic.parsers.jsonld import jsonld_parser
  graph = jsonld_parser.parse_json(json.load(io.open('file.jsonld', mode='rt')))

Remote contexts are not fetched by default: a document whose ``@context`` (or
``@import``) points at a URL raises :class:`RemoteContextsDisabledError`
instead of making an HTTP request, so untrusted documents cannot make the
parsing host contact arbitrary servers. To allow fetching, opt in with a pyld
document loader, either for a parser instance::

  from pyld.jsonld import requests_document_loader
  from pymantic.parsers.jsonld import PyLDLoader
  parser = PyLDLoader(document_loader=requests_document_loader())
  graph = parser.parse_json(document)

or for a single call::

  graph = jsonld_parser.parse_json(
      document, options={"documentLoader": requests_document_loader()}
  )
"""

import json
from pyld.jsonld import JsonLdError, to_rdf

from .base import BaseParser


class RemoteContextsDisabledError(JsonLdError):
    """A document referenced a remote context but no document loader was
    opted into, so the request was refused."""

    def __init__(self, url):
        super().__init__(
            "Loading remote JSON-LD contexts is disabled: the document references "
            "%r but no document loader is configured. To allow network access, "
            "pass a loader such as pyld.jsonld.requests_document_loader() via "
            "PyLDLoader(document_loader=...) or "
            'parse_json(..., options={"documentLoader": ...}).' % (url,),
            "jsonld.LoadDocumentError",
            {"url": url},
            code="loading document failed",
        )
        self.url = url


def _refuse_remote_documents(url, options):
    raise RemoteContextsDisabledError(url)


class PyLDLoader(BaseParser):
    class _Loader:
        def __init__(self, pyld_loader):
            self.pyld_loader = pyld_loader

        def parse_file(self, f):
            jobj = json.load(f)
            self.pyld_loader.process_jobj(jobj)

        def parse(self, string):
            jobj = json.loads(string)
            self.pyld_loader.process_jobj(jobj)

    def parse_json(self, jobj, sink=None, options=None):
        if sink is None:
            sink = self._make_graph()
        self._prepare_parse(sink)
        self.process_jobj(jobj, options)
        self._cleanup_parse()

        return sink

    def make_quad(self, values):
        quad = self.env.createQuad(*values)
        self._call_state.graph.add(quad)
        return quad

    def _make_graph(self):
        return self.env.createDataset()

    def __init__(self, *args, document_loader=None, **kwargs):
        self.document = self._Loader(self)
        self.document_loader = document_loader
        super(PyLDLoader, self).__init__(*args, **kwargs)

    def process_triple_fragment(self, triple_fragment):
        if triple_fragment["type"] == "IRI":
            return self.env.createNamedNode(triple_fragment["value"])
        elif triple_fragment["type"] == "blank node":
            return self._call_state.bnodes[triple_fragment["value"]]
        elif triple_fragment["type"] == "literal":
            language = None
            if "language" in triple_fragment:
                language = triple_fragment["language"]
            return self.env.createLiteral(
                value=triple_fragment["value"],
                datatype=self.env.createNamedNode(triple_fragment["datatype"]),
                language=language,
            )

    def process_jobj(self, jobj, options=None):
        options = dict(options) if options else {}
        if self.document_loader is not None:
            options.setdefault("documentLoader", self.document_loader)
        options.setdefault("documentLoader", _refuse_remote_documents)

        try:
            dataset = to_rdf(jobj, options=options)
        except JsonLdError as error:
            # pyld wraps loader failures in several layers of JsonLdError; surface
            # our refusal directly so callers get a specific, actionable exception.
            cause = error
            while cause is not None:
                if isinstance(cause, RemoteContextsDisabledError):
                    raise cause from None
                cause = cause.__cause__
            raise
        for graph_name, triples in dataset.items():
            graph_iri = (
                self.env.createNamedNode(graph_name)
                if graph_name != "@default"
                else None
            )
            for triple in triples:
                self.make_quad(
                    (
                        self.process_triple_fragment(triple["subject"]),
                        self.process_triple_fragment(triple["predicate"]),
                        self.process_triple_fragment(triple["object"]),
                        graph_iri,
                    )
                )


jsonld_parser = PyLDLoader()
