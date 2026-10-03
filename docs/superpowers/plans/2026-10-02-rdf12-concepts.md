# RDF 1.2 Concepts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Triple terms and base direction in pymantic's data model, parsers, serializers and graph comparison, for 2.0.0.

**Architecture:** A triple term is a `Triple` in object position, interned whole by `TermDictionary`. `Literal` becomes a 4-tuple with a `direction` field. `compare.statements()` flattens non-ground triple terms into helper blank nodes so the molecule algorithm runs unchanged.

**Tech Stack:** Python 3.10+, Lark (LALR) grammars, pytest, tox + tox-uv, pyoxigraph (test oracle).

**Spec:** `docs/superpowers/specs/2026-10-02-rdf12-concepts-design.md`

## Global Constraints

- Branch `rdf12/concepts`, based on `graph-index-on-25` (b4eacd5).
- Work and test with `uvx --with tox-uv tox -e py314`; a single test with `uvx --with tox-uv tox -e py314 -- tests/test_x.py::test_y -q`.
- **No existing digest or stable output changes.** `term_key` stays byte-identical for every literal without a direction; Task 1's golden test enforces it and must pass after every task.
- `direction` values: `"ltr"`, `"rtl"` or `None`, lowercased on construction. `rdf:dirLangString` is `http://www.w3.org/1999/02/22-rdf-syntax-ns#dirLangString`.
- Canonical triple-term form: `<<( s p o )>>`, one space after `<<(` and after each part.
- No class-aware `__eq__`/`__hash__` on `Triple`, `Quad` or `Literal` (4x intern slowdown; spec "Term-kind equality").
- A `None` inside a triple-term pattern raises `ValueError`; it never silently matches nothing.
- pymantic's own `compare` is never the oracle for RDF 1.2 test results; pyoxigraph is.
- Out of scope: reified triples `<< >>`, annotations `{| |}`, reifiers `~`, `VERSION`, JSON-LD changes. Their xfail lines stay.
- Follow repo style: black 26.5, isort, flake8 (`tox -e lint`). Comments explain why, not history.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- **A blank node that appears both asserted and inside a triple term** must keep one identity through parse, `stable=True` labels, Turtle output and back. Tested in Tasks 5 and 7.
- **Direction case** (`@en--LTR`, `direction="RTL"`) normalizes to lowercase; anything other than ltr/rtl (`@en--up`) is rejected by every parser. Tested in Tasks 2, 4 and 6.
- **A blank node that occurs only inside a triple term** must not be written by the Turtle writer as `[ … ]` or as an unlabelled `[]` subject block. Tested in Task 7.
- **`Literal._make` and `_replace`** with three fields keep working for existing callers, and `_replace(language=None)` on a directional literal clears the direction rather than raising. Tested in Task 2.
- **A triple term containing a directional literal** gets distinct keys and codes from the same term without direction. Tested in Task 5.

---

### Task 1: Golden digests

Record what the base produces today, so every later task proves it moved no digest. Run this task before touching `src/`.

**Files:**
- Create: `tests/stable_digests.py` (recorder script and shared corpus code)
- Create: `tests/fixtures/stable_digests.json`
- Create: `tests/test_stable_digests.py`

**Interfaces:**
- Produces: `tests.stable_digests.corpus() -> list[tuple[str, object]]` (test id, parsed graph or dataset) and `tests.stable_digests.digests() -> dict`, the JSON-ready record.

- [ ] **Step 1: Write `tests/stable_digests.py`**

A module docstring says when to run it: "Re-record only when a change is meant to move digests; the test then shows exactly which." `python -m tests.stable_digests --write` writes the fixture; with no argument it prints how many entries differ from the fixture and the first 10 ids. `--help` via argparse.

`corpus()` reuses `tests.test_w3c.ENTRIES`, `EXPECTED_FAILURES` and `parse_action`: every entry whose kind is `TestTurtleEval`, ends in `PositiveSyntax` or ends in `PositiveC14N`, whose id is not in `EXPECTED_FAILURES`.

