__all__ = [
    "Triple",
    "Quad",
    "q_as_t",
    "t_as_q",
    "Literal",
    "XSD_STRING",
    "RDF_LANGSTRING",
    "NamedNode",
    "Prefix",
    "BlankNode",
    "Graph",
    "Dataset",
    "PrefixMap",
    "TermMap",
    "parse_curie",
    "is_language",
    "lang_match",
    "to_curie",
    "Profile",
]

import collections
import datetime
import itertools
from operator import itemgetter
import threading

from pymantic.serializers import iri_escape, nt_escape, validate_language
from pymantic.term_dictionary import TermDictionary
from pymantic.triple_index import TripleIndex
import pymantic.uri_schemes as uri_schemes

# Builds a Triple without the Python-level __new__, for the hot read paths.
_new_triple = tuple.__new__

_DATASET_CHANGED = "Dataset changed during iteration"

# Raised by whatever refuses to put a quad in a Graph.
GRAPH_HOLDS_TRIPLES = "a Graph holds triples; use a Dataset for quads"

# addAll adds this many triples or quads per hold of the lock, so a long
# stream neither takes the lock per triple nor holds it while the stream
# produces the next ones.
_ADD_BATCH = 1024


def _add_in_batches(source, lock, add_batch):
    """Read `source` in batches of _ADD_BATCH, calling `add_batch(batch)`
    with `lock` held for each. If reading the source raises, what it
    produced before is added first, so a parser that fails part way keeps
    the statements before the error, as adding them one by one would."""
    items = iter(source)
    while True:
        batch = []
        try:
            for item in items:
                batch.append(item)
                if len(batch) == _ADD_BATCH:
                    break
        except BaseException:
            if batch:
                with lock:
                    add_batch(batch)
            raise
        if batch:
            with lock:
                add_batch(batch)
        if len(batch) < _ADD_BATCH:
            return


def is_language(lang):
    """Is something a valid XML language?"""
    if isinstance(lang, NamedNode):
        return False
    return True


def lang_match(lang1, lang2):
    """Determines if two languages are, in fact, the same language.

    Eg: en is the same as en-us and en-uk."""
    if lang1 is None and lang2 is None:
        return True
    elif lang1 is None or lang2 is None:
        return False
    lang1 = lang1.partition("-")
    lang2 = lang2.partition("-")
    return lang1[0] == lang2[0] and (
        lang1[2] == "" or lang2[2] == "" or lang1[2] == lang2[2]
    )


def parse_curie(curie, prefixes):
    """
    Parses a CURIE within the context of the given namespaces. Will also accept
    explicit URIs and wrap them in an rdflib URIRef.

    Specifically:

    1) If the CURIE is not of the form [stuff] and the prefix is in the list of
       standard URIs, it is wrapped in a URIRef and returned unchanged.
    2) Otherwise, the CURIE is parsed by the rules of CURIE Syntax 1.0:
       http://www.w3.org/TR/2007/WD-curie-20070307/ The default namespace is
       the namespace keyed by the empty string in the namespaces dictionary.
    3) If the CURIE's namespace cannot be resolved, a ValueError is raised.
    """
    definitely_curie = False
    if curie[0] == "[" and curie[-1] == "]":
        curie = curie[1:-1]
        definitely_curie = True
    prefix, sep, reference = curie.partition(":")
    if not definitely_curie:
        if prefix in uri_schemes.schemes:
            return NamedNode(curie)
    if not reference and "" in prefixes:
        reference = prefix
        return Prefix(prefixes[""])(reference)
    if prefix in prefixes:
        return Prefix(prefixes[prefix])(reference)
    else:
        raise ValueError(
            f"Could not parse CURIE prefix {prefix} from prefixes {prefixes}"
        )


def parse_curies(curies, namespaces):
    """Parse multiple CURIEs at once."""
    for curie in curies:
        yield parse_curie(curie, namespaces)


def to_curie(uri, namespaces, seperator=":", explicit=False):
    """Converts a URI to a CURIE using the prefixes defined in namespaces. If
    there is no matching prefix, return the URI unchanged.

    namespaces - a dictionary of prefix -> namespace mappings.

    separator - the character to use as the separator between the prefix and
                the local name.

    explicit - if True and the URI can be abbreviated, wrap the abbreviated
               form in []s to indicate that it is definitely a CURIE."""
    matches = []
    for prefix, namespace in namespaces.items():
        if uri.startswith(namespace):
            matches.append((prefix, namespace))
    if len(matches) > 0:
        prefix, namespace = sorted(matches, key=lambda pair: -len(pair[1]))[0]
        curie = prefix + seperator + uri[len(namespace) :]
        if explicit:
            return f"[{curie}]"
        else:
            return curie
    return uri


class Triple(tuple):
    """Triple(subject, predicate, object)

    The Triple interface represents an RDF Triple. The stringification of a
    Triple results in an N-Triples.
    """

    __slots__ = ()

    _fields = ("subject", "predicate", "object")

    def __new__(_cls, subject, predicate, object):
        return tuple.__new__(_cls, (subject, predicate, object))

    @classmethod
    def _make(cls, iterable, new=tuple.__new__, len=len):
        "Make a new Triple object from a sequence or iterable"
        result = new(cls, iterable)
        if len(result) != 3:
            raise TypeError("Expected 3 arguments, got %d" % len(result))
        return result

    def __repr__(self):
        return "Triple(subject=%r, predicate=%r, object=%r)" % self

    def _asdict(t):
        "Return a new dict which maps field names to their values"
        return {"subject": t[0], "predicate": t[1], "object": t[2]}

    def _replace(_self, **kwds):
        "Return a new Triple object replacing specified fields with new values"
        result = _self._make(map(kwds.pop, ("subject", "predicate", "object"), _self))
        if kwds:
            raise ValueError("Got unexpected field names: %r" % kwds.keys())
        return result

    def __getnewargs__(self):
        return tuple(self)

    subject = property(itemgetter(0))
    predicate = property(itemgetter(1))
    object = property(itemgetter(2))

    def __str__(self):
        return f"{self.subject.toNT()} {self.predicate.toNT()} {self.object.toNT()} .\n"

    def toString(self):
        return str(self)


