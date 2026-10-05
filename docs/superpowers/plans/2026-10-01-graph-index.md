# Graph Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `Graph`'s nested-defaultdict index with a term dictionary
and sorted `array('I')` columns, make `Dataset` a real quad store, and add
the Line-TriG reader and writer its tests need.

**Architecture:** Two new int-only building blocks, `TermDictionary`
(terms to dense ids) and `TripleIndex` (id triples in a key dict plus SPO,
POS, OSP sorted columns), know nothing about RDF. `Graph` and `Dataset` in
`primitives.py` compose them and translate between terms and ids. Line-TriG
lands first and is independent of the index.

**Tech Stack:** Python 3.10+ standard library (`array`, `bisect`), Lark for
the Line-TriG grammar, pytest, tox + tox-uv.

**Spec:** `docs/superpowers/specs/2026-10-01-graph-index-design.md`.
Line-TriG profile: `docs/line-trig.rst`.

## Global Constraints

- Pure Python, standard library only; no new dependencies.
- Must pass on every tox env: py312, py313, py314, py315, pypy312,
  graalpy312, graalpy313, pyodide312, pyodide314. 3.14 is the primary target.
- Index columns are `array('I')`, never `'l'` (4 bytes on Pyodide, 8 on
  macOS). Ids are below `MAX_TERMS = 2**32`.
- Packed key: `s << 64 | p << 32 | o`.
- Compaction trigger: after a remove, compact when
  `len(dictionary) > 6 * n + names` (n = triples or quads, names = named
  graphs; `len(dictionary)` counts live interned terms, not freed slots).
- Bound vs wildcard is `is not None`, never truthiness.
- The only breaking changes are those listed under "Behavior changes" in
  the spec. Any other change to existing test expectations stops the task:
  report it, do not edit the test.
- Test output must be pristine: no warnings, no stray prints.
- Code style: black 26.5 (`tox -e format`), flake8 via `tox -e lint`.
  Match the surrounding code's comment density and naming. Comments explain
  why, never history.
- Commit messages: imperative sentence, body explains why, end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never skip
  hooks. Never `git add -A`.

Running tests from this worktree, with the shared tox envs:

```bash
PYTHONPATH=src /Users/gavin/Programing/pymantic/.tox/py314/bin/python -m pytest -q <tests>
```

## Review Focus

1. A plain `str` passed where a term is expected (`match(graph="http://…")`,
   as `tests/test_primitives.py` does): `NamedNode` is a `str` subclass with
   the same hash, so it must still find the term. Test in Task 7 and Task 8.
2. Alternating single adds and queries (add, match, add, match, …): each
   query merges a one-triple buffer; results must stay correct and the cost
   must stay per-insert, not a full re-sort. Test in Task 6.
3. Removing a triple that is not present: today `KeyError`; it stays
   `KeyError` for `Graph.remove` and `Dataset.remove`. Test in Task 7 and 8.
4. The same literal written as `"x"` and `"x"^^xsd:string` is one triple
   (the base branch normalizes `Literal`). Test in Task 7.
5. A `Graph` view kept after `Dataset.remove_graph` removed its graph: any
   use raises `RuntimeError`, never reads freed term slots. Test in Task 8.

---

### Task 1: Line-TriG reader

**Files:**
- Create: `src/pymantic/parsers/lark/linetrig.py`
- Modify: `src/pymantic/parsers/lark/__init__.py`, `src/pymantic/parsers/__init__.py` (export `linetrig_parser`)
- Test: `tests/test_linetrig.py`

**Interfaces:**
- Consumes: `grammar`, `NTriplesTransformer` from `parsers/lark/ntriples.py`;
  `LarkParser` from `parsers/lark/base.py`; `NQuadsTransformer.quad` shape.
- Produces: `linetrig_parser.parse(string_or_stream, dataset=None) -> Dataset`
  and `linetrig_parser.parse_string(string_or_bytes, dataset=None) -> Dataset`.

- [ ] **Step 1: Write the failing tests** in `tests/test_linetrig.py`:

