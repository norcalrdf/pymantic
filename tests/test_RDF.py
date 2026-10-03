import datetime
import pytest
import warnings

from pymantic.primitives import (
    Graph,
    Literal,
    NamedNode,
    Prefix,
    PrefixMap,
    Triple,
    UnknownSchemeWarning,
)
import pymantic.rdf
import pymantic.util

XSD = Prefix("http://www.w3.org/2001/XMLSchema#")

RDF = Prefix("http://www.w3.org/1999/02/22-rdf-syntax-ns#")


@pytest.fixture()
def reset_metaresource():
    yield
    pymantic.rdf.MetaResource._classes = {}


def testResolveAbsoluteIRIs(reset_metaresource):
    """A value whose suffix starts with // is always an absolute IRI, even
    when its scheme is also a declared prefix."""
    prefixes = PrefixMap({"http": "reallybadidea/"})
    assert prefixes.resolve("http://example.com") == NamedNode("http://example.com")


def testResolveUndeclaredPrefixAsIRI(reset_metaresource):
    """A value whose prefix isn't declared is taken as an absolute IRI, with
    no warning when its scheme is registered, in any case."""
    prefixes = PrefixMap({"foo": "WRONG!"})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert prefixes.resolve("urn:isbn:1234567890123") == NamedNode(
            "urn:isbn:1234567890123"
        )
        assert prefixes.resolve("MAILTO:a@example.com") == NamedNode(
            "MAILTO:a@example.com"
        )
        assert prefixes.resolve("http://example.com") == NamedNode("http://example.com")


def testResolveUnknownSchemeWarns(reset_metaresource):
    """An undeclared prefix that isn't a registered scheme either, which is
    probably a typo, still resolves as an absolute IRI but warns."""
    prefixes = PrefixMap({"rdfs": "http://www.w3.org/2000/01/rdf-schema#"})
    with pytest.warns(UnknownSchemeWarning, match="'rdsf'"):
        assert prefixes.resolve("rdsf:label") == NamedNode("rdsf:label")


def testUnknownSchemeWarningPointsAtCaller(reset_metaresource):
    """The warning names the user's line, not pymantic's internals, even when
    it comes through Resource lookups and scalar declarations."""

    class Thing(pymantic.rdf.Resource):
        prefixes = {"ex": "http://example.com/"}

    with pytest.warns(UnknownSchemeWarning) as record:
        Thing.resolve("rdsf:label")
    assert record[0].filename == __file__

    with pytest.warns(UnknownSchemeWarning) as record:

        class Other(pymantic.rdf.Resource):
            scalars = frozenset(("rdsf:label",))

    assert record[0].filename == __file__


def testResolveLeavesNamedNodesAlone(reset_metaresource):
    """An already-resolved NamedNode isn't expanded again, even when its
    scheme is a declared prefix."""
    prefixes = PrefixMap({"urn": "http://example.com/urn#"})
    assert prefixes.resolve(NamedNode("urn:isbn:1")) == NamedNode("urn:isbn:1")

    class Thing(pymantic.rdf.Resource):
        prefixes = {"urn": "http://example.com/urn#"}

    assert Thing.resolve(NamedNode("urn:isbn:1")) == NamedNode("urn:isbn:1")


def testResolveBarePrefixName(reset_metaresource):
    """A bare declared prefix name resolves to its namespace, unless a default
    prefix is set, which takes precedence as it always has."""
    assert PrefixMap({"foo": "http://example.com/foo#"}).resolve("foo") == (
        NamedNode("http://example.com/foo#")
    )
    assert PrefixMap({"": "http://default/", "foo": "http://example.com/foo#"}).resolve(
        "foo"
    ) == NamedNode("http://default/foo")


def testResolveDeclaredPrefixWinsOverScheme(reset_metaresource):
    """A declared prefix expands even when it is also a URI scheme."""
    prefixes = PrefixMap(
        {
            "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#",
            "urn": "http://example.com/urn/",
        }
    )
    assert prefixes.resolve("geo:lat") == NamedNode(
        "http://www.w3.org/2003/01/geo/wgs84_pos#lat"
    )
    assert prefixes.resolve("urn:isbn:1234567890123") == NamedNode(
        "http://example.com/urn/isbn:1234567890123"
    )


def testResolveDefaultPrefix(reset_metaresource):
    """A value with no colon, or an empty prefix, uses the default prefix."""
    prefixes = PrefixMap({"": "foo/", "wrong": "WRONG!"})
    assert prefixes.resolve("bar") == NamedNode("foo/bar")
    assert prefixes.resolve(":baz") == NamedNode("foo/baz")


def testResolveDeclaredPrefixes(reset_metaresource):
    """Declared prefixes expand."""
    prefixes = PrefixMap({"": "WRONG!", "foo": "foobly/", "bar": "bardle/"})
    assert prefixes.resolve("foo:aap") == NamedNode("foobly/aap")
    assert prefixes.resolve("bar:baz") == NamedNode("bardle/baz")


