# Graph index design

Date: 2026-10-01. Branch `graph-index`, from `benchmarks/real-data` (3938832).

## Why

`Graph` stores triples in three nested `defaultdict` indexes (SPO, POS, OSP)
plus an insertion-ordered dict of `Triple`s. It has worked for 15 years, but
on real data the cost is now the cyclic garbage collector, not lookups:

- FHIR R5 examples as one graph (645,566 triples, 346,108 blank nodes),
  measured by the compare session with `benchmarks/gc_census.py`: loading
  adds about 4.19M GC-tracked objects. 2.44M of them (58%) are index
  `defaultdict`s, about 3.8 per triple, most holding one entry. One full
  `gc.collect()` takes about 2 ms before loading and 0.30-0.32 s after, on
  3.12 and 3.14. Every long-lived program holding a graph pays that on every
  full collection.
- `obi.nt` (117,997 triples), measured by a scratch probe on 3.12 and 3.14:
  the index adds 3.0 tracked objects and about 833 bytes per triple on top of
  the terms, and full-collection time goes from 44-48 ms (terms only) to
  107-113 ms.
- `gc.freeze()` is not a substitute: on 3.14 it leaves `canonical_labels`'
  full collections at 0.88 s on FHIR.

Facts that shape the design, each checked on the supported interpreters:

- Every instance of a Python-defined class is GC-tracked, even a `str` or
  `tuple` subclass with `__slots__ = ()`. Term objects cannot be made
  invisible to the collector; there can only be fewer of them.
- CPython 3.14 no longer untracks dicts that hold only ints (3.12 does), so
  integer ids in nested dicts do not help the primary target.
- An `array.array` is one tracked object whatever its length, and the
  collector does not visit its items. `array` and `bisect` exist on every
  supported interpreter.
- Hash width is 64 bits everywhere except Pyodide (32 bits). Only PyPy holds
  a 63-bit int in a machine word; on CPython, GraalPy and Pyodide a 63-bit
  and a 96-bit key cost the same in a set (measured: 91-110 ns, 349-409 ns,
  130-148 ns per add and lookup).
- `array('l')` is 8 bytes on macOS and 4 on Pyodide; `array('I')` is 4 bytes
  and `array('q')` 8 bytes on both.

## Goals

1. Fix the existing bugs (listed under Behavior changes).
2. Cut memory per triple.
3. Cut GC work: the index adds close to zero tracked objects per triple.
4. Stay no slower than today on 3.14 for loading and Turtle writing.

Pure Python, standard library only, on everything in the tox env list:
CPython 3.12-3.15, PyPy 3.12, GraalPy 3.12/3.13, Pyodide 3.12/3.14. 3.14 is
the primary target.

Non-goals: persistence, concurrency, a SPARQL engine, lookups inside triple
terms (see Future work).

## API

The public `Graph` and `Dataset` API stays as it is, with additions to
`Dataset`. Callers outside `primitives.py` use only `match`, `subjects`,
`predicates`, `objects`, `in`, `len` and iteration, and none touch the
private indexes. The behavior changes below are the only breaking changes
this work makes; any other is raised with Gavin before it goes in.

## Design

### Term dictionary

`TermDictionary` maps terms to dense integer ids and back.

- `_terms`: list, `_terms[id]` is the term, or `None` for a freed id.
- `_ids`: dict, term to id.
- `_free`: list of freed ids, reused by `intern` before new ids are appended.
- `intern(term) -> id` adds the term if it is new.
- `lookup(term) -> id | None` never adds, so querying an unknown term
  allocates nothing.

Ids come from the term's `__eq__` and `__hash__`, so equal IRIs and literals
share an id, and a `BlankNode` keeps identity semantics. This relies on
`Literal` normalizing a simple literal to `xsd:string`, which the base branch
does. The graph returns its own instance of each term: equal to the caller's,
not necessarily the same object.

Ids are below 2^32, so they fit an `array('I')` column and a 32-bit field of
a packed key. `intern` raises `OverflowError` past that.