```python
def test_default_graph_line_is_a_default_graph_quad():
    ds = linetrig_parser.parse("<http://e/s> <http://e/p> <http://e/o> .\n")
    assert Quad(S, P, O, None) in ds and len(ds) == 1

def test_named_graph_line():
    ds = linetrig_parser.parse("<http://e/g> { <http://e/s> <http://e/p> <http://e/o> . }\n")
    assert Quad(S, P, O, G) in ds

def test_empty_named_graph_exists():
    ds = linetrig_parser.parse("<http://e/g> { }\n")
    assert len(ds) == 0
    assert [g.uri for g in ds.graphs if g.uri is not None] == [G]

def test_blank_node_label_is_document_scoped():
    ds = linetrig_parser.parse(
        "_:g { _:b <http://e/p> <http://e/o> . }\n_:b <http://e/p> _:g .\n")
    (named,) = [q for q in ds if q.graph is not None]
    (default,) = [q for q in ds if q.graph is None]
    assert named.subject is default.subject and named.graph is default.object

def test_repeated_graph_name_is_a_union():  # two lines, same <g>, len(ds) == 2

def test_comments_and_blank_lines_are_ignored():

def test_out_of_profile_line_is_rejected_with_its_line_number():
    with pytest.raises(ValueError, match="line 2"):
        linetrig_parser.parse("<http://e/s> <http://e/p> <http://e/o> .\n"
                              "<http://e/g> { <http://e/s> <http://e/p> <http://e/o> . <http://e/s> <http://e/p> <http://e/o2> . }\n")
```

Also reject, each in a parametrized test: two statements on one line, a
prefixed name (`ex:s`), `GRAPH <g> { … }`, a missing `.` inside the braces,
a literal as graph name. Use both a string and a `StringIO` input.

- [ ] **Step 2: Run** `pytest tests/test_linetrig.py -q`. Expected: FAIL, import error.

- [ ] **Step 3: Implement `linetrig.py`.** The grammar is the N-Triples
  `grammar` string plus these rules (start rule `linetrig_start`):

```
linetrig_start: EOL* (statement EOL+)* statement?
?statement: triple | graph_triple | empty_graph
graph_triple: graph_name "{" subject predicate object "." "}"
empty_graph: graph_name "{" "}"
?graph_name: iriref | BLANK_NODE_LABEL -> blank_node_label
```

The transformer subclasses `NTriplesTransformer`: `triple` returns a
`Quad` with graph `None`, `graph_triple` a `Quad` in the named graph, and
`empty_graph` a small `EmptyGraph(name)` marker. `_make_graph` returns
`self.env.createDataset()`. A `LineTriGParser(LarkParser)` overrides
`parse` to add quads with `dataset.add(quad)`, and for an `EmptyGraph`
marker call `dataset.add_graph(Graph(), named=marker.name)`. It parses
line by line for both strings (`splitlines(keepends=True)`) and streams,
and re-raises any Lark or `ValueError` as
`ValueError(f"line {n}: {error}")`.

- [ ] **Step 4: Run** `pytest tests/test_linetrig.py -q`. Expected: PASS.
- [ ] **Step 5: Run the full suite**; expected all pass as before.
- [ ] **Step 6: Commit** `Add a Line-TriG reader for dataset fixtures`.

### Task 2: Line-TriG writer

**Files:**
- Modify: `src/pymantic/serializers.py` (add `serialize_linetrig` after `serialize_nquads`)
- Modify: `docs/modules/serializers.rst` if it lists functions explicitly
- Test: `tests/test_linetrig.py`

**Interfaces:**
- Consumes: `linetrig_parser` (Task 1), `Dataset`, `term.toNT()`.
- Produces: `serialize_linetrig(dataset, f) -> None`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_writer_puts_default_graph_first_then_named_then_empty():
    ds = Dataset()
    ds.add(Quad(S, P, O, G)); ds.add(Quad(S, P, O, None)); ds.add_graph(Graph(), named=EMPTY)
    out = io.StringIO(); serialize_linetrig(ds, out)
    assert out.getvalue() == (
        "<http://e/s> <http://e/p> <http://e/o> .\n"
        "<http://e/g> { <http://e/s> <http://e/p> <http://e/o> . }\n"
        "<http://e/empty> { }\n")