`digests()` returns:
```python
{
  "term_codes": {term_key(lit): term_code(term_key(lit)) for lit in LITERALS},
  "outputs": {test_id: {"nt" or "nq": sha256hex, "ttl": sha256hex (graphs only)}},
}
```
`LITERALS` is a fixed list in the module: `Literal("")`, `Literal("chat")`, `Literal("chat", "fr")`, `Literal("chat", "EN-gb")`, `Literal("5", datatype=XSD("integer"))`, `Literal("a\"b\\c\nd\te")`, `Literal("café 日本 \U0001f600")`, `Literal("\x00\x7f")`, `Literal("x", datatype=NamedNode("http://example/dt"))`. Outputs use `serialize_ntriples`/`serialize_nquads`/`serialize_turtle` with `stable=True`; sha256 of the UTF-8 bytes.

- [ ] **Step 2: Record the fixture on the unchanged base**

Run, from the worktree root: `PYTHONPATH=src /Users/gavin/Programing/pymantic/.claude/worktrees/venv-314/bin/python -m tests.stable_digests --write`. `PYTHONPATH=src` matters: that venv's editable install points at another worktree.
Expected: writes `tests/fixtures/stable_digests.json` with several hundred `outputs` entries.

- [ ] **Step 3: Write `tests/test_stable_digests.py`**

```python
def test_term_codes_unchanged():
    assert digests()["term_codes"] == recorded()["term_codes"]

def test_stable_outputs_unchanged():
    now, then = digests()["outputs"], recorded()["outputs"]
    changed = sorted(k for k in then if now.get(k) != then[k])
    assert not changed, changed[:10]
```
`recorded()` loads the JSON. Entries that later start passing W3C tests are new ids and are not compared.

- [ ] **Step 4: Run it**

Run: `uvx --with tox-uv tox -e py314 -- tests/test_stable_digests.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit** — "Pin term codes and stable output before RDF 1.2 work"

---

### Task 2: Literal direction

**Files:**
- Modify: `src/pymantic/primitives.py` (`Literal`, `__all__`, constants, `RDFEnvironment.createLiteral`)
- Test: `tests/test_primitives.py`

**Interfaces:**
- Produces: `Literal(value, language=None, datatype=None, direction=None)`, a 4-tuple `(value, language, datatype, direction)`; `Literal.direction`; `RDF_DIRLANGSTRING` exported from `pymantic.primitives`; `RDFEnvironment.createLiteral(value, language=None, datatype=None, direction=None)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_directional_literal():
    lit = Literal("שלום", "he", direction="rtl")
    assert lit.direction == "rtl"
    assert lit.datatype == RDF_DIRLANGSTRING
    assert lit.toNT() == '"שלום"@he--rtl'

def test_direction_is_lowercased():
    assert Literal("x", "EN", direction="LTR") == Literal("x", "en", direction="ltr")

@pytest.mark.parametrize("kwargs", [
    dict(direction="up", language="en"),                 # not ltr/rtl
    dict(direction="ltr"),                                # no language
    dict(direction="ltr", language="en", datatype=RDF_LANGSTRING),
    dict(direction="ltr", language="en", datatype=XSD_STRING),
    dict(datatype=RDF_DIRLANGSTRING),                     # dirLangString, no direction
    dict(datatype=RDF_DIRLANGSTRING, language="en"),
])
def test_rejected_direction_combinations(kwargs):
    with pytest.raises(ValueError):
        Literal("x", **kwargs)

def test_direction_is_part_of_the_term():
    assert Literal("x", "en") != Literal("x", "en", direction="ltr")
    assert Literal("x", "en", direction="ltr") != Literal("x", "en", direction="rtl")

def test_literal_never_equals_triple():
    lit = Literal("x", "en")
    t = Triple(NamedNode("x"), NamedNode("en"), lit.datatype)
    assert lit != t
    d = TermDictionary()
    assert d.intern(lit) != d.intern(t)

def test_make_takes_three_or_four_fields():
    assert Literal._make(("x", "en", None)) == Literal("x", "en")
    assert Literal._make(("x", "en", None, "rtl")).direction == "rtl"

def test_replace_language_clears_direction_and_datatype():
    lit = Literal("x", "he", direction="rtl")
    assert lit._replace(language=None) == Literal("x")
    assert lit._replace(direction=None) == Literal("x", "he")
    assert Literal("x", "he")._replace(direction="rtl") == lit

def test_repr_asdict_pickle_include_direction():
    lit = Literal("x", "he", direction="rtl")
    assert "direction='rtl'" in repr(lit)
    assert lit._asdict()["direction"] == "rtl"
    assert pickle.loads(pickle.dumps(lit)) == lit

