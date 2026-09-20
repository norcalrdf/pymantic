=====================================
Graph comparison and stable output
=====================================

This note describes how pymantic decides whether two RDF graphs are the same
and how it writes a graph so that the same graph always produces the same
bytes. Both come from one piece of machinery, described here so the code in
:mod:`pymantic.compare` can be read against the idea rather than the other
way round.

Why
===

RDF files under version control need to be stable: writing the same graph
twice must produce an identical file, and a small change to the graph must
produce a small diff. Blank nodes break this. Their labels have no meaning
outside the file, so a tool that assigns them in encounter order, or in the
iteration order of a hash table, rewrites every label and reorders every
block on every save. SHACL shape files are the common case: a shape is a
named node with dozens of anonymous ``sh:property`` nodes, many of which
nest further anonymous nodes and lists.

The fix is to derive blank node labels, and the order of statements, from
the content of the graph and nothing else. Once that exists, deciding
whether two graphs are isomorphic is a comparison of their canonical forms.

The approach here, treating the ground part of a graph as fixed and only
ever reasoning about connected groups of blank nodes ("molecules"), was
worked out by Gavin Carothers and Jeremy Carroll at TopQuadrant around
2012 to keep TopBraid's Turtle files stable in git. It was not published.
The refinement used inside a molecule is Carroll's from *Matching RDF
Graphs* (HP Labs, HPL-2001-293, 2001), the algorithm behind Jena's
isomorphism check, which in turn is Read and Corneil's iterative vertex
classification of 1977.

What this is not
================

This is not an implementation of the W3C RDF Dataset Canonicalization
specification (RDFC-1.0), and pymantic does not run its test suite. RDFC-1.0
exists to sign datasets, so it mandates SHA-256 hashing and a canonical
N-Quads form whose exact labels other implementations must reproduce. None
of that is needed to compare two graphs in memory or to write a stable file.
Speed is not the reason: on the schema.org SHACL shapes (24k triples, 11.6k
blank nodes) the RDFC-1.0 implementations in pyld and rdf-canonize finish
in 0.2 s and 1.1 s, within a small factor of this module, because their
first-degree hash already tells nearly every blank node apart. What is
avoided here is the fixed label format and the search that RDFC-1.0
prescribes, so that labels can be chosen for diff locality and the work
budget can be set by molecule. Carroll's 2001 observation still applies to
the hashing: collisions in refinement merely merge two classes and cost
efficiency, never correctness, so cheap hashes are the right choice. The
inputs of the RDFC-1.0 test suite are useful as adversarial fixtures; see
*Tests* below.

The algorithm
=============

Terms. A *ground* triple has no blank node in any position. A *molecule* is
a maximal set of blank nodes connected by triples whose subject and object
are both blank nodes, together with every triple that touches one of its
nodes. A molecule's *attachments* are the IRIs and literals in those
triples.

Isomorphism of two graphs proceeds in stages, and bails at the first stage
that can show a difference:

1. Triple counts must match.
2. The sets of ground triples must be equal.
3. The multisets of non-ground triples with every blank node replaced by a
   placeholder must be equal.
4. Both graphs are split into molecules. Each molecule gets a *signature*:
   its size and the multiset of its placeholder triples. Molecules are
   grouped by signature on each side; the group sizes must match.
5. Only now is any refinement done, and only within a molecule. Each
   molecule is reduced to a canonical form (below). Within a signature
   group the multisets of canonical forms must be equal. Two molecules with
   the same canonical form are isomorphic, and molecules with the same
   canonical form are interchangeable, so no matching between them is ever
   searched.

Stages 1 to 4 are linear in the size of the graph. Stage 5 works on inputs
the size of one molecule, which in real data is a handful of nodes.

Canonical form of a molecule. Carroll's iterative vertex classification with
hash codes:

* Every blank node starts in one class. A node's code for the next round is
  a commutative combination (a sum is fine) over the triples it appears in
  of a per-triple code, where the per-triple code combines the predicate,
  the node's role in the triple (subject, object, or both), and the current
  code of the other term: the term itself for an IRI or literal, the
  previous-round class code for a blank node.
* Repeat until the partition into classes stops changing. There is no cap
  on the number of rounds; Carroll notes that Jena's cap was "probably an
  error".
* If every class is a singleton, the classes ordered by code give the
  canonical order of the nodes, and the canonical form is the molecule's
  triples written with nodes replaced by their position in that order,
  sorted.
* Otherwise take the smallest class with more than one node, individualize
  one of its nodes into a class of its own, refine again, and recurse over
  each choice of node, keeping the lexicographically smallest resulting
  canonical form. This is the only place the algorithm guesses, and it only
  happens for nodes the labelled part of the graph cannot tell apart.

Hashes are ordinary Python ``hash`` values or a fast non-cryptographic
digest. A collision merges two classes and makes the search do a little
more work; it never makes two different molecules compare equal, because
the final comparison is on the canonical forms themselves, not on hashes.