def test_round_trip_keeps_empty_graphs_and_shared_blank_nodes():
    # parse the Task 1 blank-node document plus an empty graph, write, re-parse;
    # assert pymantic.compare.isomorphic(original, reparsed)
```

- [ ] **Step 2: Run**; expected FAIL, `serialize_linetrig` missing.
- [ ] **Step 3: Implement.** Default-graph quads first, then named-graph
  quads, each in dataset order; then `G { }` for every named graph in
  `dataset.graphs` with no triples. Single spaces, LF line ends, terms via
  `toNT()`. Docstring points to `docs/line-trig.rst`.
- [ ] **Step 4: Run** the Line-TriG tests and the full suite; expected PASS.
- [ ] **Step 5: Commit** `Add a Line-TriG writer`.

### Task 3: N-Quads parse into a Dataset

**Files:**
- Modify: `src/pymantic/parsers/lark/nquads.py`, `src/pymantic/primitives.py` (`Graph.__init__`, `Graph.add`), `src/pymantic/compare.py:166-167` (comment)
- Modify tests: `tests/test_parsers.py` N-Quads tests, `tests/test_serializers.py` N-Quads round trips as needed
- Test: `tests/test_parsers.py`, `tests/test_primitives.py`

**Interfaces:**
- Produces: `nquads_parser.parse(...) -> Dataset`; `Graph().uri is None`;
  `Graph.add(x)` raises `TypeError` when `len(x) != 3`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_nquads_parser_returns_a_dataset():
    ds = nquads_parser.parse("<http://example/s> <http://example/p> <http://example/o> <http://example/g> .")
    assert isinstance(ds, Dataset)

def test_nquads_parser_rejects_a_graph():
    with pytest.raises(TypeError, match="Dataset"):
        nquads_parser.parse("<http://example/s> <http://example/p> <http://example/o> .", Graph())

def test_graph_without_a_name_has_no_uri():
    assert Graph().uri is None

def test_graph_rejects_a_quad():
    with pytest.raises(TypeError):
        Graph().add(Quad(S, P, O, G))
```

- [ ] **Step 2: Run**; expected FAIL.
- [ ] **Step 3: Implement.** `NQuadsTransformer._make_graph` returns
  `self.env.createDataset()` (as `parsers/jsonld.py:87` does). `Graph.add`
  raises `TypeError("a Graph holds triples; parse N-Quads into a Dataset")`
  when `len(triple) != 3`. `Graph.__init__` leaves `uri` `None` when
  `graph_uri` is `None`.
- [ ] **Step 4: Update** the existing N-Quads tests that pass `Graph()` to
  pass `Dataset()` instead, keeping every assertion's meaning. Drop "and so
  does a Graph filled by the N-Quads parser" from the `compare.statements`
  comment.
- [ ] **Step 5: Run the full suite, W3C tests included**; expected PASS.
- [ ] **Step 6: Commit** `Parse N-Quads into a Dataset`.

### Task 4: Graph index benchmark tool and baseline

**Files:**
- Create: `benchmarks/graph_index.py`
- Modify: `benchmarks/README.rst` (one entry under Tools)

**Interfaces:**
- Consumes: `benchmarks/inputs.py` (`select`, `load`, `data_path`), public
  `Graph`/`Dataset` API only, so it runs against old and new trees.
- Produces: a tool later tasks run to compare trees.

