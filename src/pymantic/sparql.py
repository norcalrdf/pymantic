"""Provide an interface to SPARQL query endpoints."""

import datetime
import json
import logging
import pytz
import rdflib
import requests

log = logging.getLogger(__name__)


# How much of an error response body to keep. Endpoints can return whole HTML
# pages or stack traces; the first kilobyte is enough to see what went wrong.
ERROR_BODY_LIMIT = 1000


class SPARQLQueryException(Exception):

    """Raised when the SPARQL store returns an HTTP status code other than 200 OK.

    :ivar status_code: The HTTP status code of the response.
    :ivar content_type: The content-type of the response, or "" if absent.
    :ivar body: The response body decoded as UTF-8 with replacement and
        truncated to ERROR_BODY_LIMIT characters.
    :ivar query: The SPARQL that was sent.
    """

    def __init__(self, status_code, content_type, body, query):
        self.status_code = status_code
        self.content_type = content_type
        self.body = body[:ERROR_BODY_LIMIT]
        self.query = query
        truncated = " [truncated]" if len(body) > ERROR_BODY_LIMIT else ""
        super().__init__(
            "HTTP %s (%s): %s%s\nQuery: %s"
            % (status_code, content_type, self.body, truncated, query)
        )


class UnknownSPARQLReturnTypeException(Exception):

    """Raised when the SPARQL store provides a response with an unrecognized content-type."""

    pass


class _SelectOrUpdate:

    """A server that can run SPARQL queries."""

    def __init__(
        self, server, sparql, default_graph=None, named_graph=None, *args, **kwargs
    ):
        self.server = server
        self.sparql = sparql
        self.default_graphs = default_graph
        self.named_graphs = named_graph
        self.headers = dict()
        self.params = dict()

    # abstract methods, see Select for the idea
    def default_graph_uri(self):
        pass

    def named_graph_uri(self):
        pass

    def query_or_update(self):
        pass

    def directContentType(self):
        pass

    def postQueries(self):
        pass

    def execute(self):
        log.debug("Querying: %s with: %r", self.server.query_url, self.sparql)

        sparql = self.sparql.encode("utf-8")

        if self.default_graphs:
            self.params[self.default_graph_uri()] = self.default_graphs
        if self.named_graphs:
            self.params[self.named_graph_uri()] = self.named_graphs

        if self.server.post_directly:
            self.headers["Content-Type"] = self.directContentType() + "; charset=utf-8"
            uri_params = self.params
            data = sparql
            method = "post"
        elif self.postQueries():
            uri_params = None
            self.params[self.query_or_update()] = sparql
            data = self.params
            method = "post"
        else:
            # select only
            self.params[self.query_or_update()] = sparql
            uri_params = self.params
            data = None
            method = "get"

        response = self.server.s.request(
            method,
            self.server.query_url,
            params=uri_params,
            headers=self.headers,
            data=data,
            **self.server.requests_kwargs
        )
        if response.status_code == 204:
            return True
        if response.status_code != 200:
            raise SPARQLQueryException(
                response.status_code,
                response.headers.get("content-type", ""),
                response.content.decode("utf-8", errors="replace"),
                self.sparql,
            )
        return response


class _Select(_SelectOrUpdate):
    acceptable_responses = [
        "application/sparql-results+json",
    ]

    def __init__(self, server, query, *args, **kwargs):
        super(_Select, self).__init__(server, query, *args, **kwargs)
        self.headers["Accept"] = ",".join(self.acceptable_responses)

    def default_graph_uri(self):
        return "default-graph-uri"

    def named_graph_uri(self):
        return "named-graph-uri"

    def query_or_update(self):
        return "query"

    def directContentType(self):
        return "application/sparql-query"

    def postQueries(self):
        return self.server.post_queries

    def execute(self):
        response = super(_Select, self).execute()
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/sparql-results+json"):
            return json.loads(response.content.decode("utf-8"))
        raise UnknownSPARQLReturnTypeException("Got content of type: %s" % content_type)


class _Update(_SelectOrUpdate):
    def default_graph_uri(self):
        return "using-graph-uri"

    def named_graph_uri(self):
        return "using-named-graph-uri"

    def query_or_update(self):
        return "update"

    def directContentType(self):
        return "application/sparql-update"

    def postQueries(self):
        return True


class SPARQLServer:

    """A server that can run SPARQL queries."""

    def __init__(
        self,
        query_url,
        post_queries=False,
        post_directly=False,
        verify=None,
        timeout=30,
    ):
        """
        :param query_url: The SPARQL endpoint URL.
        :param post_queries: Send queries by POST instead of GET.
        :param post_directly: Send the SPARQL as the request body rather
            than as a form parameter.
        :param verify: Passed through to requests; controls TLS verification.
        :param timeout: Seconds to wait for the endpoint to connect and to
            send each chunk of the response, as requests' ``timeout``. None
            waits forever.
        """
        self.query_url = query_url
        self.post_queries = post_queries
        self.post_directly = post_directly
        self.requests_kwargs = {"timeout": timeout}
        if verify is not None:
            self.requests_kwargs["verify"] = verify

        self.s = requests.Session()

    def query(self, sparql, *args, **kwargs):
        """Execute a SPARQL query.

        The store must respond with application/sparql-results+json; any
        other content-type raises UnknownSPARQLReturnTypeException.

        :param sparql: The SPARQL to execute.
        :returns: The decoded JSON results, as a dictionary.
        """
        return _Select(self, sparql, *args, **kwargs).execute()

    def update(self, sparql, **kwargs):
        """Execute a SPARQL update.

        :param sparql: The SPARQL Update request to execute.
        """
        return _Update(self, sparql, **kwargs).execute()


def changeset(a, b, graph_uri):
    """Create an RDF graph with the changeset between graphs a and b."""
    cs = rdflib.Namespace("http://purl.org/vocab/changeset/schema#")
    graph = rdflib.Graph()
    graph.namespace_manager.bind("cs", cs)
    removal, addition = differences(a, b)
    change_set = rdflib.BNode()
    graph.add((change_set, rdflib.RDF.type, cs["ChangeSet"]))
    graph.add(
        (
            change_set,
            cs["createdDate"],
            rdflib.Literal(datetime.datetime.now(pytz.UTC).isoformat()),
        )
    )
    graph.add((change_set, cs["subjectOfChange"], rdflib.URIRef(graph_uri)))

    for stmt in removal:
        statement = reify(graph, stmt)
        graph.add((change_set, cs["removal"], statement))
    for stmt in addition:
        statement = reify(graph, stmt)
        graph.add((change_set, cs["addition"], statement))
    return graph


def reify(graph, statement):
    """Add reifed statement to graph."""
    s, p, o = statement
    statement_node = rdflib.BNode()
    graph.add((statement_node, rdflib.RDF.type, rdflib.RDF.Statement))
    graph.add((statement_node, rdflib.RDF.subject, s))
    graph.add((statement_node, rdflib.RDF.predicate, p))
    graph.add((statement_node, rdflib.RDF.object, o))
    return statement_node


def differences(a, b, exclude=[]):
    """Return (removes,adds) excluding statements with a predicate in exclude."""
    exclude = [rdflib.URIRef(excluded) for excluded in exclude]
    return (
        [s for s in a if s not in b and s[1] not in exclude],
        [s for s in b if s not in a and s[1] not in exclude],
    )