def testUnresolvableValues(reset_metaresource):
    """Values that are neither prefixed names nor absolute IRIs raise."""
    prefixes = PrefixMap({"foo": "WRONG!"})
    with pytest.raises(ValueError):
        prefixes.resolve("bar")
    with pytest.raises(ValueError):
        prefixes.resolve(":bar")
    with pytest.raises(ValueError):
        prefixes.resolve("_:b0")
    with pytest.raises(ValueError):
        prefixes.resolve("1bar:baz")


def testResourceResolveFallsBackToGlobalProfile(reset_metaresource):
    """A prefix the class doesn't declare resolves through the global profile,
    and one neither declares is taken as an absolute IRI."""

    class Thing(pymantic.rdf.Resource):
        prefixes = {"ex": "http://example.com/"}

    assert Thing.resolve("ex:a") == NamedNode("http://example.com/a")
    assert Thing.resolve("xsd:string") == XSD("string")
    assert Thing.resolve("urn:x") == NamedNode("urn:x")


def testResourceSeesLaterGlobalPrefixes(reset_metaresource):
    """A prefix added to the global profile after a class is defined is
    visible to that class, and the class's own prefixes still win."""

    class Thing(pymantic.rdf.Resource):
        prefixes = {"ex": "http://example.com/"}

    profile = pymantic.rdf.Resource.global_profile
    profile.setPrefix("later", "http://later.example/")
    profile.setPrefix("ex", "http://WRONG/")
    try:
        assert Thing.resolve("later:a") == NamedNode("http://later.example/a")
        assert Thing.resolve("ex:a") == NamedNode("http://example.com/a")
    finally:
        del profile.prefixes["later"]
        del profile.prefixes["ex"]


def testResourceFollowsReplacedGlobalProfile(reset_metaresource):
    """Replacing global_profile, on the class or a base, after the class is
    defined changes the prefixes it falls back to."""

    class Thing(pymantic.rdf.Resource):
        pass

    class Child(Thing):
        pass

    replacement = pymantic.primitives.Profile()
    replacement.setPrefix("foo", "http://foo.example/")
    Thing.global_profile = replacement
    try:
        assert Thing.resolve("foo:bar") == NamedNode("http://foo.example/bar")
        assert Child.resolve("foo:bar") == NamedNode("http://foo.example/bar")
    finally:
        del Thing.global_profile


def testResourceBareNamesAreGlobalTerms(reset_metaresource):
    """A bare name the class's own prefixes don't resolve is a term of the
    global profile, even when the global profile has a default prefix or a
    prefix of that name."""

    class Thing(pymantic.rdf.Resource):
        pass

    profile = pymantic.rdf.Resource.global_profile
    profile.setTerm("label", "http://www.w3.org/2000/01/rdf-schema#label")
    profile.setDefaultPrefix("http://WRONG/#")
    try:
        assert Thing.resolve("label") == NamedNode(
            "http://www.w3.org/2000/01/rdf-schema#label"
        )
        with pytest.raises(ValueError, match="'xsd'"):
            Thing.resolve("xsd")
    finally:
        del profile.terms["label"]
        del profile.prefixes[""]


def testPrefixMapExpand(reset_metaresource):
    """expand applies only the map's own prefixes, returning None where
    resolve would fall back to an absolute IRI or raise."""
    prefixes = PrefixMap({"ex": "http://example.com/", "": "http://default/"})
    assert prefixes.expand("ex:a") == NamedNode("http://example.com/a")
    assert prefixes.expand("a") == NamedNode("http://default/a")
    assert prefixes.expand(":a") == NamedNode("http://default/a")
    assert prefixes.expand(NamedNode("ex:a")) == NamedNode("ex:a")
    assert prefixes.expand("urn:x") is None
    assert prefixes.expand("rdsf:label") is None
    assert prefixes.expand("ex://a") is None
    assert PrefixMap({"ex": "http://example.com/"}).expand("ex") == NamedNode(
        "http://example.com/"
    )
    assert PrefixMap().expand("a") is None


def testScalarsResolveThroughGlobalProfile(reset_metaresource):
    """Scalars resolve like predicates do, including prefixes only the global
    profile declares."""

    class Thing(pymantic.rdf.Resource):
        prefixes = {"ex": "http://example.com/"}
        scalars = frozenset(("ex:a", "xsd:string"))

    assert NamedNode("http://example.com/a") in Thing.scalars
    assert XSD("string") in Thing.scalars
    assert NamedNode("xsd:string") not in Thing.scalars


def testScalarsResolveGlobalTerms(reset_metaresource):
    """A bare scalar name resolves as a global profile term, as it does when
    used as a predicate."""
    profile = pymantic.rdf.Resource.global_profile
    profile.setTerm("label", "http://www.w3.org/2000/01/rdf-schema#label")
    try:

        class Thing(pymantic.rdf.Resource):
            scalars = frozenset(("label",))

        assert NamedNode("http://www.w3.org/2000/01/rdf-schema#label") in Thing.scalars
    finally:
        del profile.terms["label"]