- [ ] **Step 1: Write the tool.** For each input (names or kinds via
  `inputs.select`, default `fhir-r5-examples obi doid schemaorg-shapes`):
  - load: best of `--repeat` (default 3) of `Graph().addAll(triples)` from a
    pre-parsed list of triples, every run printed;
  - bytes per triple of the loaded graph (tracemalloc), excluding the
    triples list;
  - GC-tracked objects added by the graph (`len(gc.get_objects())` delta
    after `gc.collect()`), per triple, and best-of-3 full `gc.collect()` ms;
  - the 8 `match` patterns: 1000 bound terms sampled with
    `random.Random(0)` from the graph's own triples, time per pattern;
  - full iteration, and `Counter(t.object for t in graph)`;
  - `--dataset-per-file`: `fhir-r5-examples` loaded one named graph per
    `.ttl` file (graph name = the file's `file://` IRI), reporting load
    time, tracked objects and bytes per quad.
  Prints which pymantic it imported, as the other tools do; `--help`
  documents all of it. Output stays under ~40 lines per input.
- [ ] **Step 2: Link the data** for this worktree (never commit it):
  `ln -s /Users/gavin/Programing/pymantic/.claude/worktrees/benchmarks/benchmarks/data benchmarks/data`.
- [ ] **Step 3: Record the baseline** against the unchanged base tree on
  3.12, 3.13 and 3.14:
  `PYTHONPATH=/Users/gavin/Programing/pymantic/.claude/worktrees/benchmarks/src <tox py3XX python> benchmarks/graph_index.py --dataset-per-file > benchmarks/out/graph_index-baseline-py3XX.txt`.
  Also record `timing.py` (all three `--what`) and `gc_census.py
  fhir-r5-examples` the same way. Check each file ran to completion.
- [ ] **Step 4: Commit** the tool and README entry only:
  `Add a benchmark for the graph index`.

### Task 5: TermDictionary

**Files:**
- Create: `src/pymantic/term_dictionary.py`
- Test: `tests/test_term_dictionary.py`

**Interfaces:**
- Produces:

```python
MAX_TERMS = 2**32
class TermDictionary:
    terms: list            # terms[id] -> term, or None for a freed id; read-only for callers
    def intern(self, term) -> int        # OverflowError when an id would reach MAX_TERMS
    def lookup(self, term) -> int | None # never allocates
    def __len__(self) -> int             # live interned terms (len of the term->id dict)
    def compact(self, live_ids) -> int   # frees every id not in live_ids; returns how many
```

- [ ] **Step 1: Write the failing tests:** equal terms get one id
  (`NamedNode("http://a")` twice); a plain `str` looks up the `NamedNode`
  with the same text; two `BlankNode()`s get two ids; `lookup` of an unknown
  term returns `None` and `len` is unchanged; `compact({ids to keep})` sets
  freed slots to `None`, drops them from `lookup`, returns the count, and
  the next `intern` reuses a freed id; `len` after compaction counts only
  live terms; `intern` raises `OverflowError` with `MAX_TERMS` monkeypatched
  to 3; a `Literal` and a triple-term stand-in with the same parts get
  distinct ids:

```python
class TripleTermStandIn(tuple):
    """Meets the spec's requirement for the 2.0 triple-term type: never
    equal to a Literal or a plain tuple."""
    __slots__ = ()
    def __eq__(self, other): return type(other) is type(self) and tuple.__eq__(self, other)
    def __ne__(self, other): return not self == other
    def __hash__(self): return hash((TripleTermStandIn, tuple(self)))

def test_literal_and_triple_term_with_equal_parts_get_distinct_ids():
    d = TermDictionary()
    parts = ("x", None, NamedNode("http://e/dt"))
    assert d.intern(Literal(*parts)) != d.intern(TripleTermStandIn(parts))
```

- [ ] **Step 2: Run**; expected FAIL, import error.
- [ ] **Step 3: Implement** with `__slots__`, a list, a dict and a free list,
  as the spec's "Term dictionary" section describes.
- [ ] **Step 4: Run**; expected PASS.
- [ ] **Step 5: Commit** `Add a term dictionary for the graph index`.

### Task 6: TripleIndex

**Files:**
- Create: `src/pymantic/triple_index.py`
- Test: `tests/test_triple_index.py`

**Interfaces:**
- Produces (ids are ints, `None` is a wildcard):

```python
SMALL_MERGE = 32   # buffers up to this size are inserted by bisect; larger ones trigger a re-sort. Tuned in Task 9.
class TripleIndex:
    def __len__(self) -> int
    def __contains__(self, spo: tuple) -> bool
    def __iter__(self) -> Iterator[tuple[int, int, int]]   # insertion order
    def add(self, s, p, o) -> bool             # False if already present
    def remove(self, s, p, o) -> None          # KeyError if absent
    def remove_many(self, spos) -> None        # one re-sort; KeyError before any change if one is absent
    def match(self, s, p, o) -> Iterator[tuple[int, int, int]]
    def subjects(self) / predicates(self) / objects(self) -> Iterator[int]   # distinct, id order
    def ids(self) -> set[int]                  # every id in any position
    def detach(self) -> None                   # every later call raises RuntimeError
```

Layout and behavior are the spec's "Index layout" and "match and
iteration" sections: `_keys` dict of packed keys (membership and insertion
order), 9 sorted `array('I')` columns (SPO, POS, OSP), a 3-column pending
buffer, a version counter.

