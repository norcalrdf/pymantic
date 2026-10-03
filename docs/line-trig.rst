=========
Line-TriG
=========

Line-TriG is a line-oriented profile of `RDF 1.2 TriG`_ for writing RDF
datasets. Every Line-TriG document is a TriG document with the same meaning,
so any TriG parser reads it. Pymantic uses it for dataset test fixtures.

Why
===

`RDF 1.2 N-Quads`_ cannot write an empty named graph: there is no quad to
put on the line, as the spec notes. A dataset with ``<g>`` holding no
triples is not the same dataset as one without ``<g>``, so N-Quads loses
information. TriG can write an empty
graph, but full TriG is a large grammar. Line-TriG keeps what makes N-Quads
pleasant, one statement per line in N-Triples term syntax, and borrows TriG's
braces for named graphs.

Example
=======

::

    # The default graph.
    <http://example.org/alice> <http://xmlns.com/foaf/0.1/knows> _:b .
    # Two triples in a named graph, one shared blank node.
    <http://example.org/g1> { _:b <http://xmlns.com/foaf/0.1/name> "Bob" . }
    <http://example.org/g1> { _:b <http://xmlns.com/foaf/0.1/age> "42"^^<http://www.w3.org/2001/XMLSchema#integer> . }
    # A blank node naming a graph.
    _:g { <http://example.org/s> <http://example.org/p> <http://example.org/o> . }
    # An empty named graph.
    <http://example.org/empty> { }

Rules
=====

1. A document is a sequence of lines. Blank lines and comment lines (``#``
   to end of line) are allowed.
2. A line holds one statement:

   - a default-graph triple, written exactly as an N-Triples triple:
     ``S P O .``
   - a named-graph triple: ``G { S P O . }``, where the part inside the
     braces is exactly an N-Triples triple;
   - an empty named graph: ``G { }``.

3. ``G`` is an IRI or a blank node label. ``S``, ``P`` and ``O`` are
   N-Triples terms: IRIs in angle brackets (absolute, no prefixes, no
   relative IRIs), blank node labels, and literals in quoted form with an
   optional language tag or datatype IRI.
4. Blank node labels are scoped to the document. The same label in two
   graphs, or as a graph name and in a triple, is the same blank node.
5. A graph name may appear on any number of lines. The graph holds the union
   of their triples. A ``G { }`` line makes ``G`` a named graph of the
   dataset whether or not other lines give it triples.
6. Order of lines carries no meaning.

Grammar
=======

.. code-block:: ebnf

    document     ::= EOL* (statement EOL+)* statement?
    statement    ::= triple | graphTriple | emptyGraph
    triple       ::= subject predicate object '.'
    graphTriple  ::= graphName '{' triple '}'
    emptyGraph   ::= graphName '{' '}'
    graphName    ::= IRIREF | BLANK_NODE_LABEL

``subject``, ``predicate``, ``object``, ``IRIREF``, ``BLANK_NODE_LABEL``,
``EOL`` and comments are the `RDF 1.2 N-Triples`_ productions, with the
same whitespace and comment rules, so Line-TriG has every term N-Triples
has, including triple terms and directional language-tagged strings.

Line-TriG is the only format pymantic reads and writes that holds every
RDF 1.2 dataset. N-Quads cannot write an empty named graph, and N-Triples
and Turtle hold one graph. Turtle's missing reifiers and annotations are
shorthand for triples that Line-TriG writes out, so they cost no
expressiveness.

Why it is valid TriG
--------------------

Each kind of line maps to TriG productions:

- ``S P O .`` is ``triplesOrGraph`` with a ``predicateObjectList`` and
  ``'.'``: a triple in the default graph.
- ``G { S P O . }`` is ``triplesOrGraph`` with a ``wrappedGraph`` whose
  ``triplesBlock`` is ``triples '.'``.
- ``G { }`` is a ``wrappedGraph`` with no ``triplesBlock``, which TriG
  allows.

TriG takes the union of graph statements that share a name, and scopes blank
node labels to the document, which gives rules 4 and 5.

Writing
=======

A writer emits the default graph first, then each named graph's triples,
then a ``G { }`` line for each named graph with no triples. Terms are
written as in N-Triples, separated by single spaces, lines ending in LF. Use
the ``.trig`` extension: the file is TriG.

Reading
=======

A Line-TriG reader rejects any line outside the profile, with the line
number, even if the line is valid TriG. That keeps fixtures in the profile,
so they stay line-diffable and readable by both a Line-TriG reader and a
full TriG parser.

References
==========

All three are W3C Working Drafts as of October 2026.

.. _RDF 1.2 TriG: https://www.w3.org/TR/rdf12-trig/
.. _RDF 1.2 N-Triples: https://www.w3.org/TR/rdf12-n-triples/
.. _RDF 1.2 N-Quads: https://www.w3.org/TR/rdf12-n-quads/

- `RDF 1.2 TriG`_: the grammar productions cited above, the union of graph
  statements sharing a name, and document-scoped blank node labels.
- `RDF 1.2 N-Triples`_: the term syntax.
- `RDF 1.2 N-Quads`_: the note that N-Quads cannot serialize empty graphs.
