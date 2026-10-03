# Changelog

All notable changes to pymantic are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Releases before
1.0.1 were not documented.

## [Unreleased]

### Added

- `pymantic.compare`, with `isomorphic(a, b)` to decide whether two graphs
  or datasets are the same up to blank node labels, and
  `canonical_labels(graph)` to give every blank node a label derived from
  the graph's content alone. Both raise `Undecidable` for a graph built so
  that no content tells its blank nodes apart (a large clique of blank
  nodes, for instance) rather than search for an exponential time; the work
  allowed is polynomial in each group of connected blank nodes, and
  `work_limit=` lowers it. The approach is described in
  `docs/graph-comparison.rst`.
- `stable=True` on `serialize_turtle`, `serialize_ntriples` and
  `serialize_nquads`. Blank nodes are then named by `canonical_labels` and
  statements are written in an order derived from content, so the same graph
  always produces the same bytes and a small edit produces a small diff. In
  Turtle, a blank node referenced exactly once is written inline as
  `[ ... ]`, nested up to 32 levels deep (`MAX_INLINE_DEPTH`), beyond
  which nodes keep a labelled block; each level is indented four columns,
  and only the prefixes the output uses are declared. The default is
  `False`.
- `profile=None` on the Turtle parser's `parse`, `parse_string` and
  `TurtleTransformer`. With a `Profile`, the document's `@prefix` and
  `PREFIX` declarations are recorded in it, so
  `serialize_turtle(graph, f, profile=profile, stable=True)` writes the
  document back with its own prefixes. Prefixes already in the profile are
  not used to read the document.
- Line-TriG, a line-oriented profile of TriG defined in `docs/line-trig.rst`:
  one statement per line in N-Triples term syntax, `G { S P O . }` for a
  triple in a named graph and `G { }` for an empty named graph, which
  N-Quads cannot express. `pymantic.parsers.linetrig_parser` reads it into a
  `Dataset`, rejecting any line outside the profile with its line number,
  and `serialize_linetrig(dataset, f)` writes it. Every Line-TriG document
  is a TriG document with the same meaning.
- `Graph.subjects(predicate, object)`, `Graph.predicates(subject, object)`
  and `Graph.objects(subject, predicate)` yield the matching terms directly,
  and `Graph.predicate_objects(subject)` yields a subject's (predicate,
  object) pairs. None of them builds a `Triple`, so they are cheaper than
  reading the same positions from `match`.
- RDF 1.2 triple terms and base direction. A `Triple` may be the object of a
  triple, and `Literal` has a fourth field, `direction` (`"ltr"` or
  `"rtl"`), for `rdf:dirLangString` literals. `createLiteral` and
  `Resource.objects_by_lang` take `direction=`. N-Triples, N-Quads,
  Line-TriG and Turtle read and write triple terms and base direction, and
  `pymantic.compare` and `stable=True` handle graphs that hold them. Line-TriG
  is the only format that holds every RDF 1.2 dataset.

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
- The N-Quads serializer now writes terms in their N-Triples forms with
  escaping. Previously it wrote bare values with no quoting, so output was
  both unparseable and open to injection through literal values.
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

- JSON-LD support is an optional extra. Install it with
  `pip install 'pymantic[jsonld]'`; a plain `pip install pymantic` no longer
  pulls in pyld or its lxml dependency, which cannot be installed on PyPy
  3.12 or Pyodide. Without the extra, the rest of pymantic works, and
  importing `pymantic.parsers.jsonld`, or importing `jsonld_parser` from
  `pymantic.parsers`, raises an `ImportError` naming the extra.
- `Graph` and `Dataset` keep their triples in a new index: each term is
  interned to an integer id, and each triple is one packed integer key plus
  one entry in each of three orderings (SPO, POS, OSP), held in tuples of
  ints that Python's cyclic garbage collector does not track. With the FHIR
  R5 examples loaded as one graph (645,566 triples) on Python 3.14, a full
  `gc.collect()` takes about 61 ms instead of 411 ms, the index adds no
  collector-tracked objects per triple instead of 3.79, and it takes 421
  bytes per triple instead of 1030. Loading the triples into a graph takes
  0.68 s instead of 1.59 s. Writing Turtle is slower: 1.64 s instead of
  1.44 s by default, and 7.73 s instead of 7.42 s with `stable=True`.
- `match` with any term bound yields triples in index order (by term id)
  rather than in the order they were added per subject. The default Turtle
  output's order (of blocks, of blank node labels, and of objects under a
  predicate) follows that order and is not guaranteed. `stable=True` output
  and `pymantic.compare` are unchanged.
- `subjects()`, `predicates()` and `objects()` with no arguments return lists
  of the distinct terms in term-id order, instead of dict key views in
  first-seen order.
