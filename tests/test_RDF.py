import datetime
import pytest

from pymantic.primitives import Graph, Literal, NamedNode, Prefix, Triple
import pymantic.rdf
import pymantic.util

XSD = Prefix("http://www.w3.org/2001/XMLSchema#")

RDF = Prefix("http://www.w3.org/1999/02/22-rdf-syntax-ns#")


@pytest.fixture()
def reset_metaresource():
    yield
    pymantic.rdf.MetaResource._classes = {}


def testCurieURI(reset_metaresource):
    """Test CURIE parsing of explicit URIs."""
    test_ns = {
        "http": Prefix("WRONG!"),
        "urn": Prefix("WRONG!"),
    }
    assert pymantic.rdf.parse_curie("http://example.com", test_ns) == NamedNode(
        "http://example.com"
    )
    assert pymantic.rdf.parse_curie("urn:isbn:1234567890123", test_ns) == NamedNode(
        "urn:isbn:1234567890123"
    )


def testCurieDefaultPrefix(reset_metaresource):
    """Test CURIE parsing of CURIEs in the default Prefix."""
    test_ns = {"": Prefix("foo/"), "wrong": Prefix("WRONG!")}
    assert pymantic.rdf.parse_curie("bar", test_ns) == NamedNode("foo/bar")
    assert pymantic.rdf.parse_curie("[bar]", test_ns) == NamedNode("foo/bar")
    assert pymantic.rdf.parse_curie("baz", test_ns) == NamedNode("foo/baz")
    assert pymantic.rdf.parse_curie("[aap]", test_ns) == NamedNode("foo/aap")


def testCurieprefixes(reset_metaresource):
    """Test CURIE parsing of CURIEs in non-default prefixes."""
    test_ns = {
        "": Prefix("WRONG!"),
        "foo": Prefix("foobly/"),
        "bar": Prefix("bardle/"),
        "http": Prefix("reallybadidea/"),
    }
    assert pymantic.rdf.parse_curie("foo:aap", test_ns) == NamedNode("foobly/aap")
    assert pymantic.rdf.parse_curie("[bar:aap]", test_ns) == NamedNode("bardle/aap")
    assert pymantic.rdf.parse_curie("[foo:baz]", test_ns) == NamedNode("foobly/baz")
    assert pymantic.rdf.parse_curie("bar:baz", test_ns) == NamedNode("bardle/baz")
    assert pymantic.rdf.parse_curie("[http://example.com]", test_ns) == NamedNode(
        "reallybadidea///example.com"
    )


def testUnparseableCuries(reset_metaresource):
    """Test some CURIEs that shouldn't parse."""
    test_ns = {
        "foo": Prefix("WRONG!"),
    }
    with pytest.raises(ValueError):
        pymantic.rdf.parse_curie("[bar]", test_ns)
    with pytest.raises(ValueError):
        pymantic.rdf.parse_curie("bar", test_ns)
    with pytest.raises(ValueError):
        pymantic.rdf.parse_curie("bar:baz", test_ns)
    with pytest.raises(ValueError):
        pymantic.rdf.parse_curie("[bar:baz]", test_ns)


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
