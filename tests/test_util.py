import pytest

from pymantic.util import (
    decode_literal,
    normalize_iri,
    quote_normalized_iri,
    resolve_iri,
    smart_urljoin,
)


def test_normalize_iri_no_escapes():
    uri = "http://example.com/foo/bar?garply=aap&maz=bies"
    normalized = normalize_iri(uri)
    assert normalized == "http://example.com/foo/bar?garply=aap&maz=bies"
    assert normalized == normalize_iri(normalized)
    assert quote_normalized_iri(normalized) == uri


def test_normalize_iri_escaped_slash():
    uri = "http://example.com/foo%2Fbar?garply=aap&maz=bies"
    normalized = normalize_iri(uri)
    assert normalized == "http://example.com/foo%2Fbar?garply=aap&maz=bies"
    assert normalized == normalize_iri(normalized)
    assert quote_normalized_iri(normalized) == uri


def test_normalize_iri_escaped_ampersand():
    uri = "http://example.com/foo/bar?garply=aap%26yak&maz=bies"
    normalized = normalize_iri(uri)
    assert normalized == "http://example.com/foo/bar?garply=aap%26yak&maz=bies"
    assert normalized == normalize_iri(normalized)
    assert quote_normalized_iri(normalized) == uri


def test_normalize_iri_escaped_international():
    uri = "http://example.com/foo/bar?garply=aap&maz=bi%C3%89s"
    normalized = normalize_iri(uri)
    assert normalized == "http://example.com/foo/bar?garply=aap&maz=bi\u00C9s"
    assert normalized == normalize_iri(normalized)
    assert quote_normalized_iri(normalized) == uri


def test_decode_literal_escapes():
    assert decode_literal(r"a\tb\nc\\d\"e\'f") == "a\tb\nc\\d\"e'f"
    assert decode_literal(r"\u00e9\U0001F0A1") == "\u00e9\U0001F0A1"
    assert decode_literal(r"\ud7ff\ue000\U0010FFFF") == "\ud7ff\ue000\U0010FFFF"


@pytest.mark.parametrize(
    "escaped",
    [
        r"\ud800",
        r"\udfff",
        r"\U0000D800",
        r"\uD83C\uDCA1",  # a surrogate pair is not allowed either
        r"\uDCA1\uD83C",
        r"Single high surrogate (\uD83C)",
    ],
)
def test_decode_literal_rejects_surrogates(escaped):
    with pytest.raises(ValueError, match="surrogate"):
        decode_literal(escaped)


def test_decode_literal_rejects_code_points_beyond_unicode():
    with pytest.raises(ValueError, match=r"U\+110000 .*Unicode.*\\U00110000"):
        decode_literal(r"\U00110000")


# RFC 3986 section 5.4.1, all resolved against http://a/b/c/d;p?q
RFC3986_NORMAL_EXAMPLES = [
    ("g:h", "g:h"),
    ("g", "http://a/b/c/g"),
    ("./g", "http://a/b/c/g"),
    ("g/", "http://a/b/c/g/"),
    ("/g", "http://a/g"),
    ("//g", "http://g"),
    ("?y", "http://a/b/c/d;p?y"),
    ("g?y", "http://a/b/c/g?y"),
    ("#s", "http://a/b/c/d;p?q#s"),
    ("g#s", "http://a/b/c/g#s"),
    ("g?y#s", "http://a/b/c/g?y#s"),
    (";x", "http://a/b/c/;x"),
    ("g;x", "http://a/b/c/g;x"),
    ("g;x?y#s", "http://a/b/c/g;x?y#s"),
    ("", "http://a/b/c/d;p?q"),
    (".", "http://a/b/c/"),
    ("./", "http://a/b/c/"),
    ("..", "http://a/b/"),
    ("../", "http://a/b/"),
    ("../g", "http://a/b/g"),
    ("../..", "http://a/"),
    ("../../", "http://a/"),
    ("../../g", "http://a/g"),
]

# RFC 3986 section 5.4.2, same base; "http:g" as a strict parser resolves it
RFC3986_ABNORMAL_EXAMPLES = [
    ("../../../g", "http://a/g"),
    ("../../../../g", "http://a/g"),
    ("/./g", "http://a/g"),
    ("/../g", "http://a/g"),
    ("g.", "http://a/b/c/g."),
    (".g", "http://a/b/c/.g"),
    ("g..", "http://a/b/c/g.."),
    ("..g", "http://a/b/c/..g"),
    ("./../g", "http://a/b/g"),
    ("./g/.", "http://a/b/c/g/"),
    ("g/./h", "http://a/b/c/g/h"),
    ("g/../h", "http://a/b/c/h"),
    ("g;x=1/./y", "http://a/b/c/g;x=1/y"),
    ("g;x=1/../y", "http://a/b/c/y"),
    ("g?y/./x", "http://a/b/c/g?y/./x"),
    ("g?y/../x", "http://a/b/c/g?y/../x"),
    ("g#s/./x", "http://a/b/c/g#s/./x"),
    ("g#s/../x", "http://a/b/c/g#s/../x"),
    ("http:g", "http:g"),
]


@pytest.mark.parametrize(
    "reference,expected", RFC3986_NORMAL_EXAMPLES + RFC3986_ABNORMAL_EXAMPLES
)
def test_resolve_iri_rfc3986_examples(reference, expected):
    assert resolve_iri("http://a/b/c/d;p?q", reference) == expected


@pytest.mark.parametrize(
    "base,reference,expected",
    [
        # Empty path segments are ordinary segments (W3C IRI-resolution-08)
        ("http://ab//de//ghi", "xyz", "http://ab//de//xyz"),
        ("http://ab//de//ghi", "./xyz", "http://ab//de//xyz"),
        ("http://ab//de//ghi", "../xyz", "http://ab//de/xyz"),
        ("http://abc/d:f/ghi", "xyz", "http://abc/d:f/xyz"),
        ("http://abc/d:f/ghi", "../xyz", "http://abc/xyz"),
        # An empty fragment is a fragment, and the base's fragment is dropped
        ("http://a/b/c", "#", "http://a/b/c#"),
        ("http://a/b/c#frag", "", "http://a/b/c"),
        ("http://a/b/c#frag", "d#", "http://a/b/d#"),
        ("http://a/b/c", "http://x/y#", "http://x/y#"),
        # A base with an authority and no path (RFC 3986 section 5.2.3)
        ("http://a", "g", "http://a/g"),
        ("http://a?q", "g?y", "http://a/g?y"),
        # A non-hierarchical base
        ("urn:isbn:0451450523", "?x", "urn:isbn:0451450523?x"),
        ("urn:isbn:0451450523", "g", "urn:g"),
        # No base: absolute references pass through
        ("", "http://a/b", "http://a/b"),
        ("", "urn:ex:s", "urn:ex:s"),
    ],
)
def test_resolve_iri(base, reference, expected):
    assert resolve_iri(base, reference) == expected


def test_smart_urljoin_resolves_like_resolve_iri():
    assert smart_urljoin("http://ab//de//ghi", "../xyz#") == "http://ab//de/xyz#"