def testUnresolvableScalarRaises(reset_metaresource):
    """A scalar that resolves to nothing fails when the class is defined."""
    with pytest.raises(ValueError, match="labl"):

        class Thing(pymantic.rdf.Resource):
            scalars = frozenset(("labl",))


def testUnresolvableNameRaises(reset_metaresource):
    """A bare name that is neither a prefix nor a known term raises, rather
    than resolving to None, which graph matching treats as a wildcard."""
    graph = Graph()
    subject = NamedNode("http://example.com/s")
    graph.add(
        Triple(
            subject,
            NamedNode("http://www.w3.org/2000/01/rdf-schema#label"),
            Literal("s"),
        )
    )
    resource = pymantic.rdf.Resource(graph, subject)
    with pytest.raises(ValueError, match="'labl'"):
        pymantic.rdf.Resource.resolve("labl")
    with pytest.raises(ValueError, match="'labl'"):
        resource["labl"]


def testMetaResourceNothingUseful(reset_metaresource):
    """Test applying a MetaResource to a class without anything it uses."""

    class Foo(metaclass=pymantic.rdf.MetaResource):
        pass


def testMetaResourceprefixes(reset_metaresource):
    """Test the handling of prefixes by MetaResource."""

    class Foo(metaclass=pymantic.rdf.MetaResource):
        prefixes = {
            "foo": "bar",
            "baz": "garply",
            "meme": "lolcatz!",
        }

    assert Foo.prefixes == {
        "foo": Prefix("bar"),
        "baz": Prefix("garply"),
        "meme": Prefix("lolcatz!"),
    }


def testMetaResourcePrefixInheritance(reset_metaresource):
    """Test the composition of Prefix dictionaries by MetaResource."""

    class Foo(metaclass=pymantic.rdf.MetaResource):
        prefixes = {
            "foo": "bar",
            "baz": "garply",
            "meme": "lolcatz!",
        }

    class Bar(Foo):
        prefixes = {
            "allyourbase": "arebelongtous!",
            "bunny": "pancake",
        }

    assert Foo.prefixes == {
        "foo": Prefix("bar"),
        "baz": Prefix("garply"),
        "meme": Prefix("lolcatz!"),
    }
    assert Bar.prefixes == {
        "foo": Prefix("bar"),
        "baz": Prefix("garply"),
        "meme": Prefix("lolcatz!"),
        "allyourbase": Prefix("arebelongtous!"),
        "bunny": Prefix("pancake"),
    }


def testMetaResourcePrefixInheritanceReplacement(reset_metaresource):
    """Test the composition of Prefix dictionaries by MetaResource where
    some prefixes on the parent get replaced."""

    class Foo(metaclass=pymantic.rdf.MetaResource):
        prefixes = {
            "foo": "bar",
            "baz": "garply",
            "meme": "lolcatz!",
        }

    class Bar(Foo):
        prefixes = {
            "allyourbase": "arebelongtous!",
            "bunny": "pancake",
            "foo": "notbar",
            "baz": "notgarply",
        }

    assert Foo.prefixes == {
        "foo": Prefix("bar"),
        "baz": Prefix("garply"),
        "meme": Prefix("lolcatz!"),
    }
    assert Bar.prefixes == {
        "foo": Prefix("notbar"),
        "baz": Prefix("notgarply"),
        "meme": Prefix("lolcatz!"),
        "allyourbase": Prefix("arebelongtous!"),
        "bunny": Prefix("pancake"),
    }


def testResourceEquality(reset_metaresource):
    graph = Graph()
    otherGraph = Graph()
    testResource = pymantic.rdf.Resource(graph, "foo")
    assert testResource == pymantic.rdf.Resource(graph, "foo")
    assert testResource == NamedNode("foo")
    assert testResource == "foo"
    assert testResource != pymantic.rdf.Resource(graph, "bar")
    assert testResource == pymantic.rdf.Resource(otherGraph, "foo")
    assert testResource != NamedNode("bar")
    assert testResource != "bar"
    assert testResource != 42


def testClassification(reset_metaresource):
    """Test classification of a resource."""

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

    test_subject = NamedNode("http://example.com/athing")
    graph = Graph()
    graph.add(
        Triple(
            test_subject,
            Offering.resolve("rdf:type"),
            Offering.resolve("gr:Offering"),
        )
    )
    offering = pymantic.rdf.Resource.classify(graph, test_subject)
    assert isinstance(offering, Offering)