def test_partial_makes_a_language_helper():
    he_rtl = partial(Literal, language="he", direction="rtl")
    assert he_rtl("שלום") == Literal("שלום", "he", direction="rtl")

def test_create_literal_direction():
    assert RDFEnvironment().createLiteral("x", "he", direction="rtl").direction == "rtl"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uvx --with tox-uv tox -e py314 -- tests/test_primitives.py -q`
Expected: the new tests FAIL (`TypeError: unexpected keyword argument 'direction'`, `ImportError: RDF_DIRLANGSTRING`); existing tests pass.

- [ ] **Step 3: Implement**

`RDF_DIRLANGSTRING = RDF("dirLangString")` next to `RDF_LANGSTRING`, added to `__all__`. In `Literal.__new__`: lowercase `direction`; reject values other than ltr/rtl; reject direction without language; with direction the datatype must be absent or `RDF_DIRLANGSTRING` and becomes `RDF_DIRLANGSTRING`; without direction, `RDF_DIRLANGSTRING` raises like `RDF_LANGSTRING` does without a language. `_fields` gains `"direction"`. `_make` accepts 3 or 4 fields. `_replace`: changing `language` re-derives the datatype as today, and for `RDF_DIRLANGSTRING` too; `language=None` also clears `direction`; changing `direction` alone re-derives the datatype between `rdf:langString` and `rdf:dirLangString`. `toNT()` appends `--` + direction after the language. Update the class docstring for the fourth field and add the `partial` example. `createLiteral` passes `direction` through.

- [ ] **Step 4: Run tests**

Run: `uvx --with tox-uv tox -e py314 -- tests/test_primitives.py tests/test_stable_digests.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `uvx --with tox-uv tox -e py314 -q`
Expected: PASS, xfails unchanged. Fix any caller that unpacked a literal into three names.

- [ ] **Step 6: Commit** — "Give literals an RDF 1.2 base direction"

---

### Task 3: Triple as a term

**Files:**
- Modify: `src/pymantic/primitives.py` (`Triple`, `_pattern_ids`)
- Test: `tests/test_primitives.py`, `tests/test_index.py`

**Interfaces:**
- Consumes: Task 2's `Literal`.
- Produces: `Triple.toNT() -> str` (`<<( s p o )>>`, recursive); `Triple.interfaceName = "Triple"`; `Graph.match`/`Dataset.match`/`removeMatches` accept a bound triple term and raise `ValueError("a triple term in a pattern must be fully bound")` for `None` at any depth inside one.

- [ ] **Step 1: Write the failing tests**

```python
def test_triple_term_to_nt_nested():
    inner = Triple(NamedNode("http://a"), NamedNode("http://b"), Literal("c", "en", direction="ltr"))
    outer = Triple(BlankNode(), NamedNode("http://p"), inner)
    assert inner.toNT() == '<<( <http://a> <http://b> "c"@en--ltr )>>'
    assert outer.toNT().endswith("<http://p> <<( <http://a> <http://b> \"c\"@en--ltr )>> )>>")

def test_graph_holds_and_matches_triple_terms():
    inner = Triple(ex.s, ex.p, ex.o)
    g = Graph()
    g.add(Triple(ex.r, RDF_REIFIES, inner))
    g.add(Triple(ex.r2, RDF_REIFIES, Triple(ex.s, ex.p, inner)))
    assert [t.subject for t in g.match(None, RDF_REIFIES, Triple(ex.s, ex.p, ex.o))] == [ex.r]
    assert len(list(g.match(None, None, Triple(ex.s, ex.p, inner)))) == 1
    assert str(next(iter(g))) == f"{ex.r.toNT()} {RDF_REIFIES.toNT()} {inner.toNT()} .\n"

@pytest.mark.parametrize("pattern", [
    Triple(None, ex.p, ex.o),
    Triple(ex.s, ex.p, Triple(ex.a, None, ex.c)),
])
def test_unbound_triple_term_pattern_raises(pattern):
    g = Graph()
    with pytest.raises(ValueError, match="fully bound"):
        list(g.match(None, None, pattern))
    with pytest.raises(ValueError, match="fully bound"):
        list(Dataset().match(None, None, pattern))

def test_removing_last_use_frees_triple_term():
    ...  # as test_removing_triples_compacts_the_dictionary in tests/test_index.py:
         # add then remove a triple whose object is a triple term; once compacted,
         # graph._dictionary.lookup(term) is None
```
`ex` and `RDF_REIFIES` are test-local `Prefix`/`NamedNode` values. `Graph.match` is a generator, so the `ValueError` is raised when it is first iterated; either raising at the call or on first iteration is acceptable, and the tests use `list()` to cover both.