Work budget. The individualization search can be forced into exponential
time by a graph built for the purpose: a hundred triples arranged so that
no content distinguishes any node, in the manner of the billion laughs
entity attack. Real data never looks like this. Each molecule therefore has
a work budget that is a polynomial in its size, so the time a molecule can
consume is bounded by how big it is: a small molecule cannot eat much,
whatever its shape, and only a large one can take long. When it is spent, :func:`pymantic.compare.isomorphic` raises
:class:`pymantic.compare.Undecidable` naming the molecule, and the stable
serializer raises the same error rather than silently write a file whose
blank node order is not derived from content. A caller that hits this has
a graph theorist's input, not a document.

Stable output. :func:`pymantic.compare.canonical_labels` assigns every
blank node a label from its molecule's canonical form and its position
within it. Molecules with identical canonical forms are interchangeable and
are numbered by a stable tie-break on their attachments' order. The
serializers, given ``stable=True``, use those labels and order sibling
blank nodes by their canonical form, so a ``sh:property`` set of twenty
anonymous nodes comes out in the same order regardless of insertion order.
Lists are already ordered by ``rdf:rest`` and need nothing extra. The
Turtle serializer also writes a blank node that is the object of exactly
one triple inline, as ``[ ... ]`` at that reference (``[]`` when it has no
triples of its own), nesting as deep as the data does up to
``MAX_INLINE_DEPTH`` (32) levels, a cap that keeps both the writer and a
recursive reader such as pymantic's own parser well inside Python's stack;
collections count toward the same cap, each ``(`` one level like each
``[``, and a list head past it is written as a labelled block of
``rdf:first`` and ``rdf:rest`` triples. Only a node referenced more than
once, one in a cycle that nothing outside refers to, or one past that depth
keeps its label and its own block. It
declares only the prefixes the output uses, in the profile's order. To
write a document back with its own prefixes, parse it with a
:class:`~pymantic.primitives.Profile`
(``turtle_parser.parse(data, profile=profile)``), which records the
document's declarations, and serialize with the same profile.

Implementation choices
======================

Points the description above leaves open, and how :mod:`pymantic.compare`
settles them:

* **Hashes.** Class codes are 64-bit integers from a fixed FNV-style mix.
  IRIs and literals are coded by an 8-byte BLAKE2b digest of their
  N-Triples form, cached per term. Python's own ``hash`` is not used because
  it is seeded per process, which would make stable output differ between
  runs. BLAKE2b here is a cheap, fixed digest, not a security measure.
* **Term identity.** The term model itself is canonical: every
  :class:`~pymantic.primitives.Literal` carries a datatype, filled in on
  construction with ``xsd:string`` for a simple literal and
  ``rdf:langString`` for a language-tagged string (RDF 1.1 Concepts 3.3), so
  a value written both ways is one term, one key, and one triple in the
  graph. Nothing downstream -- comparison, collection and inline-node
  planning, or the serializers -- has to reconcile the two forms.
* **Twins.** When a class must be split by guessing, nodes of that class
  whose incident statements are identical once the node itself is masked
  (with neighbours compared by identity) are twins: swapping two of them is
  an automorphism, so only one is tried. Twenty identical anonymous
  siblings under one blank node would otherwise cost twenty factorial
  branches. Nodes joined to each other by a statement are never twins.
* **Budget.** Work is counted in node visits: a refinement round over a
  molecule of n nodes costs n, and so does opening a branch. The allowance
  is n² × (64 + n). Honest but symmetric shapes, rings and ring lattices,
  need about n³/2 (n choices at the top, n/2 rounds each, one reflection to
  break) and fit at any size; random regular graphs and grids need a few
  n²; a list of a thousand identical anonymous members needs n²/3. A clique
  needs factorial work and trips at once. Measured worst case for a poison
  molecule, which always exhausts the budget: 0.04 s at 10 nodes, 0.4 s at
  20, 3 s at 40, 34 s at 80. The slowest honest case measured is a regular
  200-node ring lattice at 16 s.
  A caller can lower the allowance with ``work_limit`` (node visits per
  molecule) but never raise it.
* **Labels.** ``b`` followed by twelve hex digits of a digest of the
  molecule's canonical form, then ``m<i>`` when several molecules share a
  digest (numbered in canonical-form order, identical ones in encounter
  order) and ``n<position>`` when the molecule has several nodes. A digest
  rather than a rank across the file, because a rank would shift for every
  molecule after an edited one and destroy diff locality.
* **Datasets.** The graph name is part of every statement, and a blank
  graph name is a node of the molecule like any other. A named graph with
  no statements is part of the dataset too, so it is compared and labelled
  as a record of its own carrying only the name; N-Quads has no syntax for
  such a graph, so ``serialize_nquads(dataset, f, stable=True)`` cannot
  write it.

API
===

.. code-block:: python

   from pymantic.compare import isomorphic, canonical_labels, Undecidable

   isomorphic(graph_a, graph_b, work_limit=None)   # True/False; raises Undecidable
   canonical_labels(graph, work_limit=None)        # {BlankNode: "label"}

   serialize_turtle(graph, f, stable=True)
   serialize_ntriples(graph, f, stable=True)
   serialize_nquads(dataset, f, stable=True)

Both functions accept a :class:`~pymantic.primitives.Graph` or a
:class:`~pymantic.primitives.Dataset`; for a dataset, the graph name is
part of every triple's signature, so blank nodes shared across graphs are
handled by the same molecule logic. ``stable`` defaults to ``False`` so that
existing output does not change until a caller asks for it.

Measurements
============

Canonical blank node labels for one graph already in memory, parsing
excluded, measured on 2026-09-20 with Python 3.14 and Node 26 on the same
inputs for four implementations: this module; pyld 3.3.0's ``URDNA2015``,
which is RDFC-1.0's algorithm in pure Python; rdf-canonize 5.0.0, the
reference RDFC-1.0 implementation in Node, shown at the best of its work
factor settings because its default aborts on 18 of the RDFC-1.0 suite's own
inputs; and rdflib 7.6.0's canonicalizer, which is what its ``isomorphic``
computes. rdflib was capped at 60 seconds per input, the others at 120.

.. list-table::
   :header-rows: 1

   * - Input
     - Triples
     - Blank nodes
     - pymantic
     - pyld
     - rdf-canonize
     - rdflib
   * - schema.org SHACL shapes, 100 of 1017
     - 777
     - 258
     - 0.002 s
     - 0.003 s
     - 0.003 s
     - 0.22 s
   * - schema.org SHACL shapes, 400 of 1017
     - 5025
     - 2119
     - 0.016 s
     - 0.026 s
     - 0.015 s
     - 35.7 s
   * - schema.org SHACL shapes, whole file
     - 24039
     - 11658
     - 0.093 s
     - 0.166 s
     - 0.074 s
     - timeout
   * - preferential attachment graph, 1000 blank people, no attributes
     - 3984
     - 1000
     - 0.052 s
     - timeout
     - timeout
     - 11.4 s
   * - preferential attachment graph, 5000 blank people
     - 19956
     - 5000
     - 0.65 s
     - recursion error
     - timeout
     - timeout
   * - cycle, 80 nodes
     - 80
     - 80
     - 0.64 s
     - 0.15 s
     - 0.047 s
     - 1.3 s
   * - random 3-regular, 20 nodes
     - 60
     - 20
     - 0.010 s
     - 1.0 s
     - 0.25 s
     - 0.039 s
   * - random 3-regular, 40 nodes
     - 120
     - 40
     - 0.046 s
     - timeout
     - timeout
     - 0.24 s
   * - 8x8 grid
     - 112
     - 64
     - 0.004 s
     - 0.51 s
     - 0.13 s
     - 0.36 s
   * - 12x12 grid
     - 264
     - 144
     - 0.014 s
     - timeout
     - timeout
     - 4.2 s
   * - hub with 40 identical children
     - 80
     - 41
     - 0.004 s
     - 0.001 s
     - 0.001 s
     - 1.8 s
   * - 10-node clique (RDFC-1.0 poison test)
     - 100
     - 10
     - Undecidable, 0.04 s
     - timeout
     - timeout
     - n/a
   * - the other 64 RDFC-1.0 suite inputs, summed
     -
     -
     - 0.010 s
     - 0.042 s
     - 0.044 s
     - n/a

On real SHACL data the three fast implementations are within a factor of two
of each other and rdflib cannot finish the file. On relationship graphs,
every node blank and every edge symmetric, both RDFC-1.0 implementations
fail, one by timeout and recursion limit and the other by its own
denial-of-service guard, because their n-degree hashing follows blank-to-blank
chains; refinement here resolves such graphs on degree structure with a
handful of guesses. On locally symmetric graphs (regular graphs, grids)
RDFC-1.0's per-node permutation step blows up while one individualization
here resolves them. On globally symmetric rings this module is the slowest
of the three fast ones, n top-level choices each followed by n/2 refinement
rounds, bounded by the cubic budget; automorphism pruning would bring that
family from n³ to n² without changing any output. The clique is the only
input that is genuinely hard, and this module refuses it in 40 ms while the
others run until stopped.

Tests
=====

* Hand-written pairs in a manifest in the style of the W3C rdf-tests
  suites: isomorphic pairs that differ only in blank node labels and triple
  order, and near-miss pairs that differ in one triple, one datatype, one
  language tag, or the direction of one blank-node edge.
* The input files of the RDFC-1.0 test suite, vendored under the W3C test
  suite licence. Their expected outputs are not used. Each input yields
  three cases: relabelled and shuffled, it must be isomorphic to the
  original and serialize identically; with one triple removed or altered,
  it must not be isomorphic. The suite's poison graphs must raise
  :class:`Undecidable` quickly.
* Every Turtle evaluation test in the vendored W3C suites, parsed,
  shuffled, and serialized with ``stable=True`` twice, must give identical
  bytes.
* Real-world SHACL: the schema.org shapes file (24k triples, 11k blank
  nodes) serialized after a random shuffle must be byte-identical, and a
  single edited constraint must produce a diff confined to its shape. This
  file is not vendored; the check is run by hand before a release.