def testMulticlassClassification(reset_metaresource):
    """Test classification of a resource that matches multiple registered
    classes."""

    @pymantic.rdf.register_class("foaf:Organization")
    class Organization(pymantic.rdf.Resource):
        prefixes = {
            "foaf": "http://xmlns.com/foaf/0.1/",
        }

    @pymantic.rdf.register_class("foaf:Group")
    class Group(pymantic.rdf.Resource):
        prefixes = {
            "foaf": "http://xmlns.com/foaf/0.1/",
        }

    test_subject1 = NamedNode("http://example.com/aorganization")
    test_subject2 = NamedNode("http://example.com/agroup")
    test_subject3 = NamedNode("http://example.com/aorgandgroup")
    graph = Graph()
    graph.add(
        Triple(
            test_subject1,
            Organization.resolve("rdf:type"),
            Organization.resolve("foaf:Organization"),
        )
    )
    graph.add(
        Triple(test_subject2, Group.resolve("rdf:type"), Group.resolve("foaf:Group"))
    )
    graph.add(
        Triple(
            test_subject3,
            Organization.resolve("rdf:type"),
            Organization.resolve("foaf:Organization"),
        )
    )
    graph.add(
        Triple(
            test_subject3,
            Organization.resolve("rdf:type"),
            Organization.resolve("foaf:Group"),
        )
    )
    organization = pymantic.rdf.Resource.classify(graph, test_subject1)
    group = pymantic.rdf.Resource.classify(graph, test_subject2)
    both = pymantic.rdf.Resource.classify(graph, test_subject3)
    assert isinstance(organization, Organization)
    assert not isinstance(group, Organization)
    assert not isinstance(organization, Group)
    assert isinstance(group, Group)
    assert isinstance(both, Organization)
    assert isinstance(both, Group)


def testStr(reset_metaresource):
    """Test str-y serialization of Resources."""
    graph = Graph()
    test_subject1 = NamedNode("http://example.com/aorganization")
    test_label = Literal("Test Label", language="en")
    graph.add(
        Triple(test_subject1, pymantic.rdf.Resource.resolve("rdfs:label"), test_label)
    )
    r = pymantic.rdf.Resource(graph, test_subject1)
    assert r["rdfs:label"] == test_label
    assert str(r) == test_label.value


def testGetSetDelPredicate(reset_metaresource):
    """Test getting, setting, and deleting a multi-value predicate."""
    graph = Graph()
    test_subject1 = NamedNode("http://example.com/")
    r = pymantic.rdf.Resource(graph, test_subject1)
    r["rdfs:example"] = set(("foo", "bar"))
    example_values = set(r["rdfs:example"])
    assert Literal("foo") in example_values
    assert Literal("bar") in example_values
    assert len(example_values) == 2
    del r["rdfs:example"]
    example_values = set(r["rdfs:example"])
    assert len(example_values) == 0


def testGetSetDelScalarPredicate(reset_metaresource):
    """Test getting, setting, and deleting a scalar predicate."""
    graph = Graph()
    test_subject1 = NamedNode("http://example.com/")
    r = pymantic.rdf.Resource(graph, test_subject1)
    r["rdfs:label"] = "foo"
    assert r["rdfs:label"] == Literal("foo", language="en")
    del r["rdfs:label"]
    assert r["rdfs:label"] is None


def testGetSetDelPredicateLanguage(reset_metaresource):
    """Test getting, setting and deleting a multi-value predicate with an explicit language."""
    graph = Graph()
    test_subject1 = NamedNode("http://example.com/")
    r = pymantic.rdf.Resource(graph, test_subject1)
    r["rdfs:example", "en"] = set(("baz",))
    r["rdfs:example", "fr"] = set(("foo", "bar"))
    example_values = set(r["rdfs:example", "fr"])
    assert Literal("foo", language="fr") in example_values
    assert Literal("bar", language="fr") in example_values
    assert Literal("baz", language="en") not in example_values
    assert len(example_values) == 2
    example_values = set(r["rdfs:example", "en"])
    assert Literal("foo", language="fr") not in example_values
    assert Literal("bar", language="fr") not in example_values
    assert Literal("baz", language="en") in example_values
    assert len(example_values) == 1
    del r["rdfs:example", "fr"]
    example_values = set(r["rdfs:example", "fr"])
    assert len(example_values) == 0
    example_values = set(r["rdfs:example", "en"])
    assert Literal("foo", language="fr") not in example_values
    assert Literal("bar", language="fr") not in example_values
    assert Literal("baz", language="en") in example_values
    assert len(example_values) == 1


def testGetSetDelScalarPredicateLanguage(reset_metaresource):
    """Test getting, setting, and deleting a scalar predicate with an explicit language."""
    graph = Graph()
    test_subject1 = NamedNode("http://example.com/")
    r = pymantic.rdf.Resource(graph, test_subject1)
    r["rdfs:label"] = "foo"
    r["rdfs:label", "fr"] = "bar"
    assert r["rdfs:label"] == Literal("foo", language="en")
    assert r["rdfs:label", "en"] == Literal("foo", language="en")
    assert r["rdfs:label", "fr"] == Literal("bar", language="fr")
    del r["rdfs:label"]
    assert r["rdfs:label"] is None
    assert r["rdfs:label", "en"] is None
    assert r["rdfs:label", "fr"] == Literal("bar", language="fr")