- `match` and iteration return the graph's own instance of each term, equal
  to the one that was added but not necessarily the same object.
- `Graph.add` and `Graph.remove` raise `TypeError` for anything that is not
  a triple of three terms, so a `Quad` can no longer be put in a `Graph`.
  The N-Quads and JSON-LD parsers create a `Dataset` and raise `TypeError`
  if given a `Graph`.
- `Graph()` without a name has `uri` `None` instead of `NamedNode("None")`.
- `Dataset` keeps one term dictionary for all its graphs, so a blank node is
  the same node in every graph it appears in, including as a graph name. An
  empty named graph persists until `remove_graph`. `Triple in dataset`
  checks only the default graph, a `Quad` is checked in its own graph, and
  `in` returns a `bool`. `add_graph` copies the graph's triples in, so later
  edits to the `Graph` passed do not reach the dataset. `Dataset.graphs`
  lists the default graph first, always.
- Every `Literal` carries a datatype, as RDF 1.1 Concepts requires: a literal
  built with neither datatype nor language gets `xsd:string`, and one built
  with a language gets `rdf:langString`. `Literal("v")` and
  `Literal("v", datatype=XSD_STRING)` are therefore equal and hash alike, and
  a `Graph` given both holds one triple instead of two. An empty language
  tag counts as none. Giving a language together with any other datatype,
  or `rdf:langString` without a language, raises `ValueError`.
  Serialization is unchanged: a simple literal is still written `"v"` and a
  language-tagged string `"v"@en`, with no datatype.
- Turtle output writes a subject wider than 40 columns on a line of its
  own, with its predicates indented four columns, instead of lining the
  predicates up after it. Subjects up to 40 columns are written as before.
- Turtle and N-Triples serialization are faster, with the same output.
  Measured on Python 3.14 against the previous code: Turtle 1.6 to 2.4
  times (the FHIR R5 examples, 645k triples, 2.7 s to 1.5 s) and N-Triples
  about 9 times (4.6 s to 0.5 s).
- Numeric escapes that produce surrogate code points (`\uD800` to `\uDFFF`)
  or values above U+10FFFF are rejected in all parsers, as the Turtle and
  N-Triples grammars require.
- The N-Triples and N-Quads parsers reject relative IRIs and `:` inside blank
  node labels, and require language subtags of at most eight characters.
  A literal typed `rdf:langString` without a language tag is rejected.
- pymantic requires Python 3.10 or newer. Python 3.10 through 3.14 are
  tested in CI. Python 3.10 reached end of life in October 2026, and a
  future release will drop support for it.
- `pymantic.parsers.jsonld`: documents that reference a remote context raise
  `RemoteContextsDisabledError` (a `pyld.jsonld.JsonLdError` subclass) unless
  a pyld document loader is supplied, either per parser instance with
  `PyLDLoader(document_loader=...)` or per call with
  `parse_json(..., options={"documentLoader": ...})`. Inline contexts are
  unaffected. `UnsafePyLDLoader` is a parser that fetches remote
  contexts by default, for trusted documents.
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
- N-Triples and N-Quads output follows the canonical N-Triples rules of
  RDF 1.2: characters outside ASCII are written raw rather than as `\u`
  escapes, backspace and form feed are written `\b` and `\f`, and a simple
  literal is written without `^^xsd:string`.
- `Literal` lowercases its language tag on construction
  (`Literal("x", "EN").language == "en"`), so literals whose tags differ
  only in case are equal, as RDF Concepts requires, and serialize in
  canonical form.
- `Graph` iterates over its triples in insertion order. `Graph.toArray()`
  still returns a `frozenset`.
- N-Triples output escapes control characters as `\uXXXX` instead of
  silently dropping them.
- N-Triples and N-Quads output writes non-ASCII characters in IRIs as they
  are. Previously they were percent-encoded, so `<http://x/é>` came back
  from a round trip as `<http://x/%C3%A9>`, a different IRI, and the two
  could not be told apart in output. Characters no IRI may contain are
  still percent-encoded, as in Turtle output.
- `Dataset` lookups no longer create the graph they are asked about. Only
  `add` and `add_graph` create a named graph; `match(graph=name)` on an
  unknown graph yields nothing and leaves the dataset alone, and `remove`
  raises `KeyError` for a quad in a graph the dataset does not have. An
  empty named graph is part of a dataset and is counted by
  `pymantic.compare`, so a query must not bring one into being.
- `Literal` is a four-field tuple: code that unpacks a literal as
  `(value, language, datatype)` breaks and must also take `direction`.
- A base direction must be lowercase, `--ltr` or `--rtl`, in N-Triples,
  N-Quads and Turtle; the W3C suites reject `--LTR`.