- [ ] **Step 1: Write the failing tests:**
  - Model-based: `random.Random(seed)` for seeds 0-19 drives 2,000
    operations each over ids 0-15 (so collisions and duplicates are common):
    add, remove of a present triple, `remove_many` of a random subset, and
    after every operation compare against a reference `dict` used as an
    ordered set: `len`, `in`, `list(index)` (insertion order, re-add moves to
    the end), all 8 `match` patterns for sampled bound values (as sets), and
    `subjects/predicates/objects` (sorted distinct). Include runs that add
    more than `SMALL_MERGE` triples between queries and runs that add one
    triple between queries.
  - `remove` of an absent triple raises `KeyError`; `remove_many` with one
    absent triple raises `KeyError` and changes nothing.
  - Mutating during `match` or iteration: `add` or `remove` then `next()`
    raises `RuntimeError`.
  - Interleaving cost (Review Focus 2): add 20,000 triples one at a time
    with a `match` after each; assert the number of full re-sorts (count
    via a test-visible counter attribute, e.g. `index.resorts`) is 0 after
    the first bulk load.
  - `subjects()` after removing a subject's last triple does not yield it.
  - `detach()` then `add`, `match`, `iter` each raise `RuntimeError`.
  - Columns are `array('I')`: `assert all(c.typecode == "I" for c in index._columns())`
    (expose a `_columns()` helper listing the 12 arrays).
- [ ] **Step 2: Run**; expected FAIL.
- [ ] **Step 3: Implement.** Choosing the ordering per pattern follows the
  current `Graph.match`: SPO for `s`/`s p`, POS for `p`/`p o`, OSP for
  `o`/`o s`; `s p o` is a `_keys` lookup; nothing bound walks `_keys`.
  Range search: `bisect_left`/`bisect_right` on the first column, then on
  the second column with `lo`/`hi`. `remove` merges the buffer first, then
  finds the exact row by bisect in each ordering and deletes it from the
  three columns. `remove_many` deletes from `_keys` and re-sorts all
  orderings from `_keys`. Re-sort: sort packed keys per ordering and unpack
  into fresh arrays. Generators snapshot the version on first `next()` and
  check it before every yield.
- [ ] **Step 4: Run**; expected PASS on py314, then on pypy312 and pyodide314
  (`PYTHONPATH=src <env python> -m pytest -q tests/test_triple_index.py`).
- [ ] **Step 5: Commit** `Add a sorted-array triple index`.

### Task 7: Graph on the new index

**Files:**
- Modify: `src/pymantic/primitives.py` (`Index`, `Graph`; remove the `defaultdict` import if unused)
- Test: `tests/test_index.py` (new), existing `tests/test_primitives.py`, whole suite

