========
Pymantic
========
---------------------------------------
Semantic Web and RDF library for Python
---------------------------------------


Quick Start
===========
::

    >>> from __future__ import print_function
    >>> from pymantic.rdf import *
    >>> from pymantic.parsers import turtle_parser
    >>> import requests
    >>> Resource.prefixes['foaf'] = Prefix('http://xmlns.com/foaf/0.1/')
    >>> graph = turtle_parser.parse(requests.get('https://raw.github.com/norcalrdf/pymantic/master/examples/foaf-bond.ttl').text)
    >>> bond_james = Resource(graph, 'http://example.org/stuff/Bond')
    >>> print("%s knows:" % (bond_james.get_scalar('foaf:name'),))
    >>> for person in bond_james['foaf:knows']:
            print(person.get_scalar('foaf:name'))



Requirements
============

``pymantic`` requires Python 2.7 or higher.
``lark`` is used for the Turtle and NTriples parser.
The ``requests`` library is used for HTTP requests and the SPARQL client.
``lxml`` and ``rdflib`` are required by the SPARQL client as well.


Install
=======

::

    $ pip install pymantic

This will install ``pymantic`` and all its dependencies.


Documentation
=============

Generating a local copy of the documentation requires Sphinx:

::

    $ pip install Sphinx


