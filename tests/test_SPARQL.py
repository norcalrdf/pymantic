from betamax import Betamax
import os.path
import pytest

from pymantic.sparql import (
    SPARQLQueryException,
    SPARQLServer,
    UnknownSPARQLReturnTypeException,
)

with Betamax.configure() as config:
    config.cassette_library_dir = os.path.join(
        os.path.dirname(__file__),
        "playbacks",
    )


def testMockSPARQL():
    """Test a SPARQL query against a mocked-up endpoint."""
    test_query = """PREFIX dc: <http://purl.org/dc/terms/>
    SELECT ?product ?title WHERE { ?product dc:title ?title } LIMIT 10"""

    sparql = SPARQLServer(
        "http://localhost/tenuki/sparql",
        post_queries=True,
    )

    with Betamax(sparql.s).use_cassette("mock_sparql", record="none"):
        results = sparql.query(test_query)

    assert results["results"]["bindings"][0]["product"]["value"] == "test_product"
    assert results["results"]["bindings"][0]["title"]["value"] == "Test Title"


def testMockSPARQLError():
    """Test a SPARQL query against a mocked-up endpoint."""
    test_query = """PREFIX dc: <http://purl.org/dc/terms/>
    SELECT ?product ?title WHERE { ?product dc:title ?title } LIMIT 10"""

    sparql = SPARQLServer(
        "http://localhost/tenuki/sparql",
        post_queries=True,
    )
    with Betamax(sparql.s).use_cassette(
        "mock_sparql_error",
        record="none",
    ), pytest.raises(SPARQLQueryException):
        sparql.query(test_query)


class FakeResponse:
    """The parts of a requests.Response that pymantic.sparql reads."""

    def __init__(
        self,
        status_code=200,
        content_type="application/sparql-results+json",
        content=b'{"results": {"bindings": []}}',
        extra_headers=None,
    ):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.headers.update(extra_headers or {})
        self.content = content


def stub_request(monkeypatch, server, response):
    """Replace the server's session.request with a fake; return the recorded calls."""
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return response

    monkeypatch.setattr(server.s, "request", fake_request)
    return calls


TEST_QUERY = "SELECT * WHERE { ?s ?p ?o } LIMIT 1"


def test_query_accepts_only_json_results(monkeypatch):
    sparql = SPARQLServer("http://localhost/sparql")
    calls = stub_request(monkeypatch, sparql, FakeResponse())

    sparql.query(TEST_QUERY)

    assert calls[0]["headers"]["Accept"] == "application/sparql-results+json"


def test_query_returns_parsed_json(monkeypatch):
    sparql = SPARQLServer("http://localhost/sparql")
    stub_request(monkeypatch, sparql, FakeResponse(content=b'{"boolean": true}'))

    assert sparql.query(TEST_QUERY) == {"boolean": True}


@pytest.mark.parametrize(
    "content_type",
    [
        "text/html",
        "application/rdf+xml",
        "text/turtle",
        "application/sparql-results+xml",
    ],
)
def test_unknown_content_type_raises(monkeypatch, content_type):
    sparql = SPARQLServer("http://localhost/sparql")
    stub_request(
        monkeypatch,
        sparql,
        FakeResponse(content_type=content_type, content=b"<not json>"),
    )

    with pytest.raises(UnknownSPARQLReturnTypeException) as excinfo:
        sparql.query(TEST_QUERY)
    assert content_type in str(excinfo.value)


def test_missing_content_type_raises(monkeypatch):
    sparql = SPARQLServer("http://localhost/sparql")
    response = FakeResponse()
    del response.headers["content-type"]
    stub_request(monkeypatch, sparql, response)

    with pytest.raises(UnknownSPARQLReturnTypeException):
        sparql.query(TEST_QUERY)


def test_query_uses_default_timeout(monkeypatch):
    sparql = SPARQLServer("http://localhost/sparql")
    calls = stub_request(monkeypatch, sparql, FakeResponse())

    sparql.query(TEST_QUERY)

    assert calls[0]["timeout"] == 30


def test_update_uses_default_timeout(monkeypatch):
    sparql = SPARQLServer("http://localhost/sparql")
    calls = stub_request(monkeypatch, sparql, FakeResponse(status_code=204))

    assert sparql.update("INSERT DATA { <a> <b> <c> }") is True
    assert calls[0]["timeout"] == 30


def test_timeout_can_be_overridden(monkeypatch):
    sparql = SPARQLServer("http://localhost/sparql", timeout=5)
    calls = stub_request(monkeypatch, sparql, FakeResponse())

    sparql.query(TEST_QUERY)

    assert calls[0]["timeout"] == 5


def test_timeout_can_be_disabled(monkeypatch):
    sparql = SPARQLServer("http://localhost/sparql", timeout=None)
    calls = stub_request(monkeypatch, sparql, FakeResponse())

    sparql.query(TEST_QUERY)

    assert calls[0]["timeout"] is None


def test_verify_is_still_passed_alongside_timeout(monkeypatch):
    sparql = SPARQLServer("http://localhost/sparql", verify=False)
    calls = stub_request(monkeypatch, sparql, FakeResponse())

    sparql.query(TEST_QUERY)

    assert calls[0]["verify"] is False
    assert calls[0]["timeout"] == 30


def test_error_response_exposes_status_and_truncated_body(monkeypatch):
    sparql = SPARQLServer("http://localhost/sparql")
    body = b"x" * 5000
    stub_request(
        monkeypatch,
        sparql,
        FakeResponse(
            status_code=500,
            content_type="text/plain",
            content=body,
            extra_headers={"X-Secret": "hunter2"},
        ),
    )

    with pytest.raises(SPARQLQueryException) as excinfo:
        sparql.query(TEST_QUERY)

    exc = excinfo.value
    assert exc.status_code == 500
    assert exc.content_type == "text/plain"
    assert exc.body == "x" * 1000
    assert exc.query == TEST_QUERY
    message = str(exc)
    assert "500" in message
    assert "text/plain" in message
    assert "x" * 1000 in message
    assert "x" * 1001 not in message
    assert TEST_QUERY in message
    assert "hunter2" not in message
    assert "X-Secret" not in message


def test_error_response_body_is_decoded_with_replacement(monkeypatch):
    sparql = SPARQLServer("http://localhost/sparql")
    stub_request(
        monkeypatch,
        sparql,
        FakeResponse(status_code=400, content_type="text/plain", content=b"bad \xff"),
    )

    with pytest.raises(SPARQLQueryException) as excinfo:
        sparql.query(TEST_QUERY)

    assert excinfo.value.body == "bad �"