- [ ] **Step 2: Run to verify they fail**

Expected: FAIL (`AttributeError: 'Triple' object has no attribute 'toNT'`; no `ValueError`).

- [ ] **Step 3: Implement**

`Triple.toNT()` and `interfaceName`. In `_pattern_ids`, before looking up a bound term that is a `Triple`, walk it (recursively into object position) and raise the `ValueError` above if any part is `None`. No change to `TermDictionary`.

- [ ] **Step 4: Run tests and the full suite**

Run: `uvx --with tox-uv tox -e py314 -q`
Expected: PASS.

- [ ] **Step 5: Commit** — "Let a triple be the object of another triple"

---

### Task 4: N-Triples, N-Quads and Line-TriG syntax

**Files:**
- Modify: `src/pymantic/parsers/lark/ntriples.py` (grammar, transformer), `src/pymantic/parsers/base.py` (`make_language_literal`), `src/pymantic/parsers/lark/turtle.py` (`rdf_literal` caller only)
- Modify: `tests/w3c/expected_failures.txt`
- Test: `tests/test_parsers.py`, `tests/test_linetrig.py`, `tests/test_serializers.py`

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces: `BaseParser.make_language_literal(value, lang=None)` where `lang` may carry `--dir` (it splits on the first `--`); N-Triples rule `triple_term` returning a `Triple`.

- [ ] **Step 1: Write the failing tests**

