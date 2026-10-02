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

Each graph has:

- `_keys`: a dict from packed key to `None`. A packed key is
  `s << 64 | p << 32 | o`, an untracked int. The dict is membership, the
  duplicate check, and insertion order: removing and re-adding a key moves it
  to the end, as `_triples` does today.
- SPO, POS and OSP orderings, each three parallel `array('I')` columns sorted
  together lexicographically: 9 arrays, about 36 bytes per triple.
- A pending buffer: three `array('I')` columns of adds not yet in the
  orderings.

Operations:

- `add`: intern the three terms; if the key is new, insert it in `_keys` and
  append to the buffer.
- Merge: the first query that needs the orderings sorts the buffer into each
  ordering. A small buffer is merged; a large one (a bulk load, starting from
  empty) is sorted once. The threshold between the two is set from the
  benchmarks.
- `remove`: delete from `_keys`; delete from the buffer by a linear scan,
  or from each ordering by bisect. Removing one triple is O(n) per ordering
  because the arrays shift.
- `removeMatches`: collect the matches first, then delete them in one
  rebuild of the orderings.

Tracked objects per graph: `_keys`, 12 arrays, and a few fixed attributes.
Per triple: none from the index.

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
- A version counter is bumped on every add and remove. A `match` or
  iteration generator checks it on each step and raises `RuntimeError` if
  the graph changed, as dict iteration does today. This is required because
  a merge rewrites the arrays under a live generator.

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
- `match` on a pattern with a bound term yields in term-id order (the order
  terms were first seen in the graph), not per-subject insertion order. In
  default (non-stable) Turtle output, the objects listed under one predicate
  can come out in a different order. Stable Turtle and `pymantic.compare`
  are unaffected: they sort.
- `match` and the graph return the graph's own instance of each term, equal
  to the one added.
- `Graph()` without a name has `uri` `None`, not `NamedNode("None")`.
- The N-Quads parser returns a `Dataset`. Passing it a `Graph` raises
  `TypeError`; `Graph.add` rejects `Quad`s.
- `Dataset`: reads no longer create graphs; `remove_graph` works; empty named
  graphs persist; `Triple in dataset` checks only the default graph;
  `__contains__` returns a `bool`; `add_graph` copies, so the passed `Graph`
  is not the dataset's graph.

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
noise; pypy312 and pyodide314 for correctness and memory.

- `timing.py`: the `canonical_labels` and stable Turtle digests are
  identical before and after. The default Turtle digest may change, and any
  difference must come only from object order within a predicate.
- `gc_census.py`: `defaultdict` and `Triple` drop out of the tracked-object
  census for a loaded graph.
- New `benchmarks/graph_index.py`, following the README conventions (names
  from `inputs.py`, `--help`, best-of-N): load time, bytes per triple, the 8
  `match` patterns, full iteration, the `Counter` over objects, and a
  dataset with one graph per FHIR file. It sets the merge threshold and
  decides per-graph indexes vs GSPO.

Acceptance:

- The index adds close to zero GC-tracked objects per triple.
- Full-collection time with FHIR loaded drops well below 0.30 s; the
  measured before and after go in the changelog.
- Load time and Turtle write time on 3.14 are no slower than today.

## Future work

- A component index for lookups inside triple terms (three more `array('I')`
  columns from a triple term's parts to its id), when a SPARQL engine or
  other consumer needs it. Ids and the dictionary need no change for it.
- A full TriG parser and writer; Line-TriG becomes a writer setting. The
  Line-TriG fixtures double as conformance input for it.
- A small branch off main fixing the `remove`/`subjects()` bug ahead of this
  work, as the compare session suggested.