**Interfaces:**
- Consumes: `TermDictionary` (Task 5), `TripleIndex` (Task 6).
- Produces: `Graph(graph_uri=None)` with its existing public methods, and
  for Task 8 an internal constructor
  `Graph._view(uri, dictionary, index, owner) -> Graph` and the owner hook
  `owner._maybe_compact() -> None` (a standalone `Graph` is its own owner).

- [ ] **Step 1: Write the failing tests** in `tests/test_index.py`:
  - Model-based over real terms: seeds 0-9, 1,000 operations each over a
    pool of 6 IRIs, 4 blank nodes and 4 literals (including `NamedNode("")`
    and `Literal("")`); reference is a `dict` of `Triple`s as an ordered
    set; after each operation compare `len`, `in`, `list(graph)`, the 8
    `match` patterns (as sets), `subjects/predicates/objects` (as sets).
  - Regressions: `subjects()` after the last triple of a subject is
    removed; `removeMatches(s, None, None)` with three matches;
    `match(subject=NamedNode(""))` returns only triples with that subject.
  - Review Focus: `match(subject="http://e/s")` with a plain `str` finds the
    `NamedNode` triples; `Graph.remove` of an absent triple raises
    `KeyError`; adding `Triple(S, P, Literal("x"))` and
    `Triple(S, P, Literal("x", datatype=XSD_STRING))` gives `len(g) == 1`.
  - Compaction: add 100 triples with distinct terms, remove 99; assert
    `len(g._dictionary) <= 6 * len(g) + 0` after the last remove and that a
    following remove-free `match` still returns correct terms.
  - GC: build a 10,000-triple graph; assert the tracked-object delta from
    the graph (excluding the input triples list, which the test deletes
    first) is under 1 per distinct term + 50.
- [ ] **Step 2: Run**; expected FAIL.
- [ ] **Step 3: Implement** `Graph` per the spec: `_dictionary`, `_index`,
  `_owner`, `_actions`. `add` interns and adds; `remove` looks terms up
  (unknown term → `KeyError`), removes, calls `self._owner._maybe_compact()`;
  `match` looks up bound terms and returns empty for unknown ones, then
  yields `Triple(terms[s], terms[p], terms[o])` from `_index.match`;
  `removeMatches` uses `remove_many`; `subjects/predicates/objects`,
  `__iter__`, `__contains__`, `__len__`, `toArray` map ids to terms.
  `_maybe_compact` on a standalone graph:
  `if len(d) > 6 * len(index): d.compact(index.ids())`. Delete the old
  `Index()` helper.
- [ ] **Step 4: Run the whole suite, W3C included.** Expected PASS. Any
  failing existing test that is not explained by a spec "Behavior changes"
  entry stops the task.
- [ ] **Step 5: Commit** `Store Graph triples as term ids in sorted arrays`.

### Task 8: Dataset on the new index

**Files:**
- Modify: `src/pymantic/primitives.py` (`Dataset`)
- Create: `tests/fixtures/datasets/*.trig` (Line-TriG)
- Test: `tests/test_index.py`, `tests/test_primitives.py`

**Interfaces:**
- Consumes: `Graph._view`, `_maybe_compact` (Task 7); `TripleIndex.detach`
  (Task 6); `linetrig_parser` (Task 1).
- Produces: `Dataset` with `add`, `remove`, `match(s, p, o, graph)`,
  `removeMatches`, `addAll`, `add_graph(graph, named=None)`,
  `remove_graph(graph_or_name)`, `graphs`, `__len__`, `__contains__`,
  `__iter__`, `toArray`, per the spec's "Dataset" section.

- [ ] **Step 1: Write the fixtures**: `shared-blank-nodes.trig` (a blank node
  in two graphs and naming a third), `empty-graphs.trig` (two empty named
  graphs and one non-empty), `default-only.trig`.