**Triple terms (RDF 1.2).** A triple term is interned as one opaque term and
can be a subject or object. Its components are not interned separately; the
Python object keeps them alive. The 2.0 triple-term type does not exist yet;
this design requires that it never compares or hashes equal to a `Literal` or
a plain tuple. `Triple` and `Literal` are both tuple subclasses today, and
tuple equality ignores the subclass, so a bare tuple subclass would merge a
triple term and a literal with equal parts into one id.

**Compaction.** A triple refers to at most 3 terms, so the live terms number
at most 3n for n triples (quads, in a dataset; plus one per graph name).
After a remove, if the number of interned terms, `len(_ids)`, exceeds
`6n + names`, at least half of them are provably dead, and `compact()`
runs. It counts `_ids`, not `_terms`: freed slots stay in `_terms` as `None`
and must not keep the trigger firing.

1. Scan the index arrays (and, in a dataset, the graph names) for live ids.
   The scan is the caller's job; `compact(live_ids)` frees every other id.
2. Set each dead id's slot to `None`, delete it from `_ids`, push it on
   `_free`.

No ids are renumbered and no arrays rewritten. Ids are private to the graph
or dataset, so reusing them is safe. With n = 0 any leftover term triggers
compaction. Wasted space stays linear in live triples.

### Index layout

The index is an adjacency list kept three ways, chosen by the trial
described under "Index trial" below. Each graph has:

- `_keys`: a dict from packed key to `None`. A packed key is
  `s << 64 | p << 32 | o`, an untracked int. The dict is membership, the
  duplicate check, and insertion order: removing and re-adding a key moves it
  to the end, as `_triples` did.
- SPO, POS and OSP orderings, each a dict from a first-position id to a
  row: the sorted packed `second << 32 | third` values of the triples with
  that first id. `match(s)` is one dict lookup; `match(s, p)` adds a bisect
  within the row.
- A row is a tuple. CPython untracks a tuple holding only ints (at creation
  since 3.14, after its first collection before that), so an ordering costs
  the collector one dict whatever its size. A row longer than `LIST_DEGREE`
  (rdf:type in POS, say) is a sorted list instead, so inserts do not rebuild
  it; only those few rows are tracked.
- A pending list of adds not yet in the orderings.

Operations:

- `add`: intern the three terms; if the key is new, insert it in `_keys` and
  append it to the pending list.
- Merge: the next query that needs the orderings moves pending adds in. A
  few are inserted value by value; a batch larger than
  `max(FOLD_MIN, len(keys) // FOLD_DIVISOR)` is folded: sorted per ordering,
  grouped by first id, and each touched row rebuilt once.
- `remove`: delete from `_keys` and bisect the value out of each ordering's
  row, dropping a row when it empties.
- `removeMatches`: collect the matches first, then remove them in one pass.

Tracked objects per graph: `_keys`, three ordering dicts, the pending list,
and the list rows of high fan-out keys. Per triple: none.

### match and iteration

- Bound or unbound is `is not None`, so a falsy term such as `NamedNode("")`
  is a real term, not a wildcard.
- A bound term the dictionary has never seen gives an empty result at once.
- All three bound: one `_keys` lookup.
- None bound: walk `_keys` in insertion order.
- The other six patterns: a bisect range on the first column of SPO, POS or
  OSP, then on the second column within it. They yield in index order, which
  is term-id order; ids follow the order terms were first seen anywhere in
  the graph.
- Iterating the graph walks `_keys` and builds each `Triple` from
  `_terms`. `match` builds fresh `Triple`s too: the graph keeps no `Triple`
  objects.
- `subjects()`, `predicates()` and `objects()` walk the distinct runs of the
  first column of SPO, POS and OSP, so a term with no remaining triples never
  appears.
