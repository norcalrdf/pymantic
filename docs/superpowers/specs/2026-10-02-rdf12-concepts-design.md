# RDF 1.2 concepts design

Date: 2026-10-02. Branch `rdf12/concepts`, from `graph-index-on-25` (b4eacd5).

## Why

pymantic 2.0.0 ships the RDF 1.2 changes to the data model: triple terms and
base direction. Both change primitives, so shipping them after 2.0 would force
a 3.0. Reified triples, annotations, reifiers and `VERSION` are syntax over
that model and can follow in 2.x.

What [RDF 1.2 Concepts](https://www.w3.org/TR/rdf12-concepts/) changes, and
what this branch does about it:

| Concept | This branch |
|---|---|
| Triple terms (3.6), nested, object position only | Yes |
| Directional language-tagged strings, `rdf:dirLangString` (3.4) | Yes |
| Isomorphism maps blank nodes inside triple terms (3.7) | Yes |
| Language tags compare case-insensitively | Already done: `Literal` lowercases |
| Ill-typed literals SHOULD be accepted | Already done |
| Full and Basic conformance, version labels (2, 2.1) | pymantic is Full; no version handling |
| `rdf:JSON` datatype (A.3) | Nothing to do: any datatype IRI works |
| `rdf:reifies` | An ordinary predicate; nothing to do |

## Goals

- `Triple` is a term and can be the object of another triple, nested to any
  depth.
- `Literal` carries an optional base direction.
- Parsers and serializers for N-Triples, N-Quads, Line-TriG and Turtle read
  and write both.
- `compare.isomorphic`, `compare.canonical_labels` and `stable=True` handle
  blank nodes inside triple terms.
- **No existing digest or stable output changes.** Every literal without a
  direction keeps its `term_key`, so its `term_code` (the first 8 bytes of
  SHA-256 over the key), every canonical label and every `stable=True` byte
  stay the same.
- The W3C xfails for triple terms and base direction pass.

Out of scope: Turtle `<< … >>` reified triples, `{| … |}` annotations,
`~ reifier`, `VERSION` parsing and writing, JSON-LD changes, SPARQL 1.2
results formats, and wildcards inside triple-term patterns.

## Design

### Triple as a term

A triple term is a `Triple`. RDF 1.2 defines a triple term as an RDF triple,
and `Triple` is already a hashable tuple, so a second class would only add
conversions.

- `Triple(s, p, o)` may appear as the object of a triple, at any depth.
- `Triple.toNT()` returns `<<( s p o )>>`, calling `toNT()` on each part. This
  is canonical N-Triples: one space after `<<(` and after each part.
- Parsers enforce the term rules (subject an IRI or blank node, predicate an
  IRI). `Graph.add` does not validate statements today and does not start.
- `Quad` is not a term.

### Term-kind equality

`Literal` and `Triple` are both 3-tuples, and `NamedNode` is a `str`, so
today a literal can equal a triple:

```python
l = Literal("x", "en")                     # ("x", "en", rdf:langString)
t = Triple(NamedNode("x"), NamedNode("en"), l.datatype)
l == t, hash(l) == hash(t)                 # True True
```

Once triple terms sit in `TermDictionary` beside literals, such a pair would
share an id. Shape separates them: `Literal` becomes a 4-tuple (next
section), and a 4-tuple never equals a 3-tuple. A test pins
`Literal != Triple` with unequal hashes, so a later change of shape fails
loudly.

Class-aware `__eq__` and `__hash__` were rejected: replacing tuple's C
methods with Python ones made interning an equal, non-identical literal about
4x slower on 3.14 (31 ns to 129 ns), on the parse path the graph index was
tuned for. What remains is harmless: a `Literal` can equal a `Quad` (both
4-tuples), but quads are never interned as terms, and `Triple(a, b, c)` still
equals `(a, b, c)`.

### Literal direction

`Literal(value, language=None, datatype=None, direction=None)` is a 4-tuple.
A literal takes one of three shapes:

| Kind | language | datatype | direction |
|---|---|---|---|
| Typed or simple | None | the datatype, default `xsd:string` | None |
| Language-tagged | the tag | `rdf:langString` | None |
| Directional | the tag | `rdf:dirLangString` | `"ltr"` or `"rtl"` |

- `direction` is lowercased like `language`, then must be `"ltr"` or `"rtl"`;
  anything else raises `ValueError`. RDF has no default direction: `None`
  means absent, which is a different term from `"ltr"`.
- A direction without a language raises `ValueError`.
- With a direction, the datatype defaults to `rdf:dirLangString`; any other
  explicit datatype raises. `rdf:dirLangString` without a direction raises,
  as `rdf:langString` without a language does today.
- `language` stays a bare BCP 47 tag. The constructor does not accept the
  combined `"he--rtl"` form; parsers split it.
- `toNT()` writes `"…"@he--rtl`. `__repr__`, `_asdict`, `_replace` and
  `__getnewargs__` include the direction.

The value strings follow Python practice: Babel's `Locale.text_direction` and
HTML and CSS use lowercase `ltr` and `rtl`, and python-bidi uses `None` for an
unspecified base direction.

### Direction API

A `direction=` keyword, next to every existing `language` argument:

- `Literal(value, language, datatype, direction=None)`
- `RDFEnvironment.createLiteral(value, language=None, datatype=None,
  direction=None)`
- `Resource.objects_by_lang(predicate, lang=None, direction=None)`: with a
  direction, only literals in that direction. `objects_by_lang(p, "he")`
  matches Hebrew literals of any direction.

There are no per-language or per-direction helper functions. The `Literal`
docstring shows `functools.partial` as the way to make one:

```python
he_rtl = partial(Literal, language="he", direction="rtl")
he_rtl("שלום")    # "שלום"@he--rtl
```

`util.en` and `util.de` (unused and untested since 2010) are left alone here;
whether 2.0 removes them is a separate decision.

`rdf.IMPLIED_DATATYPES` gains `rdf:dirLangString`, so
`objects_by_datatype(p)` does not count it as a written datatype. The
`Resource` key filter (`r['rdfs:label', 'en']`) does not gain a direction
form.

### Term dictionary and graph matching

`TermDictionary` interns a whole triple term as one value. Its parts are not
interned separately, and the graph and index need no change.

`Graph.match` and `Dataset.match` take a fully bound triple term as the object
of a pattern. A `None` anywhere inside a triple term raises `ValueError`. A
later release can make that a wildcard without breaking callers, and can add
an index from part ids to triple-term ids without changing this design.

### Parsers

N-Triples and N-Quads (Lark grammars), and Line-TriG through the N-Triples
grammar:

- `object` gains `tripleTerm: "<<(" subject predicate object ")>>"`.
- `LANGTAG` gains an optional `--` direction, following the RDF 1.2 grammar:
  `'@' [a-zA-Z]+ ('-' [a-zA-Z0-9]+)* ('--' [a-zA-Z]+)?`, keeping the existing
  8-character subtag limit. The transformer splits the tag into language and
  direction; `Literal` rejects a direction other than `ltr` or `rtl`.

Turtle:

- `object` gains `tripleTerm ::= '<<(' ttSubject verb ttObject ')>>'`, with
  `ttSubject ::= iri | BlankNode` and
  `ttObject ::= iri | BlankNode | literal | tripleTerm`. `BlankNode` includes
  `[]` (`ANON`); property lists and collections are not allowed inside.
- `LANGTAG` gains the same `--` direction.
- Reified triples, annotations, reifiers and `VERSION` remain parse errors.

### Serializers

- N-Triples, N-Quads and Line-TriG write terms through `toNT()` and need
  nothing more.
- The Turtle writer writes triple terms as `<<( … )>>` and directional
  literals as `"…"@he--rtl`. A blank node that occurs inside a triple term is
  never inlined as `[ … ]`; it always gets a label.
- No serializer writes `VERSION "1.2"`. The spec encourages it, but pymantic
  cannot parse it yet; it arrives with `VERSION` parsing.
- pymantic has no JSON-LD serializer. The JSON-LD parser is unchanged: JSON-LD
  1.1 has no triple terms, and pyld drops `@direction` unless asked.

### compare

`term_key` gains two cases and keeps every existing key:

- A directional literal appends `--ltr` or `--rtl` after its language. No
  existing key contains `--` after `@`, since BCP 47 tags cannot.
- A ground triple term (no blank nodes at any depth) has the key
  `<<( k k k )>>` built from its parts' keys. It is a ground term like an IRI.

A triple term that contains blank nodes is flattened before molecules are
split. `statements()` replaces each distinct such term with a helper blank
node `t` and adds three statements, `(t, TT_SUBJECT, s)`,
`(t, TT_PREDICATE, p)` and `(t, TT_OBJECT, o)`. A nested term is flattened
first, so its helper is the `s` or `o` of the outer one. The markers are
reserved keys that start with neither `<` nor `"`, so no real term key equals
one.

This preserves isomorphism in both directions: a bijection on blank nodes
induces a bijection on triple terms, so one helper per distinct term matches
exactly when the graphs do. Molecules, refinement, twin pruning and the work
cap run unchanged. Helpers count toward the cap, so a graph with many
non-ground triple terms reaches it sooner. `canonical_labels` drops the
helpers from its result. A graph without triple terms is not flattened at
all, so its statements, labels and digests are unchanged.

## Behavior changes (for the changelog)

- Triple terms: `Triple` may be the object of a triple.
- `Literal` has a fourth field, `direction`; code that unpacks a literal as
  three values breaks.
- `rdf:dirLangString` literals.
- `direction=` on `createLiteral` and `Resource.objects_by_lang`.- N-Triples, N-Quads, Line-TriG and Turtle read and write triple terms and
  base direction.

## Testing

Test-driven throughout, on `tox -e py314` while working.

**Oracle.** The W3C harness and the compare-manifest cross-check convert
graphs to rdflib and use `rdflib.compare.isomorphic`, but rdflib 7.6.0
cannot represent triple terms or directions (its parser rejects both).
Graphs containing either are compared with pyoxigraph instead, a Rust
implementation with RDF 1.2 support: both sides are written as N-Quads,
loaded into `pyoxigraph.Dataset`, canonicalized with
`CanonicalizationAlgorithm.UNSTABLE` and compared with `==`. pymantic's own
`compare` is never the oracle for its own output. Graphs with only RDF 1.1
terms keep rdflib, so no existing test changes.

pyoxigraph joins the `testing` extra as
`pyoxigraph>=0.5.11; platform_python_implementation == "CPython"`. PyPI has
wheels for CPython 3.10 to 3.14 and abi3 for 3.15, but none for PyPy 3.12,
GraalPy or Pyodide. There, a test that needs the oracle skips with the reason
"pyoxigraph, the RDF 1.2 oracle, is not available on this interpreter".

1. **Golden digests, first commit.** On b4eacd5, before any change, record
   `term_code` for a spread of literals (simple, typed, language-tagged,
   escapes, non-ASCII) and the `stable=True` N-Triples, N-Quads and Turtle
   output of every W3C test input that parses today, stored as one SHA-256
   per input. A test asserts both.
2. **Primitives.** The Literal/Triple collision (unequal, unequal hashes,
   distinct dictionary ids); every allowed and rejected direction,
   language and datatype combination; direction case; nested `toNT()`;
   interning and matching triple terms; `ValueError` for `None` inside a
   triple-term pattern.
3. **Resource.** `objects_by_lang` with and without direction;
   `objects_by_datatype` with directional literals; `createLiteral`; the
   docstring's `partial` example as a doctest-style test.
4. **compare.** Isomorphic and non-isomorphic pairs with blank nodes inside
   triple terms, nested two deep, with one blank node both asserted and inside
   a triple term, and pairs that differ only in direction. `canonical_labels`
   returns no helper nodes.
5. **W3C suites.** Remove each xfail line as its test passes and report the
   exact count. Expected: the 24 N-Triples and N-Quads lines, the two Turtle
   `nt-ttl12-langdir` lines, and the Turtle lines that test only triple
   terms.
6. **Round trips.** Parse, write, parse through N-Triples, N-Quads, Line-TriG
   and Turtle, with and without `stable=True`. Line-TriG also round-trips one
   dataset that uses everything at once: an empty named graph, nested triple
   terms with blank nodes inside, and directional literals.
7. **Interpreters.** The full tox interpreter matrix before finishing.

Docs: `CHANGELOG.md`, `docs/graph-comparison.rst` (flattening) and
`docs/line-trig.rst`. Line-TriG inherits both features, which makes it the
only format pymantic reads and writes that holds every RDF 1.2 dataset:
N-Quads cannot write an empty named graph, and N-Triples and Turtle hold one
graph. (Turtle's missing reifiers and annotations are shorthand for triples it
can already write, so they cost no expressiveness.) `line-trig.rst` says so.

## Future work

- Turtle reified triples, annotations and reifiers.
- `VERSION` parsing and writing.
- Wildcards inside triple-term patterns, with an index from part ids to
  triple-term ids.
- JSON-LD `@direction` through pyld's `rdfDirection` option
  (`'i18n-datatype'` or `'compound-literal'`).
- A Jena 6.1+ cross-check script (Jena has RDF 1.2 syntax since 6.1.0),
  run by hand, not in CI. Its graph comparison CLI is unverified: the tool
  docs list `rdfdiff`.