- [ ] **Step 2: Write the failing tests:**
  - Model-based: seeds 0-9, 1,000 operations over quads in the default
    graph and 3 named graphs (one a blank node also used in triples);
    reference is a dict of quads plus a set of named-graph names; compare
    `len`, `in`, `list(ds)` as a set, `match` with and without `graph`, and
    the set of named graphs. Operations include `remove_graph`.
  - Empty named graphs persist after their last quad is removed, and leave
    on `remove_graph`; `remove_graph(None)` raises `ValueError`;
    `remove_graph` of an unknown name raises `KeyError`.
  - Reads create nothing: `list(ds.match(graph=G))` and `Quad(..., G) in ds`
    on an empty dataset leave `[g.uri for g in ds.graphs] == [None]`.
  - `Triple in ds` is default-graph membership; `__contains__` returns a
    `bool`.
  - Shared blank nodes from the fixture: the same `BlankNode` object comes
    back from both graphs and as the third graph's name.
  - `add_graph(g)` copies: later `g.add` does not change the dataset;
    blank nodes shared with existing graphs stay shared; `add_graph` on an
    existing name takes the union.
  - Review Focus: a view from `ds.graphs` used after `remove_graph` raises
    `RuntimeError`; `match(graph="http://e/g")` with a plain `str` works;
    `Dataset.remove` of an absent quad raises `KeyError`.
  - Compaction counts across graphs: remove most quads from one graph and
    assert a term still used in another graph survives.
- [ ] **Step 3: Run**; expected FAIL.
- [ ] **Step 4: Implement** per the spec: one `TermDictionary`;
  `_graphs: dict` from name id (`None` for the default graph, created in
  `__init__`) to `TripleIndex`; views via `Graph._view(name_term, d, index,
  self)`; default graph first in `graphs` and iteration;
  `_maybe_compact`: `n` = total quads, `names` = named graphs, live ids =
  union of every index's `ids()` and every name id.
- [ ] **Step 5: Run the whole suite**, including `pymantic.compare` tests
  that use datasets. Expected PASS.
- [ ] **Step 6: Commit** `Make Dataset a quad store with one term dictionary`.

### Task 9: Measure, tune, record

**Files:**
- Modify: `src/pymantic/triple_index.py` (`SMALL_MERGE`), possibly `Dataset` (GSPO fallback, only if Gavin agrees)
- Modify: `CHANGELOG.md`, spec "Benchmarks and acceptance" (append measured results)

- [ ] **Step 1: Run** `graph_index.py --dataset-per-file`, `timing.py` (all
  `--what`) and `gc_census.py fhir-r5-examples` on this tree for 3.12, 3.13,
  3.14 into `benchmarks/out/graph_index-after-py3XX.txt`; `graph_index.py`
  only on pypy312 and pyodide314.
- [ ] **Step 2: Check the digests.** `canonical_labels` and stable Turtle
  digests must equal the baseline's. If the default Turtle digest differs,
  write both outputs for that input and confirm with a script that every
  difference is object order under one predicate.
- [ ] **Step 3: Tune `SMALL_MERGE`** by trying 8, 32, 128, 512 on the
  interleaved-add case and on loading; keep the fastest within noise, and
  rerun Task 6 tests.
- [ ] **Step 4: Check acceptance** (spec): near-zero tracked objects per
  triple; FHIR full collection well under 0.30 s; 3.14 load and Turtle write
  no slower than baseline beyond 5% noise. If load or write is slower, or
  per-graph indexes cost too much in `--dataset-per-file`, stop and report
  numbers to Gavin with the spec's fallback (Triple list, or GSPO); do not
  implement a fallback without his decision.
- [ ] **Step 5: Run the whole tox matrix**:
  `uvx --with tox-uv tox -p auto` from this worktree; every env passes.
- [ ] **Step 6: Record.** CHANGELOG `[Unreleased]`: an "Changed" entry for
  the index with the measured before/after (tracked objects, full-GC ms,
  bytes per triple on FHIR, 3.14), an "Added" entry for Line-TriG and
  `serialize_linetrig`, and every spec "Behavior changes" item under
  "Changed" or "Fixed". Append a "Measurements" subsection to the spec.
- [ ] **Step 7: Commit** `Record graph index measurements and tune merging`.