- A version counter is bumped on every add and remove. A `match` with a
  term unbound, or an iteration, checks it on each step and raises
  `RuntimeError` if the graph changed anywhere, even after its last
  result. A fully bound `match` is a membership test made when called, so
  it needs no check, and the caller may remove its one triple. This is required
  because a merge rewrites the arrays under a live generator. It is
  stricter than the dicts and set it replaces, which raised only when the
  part being walked changed; see Behavior changes. A dataset-wide read
  raises if any graph of the dataset changes.
  Snapshot readers that skip removed triples instead were built and
  measured (Task 22, branch `task22-snapshot-readers`), but cost 5-11%
  on default Turtle and two-bound matches, so they are not in.

If benchmarks show fresh `Triple` allocation in `match(subject=s)` slows
Turtle writing past the acceptance bar, the fallback is one plain list of
`Triple`s indexed by a triple id: one tracked object per triple, still far
under today's 3.8 dicts.

### Dataset

An RDF dataset is a default graph plus a set of (name, graph) pairs, and
blank nodes can be shared between its graphs (RDF 1.2 Concepts 4.1).

- One `TermDictionary` per dataset, shared by all its graphs. Graph names are
  interned in it. A blank node is one id across the whole dataset, whether
  it appears in several graphs or names a graph and appears in triples.
- Each graph keeps its own `_keys`, orderings and buffer, so a graph-scoped
  `match` never touches other graphs. If the benchmarks show the per-graph
  fixed cost hurts for a dataset of thousands of graphs (FHIR loaded one
  graph per file), the fallback is one GSPO index with a graph column.
- The default graph is keyed by `None`, as `Quad.graph` already is, and
  always exists.
- A named graph exists once added, by `add_graph` or by adding a quad to it.
  It persists when emptied: a dataset with `<g> { }` is not isomorphic to one
  without `<g>`. `remove_graph(graph_or_name)` removes it.
- Reads never create graphs: `match(graph=g)` and `in` on a missing graph
  give nothing.
- `Dataset.graphs` yields `Graph` views bound to the dataset and its
  dictionary. A standalone `Graph()` owns its own dictionary.
- `add_graph(graph)` copies the graph's triples in by re-interning them.
  `BlankNode` equality is identity, so blank nodes the copied graph shares
  with the dataset stay shared. The caller's `Graph` object is not the one
  inside the dataset; edits to it do not reach the dataset.
- `Triple in dataset` means the triple is in the default graph. A `Quad` is
  checked in its graph. `__contains__` returns a `bool`.
- `match(..., graph=None)` keeps today's meaning, any graph, and yields
  `Quad`s whose `graph` is `None` for the default graph.
- `remove_graph(None)` raises `ValueError`: the default graph always exists.
- `Graph.add` raises `TypeError` for anything that is not three terms, so a
  `Quad` can no longer be put in a `Graph`.
- Compaction counts quads across all graphs, and the live scan covers every
  graph's arrays and every graph name.