class Quad(tuple):
    "Quad(subject, predicate, object, graph)"

    __slots__ = ()

    _fields = ("subject", "predicate", "object", "graph")

    def __new__(_cls, subject, predicate, object, graph):
        return tuple.__new__(_cls, (subject, predicate, object, graph))

    @classmethod
    def _make(cls, iterable, new=tuple.__new__, len=len):
        "Make a new Quad object from a sequence or iterable"
        result = new(cls, iterable)
        if len(result) != 4:
            raise TypeError("Expected 4 arguments, got %d" % len(result))
        return result

    def __repr__(self):
        return "Quad(subject=%r, predicate=%r, object=%r, graph=%r)" % self

    def _asdict(t):
        "Return a new dict which maps field names to their values"
        return {
            "subject": t[0],
            "predicate": t[1],
            "object": t[2],
            "graph": t[3],
        }

    def _replace(_self, **kwds):
        "Return a new Quad object replacing specified fields with new values"
        result = _self._make(
            map(kwds.pop, ("subject", "predicate", "object", "graph"), _self)
        )
        if kwds:
            raise ValueError("Got unexpected field names: %r" % kwds.keys())
        return result

    def __getnewargs__(self):
        return tuple(self)

    subject = property(itemgetter(0))
    predicate = property(itemgetter(1))
    object = property(itemgetter(2))
    graph = property(itemgetter(3))

    def __str__(self):
        # A quad in the default graph (graph=None) is written as a triple.
        graph = "" if self.graph is None else f" {self.graph.toNT()}"
        return (
            f"{self.subject.toNT()} {self.predicate.toNT()} "
            f"{self.object.toNT()}{graph} .\n"
        )


def q_as_t(quad):
    return Triple(quad.subject, quad.predicate, quad.object)


def t_as_q(graph_name, triple):
    return Quad(triple.subject, triple.predicate, triple.object, graph_name)


class Literal(tuple):
    """Literal(`value`, `language`, `datatype`)

    Literals represent values such as numbers, dates and strings in RDF data. A
    Literal is comprised of three attributes:

    * a lexical representation of the nominalValue
    * an optional language represented by a string token
    * a datatype specified by a NamedNode

    Literals representing plain text in a natural language may have a language
    attribute specified by a text string token, as specified in [BCP47],
    normalized to lowercase (e.g., 'en', 'fr', 'en-gb').

    Every literal has a datatype (RDF 1.1 Concepts 3.3), which is filled in on
    construction when the caller leaves it out: ``xsd:string`` for a simple
    literal and ``rdf:langString`` for a language-tagged string. Two literals
    are the same term exactly when their lexical form, datatype and language
    all compare equal, so ``Literal("v")`` and
    ``Literal("v", datatype=XSD_STRING)`` are one term.

    Literals may not have both a datatype and a language."""

    __slots__ = ()

    _fields = ("value", "language", "datatype")

    types = {
        int: lambda v: (str(v), XSD("integer")),
        datetime.datetime: lambda v: (v.isoformat(), XSD("dateTime")),
    }

    def __new__(_cls, value, language=None, datatype=None):
        if not isinstance(value, str):
            value, auto_datatype = _cls.types[type(value)](value)
            if not datatype:
                datatype = auto_datatype
        if not language:
            # An empty tag is no tag: rdf:langString needs a non-empty one.
            language = None
        if language is not None:
            # RDF Concepts: language tags compare case-insensitively and
            # their value space is lowercase, so "EN" and "en" must be the
            # same term.
            language = language.lower()
            # RDF 1.1 Concepts 3.3: a language-tagged string always has the
            # datatype rdf:langString, and no other datatype may join a
            # language.
            if datatype and datatype != RDF_LANGSTRING:
                raise ValueError("Literals may not have both a datatype and a language")
            datatype = RDF_LANGSTRING
        elif not datatype:
            # A simple literal is syntactic sugar for one typed xsd:string.
            datatype = XSD_STRING
        elif datatype == RDF_LANGSTRING:
            raise ValueError("rdf:langString literals must have a language")
        return tuple.__new__(_cls, (value, language, datatype))

    @classmethod
    def _make(cls, iterable, new=None, len=len):
        "Make a new Literal object from a sequence or iterable"
        fields = tuple(iterable)
        if len(fields) != 3:
            raise TypeError("Expected 3 arguments, got %d" % len(fields))
        return cls(*fields)

    def __repr__(self):
        return "Literal(value=%r, language=%r, datatype=%r)" % self

    def _asdict(t):
        "Return a new dict which maps field names to their values"
        return {"value": t[0], "language": t[1], "datatype": t[2]}

    def _replace(_self, **kwds):
        "Return a new Literal object replacing specified fields with new value"
        if "language" in kwds and "datatype" not in kwds:
            # The datatypes of a simple literal and of a language-tagged
            # string are implied by the language, so changing the language
            # re-derives the datatype instead of carrying the old implicit
            # one forward into a literal that could not hold it.
            if _self.datatype in (XSD_STRING, RDF_LANGSTRING):
                kwds["datatype"] = None
        result = _self._make(map(kwds.pop, ("value", "language", "datatype"), _self))
        if kwds:
            raise ValueError("Got unexpected field names: %r" % kwds.keys())
        return result

    def __getnewargs__(self):
        return tuple(self)

    value = property(itemgetter(0))
    language = property(itemgetter(1))
    datatype = property(itemgetter(2))

    interfaceName = "Literal"

    def __str__(self):
        return str(self.value)

    def toNT(self):
        quoted = '"' + nt_escape(self.value) + '"'
        if self.language:
            # A language-tagged string is written with its tag alone; its
            # rdf:langString datatype is implicit.
            validate_language(self.language)
            return f"{quoted}@{self.language}"
        elif self.datatype != XSD_STRING:
            return f"{quoted}^^{self.datatype.toNT()}"
        else:
            # Canonical N-Triples writes a simple literal without its
            # implicit xsd:string datatype.
            return quoted