def testGetSetDelPredicateDatatype(reset_metaresource):
    """Test getting, setting and deleting a multi-value predicate with an explicit datatype."""
    graph = Graph()
    test_subject1 = NamedNode("http://example.com/")
    r = pymantic.rdf.Resource(graph, test_subject1)
    now = datetime.datetime.now()
    then = datetime.datetime.now() - datetime.timedelta(days=1)
    number = 42
    r["rdfs:example", XSD("integer")] = set((number,))
    r["rdfs:example", XSD("dateTime")] = set(
        (
            now,
            then,
        )
    )
    example_values = set(r["rdfs:example", XSD("dateTime")])
    assert Literal(now) in example_values
    assert Literal(then) in example_values
    assert Literal(number) not in example_values
    assert len(example_values) == 2
    example_values = set(r["rdfs:example", XSD("integer")])
    assert Literal(now) not in example_values
    assert Literal(then) not in example_values
    assert Literal(number) in example_values
    assert len(example_values) == 1
    del r["rdfs:example", XSD("dateTime")]
    example_values = set(r["rdfs:example", XSD("dateTime")])
    assert len(example_values) == 0
    example_values = set(r["rdfs:example", XSD("integer")])
    assert Literal(now) not in example_values
    assert Literal(then) not in example_values
    assert Literal(number) in example_values
    assert len(example_values) == 1


def testGetSetDelScalarPredicateDatatype(reset_metaresource):
    """Test getting, setting, and deleting a scalar predicate with an explicit datatype."""
    graph = Graph()
    test_subject1 = NamedNode("http://example.com/")
    r = pymantic.rdf.Resource(graph, test_subject1)
    now = datetime.datetime.now()
    number = 42
    r["rdfs:label", XSD("integer")] = number
    assert r["rdfs:label", XSD("integer")] == Literal(number, datatype=XSD("integer"))
    assert r["rdfs:label", XSD("dateTime")] is None
    assert r["rdfs:label"] == Literal(number, datatype=XSD("integer"))
    r["rdfs:label", XSD("dateTime")] = now
    assert r["rdfs:label", XSD("dateTime")] == Literal(now)
    assert r["rdfs:label", XSD("integer")] is None
    assert r["rdfs:label"] == Literal(now)
    del r["rdfs:label", XSD("integer")]
    assert r["rdfs:label", XSD("dateTime")] == Literal(now)
    assert r["rdfs:label", XSD("integer")] is None
    assert r["rdfs:label"] == Literal(now)
    del r["rdfs:label", XSD("dateTime")]
    assert r["rdfs:label"] is None
    r["rdfs:label", XSD("integer")] = number
    assert r["rdfs:label", XSD("integer")] == Literal(number, datatype=XSD("integer"))
    assert r["rdfs:label", XSD("dateTime")] is None
    assert r["rdfs:label"] == Literal(number, datatype=XSD("integer"))
    del r["rdfs:label"]
    assert r["rdfs:label"] is None


def testGetSetDelPredicateType(reset_metaresource):
    """Test getting, setting and deleting a multi-value predicate with an explicit expected RDF Class."""
    graph = Graph()
    test_subject1 = NamedNode("http://example.com/offering")
    test_subject2 = NamedNode("http://example.com/aposi1")
    test_subject3 = NamedNode("http://example.com/aposi2")
    test_subject4 = NamedNode("http://example.com/possip1")

    shared_prefixes = {
        "gr": "http://purl.org/goodrelations/",
    }

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = shared_prefixes

    @pymantic.rdf.register_class("gr:ActualProductOrServiceInstance")
    class ActualProduct(pymantic.rdf.Resource):
        prefixes = shared_prefixes

    @pymantic.rdf.register_class("gr:ProductOrServicesSomeInstancesPlaceholder")
    class PlaceholderProduct(pymantic.rdf.Resource):
        prefixes = shared_prefixes

    offering = Offering.new(graph, test_subject1)
    aposi1 = ActualProduct.new(graph, test_subject2)
    aposi2 = ActualProduct.new(graph, test_subject3)
    possip1 = PlaceholderProduct.new(graph, test_subject4)
    offering["gr:includes", ActualProduct] = set(
        (
            aposi1,
            aposi2,
        )
    )
    offering["gr:includes", PlaceholderProduct] = set((possip1,))
    example_values = set(offering["gr:includes", ActualProduct])
    assert aposi1 in example_values
    assert aposi2 in example_values
    assert possip1 not in example_values
    assert len(example_values) == 2
    example_values = set(offering["gr:includes", PlaceholderProduct])
    assert aposi1 not in example_values
    assert aposi2 not in example_values
    assert possip1 in example_values
    assert len(example_values) == 1
    del offering["gr:includes", ActualProduct]
    example_values = set(offering["gr:includes", ActualProduct])
    assert len(example_values) == 0
    example_values = set(offering["gr:includes", PlaceholderProduct])
    assert aposi1 not in example_values
    assert aposi2 not in example_values
    assert possip1 in example_values
    assert len(example_values) == 1