- The W3C RDF 1.2 expected-failure list shrank by 49 tests: 24 N-Triples and
  N-Quads, 15 Turtle parser, and 10 Turtle writer round-trip and stable
  output.
- `pyoxigraph` joined the `testing` extra, on CPython outside Pyodide, as the
  oracle that compares graphs holding RDF 1.2 terms; rdflib cannot represent
  them.

### Fixed

- `Graph.subjects()`, `predicates()` and `objects()` no longer return a term
  whose last triple was removed.
- `Graph.removeMatches` and `Dataset.removeMatches` no longer raise
  `RuntimeError` when more than one triple matches.
- `Graph.removeMatches` takes keyword arguments with `None` wildcards, like
  `match` (it required all three positions).
- A falsy term such as `NamedNode("")` passed to `match` is matched as a
  term instead of being treated as a wildcard.
- `Dataset.remove_graph` removes the graph; it did nothing before.
- The Turtle serializer no longer fails with `RecursionError` on a list
  nested a few hundred levels deep, such as `((((...))))`. Past 32 levels
  the inner list is written as a labelled blank node with its `rdf:first`
  and `rdf:rest` triples, which reads back as the same list.
- Shrinking an IRI to a prefixed name only strips the leading namespace.
  Previously every occurrence of the namespace inside the IRI was replaced,
  corrupting IRIs that embed their own namespace (for example in a query
  string).
- The Turtle serializer declares the `rdf` prefix when it uses it. Output
  containing `rdf:type` previously only parsed with pymantic's own parser.
- The N-Triples parser accepts digits in language subtags (for example
  `@zh-Hant-1`); a typo in the grammar limited them to `0`, `_`, and `9`.
- The Turtle serializer writes RDF collections that contain IRIs, blank
  nodes or nested lists; previously it raised `AttributeError`. Statements
  whose subject is a collection (`(1) :p :o .`) are written as such;
  previously they were dropped from the output, as was any named node that
  carried `rdf:first`/`rdf:rest`. Lists that are not well formed (extra
  predicates on a cell, several references, cycles) are written as ordinary
  triples instead of being mangled or omitted.
- N-Triples and N-Quads serialization write triples in the order they were
  added to the graph. Previously the order depended on `PYTHONHASHSEED`.
- The N-Quads parser accepts statements without a graph label (the default
  graph, represented as `Quad(..., graph=None)`) and blank node graph labels.
  Previously 46 of the 53 positive W3C N-Quads tests failed.
- The N-Triples and N-Quads parsers accept comments, statements with no
  whitespace between terms, and comment or blank lines when reading a stream
  line by line.
- `serialize_nquads` writes a quad in the default graph (`graph=None`, as
  produced by the N-Quads and JSON-LD parsers) as a triple line; previously
  it raised `AttributeError`.
- The N-Triples and N-Quads grammar's range of astral characters was written
  with a literal character instead of an escape, so digits and `:` matched as
  letters inside blank node labels.
- The Turtle parser no longer corrupts the graph when a blank node property
  list or collection is followed by `,` in an object list; previously a
  Python generator object was stored as the object term.
- Relative IRI resolution follows RFC 3986 exactly, including empty path
  segments (`http://ab//de//ghi` + `xyz`) and `..` across them. The
  `urllib.parse.urljoin` based `smart_urljoin` remains as an alias of the new
  `pymantic.util.resolve_iri`.

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

- The W3C RDF 1.1 and 1.2 test suites for N-Triples, N-Quads and Turtle are
  vendored under `tests/w3c` and run by `tests/test_w3c.py`, including a
  serializer round trip for every Turtle evaluation test and the canonical
  N-Triples tests. Tests pymantic does not pass yet are listed with reasons
  in `tests/w3c/expected_failures.txt`; at the time of writing all of them
  need RDF 1.2 syntax. `tests/w3c/sync_from_upstream.py` refreshes the copy.
  The 2013 Turtle suite under `tests/TurtleTests` is replaced by this.
- pymantic runs on PyPy 3.12, GraalPy 3.12 and 3.13, Pyodide 3.12 and 3.14,
  and Python 3.15 (tested on 3.15.0rc2). JSON-LD support is not available on
  PyPy 3.12 or Pyodide. `tox` has an environment for each of these, plus
  CPython 3.11 to 3.14, provisioned through `tox-uv`; CI does not run them
  yet. `tox -e core`, which CI does run, tests without the `jsonld` extra.
- `CHANGELOG.md` (this file).
- Releases are published to PyPI with trusted publishing from a GitHub
  release. See `RELEASING.md`.
- Dependabot configuration for Python dependencies and GitHub Actions.

## [1.0.1] - 2025-10-02

- Allow newer lark releases.

[Unreleased]: https://github.com/norcalrdf/pymantic/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/norcalrdf/pymantic/compare/v1.0.0...v1.0.1