class NamedNode(str):
    """A node identified by an IRI."""

    interfaceName = "NamedNode"

    @property
    def value(self):
        return self

    def __repr__(self):
        return f"NamedNode({self.toNT()})"

    def __str__(self):
        return self.value

    def toNT(self):
        return f"<{iri_escape(self.value)}>"


class Prefix(NamedNode):
    """Node that when called returns the the argument conctantated with
    self."""

    def __call__(self, name):
        return NamedNode(self + name)


XSD = Prefix("http://www.w3.org/2001/XMLSchema#")
XSD_STRING = XSD("string")
RDF = Prefix("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
RDF_LANGSTRING = RDF("langString")


class BlankNode:
    """A BlankNode is a reference to an unnamed resource (one for which an IRI
    is not known), and may be used in a Triple as a unique reference to that
    unnamed resource.

    BlankNodes are stringified by prepending "_:" to a unique value, for
    instance _:b142 or _:me, this stringified form is referred to as a
    "blank node identifier"."""

    interfaceName = "BlankNode"

    _labels = itertools.count()

    def __init__(self):
        self._value = "b" + str(next(BlankNode._labels))

    @property
    def value(self):
        return self._value

    def __repr__(self):
        return "BlankNode()"

    def __str__(self):
        return "_:" + self.value

    def toNT(self):
        return str(self)


class _MappedTerms(dict):
    """A cache from term id to `fn` of that id's term, filled on first use,
    so a whole-graph read calls `fn` once per distinct term."""

    __slots__ = ("fn", "terms")

    def __init__(self, fn, terms):
        self.fn = fn
        self.terms = terms

    def __missing__(self, term_id):
        mapped = self[term_id] = self.fn(self.terms[term_id])
        return mapped


def _pattern_ids(dictionary, subject, predicate, object):
    """The ids of a match pattern, keeping None as the wildcard, or None if a
    bound term is unknown and so nothing can match."""
    lookup = dictionary.lookup
    pattern = []
    for term in (subject, predicate, object):
        if term is None:
            pattern.append(None)
        else:
            term_id = lookup(term)
            if term_id is None:
                return None
            pattern.append(term_id)
    return pattern


class Graph:
    """A `Graph` holds a set of one or more `Triple`. Implements the Python
    set/sequence API for `in`, `for`, and `len`

    Terms are stored once in a `TermDictionary` and triples as id triples in
    a `TripleIndex`, so the graph keeps no `Triple` objects: reads build
    fresh ones from the graph's own term instances.

    Each call is atomic with respect to other threads: a lock is held while
    a change is made and while a read starts, never while a read yields."""

    # A read turns ids into terms without the lock, through the
    # dictionary's `terms` list as it was when the read started. The index
    # yields only ids it has checked against its version, so they belong to
    # a triple present when the read started, and were live then. Such an id
    # is never cleared or reused in that list: compaction gives the
    # dictionary a new list, and only ids free before the read started are
    # reused in place. So the read names its triple correctly even when
    # another thread removes it, compacts and reuses its ids between the
    # index's check and the lookup.

    def __init__(self, graph_uri=None):
        if graph_uri is not None and not isinstance(graph_uri, NamedNode):
            graph_uri = NamedNode(graph_uri)
        self._uri = graph_uri
        self._dictionary = TermDictionary()
        self._index = TripleIndex()
        # Whoever owns the dictionary decides when to compact it. A
        # standalone graph is its own owner, held as None rather than a
        # reference to itself so the graph is freed without the cycle
        # collector.
        self._owner = None
        # Guards the dictionary and the index. Whoever owns the dictionary
        # owns the lock: a dataset's views share the dataset's. No method
        # takes it while holding it, so it need not be reentrant.
        self._lock = threading.Lock()
        self._actions = set()

    @classmethod
    def _view(cls, uri, dictionary, index, owner):
        """A graph over a dictionary and index that `owner` holds and
        compacts, such as one graph of a dataset."""
        graph = cls.__new__(cls)
        graph._uri = uri
        graph._dictionary = dictionary
        graph._index = index
        graph._owner = owner
        graph._lock = owner._lock
        graph._actions = set()
        return graph

    @property
    def uri(self):
        """URI name of the graph, if it has been given a name"""
        return self._uri

    def addAction(self, action):
        self._actions.add(action)
        return self

    def add(self, triple):
        """Adds the specified Triple to the graph. This method returns the
        graph instance it was called on."""
        if len(triple) != 3:
            raise TypeError(GRAPH_HOLDS_TRIPLES)
        s, p, o = triple
        with self._lock:
            if self._owner is not None:
                # A view of a removed graph must not intern into its
                # dataset's dictionary before the index refuses the add.
                self._check_index()
            intern = self._dictionary.intern
            if self._index.add(intern(s), intern(p), intern(o)):
                self._changed(1)
        return self

    def remove(self, triple):
        """Removes the specified Triple from the graph. This method returns the
        graph instance it was called on."""
        if len(triple) != 3:
            raise TypeError(GRAPH_HOLDS_TRIPLES)
        with self._lock:
            ids = self._ids(triple)
            if ids is None:
                self._check_index()
                raise KeyError(triple)
            if ids not in self._index:
                raise KeyError(triple)
            self._index.remove(*ids)
            self._changed(-1)
            self._compact()
        return self

    def match(self, subject=None, predicate=None, object=None):
        """This method returns a new sequence of triples which is comprised of
        all those triples in the current instance which match the given
        arguments, that is, for each triple in this graph, it is included in
        the output graph, if:

        * calling triple.subject.equals with the specified subject as an
          argument returns true, or the subject argument is null, AND

        * calling triple.property.equals with the specified property as an
          argument returns true, or the property argument is null, AND

        * calling triple.object.equals with the specified object as an argument
          returns true, or the object argument is null

        This method implements AND functionality, so only triples matching all
        of the given non-null arguments will be included in the result.

        A pattern with a bound term yields in term-id order, the order the
        graph first saw its terms; an unbound pattern yields in insertion
        order.
        """
        with self._lock:
            pattern = _pattern_ids(self._dictionary, subject, predicate, object)
            if pattern is None:
                self._check_index()
                return
            terms = self._dictionary.terms
            if None not in pattern:
                # A membership test rather than the index's version-checked
                # generator, so the caller may remove the one match while
                # this generator is still open.
                if pattern not in self._index:
                    return
                s, p, o = pattern
                found = _new_triple(Triple, (terms[s], terms[p], terms[o]))
            else:
                found = None
                ids = self._index.match(*pattern)
        if found is not None:
            yield found
            return
        for s, p, o in ids:
            yield _new_triple(Triple, (terms[s], terms[p], terms[o]))

    def removeMatches(self, subject=None, predicate=None, object=None):
        """This method removes those triples in the current graph which match
        the given arguments. An argument of None matches any term, as in
        match(), so calling with no arguments removes every triple."""
        with self._lock:
            pattern = _pattern_ids(self._dictionary, subject, predicate, object)
            if pattern is None:
                self._check_index()
                return self
            # Collected first: removing ends any generator over the index.
            doomed = list(self._index.match(*pattern))
            if doomed:
                self._index.remove_many(doomed)
                self._changed(-len(doomed))
                self._compact()
        return self

    def addAll(self, graph_or_triples):
        """Imports the graph or set of triples in to this graph. This method
        returns the graph instance it was called on.

        The triples are added in batches, each in one hold of the lock, so
        another thread may see some batches before the rest. The source is
        read between batches, never under the lock. It must not be a read
        of this graph, or of its dataset, that the added triples change: a
        read ends with RuntimeError when its graph changes, and addAll
        raises that after adding what it had read. Re-adding a graph's own
        triples changes nothing, so ``graph.addAll(graph)`` works."""
        _add_in_batches(graph_or_triples, self._lock, self._add_batch)
        return self

    def _add_batch(self, triples):
        """Add `triples`; the caller holds the lock."""
        if self._owner is not None:
            self._check_index()
        intern = self._dictionary.intern
        add = self._index.add
        added = 0
        try:
            for triple in triples:
                if len(triple) != 3:
                    raise TypeError(GRAPH_HOLDS_TRIPLES)
                s, p, o = triple
                if add(intern(s), intern(p), intern(o)):
                    added += 1
        finally:
            if added:
                self._changed(added)

    def merge(self, graph):
        """Returns a new Graph which is a concatenation of this graph and the
        graph given as an argument."""
        new_graph = Graph()
        for triple in graph:
            new_graph.add(triple)
        for triple in self:
            new_graph.add(triple)
        return new_graph

    def __contains__(self, item):
        if not isinstance(item, tuple) or len(item) != 3:
            return False
        with self._lock:
            ids = self._ids(item)
            if ids is None:
                self._check_index()
                return False
            return ids in self._index

    def __len__(self):
        with self._lock:
            return len(self._index)

    def __iter__(self):
        with self._lock:
            terms = self._dictionary.terms
            ids = iter(self._index)
        for s, p, o in ids:
            yield _new_triple(Triple, (terms[s], terms[p], terms[o]))

    def toArray(self):
        """Return the set of :py:class:`Triple` within the :py:class:`Graph`"""
        return frozenset(self)

    def mapped_triples(self, fn):
        """Yields ``(fn(subject), fn(predicate), fn(object))`` for each
        triple, in the order iterating the graph yields the triples, and
        raises RuntimeError as that does if the graph changes meanwhile.

        This builds no `Triple`, and calls `fn` once per distinct term
        rather than once per position, so it is the fast path for reading a
        whole graph through a function of its terms."""
        with self._lock:
            mapped = _MappedTerms(fn, self._dictionary.terms)
            ids = iter(self._index)
        for s, p, o in ids:
            yield mapped[s], mapped[p], mapped[o]

    def object_counts(self):
        """Returns a `collections.Counter` from each object to the number of
        triples it is the object of, equal to counting the objects while
        iterating the graph. The index already holds each object's triples
        together, so this reads their number without visiting them."""
        with self._lock:
            terms = self._dictionary.terms
            return collections.Counter(
                {terms[o]: n for o, n in self._index.object_counts().items()}
            )

    def subjects(self, predicate=None, object=None):
        """With no arguments, returns a list of the distinct subjects in the
        graph, in term-id order.

        Otherwise yields the subject of each triple matching the predicate
        and object given, in the order :meth:`match` yields the triples.
        This builds no `Triple`, so it is cheaper than reading the subjects
        out of :meth:`match`."""
        if predicate is None and object is None:
            with self._lock:
                terms = self._dictionary.terms
                return [terms[i] for i in self._index.subjects()]
        return self._matching_terms(0, None, predicate, object)

    def predicates(self, subject=None, object=None):
        """With no arguments, returns a list of the distinct predicates in
        the graph, in term-id order.

        Otherwise yields the predicate of each triple matching the subject
        and object given, in the order :meth:`match` yields the triples.
        This builds no `Triple`, so it is cheaper than reading the
        predicates out of :meth:`match`."""
        if subject is None and object is None:
            with self._lock:
                terms = self._dictionary.terms
                return [terms[i] for i in self._index.predicates()]
        return self._matching_terms(1, subject, None, object)

    def objects(self, subject=None, predicate=None):
        """With no arguments, returns a list of the distinct objects in the
        graph, in term-id order.

        Otherwise yields the object of each triple matching the subject and
        predicate given, in the order :meth:`match` yields the triples.
        This builds no `Triple`, so it is the fast path for reading the
        values of one subject's property."""
        if subject is None and predicate is None:
            with self._lock:
                terms = self._dictionary.terms
                return [terms[i] for i in self._index.objects()]
        return self._matching_terms(2, subject, predicate, None)

    def predicate_objects(self, subject):
        """Yields (predicate, object) for each triple of `subject`, in the
        order ``match(subject)`` yields the triples. This builds no
        `Triple`, so it is the fast path for reading all of one subject's
        properties."""
        # Checked here rather than in the generator so the mistake surfaces
        # at the call instead of as a scan of the whole graph.
        if subject is None:
            raise TypeError("predicate_objects needs a subject")
        return self._predicate_objects(subject)

    def _predicate_objects(self, subject):
        with self._lock:
            pattern = _pattern_ids(self._dictionary, subject, None, None)
            if pattern is None:
                self._check_index()
                return
            terms = self._dictionary.terms
            ids = self._index.match(*pattern)
        for _, p, o in ids:
            yield terms[p], terms[o]

    def _matching_terms(self, column, subject, predicate, object):
        """Yields the term in position `column` of each triple matching the
        pattern, which leaves at least one position unbound, so the index's
        version-checked generator serves every pattern here."""
        with self._lock:
            pattern = _pattern_ids(self._dictionary, subject, predicate, object)
            if pattern is None:
                self._check_index()
                return
            terms = self._dictionary.terms
            found = self._index.match(*pattern)
        for ids in found:
            yield terms[ids[column]]

    def _ids(self, triple):
        """The id triple of `triple`, or None if a term is unknown."""
        lookup = self._dictionary.lookup
        s, p, o = triple
        ids = (lookup(s), lookup(p), lookup(o))
        return None if None in ids else ids

    # The methods below expect the caller to hold the lock.

    def _check_index(self):
        """Raise RuntimeError if this is a view of a graph its dataset has
        removed. A read that finds an unknown term answers without touching
        the index, so it calls this to fail as every other read does."""
        len(self._index)

    def _changed(self, added):
        """Tell the owning dataset, if any, that this graph changed by
        `added` triples (negative for removes), so its dataset-wide
        generators stop and its count of quads stays right."""
        owner = self._owner
        if owner is not None:
            owner._version += 1
            owner._quad_count += added

    def _compact(self):
        """Let the dictionary's owner compact it after a remove."""
        owner = self._owner
        if owner is None:
            self._maybe_compact()
        else:
            owner._maybe_compact()

    def _maybe_compact(self):
        # A triple refers to at most 3 terms, so past 6 terms per triple at
        # least half the dictionary is dead.
        dictionary = self._dictionary
        index = self._index
        if len(dictionary) > 6 * len(index):
            dictionary.compact(index.ids())


class Dataset:
    """A default graph plus named graphs, which may share blank nodes.

    Every graph's terms, and the graph names, are interned in one
    `TermDictionary`, so a term is one id across the whole dataset. Each
    graph is its own `TripleIndex`, keyed by the id of its name; the default
    graph is keyed by None and always exists. A named graph exists from when
    it is first added until `remove_graph`, holding triples or not.

    Each call is atomic with respect to other threads, as for `Graph`; the
    dataset and its views share one lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self._dictionary = TermDictionary()
        self._graphs = {None: TripleIndex()}
        # Bumped on every change to any graph, through the dataset or a
        # view. An index only notices changes to itself, so a generator
        # walking every graph checks this too: a change to another graph
        # can compact the dictionary and hand a freed id to a new term.
        self._version = 0
        # The quads in every graph, kept as they are added and removed so
        # that the compaction check after each remove costs no sum over
        # what may be thousands of graphs.
        self._quad_count = 0

    def add(self, quad):
        s, p, o, graph = quad
        with self._lock:
            intern = self._dictionary.intern
            index = self._index_for_add(graph)
            if index.add(intern(s), intern(p), intern(o)):
                self._version += 1
                self._quad_count += 1

    def remove(self, quad):
        with self._lock:
            found = self._quad_ids(quad)
            if found is None:
                raise KeyError(quad)
            index, ids = found
            index.remove(*ids)
            self._version += 1
            self._quad_count -= 1
            self._maybe_compact()

    def add_graph(self, graph, named=None):
        """Copy the triples of `graph` into the graph called `named`, or
        `graph.uri` if `named` is None, creating it if it is new. The
        dataset keeps its own copy: later edits to `graph` do not reach it."""
        name = named if named is not None else graph.uri
        if name is None:
            raise ValueError("Graph must be named")
        # Read before taking the lock: `graph` may be a view of this
        # dataset, whose reads take the same lock.
        triples = list(graph)
        with self._lock:
            intern = self._dictionary.intern
            index = self._index_for_add(name)
            for s, p, o in triples:
                if index.add(intern(s), intern(p), intern(o)):
                    self._version += 1
                    self._quad_count += 1

    def remove_graph(self, graph_or_uri):
        """Remove a named graph, given it or its name. Views of it from
        `graphs` raise RuntimeError from then on."""
        name = graph_or_uri.uri if isinstance(graph_or_uri, Graph) else graph_or_uri
        if name is None:
            raise ValueError("the default graph cannot be removed")
        with self._lock:
            name_id = self._dictionary.lookup(name)
            if name_id is None or name_id not in self._graphs:
                raise KeyError(name)
            index = self._graphs.pop(name_id)
            self._quad_count -= len(index)
            index.detach()
            self._version += 1
            self._maybe_compact()

    @property
    def graphs(self):
        """A list of `Graph` views of the dataset's graphs, default graph
        first. Editing a view edits the dataset."""
        with self._lock:
            terms = self._dictionary.terms
            return [
                Graph._view(
                    None if name_id is None else terms[name_id],
                    self._dictionary,
                    index,
                    self,
                )
                for name_id, index in self._graphs.items()
            ]

    def match(self, subject=None, predicate=None, object=None, graph=None):
        """Yield the quads matching a pattern, None being a wildcard. A
        `graph` of None matches every graph, the default graph first; the
        default graph's quads have `graph` None. Matching every graph with
        a term unbound raises RuntimeError, as iterating the dataset does,
        if any graph changes while the generator is open."""
        with self._lock:
            pattern = _pattern_ids(self._dictionary, subject, predicate, object)
            if pattern is None:
                return
            terms = self._dictionary.terms
            if None not in pattern:
                # Membership tests, as in Graph.match, so the caller may
                # remove a match while this generator is open. All done
                # before the first yield: a remove can compact the
                # dictionary and later adds reuse the freed ids, so the
                # pattern's ids are only good until then.
                triple = tuple(terms[i] for i in pattern)
                names = [
                    name for name, index in self._indexes(graph) if pattern in index
                ]
            else:
                names = None
                # Each graph's read starts here, under the lock; the
                # dataset's version stops the walk if any graph changes.
                parts = [
                    (name, index.match(*pattern))
                    for name, index in self._indexes(graph)
                ]
                version = self._version
        if names is not None:
            for name in names:
                yield _new_triple(Quad, (*triple, name))
            return
        for name, ids in parts:
            for s, p, o in ids:
                yield _new_triple(Quad, (terms[s], terms[p], terms[o], name))
                if graph is None and self._version != version:
                    raise RuntimeError(_DATASET_CHANGED)

    def removeMatches(self, subject=None, predicate=None, object=None, graph=None):
        """This method removes those triples in the current graph which match
        the given arguments."""
        with self._lock:
            pattern = _pattern_ids(self._dictionary, subject, predicate, object)
            if pattern is not None:
                removed = False
                for _, index in self._indexes(graph):
                    # Collected first: removing ends any generator over the
                    # index.
                    doomed = list(index.match(*pattern))
                    if doomed:
                        index.remove_many(doomed)
                        self._quad_count -= len(doomed)
                        removed = True
                if removed:
                    self._version += 1
                    self._maybe_compact()
        return self

    def addAll(self, dataset_or_quads):
        """Imports the graph or set of triples in to this graph. This method
        returns the graph instance it was called on.

        As with `Graph.addAll`, the quads are added in batches, each in one
        hold of the lock, and the source is read between batches; it must
        not be a read of this dataset that the added quads change."""
        _add_in_batches(dataset_or_quads, self._lock, self._add_batch)
        return self

    def _add_batch(self, quads):
        """Add `quads`; the caller holds the lock."""
        intern = self._dictionary.intern
        for quad in quads:
            if len(quad) != 4:
                raise TypeError(
                    "a Dataset holds quads; add triples to one of its graphs"
                )
            s, p, o, graph = quad
            if self._index_for_add(graph).add(intern(s), intern(p), intern(o)):
                self._version += 1
                self._quad_count += 1

    def __len__(self):
        with self._lock:
            return self._quad_count

    def __contains__(self, item):
        """A `Quad` is looked up in its graph, a `Triple` in the default
        graph."""
        if not isinstance(item, tuple):
            return False
        if len(item) == 3:
            item = (*item, None)
        elif len(item) != 4:
            return False
        with self._lock:
            found = self._quad_ids(item)
            return found is not None and found[1] in found[0]

    def __iter__(self):
        with self._lock:
            terms = self._dictionary.terms
            parts = [(name, iter(index)) for name, index in self._indexes(None)]
            version = self._version
        for name, ids in parts:
            for s, p, o in ids:
                yield _new_triple(Quad, (terms[s], terms[p], terms[o], name))
                if self._version != version:
                    raise RuntimeError(_DATASET_CHANGED)

    def toArray(self):
        return frozenset(self)

    def mapped_quads(self, fn):
        """Yields ``(fn(subject), fn(predicate), fn(object), fn(graph))``
        for each quad, in the order iterating the dataset yields the quads,
        and raises RuntimeError as that does if the dataset changes
        meanwhile. The graph position is None for the default graph, for
        which `fn` is not called.

        This builds no `Quad`, and calls `fn` once per distinct term across
        the whole dataset, graph names included, so it is the fast path for
        reading a whole dataset through a function of its terms."""
        with self._lock:
            mapped = _MappedTerms(fn, self._dictionary.terms)
            # An empty graph yields nothing, so its name is not mapped.
            parts = [
                (name_id, iter(index))
                for name_id, index in self._graphs.items()
                if len(index)
            ]
            version = self._version
        for name_id, ids in parts:
            name = None if name_id is None else mapped[name_id]
            for s, p, o in ids:
                yield mapped[s], mapped[p], mapped[o], name
                if self._version != version:
                    raise RuntimeError(_DATASET_CHANGED)

    # The methods below expect the caller to hold the lock.

    def _index_for_add(self, name):
        """The index of the graph called `name`, created if it is new."""
        if name is None:
            return self._graphs[None]
        name_id = self._dictionary.intern(name)
        index = self._graphs.get(name_id)
        if index is None:
            index = self._graphs[name_id] = TripleIndex()
            self._version += 1
        return index

    def _indexes(self, graph):
        """(name, index) for the graph called `graph`, or for every graph if
        `graph` is None. Never creates a graph."""
        if graph is None:
            terms = self._dictionary.terms
            for name_id, index in self._graphs.items():
                yield (None if name_id is None else terms[name_id]), index
            return
        name_id = self._dictionary.lookup(graph)
        index = self._graphs.get(name_id) if name_id is not None else None
        if index is not None:
            yield self._dictionary.terms[name_id], index

    def _quad_ids(self, quad):
        """(index, id triple) of `quad`, or None if its graph does not exist
        or one of its terms is unknown."""
        s, p, o, graph = quad
        lookup = self._dictionary.lookup
        if graph is None:
            index = self._graphs[None]
        else:
            name_id = lookup(graph)
            if name_id is None:
                return None
            index = self._graphs.get(name_id)
            if index is None:
                return None
        ids = (lookup(s), lookup(p), lookup(o))
        return None if None in ids else (index, ids)

    def _maybe_compact(self):
        # As Graph._maybe_compact, counting quads across every graph, plus
        # one live term per graph name.
        dictionary = self._dictionary
        names = len(self._graphs) - 1
        if len(dictionary) > 6 * self._quad_count + names:
            live = {name_id for name_id in self._graphs if name_id is not None}
            for index in self._graphs.values():
                live.update(index.ids())
            dictionary.compact(live)
            self._version += 1


# RDF Enviroment Interfaces


class PrefixMap(collections.OrderedDict):
    """A map of prefixes to IRIs, and provides methods to
    turn one in to the other.

    Example Usage:

    >>> prefixes = PrefixMap()

    Create a new prefix mapping for the prefix "rdfs"

    >>> prefixes['rdfs'] = "http://www.w3.org/2000/01/rdf-schema#"

    Resolve a known CURIE

    >>> prefixes.resolve("rdfs:label")
    u"http://www.w3.org/2000/01/rdf-schema#label"

    Shrink an IRI for a known CURIE in to a CURIE

    >>> prefixes.shrink("http://www.w3.org/2000/01/rdf-schema#label")
    u"rdfs:label"

    Attempt to resolve a CURIE with an empty prefix

    >>> prefixes.resolve(":me")
    ":me"

    Set the default prefix and attempt to resolve a CURIE with an empty prefix

    >>> prefixes.setDefault("http://example.org/bob#")
    >>> prefixes.resolve(":me")
    u"http://example.org/bob#me"
    """

    def resolve(self, curie):
        """Given a valid CURIE for which a prefix is known (for example
        "rdfs:label"), this method will return the resulting IRI (for example
        "http://www.w3.org/2000/01/rdf-schema#label")"""
        return parse_curie(curie, self)

    def shrink(self, iri):
        """Given an IRI for which a prefix is known (for example
        "http://www.w3.org/2000/01/rdf-schema#label") this method returns a
        CURIE (for example "rdfs:label"), if no prefix is known the original
        IRI is returned."""
        return to_curie(iri, self)

    def addAll(self, other, override=False):
        if override:
            self.update(other)
        else:
            for key, value in other.items():
                if key not in self:
                    self[key] = value
        return self

    def setDefault(self, iri):
        """Set the iri to be used when resolving CURIEs without a prefix, for
        example ":this"."""
        self[""] = iri


class TermMap(dict):
    """A map of simple string terms to IRIs, and provides methods to turn one
        in to the other.

    Example usage:

    >>> terms = TermMap()

    Create a new term mapping for the term "member"

    >>> terms['member'] = "http://www.w3.org/ns/org#member"

    Resolve a known term to an IRI

    >>> terms.resolve("member")
    u"http://www.w3.org/ns/org#member"

    Shrink an IRI for a known term to a term

    >>> terms.shrink("http://www.w3.org/ns/org#member")
    u"member"

    Attempt to resolve an unknown term

    >>> terms.resolve("label")
    None

    Set the default term vocabulary and then attempt to resolve an unknown term

    >>> terms.setDefault("http://www.w3.org/2000/01/rdf-schema#")
    >>> terms.resolve("label")
    u"http://www.w3.org/2000/01/rdf-schema#label"
    """

    def addAll(self, other, override=False):
        if override:
            self.update(other)
        else:
            for key, value in other.items():
                if key not in self:
                    self[key] = value
        return self

    def resolve(self, term):
        """Given a valid term for which an IRI is known (for example "label"),
        this method will return the resulting IRI (for example
        "http://www.w3.org/2000/01/rdf-schema#label").

        If no term is known and a default has been set, the IRI is obtained by
        concatenating the term and the default iri.

        If no term is known and no default is set, then this method returns
        null."""
        if hasattr(self, "default"):
            return self.get(term, self.default + term)
        else:
            return self.get(term)

    def setDefault(self, iri):
        """The default iri to be used when an term cannot be resolved, the
        resulting IRI is obtained by concatenating this iri with the term being
        resolved."""
        self.default = iri

    def shrink(self, iri):
        """Given an IRI for which an term is known (for example
        "http://www.w3.org/2000/01/rdf-schema#label") this method returns a
        term (for example "label"), if no term is known the original IRI is
        returned."""
        for term, v in self.items():
            if v == iri:
                return term
        return iri


class Profile:
    """Profiles provide an easy to use context for negotiating between CURIEs,
    Terms and IRIs."""

    def __init__(self, prefixes=None, terms=None):
        self.prefixes = prefixes or PrefixMap()
        self.terms = terms or TermMap()
        if "rdf" not in self.prefixes:
            self.prefixes["rdf"] = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        if "xsd" not in self.prefixes:
            self.prefixes["xsd"] = "http://www.w3.org/2001/XMLSchema#"

    def resolve(self, toresolve):
        """Given an Term or CURIE this method will return an IRI, or null if it
        cannot be resolved.

        If toresolve contains a : (colon) then this method returns the result
        of calling prefixes.resolve(toresolve)

        otherwise this method returns the result of calling
        terms.resolve(toresolve)"""
        if ":" in toresolve:
            return self.prefixes.resolve(toresolve)
        else:
            return self.terms.resolve(toresolve)

    def setDefaultVocabulary(self, iri):
        """This method sets the default vocabulary for use when resolving
        unknown terms, it is identical to calling the setDefault method on
        terms."""
        self.terms.setDefault(iri)

    def setDefaultPrefix(self, iri):
        """This method sets the default prefix for use when resolving CURIEs
        without a prefix, for example ":me", it is identical to calling the
        setDefault method on prefixes."""
        self.prefixes.setDefault(iri)

    def setTerm(self, term, iri):
        """This method associates an IRI with a term, it is identical to
        calling the set method on term."""
        self.terms[term] = iri

    def setPrefix(self, prefix, iri):
        """This method associates an IRI with a prefix, it is identical to
        calling the set method on prefixes."""
        self.prefixes[prefix] = iri

    def importProfile(self, profile, override=False):
        """This method functions the same as calling
        prefixes.addAll(profile.prefixes, override) and
        terms.addAll(profile.terms, override), and allows easy updating and
        merging of different profiles.

        This method returns the instance on which it was called."""
        self.prefixes.addAll(profile.prefixes, override)
        self.terms.addAll(profile.terms, override)
        return self


class RDFEnvironment(Profile):
    """The RDF Environment is an interface which exposes a high level API for
    working with RDF in a programming environment."""

    def createBlankNode(self):
        """Creates a new :py:class:`BlankNode`."""
        return BlankNode()

    def createNamedNode(self, value):
        """Creates a new :py:class:`NamedNode`."""
        return NamedNode(value)

    def createLiteral(self, value, language=None, datatype=None):
        """Creates a :py:class:`Literal` given a value, an optional language
        and/or an
        optional datatype."""
        return Literal(value, language, datatype)

    def createTriple(self, subject, predicate, object):
        """Creates a :py:class:`Triple` given a subject, predicate and
        object."""
        return Triple(subject, predicate, object)

    def createGraph(self, triples=tuple()):
        """Creates a new :py:class:`Graph`, an optional sequence of
        :py:class:`Triple` to include within the graph may be specified, this
        allows easy transition between native sequences and Graphs and is the
        counterpart for :py:meth:`Graph.toArray`."""
        g = Graph()
        g.addAll(triples)
        return g

    def createAction(self, test, action):
        raise NotImplementedError()

    def createProfile(self, empty=False):
        if empty:
            return Profile()
        else:
            return Profile(self.prefixes, self.terms)

    def createTermMap(self, empty=False):
        if empty:
            return TermMap()
        else:
            return TermMap(self.terms)

    def createPrefixMap(self, empty=False):
        if empty:
            return PrefixMap()
        else:
            return PrefixMap(self.prefixes)

    # Pymantic DataSet Extensions

    def createQuad(self, subject, predicate, object, graph):
        return Quad(subject, predicate, object, graph)

    def createDataset(self, quads=tuple()):
        ds = Dataset()
        ds.addAll(quads)
        return ds