N-Quads cannot carry an empty named graph
([RDF 1.2 N-Quads](https://www.w3.org/TR/rdf12-n-quads/) says so in a
note), so a dataset written as N-Quads loses them. Line-TriG keeps them.

### Threads

Free-threaded Python is coming, and even with the GIL a thread can switch
between any two bytecodes. Reads change shared state here: the first read
after adds merges or folds the pending adds into the rows, and interning
and compaction change the dictionary. So two threads reading one graph
could corrupt it without a lock.

- One `threading.Lock` per standalone `Graph` and one per `Dataset`, shared
  by the dataset's graph views, as they share its dictionary. It lives in
  `Graph` and `Dataset`; `TermDictionary` and `TripleIndex` stay lock-free
  building blocks, and the lock belongs to whoever owns the dictionary,
  because interning and compaction reach across every index that shares it.
- Held for every change (`add`, `remove`, `removeMatches`, `add_graph`,
  `remove_graph`, with their interning and compaction), for `len`, `in`,
  `object_counts` and the argument-free `subjects()`, `predicates()` and
  `objects()`, and for the start of every generator read: the pattern's
  ids, the merge of pending adds, and capturing what the read walks. The
  index's readers do that work when called, not on their first `next()`,
  so the lock covers it. Never held while a generator yields.
- Never taken while held. `add_graph` reads its source graph before taking
  the lock, since the source may be a view of the same dataset; `addAll`
  reads its source between batches of 1024, each added in one hold. So a
  plain `Lock` is enough.
- The contract: each call is atomic; any mix of threads reading and
  changing one graph or dataset leaves it consistent; there are no
  multi-call transactions, and `addAll` is atomic per batch, not per call.
  A read open while another thread changes the graph raises
  `RuntimeError`, as it does when its own thread changes it.

### Line-TriG

Datasets with empty named graphs and shared blank nodes need test fixtures,
and N-Quads cannot express the first. Line-TriG, a line-oriented profile of
TriG ([RDF 1.2 TriG](https://www.w3.org/TR/rdf12-trig/)) defined in
`docs/line-trig.rst`, can: one statement per line in N-Triples term syntax, `G { S P O . }` for a named-graph triple, `G { }` for
an empty named graph. Every Line-TriG document is a TriG document with the
same meaning.

pymantic gets a Line-TriG reader and writer (about 100-150 lines, reusing the
N-Triples grammar). The reader rejects any line outside the profile with its
line number. They are the first commits on this branch, ahead of the index;
the index tests use them.

## Behavior changes (for the changelog)

- `subjects()`, `predicates()` and `objects()` no longer return terms whose
  last triple was removed.
- `removeMatches` no longer raises `RuntimeError` when more than one triple
  matches.
- A falsy term such as `NamedNode("")` passed to `match` is a real term, not
  a wildcard.
- `match` on a pattern with a bound term yields in index order, not
  per-subject insertion order. Default (non-stable) Turtle output order
  (blocks, blank node labels, objects under a predicate) follows index order
  and is not guaranteed; the old order was never designed (Gavin,
  2026-10-02). Only `stable=True` output is ordered by content, and it and
  `pymantic.compare` are unchanged.
- `subjects()`, `predicates()` and `objects()` with no arguments return lists
  of distinct terms in term-id order, not dict key views in first-seen
  order. With arguments they are new Triple-free lookups (`objects(s, p)`
  and friends), alongside the new `predicate_objects(s)`.
- `Graph.add` and `Graph.remove` raise `TypeError` for anything that is not
  three terms, so JSON-LD and N-Quads must be parsed into a `Dataset`.
- `match` and the graph return the graph's own instance of each term, equal
  to the one added.
- `Graph()` without a name has `uri` `None`, not `NamedNode("None")`.
- `in` on a `Graph` or `Dataset` is `False` for a statement holding an
  unhashable term, instead of raising `TypeError`.
- The N-Quads parser returns a `Dataset`. Passing it a `Graph` raises
  `TypeError`; `Graph.add` rejects `Quad`s.
- `Dataset`: reads no longer create graphs; `remove_graph` works; empty named
  graphs persist; `Triple in dataset` checks only the default graph;
  `__contains__` returns a `bool`; `add_graph` copies, so the passed `Graph`
  is not the dataset's graph.
- `Dataset.graphs` always lists the default graph, first. Iterating a
  dataset and `match(graph=None)` yield the default graph's quads first,
  then each named graph's in creation order.
- Changing a graph in any way while a `match` with a term left unbound, a
  lookup, `mapped_triples` or an iteration over it is open raises
  `RuntimeError` on that generator's next step, even after its last
  result; a dataset-wide read raises when any of its graphs changes.
  Before, only a change to the dict or set being walked did, so editing
  one subject while reading another worked. Collect results with `list()`
  before changing the graph.

## Testing

New `tests/test_index.py`, with Dataset fixtures in Line-TriG:

- Model-based: a reference model (a set of triples or quads, filtered with
  comprehensions) runs alongside `Graph` and `Dataset` through seeded random
  add, remove and `removeMatches` sequences, sized to cross the merge
  threshold and the compaction trigger. After each step all 8 `match`
  patterns, `len`, `in`, iteration order, `subjects`, `predicates` and
  `objects` must agree. Stdlib `random` with fixed seeds.
- Regressions for each fixed bug in Behavior changes.
- Term dictionary: free-list reuse, the compaction trigger at the
  `len(_ids) > 6n + names` boundary, the trigger not refiring after a
  compaction, `OverflowError` past 2^32 (with the limit
  patched low), and a `Literal` and a triple term with colliding parts
  getting distinct ids. Until the 2.0 triple-term type exists, that test
  uses a stand-in class meeting the stated requirement and is replaced when
  the real type lands.
- Dataset: empty named graphs persist until `remove_graph`; a blank node
  shared across graphs and used as a graph name; `add_graph` keeps blank
  node identity; reads create no graphs.
- Mutation during `match` or iteration raises `RuntimeError`.
- Line-TriG: round trips, and the reader rejecting out-of-profile input.
- The full existing suite, W3C tests included, passes in every tox env.

## Benchmarks and acceptance

Use the tools on the base branch, with data fetched by
`benchmarks/fetch_data.py` from pinned checksums. Inputs:
`fhir-r5-examples`, `obi`, `doid`, `schemaorg-shapes`. Timing on 3.12, 3.13
and 3.14, best-of-N, every run printed, differences under 5% treated as
noise; pypy312 and pyodide314 for correctness and memory. The index trial
followed this plan (its tables say which interpreters each figure is
from); the Task 17 tuning below was timed on 3.14 only, with the chosen
constants checked on pypy312.

- `timing.py`: the `canonical_labels` and stable Turtle digests must be
  identical before and after.
- `gc_census.py`: `defaultdict` and `Triple` must drop out of the
  tracked-object census for a loaded graph.
- `benchmarks/graph_index.py`, following the README conventions (names
  from `inputs.py`, `--help`, best-of-N): load time, bytes per triple, the 8
  `match` patterns, full iteration, the `Counter` over objects, batched and
  interleaved adds, and a dataset with one graph per FHIR file.

Results (FHIR R5 examples as one graph, 645,566 triples, Python 3.14; "old"
is the index at 3938832; the full tables are under "Index trial"):

| | old | new |
|---|---|---|
| full `gc.collect()`, graph loaded | 411 ms | 61 ms |
| tracked objects per triple, index only | 3.79 | 0 |
| index bytes per triple | 1030 | 421 |
| load (`addAll` of parsed triples) | 1.59 s | 0.68 s |
| default Turtle | 1.44 s | 1.64 s |
| stable Turtle | 7.42 s | 7.73 s |
| FHIR as a dataset, one graph per file: load | 1.56 s | 0.63 s |
| same: full `gc.collect()` | 283 ms | 91 ms |

- `timing.py`: `canonical_labels` and stable Turtle digests are identical
  before and after, on every interpreter measured. The default Turtle digest
  changes. Beyond object order within a predicate, block order and blank
  node labels change too, since they follow index order; Gavin ruled
  default output order not guaranteed (2026-10-02, see Behavior changes).
- `gc_census.py`: `defaultdict` (2.44M) and `Triple` (646k) drop out of the
  tracked-object census for a loaded FHIR graph; what remains is the terms.
- Per-graph indexes stay: one graph per FHIR file loads faster than one
  merged graph, with 0.026 tracked objects per quad, so there is no case
  for a GSPO index.

Acceptance:

- Met: the index adds close to zero GC-tracked objects per triple (0 on
  FHIR, 0.001 on obi and schemaorg-shapes).
- Met: full-collection time with FHIR loaded is 61 ms, well below 0.30 s
  (411 ms before). The before and after are in the changelog.
- Met: load time on 3.14 is 2.3x faster (0.68 s against 1.59 s).
- Not met: Turtle writing on 3.14 is slower than with the old index, 14% by
  default (1.64 s against 1.44 s) and 4% with `stable=True` (7.73 s against
  7.42 s). Gavin chose the adjacency index with those numbers (2026-10-02).
- Not met: the full suite does not pass on every tox env. On graalpy312 and
  graalpy313, 171 tests each fail (tox on a local merge with
  tox-interpreters, Task 17): `pymantic.compare.term_code` calls
  `hashlib.blake2b(..., digest_size=8)`, which GraalPy does not support
  (3.12 has only the default 64-byte blake2b, 3.13 no blake2b at all).
  Every failing test reaches `canonical_labels`; the index tests pass. The
  code predates this branch (it came with the compare branch), and the fix
  needs Gavin's decision on a hash every interpreter has. All other envs
  pass. pyodide312 prints one `PytestCacheWarning` under tox (pytest cannot
  write its cache in `$TOX_ENV_DIR` there); a checkout of tox-interpreters
  alone prints it too.

## Index trial

The first implementation (sorted `array('I')` columns, the layout this spec
first described) met the GC and memory goals but missed the speed ones:
`match(subject=s)` cost 0.95 us against 0.41 us for the old index, Turtle
writing was up to 62% slower, and one add followed by a query cost ~120 us
on large graphs, because a merge inserted into nine arrays. `rdf.py`'s
Resource layer makes one small subject-keyed lookup after another, so lookup
speed matters beyond the writer.

`Graph` and `Dataset` only use the index through its interface, so
candidates were swapped in behind it and run under the same tests (the
20-seed model tests, the mutation and detach rules, the Graph and Dataset
tests) and the same benchmarks (`benchmarks/graph_index.py`,
`benchmarks/timing.py`, `benchmarks/gc_census.py`, each with `--index`).

Candidates:

- **sorted**: the first implementation.
- **offsets**: sorted columns plus a per-term offsets array for O(1) range
  starts, a small sorted delta for new rows, a set of dead rows, folded into
  the main columns past a threshold.
- **B+tree**: per ordering, a list of leaves of `array('I')` columns and a
  list of each leaf's first key (array leaves, because list-of-int leaves
  cost ~177 B/triple and doubled full-GC time with no lookup gain).
- **adjacency**: the layout above.
- **dict**: the original nested-dict design over ids, as a control.

### Measurements

FHIR R5 examples merged into one graph (645,566 triples), best of 3-5 runs;
"old" is the unchanged index at 3938832. Index memory and tracked objects
exclude the caller's terms and Triples. Turtle times are with the
Triple-free writer.

Python 3.14:

| | old | sorted | offsets | B+tree | adjacency | dict |
|---|---|---|---|---|---|---|
| index B/triple | 1030 | 164 | 172 | 165 | 421 | 1082 |
| tracked objects/triple | 3.79 | 0 | 0 | 0.02 | 0 | 3.79 |
| full GC, graph loaded | 411 ms | 53 | 54 | 55 | 61 | 280 |
| load | 1.59 s | 0.64 | 0.68 | 0.62 | 0.68 | 1.52 |
| 1000 `match(s)` | 1.02 ms | 1.84 | 1.27 | 1.85 | 1.45 | 1.86 |
| 1000 `match(s, p)` | 0.86 ms | 1.83 | 1.30 | 1.95 | 1.45 | 1.68 |
| 1000 adds then a query | 1.6 ms | 121 | 7.9 | 3.3 | 6.6 | 1.9 |
| 1000 add-then-match rounds | 3.2 ms | 126 | 4.4 (one run 464) | 6.6 | 9.5 | 4.6 |
| default Turtle | 1.44 s | | 1.87 | 2.17 | 1.64 | |
| stable Turtle | 7.42 s | | 7.95 | 8.26 | 7.73 | |

3.13 and 3.12 gave the same ranking. Python 3.15.0rc2:

| | old | offsets | adjacency |
|---|---|---|---|
| index B/triple | 1030 | 172 | 421 |
| full GC | 432 ms | 54 | 61 |
| 1000 `match(s)` | 1.03 ms | 1.26 | 1.43 |
| 1000 adds then a query | 1.6 ms | 5.8 | 6.9 |
| default / stable Turtle | 1.43 / 7.37 s | 1.91 / 8.29 | 1.66 / 7.80 |

PyPy 3.12 (no memory figures there):

| | old | offsets | B+tree | adjacency |
|---|---|---|---|---|
| full GC | 222 ms | 49 | 51 | 69 |
| 1000 `match(s)` | 1.60 ms | 0.92 | 4.08 | 1.23 |
| 1000 adds then a query | 1.7 ms | 14.8 | 3.7 | 5.9 |
| default / stable Turtle | 1.67 / 5.84 s | 1.69 / 5.88 | 1.95 / 6.29 | 1.66 / 5.85 |

Pyodide 3.14 (Turtle on obi, 118k triples):

| | old | offsets | B+tree | adjacency |
|---|---|---|---|---|
| index B/triple | 604 | 120 | 113 | 248 |
| full GC | 1499 ms | 137 | 141 | 152 |
| 1000 adds then a query | 200 ms | 8.0 | 6.2 | 12.6 |
| obi default / stable Turtle | 0.47 / 1.07 s | 0.43 / 1.09 | 0.47 / 1.15 | 0.40 / 1.08 |

`canonical_labels` and stable Turtle digests were identical for every
candidate on every interpreter.

### Findings

- Every array or tuple based candidate meets the GC and memory goals: full
  collections 7-10x faster, index memory 2.4-6x smaller, load 2.5x faster.
- No candidate matches the old index on small lookups. The old index handed
  back Triples it already stored; anything over ids builds them per result.
  The dict control (old structure, over ids) wrote FHIR Turtle 0.45 s slower
  than the old index, so about half the writer gap was Triple building, not
  index structure. The Triple-free `Graph` lookups and writer recovered
  9-10% for every candidate with byte-identical output.
- `canonical_labels` did not get faster. Each full collection is ~9x
  cheaper, but CPython now runs ~4x as many during it (2 vs 8 on FHIR, 3.14):
  its full-collection trigger is relative to the long-lived tracked objects,
  which the old index inflated. Its GC time is now `pymantic.compare`'s own
  working objects.
- sorted: adds ~100x slower than the others, no lookup advantage. Out.
- dict: the old GC load. Control only. Out.
- B+tree: as lean as sorted and the best adds, but lookups no faster than
  sorted (a bisect inside a boxed `array('I')` leaf) and 4x slower on PyPy,
  so the slowest writer everywhere. Out.
- offsets: the fastest `match()`, but a fold pause (~460 ms on FHIR, about
  one interleave run in five) and slow adds on PyPy.
- adjacency: never worst on any measure; the fastest writer on every
  interpreter (within 14% of the old index on CPython FHIR default Turtle,
  4% stable, equal on PyPy, faster on obi and Pyodide); no fold pauses. Its
  cost is memory: 421 B/triple, 2.4x offsets, 2.4x less than the old index.

### Decision (Gavin, 2026-10-02)

Adjacency. The other candidates are deleted.

### Tuning (Task 17)

The constants were measured on 3.14 only (pypy312 checked the chosen
values) with `benchmarks/graph_index.py`
(load, batches of 1, 32, 33 and 1000 adds, interleaved adds, the match
patterns) and `benchmarks/timing.py --what turtle`, on `fhir-r5-examples`
and `obi`, best of 5, one constant changed at a time from LIST_DEGREE 256,
FOLD_MIN 1024, FOLD_DIVISOR 16, with the defaults run first and last.

| change | FHIR | obi |
|---|---|---|
| LIST_DEGREE 64 | all within 5% | within 5% except batch 32 (-6.6%), match sp (-6.2%) and match o (-5.4%), each within 5% of one of the two default runs |
| LIST_DEGREE 1024 | batches +3 to +5.4%, interleave +6.5%, batch 1 +14% (0.007 to 0.008 ms) | batches +8 to +10% |
| FOLD_DIVISOR 8 | load +4.5%, match s +7%, otherwise within 5% | full GC +7%, match o +5%, otherwise within 5% |
| FOLD_DIVISOR 32 | all within 5% | full GC +6%, otherwise within 5% |
| FOLD_MIN 256 | all within 5% | all within 5% |
| FOLD_MIN 4096 | all within 5% | matches +13 to +18%, full GC +26%; noise, as below |

Load folds the whole graph whatever the constants, and no batch in
`graph_index.py` (at most 1000 adds into graphs of 118k and 646k triples)
crosses the fold threshold for any value tried, so FOLD_MIN and
FOLD_DIVISOR change no code path these runs take, and their columns show
the session's noise: up to 18% on obi's sub-millisecond matches.
LIST_DEGREE 1024 loses on adds, as longer tuple rows cost more to rebuild;
64 gains nothing beyond noise. The constants stay as they were.

A direct measurement of the fold threshold
(`benchmarks/out/scripts/fold_crossover.py`, not committed: one batch of k
new triples into a loaded graph, folded against inserted one by one, best
of 3; timed on 3.14 for all four inputs and pypy312 for fhir-r5-examples
and schemaorg-shapes) shows the threshold is not where the constants put
it. To regenerate: load the input with `inputs.load`, `addAll` it into a
`Graph` and query once; add k triples made by `graph_index.new_triples`,
then query once; time that with `triple_index.FOLD_MIN, FOLD_DIVISOR` set
to `0, 1 << 62` (always fold) and to `1 << 62, 1` (never fold), for k in
256, 1024, 4096 and n/64 to n/4.

| input (triples) | fold faster from | fold/insert at n/32 | at n/16 |
|---|---|---|---|
| fhir-r5-examples (646k) | 1,024 to 4,096 adds | 0.31x | 0.28x |
| doid (310k) | 1,024 to 4,096 adds | 0.65x | 0.54x |
| obi (118k) | about 3,700 adds (3%) | 0.97x | 0.83x |
| schemaorg-shapes (24k) | never clearly (1.0x at 25%) | 1.28x | 1.09x |

(PyPy 3.12 is similar, with folding winning on
FHIR from 256 adds.) A batch between FOLD_MIN and n/16 on FHIR is inserted
at up to 3.5x the cost of folding it, about 190 ms for 40k adds. FOLD_DIVISOR
32 halves that range at a cost of about 0.2 ms (10-16%) on
schemaorg-sized graphs for batches of 1,024 to 1,500. Bulk loads and small
batches are unaffected either way.

Decision (Gavin, 2026-10-03): FOLD_DIVISOR 32. LIST_DEGREE 256 and
FOLD_MIN 1024 stay.

### PyO3

A Rust index behind the same interface is possible later, but would not
help much now. A profile of FHIR default Turtle with adjacency (3.14,
cProfile, shares approximate): writer code 45%, built-ins it calls 24%,
`Graph` id-to-term translation 21%, index 8%, term dictionary 2%. A free
index would save under a tenth of the write; `canonical_labels` does not
touch the index. The clear win would be memory (packed u32 rows instead of
Python int objects). Costs: wheels per platform, a wasm build for Pyodide,
and on PyPy a C extension is often slower than the JIT running pure Python.
The pure-Python index stays either way.

## Future work

- An optional PyO3 index behind the same interface, if memory on very large
  graphs becomes the constraint (see "Index trial", PyO3). The pure-Python
  index stays as the fallback, and both run the same model tests.
- `pymantic.compare`'s working state is now what the collector walks during
  `canonical_labels`; keeping it in int structures is the next GC gain.
- `rdf.py`'s `(s, p, ?)` reads should use `Graph.objects(s, p)`.

- A component index for lookups inside triple terms (three more `array('I')`
  columns from a triple term's parts to its id), when a SPARQL engine or
  other consumer needs it. Ids and the dictionary need no change for it.
- A full TriG parser and writer; Line-TriG becomes a writer setting. The
  Line-TriG fixtures double as conformance input for it.
- A small branch off main fixing the `remove`/`subjects()` bug ahead of this
  work, as the compare session suggested.
