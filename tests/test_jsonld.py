"""Tests for the JSON-LD parser, focused on remote context loading.

Remote contexts must never be fetched unless the caller opts in with a
document loader, otherwise parsing untrusted JSON-LD lets the document author
make the parsing host issue arbitrary HTTP requests.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pyld.jsonld import JsonLdError, requests_document_loader
import pytest
import threading
import uuid

from pymantic.parsers.jsonld import PyLDLoader, RemoteContextsDisabledError
from pymantic.primitives import Literal, NamedNode, Quad

NAME_IRI = "http://ex/name"
XSD_STRING = NamedNode("http://www.w3.org/2001/XMLSchema#string")
EXPECTED_QUAD = Quad(
    NamedNode("http://ex/s"), NamedNode(NAME_IRI), Literal("x", None, XSD_STRING), None
)


class ContextHandler(BaseHTTPRequestHandler):
    """Serves one JSON-LD context at any path and records each request."""

    def do_GET(self):
        self.server.requests.append(self.path)
        body = json.dumps({"@context": {"name": NAME_IRI}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/ld+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class ContextServer(HTTPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requests = []

    def context_url(self):
        # pyld caches resolved contexts by URL process-wide, so every test gets
        # a unique URL to keep one test's fetch from satisfying another's.
        host, port = self.server_address
        return "http://%s:%d/%s/ctx.jsonld" % (host, port, uuid.uuid4().hex)


@pytest.fixture
def context_server():
    server = ContextServer(("127.0.0.1", 0), ContextHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def remote_context_document(context_url):
    return {"@context": context_url, "@id": "http://ex/s", "name": "x"}


def test_remote_context_refused_by_default(context_server):
    document = remote_context_document(context_server.context_url())

    with pytest.raises(RemoteContextsDisabledError) as excinfo:
        PyLDLoader().parse_json(document)

    assert context_server.requests == []
    assert "remote JSON-LD contexts is disabled" in str(excinfo.value)
    assert "document_loader" in str(excinfo.value)
    assert isinstance(excinfo.value, JsonLdError)


def test_remote_context_loaded_with_constructor_loader(context_server):
    document = remote_context_document(context_server.context_url())
    parser = PyLDLoader(document_loader=requests_document_loader())

    dataset = parser.parse_json(document)

    assert len(context_server.requests) == 1
    assert len(dataset) == 1
    assert EXPECTED_QUAD in dataset


def test_remote_context_loaded_with_options_loader(context_server):
    document = remote_context_document(context_server.context_url())

    dataset = PyLDLoader().parse_json(
        document, options={"documentLoader": requests_document_loader()}
    )

    assert len(context_server.requests) == 1
    assert len(dataset) == 1
    assert EXPECTED_QUAD in dataset


def test_options_loader_overrides_constructor_loader(context_server):
    document = remote_context_document(context_server.context_url())
    parser = PyLDLoader(document_loader=requests_document_loader())

    def refuse(url, options):
        raise RuntimeError("options loader must win")

    with pytest.raises(JsonLdError):
        parser.parse_json(document, options={"documentLoader": refuse})

    assert context_server.requests == []


def test_inline_context_needs_no_loader():
    document = {
        "@context": {"name": NAME_IRI},
        "@id": "http://ex/s",
        "name": "x",
    }

    dataset = PyLDLoader().parse_json(document)

    assert len(dataset) == 1
    assert EXPECTED_QUAD in dataset
