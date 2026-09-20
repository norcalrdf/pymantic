# Changelog

All notable changes to pymantic are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Releases before
1.0.1 were not documented.

## [Unreleased]

### Security

- The Turtle serializer now escapes literal strings. Previously a literal
  containing `"` or `\` was written unescaped, so a crafted value could inject
  extra triples into serialized output.
- The Turtle serializer percent-encodes characters that are illegal in an IRI
  (`<`, `>`, `"`, `{`, `}`, `|`, `^`, backtick, backslash, and control
  characters and space), closing the same injection path through IRIs.
- Turtle numeric and boolean literals use bare syntax only when their values
  match the corresponding Turtle grammar; other values remain quoted typed
  literals. Base and prefix declaration IRIs are escaped too.
- Turtle and N-Triples serialization reject invalid language tags, and Turtle
  serialization rejects invalid prefix names, preventing these fields from
  introducing additional RDF statements.
- The JSON-LD parser no longer fetches remote `@context` or `@import` URLs by
  default. Parsing an untrusted document could previously make the parsing
  host issue HTTP requests to arbitrary servers. See *Changed* for how to opt
  in.
- The SPARQL client now applies a request timeout (30 seconds by default), so
  a slow or hostile endpoint can no longer block the caller indefinitely.
- `SPARQLQueryException` no longer includes the full response headers and
  body in its message, which could leak endpoint credentials into logs.
- `requests` must now be 2.32.0 or newer (fixes CVE-2024-35195).

### Changed

- pymantic requires Python 3.10 or newer. Python 3.12, 3.13, and 3.14 are
  tested in CI.
- `pymantic.parsers.jsonld`: documents that reference a remote context raise
  `RemoteContextsDisabledError` (a `pyld.jsonld.JsonLdError` subclass) unless
  a pyld document loader is supplied, either per parser instance with
  `PyLDLoader(document_loader=...)` or per call with
  `parse_json(..., options={"documentLoader": ...})`. Inline contexts are
  unaffected.
- `SPARQLServer` accepts a `timeout` keyword. Pass `timeout=None` to restore
  the previous wait-forever behaviour.
- `SPARQLServer.query` only accepts and returns
  `application/sparql-results+json` (a dict). Any other response content type
  raises `UnknownSPARQLReturnTypeException`, as does a response with no
  content type (previously a `KeyError`).
- `SPARQLQueryException` is now constructed as
  `SPARQLQueryException(status_code, content_type, body, query)` and exposes
  those four attributes. `body` is decoded as UTF-8 with replacement and
  truncated to 1000 characters.
- Turtle output: datatyped literals are written with `^^` (previously a
  single `^`, which is not valid Turtle); prefixed names with reserved
  characters in the local part carry backslash escapes (for example
  `ex:foo\;bar`) or fall back to the full `<iri>` form; serialized blank nodes
  are written as `_:b0`, `_:b1`, ... (previously `_b0`, which did not parse).
- Invalid language tags and Turtle prefix names raise `ValueError` during
  serialization.
- Blank node labels are generated from a process-wide counter (`b0`, `b1`,
  ...) instead of being derived from the object's memory address.
- N-Triples output escapes control characters as `\uXXXX` instead of
  silently dropping them.

### Removed

- `pymantic.sparql.UpdateableGraphStore` and `PatchableGraphStore`. They
  relied on Python 2 URL functions and have not worked on Python 3.
- The `output="xml"` option of `SPARQLServer.query` and the RDF/XML, Turtle,
  and SPARQL XML result handling, which could not run on Python 3.
- `pymantic.parsers.rdfxml`, an RDF/XML parser that was never exported and
  did not function.
- `pymantic.vocab.skos`, which has been unimportable since the Python 3 port.
- The unpackaged `pymantic/scripts` directory.
- The direct dependency on `lxml`. Nothing in pymantic imports it any more.

### Added

- `CHANGELOG.md` (this file).
- Releases are published to PyPI with trusted publishing from a GitHub
  release. See `RELEASING.md`.
- Dependabot configuration for Python dependencies and GitHub Actions.

## [1.0.1] - 2025-10-02

- Allow newer lark releases.

[Unreleased]: https://github.com/norcalrdf/pymantic/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/norcalrdf/pymantic/compare/v1.0.0...v1.0.1
