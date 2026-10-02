Benchmarks
==========

Tools for measuring ``pymantic.compare`` (canonical blank node labels and
isomorphism) and the Turtle serializer on real and synthetic graphs. They are
for development, not part of the package, and are not run by the test suite.

Run everything from the repository root, in an environment with pymantic
installed (``pip install -e '.[testing]'``). To measure another source tree,
put its ``src`` first on ``PYTHONPATH``; every tool prints which pymantic it
imported.

Data
----

Real-world datasets are not kept in the repository. ``datasets.json`` lists
each one with a URL pinned to a release or commit and the SHA-256 of what it
serves; ``fetch_data.py`` downloads them into ``benchmarks/data/`` (ignored by
git), checks the checksums, and unzips or converts them::

    python benchmarks/fetch_data.py            # all of them, about 120 MB
    python benchmarks/fetch_data.py --list
    python benchmarks/fetch_data.py fhir-r5-examples

The OBO ontologies are published as RDF/XML and are converted to N-Triples
with rdflib, so fetching them needs ``pip install rdflib``.

Inputs
------

``inputs.py`` names every input once, so a name means the same graph in every
tool. Tools take input names, or one of the kinds ``real`` (fetched data, the
default), ``synthetic`` (generated blank-node graphs: cycles, ring lattices,
random regular graphs, grids, a hub with identical children, preferential
attachment social graphs) and ``rdfc10`` (the RDFC-1.0 test inputs vendored
in ``tests/compare``).

The most useful real inputs:

``fhir-r5-examples``
    The FHIR R5 Turtle examples merged into one graph: 645k triples, 95% of
    them touching a blank node, nested blank node trees and lists, molecules
    of up to 23k nodes. The stress case for real data.
``schemaorg-shapes``
    The schema.org SHACL shapes: property shapes as blank nodes, ``sh:in``
    and ``sh:or`` lists. Also ``schemaorg-shapes-100`` and ``-400``, the first
    100 and 400 shapes with their blank nodes.
``doid``, ``obi``
    OBO ontologies with many OWL restrictions and ``owl:Axiom`` annotations.

Tools
-----

``timing.py``
    Best-of-N times for ``canonical_labels``, default Turtle and stable
    Turtle, each with a digest of the result. Run it on two source trees to
    check a change is faster and changes no output.
``profiling.py``
    cProfile of the same operations; full profiles go to ``benchmarks/out/``.
``census.py``
    How blank-node heavy an input is: triples touching blank nodes, molecule
    count and sizes. Use it to judge whether a new dataset is worth adding.
``gc_census.py``
    What Python's garbage collector tracks for a loaded graph, how long a
    full collection takes, and the collections during ``canonical_labels``.
``graph_index.py``
    The ``Graph`` and ``Dataset`` index: load time, bytes per triple,
    collector-tracked objects, ``match`` time for each pattern, iteration
    speed, and adds interleaved with queries (for tuning the merge
    constants); ``--retained`` adds the memory of a parsed graph, terms
    included, and ``--dataset-per-file`` loads the FHIR examples as one named
    graph per file. Uses only the public API, so run it on two source trees to
    compare an index change.
``compare_implementations.py``
    The Measurements table of ``docs/graph-comparison.rst``: pymantic against
    pyld's URDNA2015, rdf-canonize and rdflib. Needs ``pip install pyld
    rdflib``, and for rdf-canonize, Node with ``npm ci`` run in
    ``benchmarks/rdf-canonize``.

``when_quiet.py``
    Waits until the load average is low and no other Python or Node process
    is busy, then runs a command; use it in front of any measurement that
    will be recorded::

        python benchmarks/when_quiet.py -- python benchmarks/compare_implementations.py

Every tool has ``--help``.

Measuring well
--------------

Runs of a few seconds vary by 10% or more from one to the next on a busy
machine, so compare best-of-N times, look at every run's time (the tools
print them), and treat differences under about 5% as noise. Python versions
differ: check 3.12, 3.13 and 3.14 before concluding a change helps.