def testGetSetDelScalarPredicateType(reset_metaresource):
    """Test getting, setting, and deleting a scalar predicate with an explicit language."""
    graph = Graph()
    test_subject1 = NamedNode("http://example.com/offering")
    test_subject2 = NamedNode("http://example.com/aposi")
    test_subject4 = NamedNode("http://example.com/possip")

    shared_prefixes = {
        "gr": "http://purl.org/goodrelations/",
    }

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = shared_prefixes

        scalars = frozenset(("gr:includes",))

    @pymantic.rdf.register_class("gr:ActualProductOrServiceInstance")
    class ActualProduct(pymantic.rdf.Resource):
        prefixes = shared_prefixes

    @pymantic.rdf.register_class("gr:ProductOrServicesSomeInstancesPlaceholder")
    class PlaceholderProduct(pymantic.rdf.Resource):
        prefixes = shared_prefixes

    offering = Offering.new(graph, test_subject1)
    aposi1 = ActualProduct.new(graph, test_subject2)
    possip1 = PlaceholderProduct.new(graph, test_subject4)
    offering["gr:includes", ActualProduct] = aposi1
    assert aposi1 == offering["gr:includes", ActualProduct]
    assert offering["gr:includes", PlaceholderProduct] is None
    assert aposi1 == offering["gr:includes"]
    offering["gr:includes", PlaceholderProduct] = possip1
    assert offering["gr:includes", ActualProduct] is None
    assert possip1 == offering["gr:includes", PlaceholderProduct]
    assert possip1 == offering["gr:includes"]
    del offering["gr:includes", ActualProduct]
    assert offering["gr:includes", ActualProduct] is None
    assert possip1 == offering["gr:includes", PlaceholderProduct]
    del offering["gr:includes", PlaceholderProduct]
    assert offering["gr:includes", ActualProduct] is None
    assert offering["gr:includes", PlaceholderProduct] is None
    offering["gr:includes", ActualProduct] = aposi1
    assert aposi1 == offering["gr:includes", ActualProduct]
    assert offering["gr:includes", PlaceholderProduct] is None
    assert aposi1 == offering["gr:includes"]
    del offering["gr:includes"]
    assert offering["gr:includes", ActualProduct] is None
    assert offering["gr:includes", PlaceholderProduct] is None
    assert offering["gr:includes"] is None


def testSetMixedScalarPredicate(reset_metaresource):
    """Test getting and setting a scalar predicate with mixed typing."""
    graph = Graph()
    test_subject1 = NamedNode("http://example.com/offering")
    test_subject2 = NamedNode("http://example.com/aposi")

    shared_prefixes = {
        "gr": "http://purl.org/goodrelations/",
    }

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = shared_prefixes

        scalars = frozenset(("gr:includes",))

    @pymantic.rdf.register_class("gr:ActualProductOrServiceInstance")
    class ActualProduct(pymantic.rdf.Resource):
        prefixes = shared_prefixes

    offering = Offering.new(graph, test_subject1)
    aposi1 = ActualProduct.new(graph, test_subject2)
    test_en = Literal("foo", language="en")
    test_fr = Literal("le foo", language="fr")
    test_dt = Literal("42", datatype=XSD("integer"))

    offering["gr:includes"] = aposi1
    assert offering["gr:includes"] == aposi1
    offering["gr:includes"] = test_dt
    assert offering["gr:includes"] == test_dt
    assert offering["gr:includes", ActualProduct] is None
    offering["gr:includes"] = test_en
    assert offering["gr:includes", ActualProduct] is None
    assert offering["gr:includes", XSD("integer")] is None
    assert offering["gr:includes"] == test_en
    assert offering["gr:includes", "en"] == test_en
    assert offering["gr:includes", "fr"] is None
    offering["gr:includes"] = test_fr
    assert offering["gr:includes", ActualProduct] is None
    assert offering["gr:includes", XSD("integer")] is None
    assert offering["gr:includes"] == test_en
    assert offering["gr:includes", "en"] == test_en
    assert offering["gr:includes", "fr"] == test_fr
    offering["gr:includes"] = aposi1
    assert offering["gr:includes"] == aposi1
    assert offering["gr:includes", XSD("integer")] is None
    assert offering["gr:includes", "en"] is None
    assert offering["gr:includes", "fr"] is None