```python
def test_ntriples_triple_term_and_direction():
    g = ntriples_parser.parse_string(
        '_:r <http://ex/reifies> <<( _:s <http://ex/p> <<( <http://ex/a> <http://ex/b> "c"@en--LTR )>> )>> .\n'
    )
    (t,) = g
    assert isinstance(t.object, Triple)
    assert t.object.object.object == Literal("c", "en", direction="ltr")

@pytest.mark.parametrize("bad", [
    '<http://a> <http://b> "c"@en--up .\n',
    '<<( <http://a> <http://b> <http://c> )>> <http://b> <http://c> .\n',   # not a subject
    '<http://a> <<( <http://a> <http://b> <http://c> )>> <http://c> .\n',   # not a predicate
    '<http://a> <http://b> <<( "x" <http://b> <http://c> )>> .\n',          # literal subject inside
])
def test_ntriples_rejects(bad):
    with pytest.raises(Exception):
        ntriples_parser.parse_string(bad)

def test_linetrig_triple_terms_and_direction():
    ...  # a named-graph line holding a nested triple term with a blank node and
         # a directional literal parses, and serialize_linetrig writes the same line back
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement**

Grammar: `?object` gains `| triple_term`; `triple_term: "<<(" subject predicate object ")>>"`; `LANGTAG: "@" /[a-zA-Z]{1,8}/ ("-" /[a-zA-Z0-9]{1,8}/)* ("--" /[a-zA-Z]+/)?`. The transformer's `triple_term` returns `self.make_triple(...)`. Update the grammar comment to say it is the 1.2 grammar. `make_language_literal` splits `lang` with `partition("--")` and passes `direction` to `createLiteral`. Turtle's `rdf_literal` already calls `make_language_literal`, so it needs no change until Task 6 extends its grammar.

- [ ] **Step 4: Remove xfails and run W3C**

Delete the 24 `rdf12/rdf-n-triples/*` and `rdf12/rdf-n-quads/*` lines. Run: `uvx --with tox-uv tox -e py314 -- tests/test_w3c.py tests/test_parsers.py tests/test_linetrig.py tests/test_stable_digests.py -q`
Expected: PASS; strict xfail means any of the 24 still failing shows up as a failure.

- [ ] **Step 5: Add a sentence to `docs/line-trig.rst`**

Line-TriG uses the N-Triples 1.2 grammar, so it carries triple terms and directional literals.

- [ ] **Step 6: Commit** — "Read and write RDF 1.2 triple terms and directions in N-Triples, N-Quads and Line-TriG"

---

### Task 5: Graph comparison and the RDF 1.2 oracle

**Files:**
- Modify: `src/pymantic/compare.py` (`term_key`, `statements`, `canonical_labels_and_order`), `src/pymantic/serializers.py` (`stable_lines`)
- Modify: `setup.cfg` (`testing` extra)
- Create: `tests/oracle.py`
- Modify: `tests/test_compare_manifest.py`, `tests/compare/manifest.ttl`
- Create: pair files in `tests/compare/` (listed in Step 1)
- Modify: `docs/graph-comparison.rst`
- Test: `tests/test_compare.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces: `tests.oracle.isomorphic(a, b) -> bool` (pyoxigraph when either side holds a triple term or directional literal, else rdflib via `tests.test_w3c.to_rdflib`); `tests.oracle.has_rdf12_terms(graph_or_dataset) -> bool`; `tests.oracle.require_oracle()` which calls `pytest.skip("pyoxigraph, the RDF 1.2 oracle, is not available on this interpreter")` when pyoxigraph cannot be imported. `compare.TT_SUBJECT`, `TT_PREDICATE`, `TT_OBJECT` reserved keys.

- [ ] **Step 1: Write the failing tests**

In `tests/test_compare.py`:
```python
def test_term_key_directional_literal():
    assert term_key(Literal("x", "he", direction="rtl")) == '"x"@he--rtl'

def test_term_key_ground_triple_term():
    t = Triple(NamedNode("http://a"), NamedNode("http://b"), Literal("c"))
    assert term_key(t) == '<<( <http://a> <http://b> "c" )>>'

def test_canonical_labels_omit_helper_nodes():
    x, y = BlankNode(), BlankNode()
    g = Graph().addAll([Triple(x, P, Triple(y, Q, O)), Triple(y, R, x)])
    assert set(canonical_labels(g)) == {x, y}

def test_stable_lines_label_blank_nodes_inside_triple_terms():
    ...  # serialize_ntriples(stable=True) of the graph above, relabelled and
         # shuffled twice, gives identical bytes, and every "_:" label inside
         # <<( )>> also appears as an asserted subject or object
```
New manifest pairs (N-Triples files), each `pc:IsomorphicTest` or `pc:NonIsomorphicTest`:
- `triple-term-blank.nt` / `triple-term-blank-relabelled.nt` — isomorphic: `_:x <p> <<( _:y <q> <o> )>> . _:y <r> _:x .`
- `triple-term-nested.nt` / `triple-term-nested-relabelled.nt` — isomorphic, blank nodes two levels deep.
- `triple-term-blank.nt` / `triple-term-swapped.nt` — not isomorphic: the inner subject is `_:x` instead of `_:y`.
- `triple-term-direction-ltr.nt` / `triple-term-direction-rtl.nt` — not isomorphic, differing only in a direction inside a triple term.
- `triple-term-ground.nt` / `triple-term-ground-reordered.nt` — isomorphic, no blank nodes.

`test_compare_manifest.py` uses `tests.oracle.isomorphic` as its cross-check, calling `require_oracle()` first only when `has_rdf12_terms` is true for either side.

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement the oracle**

`setup.cfg` testing extra: `pyoxigraph>=0.5.11; platform_python_implementation == "CPython"`. `tests/oracle.py` writes both sides with `serialize_nquads` (a Graph through `serialize_ntriples`), parses each with `pyoxigraph.parse(..., format=pyoxigraph.RdfFormat.N_QUADS)` into a `pyoxigraph.Dataset`, calls `canonicalize(pyoxigraph.CanonicalizationAlgorithm.UNSTABLE)` on each and compares with `==`.

- [ ] **Step 4: Implement compare**

`term_key`: a literal with a direction appends `--` + direction after `@language`; a `Triple` with no blank node at any depth returns `"<<( %s %s %s )>>"` of its parts' keys. `statements()`: its `key()` maps a non-ground `Triple` to a helper node, an instance of a private `_TripleTermNode(BlankNode)` subclass, one per distinct triple term (a dict from the term to its helper), and appends `(helper, TT_SUBJECT, key(s), "")`, `(helper, TT_PREDICATE, key(p), "")`, `(helper, TT_OBJECT, key(o), "")` to the items once per helper; keys of nested terms are taken first, so an inner helper is the outer one's object. `TT_SUBJECT = "(triple term subject)"` and so on, beside `EMPTY_GRAPH`, with a comment that no real key starts with `(`. `canonical_labels_and_order` drops `_TripleTermNode`s from both `labels` and `order` (renumber `order` without gaps). `stable_lines`' `term()` writes a `Triple` as `<<( term(s) term(p) term(o) )>>`.

- [ ] **Step 5: Document flattening** in `docs/graph-comparison.rst`: the helper-node construction and the one-line correctness argument from the spec, and that helpers count toward the work cap.

- [ ] **Step 6: Run**

Run: `uvx --with tox-uv tox -e py314 -- tests/test_compare.py tests/test_compare_manifest.py tests/test_stable_digests.py tests/test_serializers.py -q`
Expected: PASS.

- [ ] **Step 7: Commit** — "Compare and stably label graphs with triple terms"

---

### Task 6: Turtle triple terms and directions

**Files:**
- Modify: `src/pymantic/parsers/lark/turtle.py`
- Modify: `tests/test_w3c.py` (`assert_isomorphic`, `shuffled_relabelled`), `tests/w3c/expected_failures.txt`
- Test: `tests/test_parsers.py`

**Interfaces:**
- Consumes: Task 4's `make_language_literal`, Task 5's `tests.oracle`.

- [ ] **Step 1: Write the failing tests**

```python
def test_turtle_triple_term():
    g = turtle_parser.parse(
        '@prefix : <http://ex/> . :r :reifies <<( [] a <<( :a :b "c"@he--RTL )>> )>> .'
    )
    (t,) = g
    inner = t.object
    assert isinstance(inner.subject, BlankNode)
    assert inner.predicate == RDF_TYPE
    assert inner.object.object == Literal("c", "he", direction="rtl")

@pytest.mark.parametrize("bad", [
    ':r :p <<( [ :q :o ] :b :c )>> .',      # property list inside
    ':r :p <<( :a :b ( 1 2 ) )>> .',        # collection inside
    '<<( :a :b :c )>> :p :o .',             # triple term as subject
    ':r :p "c"@en--up .',
])
def test_turtle_rejects(bad):
    with pytest.raises(Exception):
        turtle_parser.parse("@prefix : <http://ex/> . " + bad)
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement**

Grammar: `?object` gains `| triple_term`; `triple_term: "<<(" tt_subject verb tt_object ")>>"`, `?tt_subject: iri | blank_node`, `?tt_object: iri | blank_node | literal | triple_term`; `LANGTAG` gains `("--" /[a-zA-Z]+/)?`. Transformer `triple_term` maps the `a` token to `RDF_TYPE` the way `unpack_predicate_object_list` does and returns `self.make_triple(...)`. `unpack_node` treats a `Triple` as a plain term.

- [ ] **Step 4: Switch the W3C oracle**

`assert_isomorphic` in `tests/test_w3c.py` uses `tests.oracle.isomorphic`, calling `require_oracle()` when either graph has RDF 1.2 terms. `shuffled_relabelled` relabels blank nodes inside triple terms (recursive `term()`).

- [ ] **Step 5: Remove xfails**

Remove `nt-ttl12-langdir-1`, `nt-ttl12-langdir-2` and each Turtle line whose test now passes; leave reifier, annotation and `VERSION` lines. Run: `uvx --with tox-uv tox -e py314 -- tests/test_w3c.py -q`. Strict xfail reports every test that passes but is still listed; remove those lines and rerun until clean. Record the count removed in the commit message.

- [ ] **Step 6: Commit** — "Parse RDF 1.2 triple terms and directions in Turtle"

---

### Task 7: Turtle writer

**Files:**
- Modify: `src/pymantic/serializers.py` (`turtle_repr`, `_TurtleWriter.__init__`)
- Modify: `tests/w3c/expected_failures.txt`
- Test: `tests/test_serializers.py`

**Interfaces:**
- Consumes: Tasks 2, 3, 5 and 6.

- [ ] **Step 1: Write the failing tests**

```python
def test_turtle_writes_triple_terms_and_directions():
    ...  # graph with :r :reifies <<( :a :b "c"@he--rtl )>>; output contains
         # '<<( ' and '"c"@he--rtl' and parses back isomorphic (tests.oracle)

@pytest.mark.parametrize("stable", [False, True])
def test_blank_node_only_inside_triple_term_keeps_its_label(stable):
    x = BlankNode()
    g = Graph().addAll([
        Triple(EX.r, EX.reifies, Triple(x, EX.p, EX.o)),
        Triple(x, EX.name, Literal("only here")),
    ])
    out = StringIO(); serialize_turtle(g, out, stable=stable)
    assert "[" not in out.getvalue()
    assert tests.oracle.isomorphic(turtle_parser.parse(out.getvalue()), g)

def test_stable_turtle_with_triple_terms_is_stable():
    ...  # shuffled_relabelled copies (seeds 1 and 2) give identical stable output
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement**

`turtle_repr`: a `Triple` is `"<<( " + repr(s) + " " + repr(p) + " " + repr(o) + " )>>"`, each through `turtle_repr` with the same arguments (so prefixes and labels apply); a literal with a direction writes `@lang--dir`. In `_TurtleWriter.__init__`, after `references = graph.object_counts()`, add 2 to the count of every blank node that occurs at any depth inside a triple-term object, so it is never inlined, never a collection, and never an anonymous subject; comment why. Objects that are triple terms sort by their Turtle name with IRIs and literals.

- [ ] **Step 4: Remove xfails**

Run `tests/test_w3c.py`; remove `[roundtrip]` and `[stable]` lines that now pass, as in Task 6.

- [ ] **Step 5: Run the full suite**

Run: `uvx --with tox-uv tox -e py314 -q`
Expected: PASS.

- [ ] **Step 6: Commit** — "Write RDF 1.2 triple terms and directions as Turtle"

---

### Task 8: Resource API

**Files:**
- Modify: `src/pymantic/rdf.py` (`IMPLIED_DATATYPES`, `objects_by_lang`, `classify`)
- Test: `tests/test_RDF.py`

**Interfaces:**
- Consumes: Task 2's `RDF_DIRLANGSTRING`.
- Produces: `Resource.objects_by_lang(predicate, lang=None, direction=None)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_objects_by_lang_direction():
    # resource with labels "a"@he, "b"@he--rtl, "c"@he--ltr, "d"@en
    assert set(r.objects_by_lang("rdfs:label", "he")) == {a, b, c}
    assert r.objects_by_lang("rdfs:label", "he", direction="rtl") == [b]

def test_dirlangstring_is_not_a_written_datatype():
    # "b"@he--rtl is not returned by objects_by_datatype(p)

def test_classify_returns_triple_terms_unchanged():
    t = Triple(EX.a, EX.b, EX.c)
    assert Resource.classify(graph, t) is t
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement** — add `RDF_DIRLANGSTRING` to `IMPLIED_DATATYPES`; filter on `direction` when given; `classify` returns a `Triple` unchanged, as it does a `Literal`.

- [ ] **Step 4: Run** `uvx --with tox-uv tox -e py314 -- tests/test_RDF.py -q`. Expected: PASS.

- [ ] **Step 5: Commit** — "Filter Resource language objects by direction"

---

### Task 9: Line-TriG completeness, docs and interpreter matrix

**Files:**
- Test: `tests/test_linetrig.py`
- Modify: `docs/line-trig.rst`, `CHANGELOG.md`

- [ ] **Step 1: Write the test**

```python
def test_linetrig_round_trips_every_rdf12_feature():
    # Dataset with: an empty named graph; a named graph holding
    # _:r <reifies> <<( _:s <p> <<( _:s <q> "v"@he--rtl )>> )>> and _:s <r> _:r;
    # a default-graph directional literal. serialize_linetrig, parse back,
    # compare with tests.oracle.isomorphic (require_oracle first).
```

- [ ] **Step 2: Run** — expected PASS with no code change; if it fails, find the root cause before changing anything.

- [ ] **Step 3: Docs**

`docs/line-trig.rst`: Line-TriG is the only format pymantic reads and writes that holds every RDF 1.2 dataset; N-Quads cannot write an empty named graph, N-Triples and Turtle hold one graph, and Turtle's missing reifiers and annotations are shorthand that costs no expressiveness. `CHANGELOG.md` 2.0 entry: the spec's "Behavior changes" list, plus the W3C xfail counts removed.

- [ ] **Step 4: Lint and the interpreter matrix**

Run: `uvx --with tox-uv tox -e lint` then `uvx --with tox-uv tox` (every env in `env_list`).
Expected: lint clean; all envs pass; on pypy312, graalpy and pyodide the oracle tests skip with the pyoxigraph reason and nothing else skips newly. Report the per-env results.

- [ ] **Step 5: Commit** — "Document RDF 1.2 support and Line-TriG's completeness"