def testResourcePredicate(reset_metaresource):
    """Test instantiating a class when accessing a predicate."""

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

    @pymantic.rdf.register_class("gr:PriceSpecification")
    class PriceSpecification(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

    test_subject1 = NamedNode("http://example.com/offering")
    test_subject2 = NamedNode("http://example.com/price")
    graph = Graph()
    graph.add(
        Triple(
            test_subject1,
            Offering.resolve("rdf:type"),
            Offering.resolve("gr:Offering"),
        )
    )
    graph.add(
        Triple(
            test_subject1,
            Offering.resolve("gr:hasPriceSpecification"),
            test_subject2,
        )
    )
    graph.add(
        Triple(
            test_subject2,
            PriceSpecification.resolve("rdf:type"),
            PriceSpecification.resolve("gr:PriceSpecification"),
        )
    )
    offering = Offering(graph, test_subject1)
    price_specification = PriceSpecification(graph, test_subject2)
    prices = set(offering["gr:hasPriceSpecification"])
    assert len(prices) == 1
    assert price_specification in prices


def testResourcePredicateAssignment(reset_metaresource):
    """Test assigning an instance of a resource to a predicate."""

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

    @pymantic.rdf.register_class("gr:PriceSpecification")
    class PriceSpecification(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

    test_subject1 = NamedNode("http://example.com/offering")
    test_subject2 = NamedNode("http://example.com/price")
    graph = Graph()
    graph.add(
        Triple(
            test_subject1,
            Offering.resolve("rdf:type"),
            Offering.resolve("gr:Offering"),
        )
    )
    graph.add(
        Triple(
            test_subject2,
            PriceSpecification.resolve("rdf:type"),
            PriceSpecification.resolve("gr:PriceSpecification"),
        )
    )
    offering = Offering(graph, test_subject1)
    price_specification = PriceSpecification(graph, test_subject2)
    before_prices = set(offering["gr:hasPriceSpecification"])
    assert len(before_prices) == 0
    offering["gr:hasPriceSpecification"] = price_specification
    after_prices = set(offering["gr:hasPriceSpecification"])
    assert len(after_prices) == 1
    assert price_specification in after_prices


def testNewResource(reset_metaresource):
    """Test creating a new resource."""
    graph = Graph()

    @pymantic.rdf.register_class("foaf:Person")
    class Person(pymantic.rdf.Resource):
        prefixes = {
            "foaf": "http://xmlns.com/foaf/0.1/",
        }

    test_subject = NamedNode("http://example.com/")
    Person.new(graph, test_subject)


def testGetAllResourcesInGraph(reset_metaresource):
    """Test iterating over all of the resources in a graph with a
    particular RDF type."""

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

    graph = Graph()
    test_subject_base = NamedNode("http://example.com/")
    for i in range(10):
        graph.add(
            Triple(
                NamedNode(test_subject_base + str(i)),
                Offering.resolve("rdf:type"),
                Offering.resolve("gr:Offering"),
            )
        )
    offerings = Offering.in_graph(graph)
    assert len(offerings) == 10
    for i in range(10):
        this_subject = NamedNode(test_subject_base + str(i))
        offering = Offering(graph, this_subject)
        assert offering in offerings


def testContained(reset_metaresource):
    """Test in against a multi-value predicate."""
    graph = Graph()
    test_subject1 = NamedNode("http://example.com/")
    r = pymantic.rdf.Resource(graph, test_subject1)
    r["rdfs:example"] = set(("foo", "bar"))
    assert "rdfs:example" in r
    assert ("rdfs:example", "en") not in r
    ("rdfs:example", "fr") not in r
    assert "rdfs:examplefoo" not in r
    del r["rdfs:example"]
    assert "rdfs:example" not in r
    assert ("rdfs:example", "en") not in r
    assert ("rdfs:example", "fr") not in r
    assert "rdfs:examplefoo" not in r
    r["rdfs:example", "fr"] = "le foo"


def testBack(reset_metaresource):
    """Test following a predicate backwards."""

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

    @pymantic.rdf.register_class("gr:PriceSpecification")
    class PriceSpecification(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

    graph = Graph()
    offering1 = Offering.new(graph, "http://example.com/offering1")
    offering2 = Offering.new(graph, "http://example.com/offering2")
    Offering.new(graph, "http://example.com/offering3")
    price1 = PriceSpecification.new(graph, "http://example.com/price1")
    price2 = PriceSpecification.new(graph, "http://example.com/price2")
    price3 = PriceSpecification.new(graph, "http://example.com/price3")
    offering1["gr:hasPriceSpecification"] = set(
        (
            price1,
            price2,
            price3,
        )
    )
    offering2["gr:hasPriceSpecification"] = set(
        (
            price2,
            price3,
        )
    )
    assert set(price1.object_of(predicate="gr:hasPriceSpecification")) == set(
        (offering1,)
    )
    assert set(price2.object_of(predicate="gr:hasPriceSpecification")) == set(
        (
            offering1,
            offering2,
        )
    )
    assert set(price3.object_of(predicate="gr:hasPriceSpecification")) == set(
        (
            offering1,
            offering2,
        )
    )


def testGetAllValues(reset_metaresource):
    """Test getting all values for a predicate."""

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

    en = Literal("foo", language="en")
    fr = Literal("bar", language="fr")
    es = Literal("baz", language="es")
    xsdstring = Literal("aap")
    xsddecimal = Literal("9.95", datatype=XSD("decimal"))
    graph = Graph()
    offering = Offering.new(graph, "http://example.com/offering")

    offering["gr:description"] = set(
        (
            en,
            fr,
            es,
        )
    )
    assert frozenset(offering["gr:description"]) == frozenset(
        (
            en,
            fr,
            es,
        )
    )
    assert frozenset(offering["gr:description", "en"]) == frozenset((en,))
    assert frozenset(offering["gr:description", "fr"]) == frozenset((fr,))
    assert frozenset(offering["gr:description", "es"]) == frozenset((es,))
    assert frozenset(offering["gr:description", None]) == frozenset(
        (
            en,
            fr,
            es,
        )
    )

    offering["gr:description"] = set(
        (
            xsdstring,
            xsddecimal,
        )
    )
    assert frozenset(offering["gr:description", ""]), frozenset((xsdstring,))
    assert frozenset(offering["gr:description", XSD("string")]) == frozenset(
        (xsdstring,)
    )
    assert frozenset(offering["gr:description", XSD("decimal")]) == frozenset(
        (xsddecimal,)
    )
    assert frozenset(offering["gr:description", None]) == frozenset(
        (
            xsdstring,
            xsddecimal,
        )
    )

    offering["gr:description"] = set(
        (
            en,
            fr,
            es,
            xsdstring,
            xsddecimal,
        )
    )
    assert frozenset(offering["gr:description"]) == frozenset(
        (
            en,
            fr,
            es,
            xsdstring,
            xsddecimal,
        )
    )
    assert frozenset(offering["gr:description", "en"]) == frozenset((en,))
    assert frozenset(offering["gr:description", "fr"]) == frozenset((fr,))
    assert frozenset(offering["gr:description", "es"]) == frozenset((es,))
    assert frozenset(offering["gr:description", ""]) == frozenset((xsdstring,))
    assert frozenset(offering["gr:description", XSD("string")]) == frozenset(
        (xsdstring,)
    )
    assert frozenset(offering["gr:description", XSD("decimal")]) == frozenset(
        (xsddecimal,)
    )
    assert frozenset(offering["gr:description", None]) == frozenset(
        (
            en,
            fr,
            es,
            xsdstring,
            xsddecimal,
        )
    )


def testGetAllValuesScalar(reset_metaresource):
    """Test getting all values for a predicate."""

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

        scalars = frozenset(("gr:description",))

    en = Literal("foo", language="en")
    fr = Literal("bar", language="fr")
    es = Literal("baz", language="es")
    graph = Graph()
    offering = Offering.new(graph, "http://example.com/offering")
    offering["gr:description"] = en
    offering["gr:description"] = fr
    offering["gr:description"] = es
    assert offering["gr:description"] == en
    assert offering["gr:description", "en"] == en
    assert offering["gr:description", "fr"] == fr
    assert offering["gr:description", "es"] == es
    assert frozenset(offering["gr:description", None]) == frozenset(
        (
            en,
            fr,
            es,
        )
    )


def testErase(reset_metaresource):
    """Test erasing an object from the graph."""

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

        scalars = frozenset(("gr:name",))

    graph = Graph()
    offering1 = Offering.new(graph, "http://example.com/offering1")
    offering2 = Offering.new(graph, "http://example.com/offering2")
    offering1["gr:name"] = "Foo"
    offering1["gr:description"] = set(
        (
            "Baz",
            "Garply",
        )
    )
    offering2["gr:name"] = "Bar"
    offering2["gr:description"] = set(
        (
            "Aap",
            "Mies",
        )
    )
    assert offering1.is_a()
    assert offering2.is_a()
    offering1.erase()
    assert not offering1.is_a()
    assert offering2.is_a()
    assert not offering1["gr:name"]
    assert not frozenset(offering1["gr:description"])
    assert offering2["gr:name"] == Literal("Bar", language="en")


def testUnboundClass(reset_metaresource):
    """Test classifying objects with one or more unbound classes."""

    @pymantic.rdf.register_class("gr:Offering")
    class Offering(pymantic.rdf.Resource):
        prefixes = {
            "gr": "http://purl.org/goodrelations/",
        }

    graph = Graph()
    funky_class = NamedNode("http://example.com/AFunkyClass")
    funky_subject = NamedNode("http://example.com/aFunkyResource")

    offering1 = Offering.new(graph, "http://example.com/offering1")
    graph.add(Triple(offering1.subject, RDF("type"), funky_class))
    assert isinstance(
        pymantic.rdf.Resource.classify(graph, offering1.subject), Offering
    )
    graph.add(Triple(funky_subject, RDF("type"), funky_class))
    assert isinstance(
        pymantic.rdf.Resource.classify(graph, funky_subject),
        pymantic.rdf.Resource,
    )
