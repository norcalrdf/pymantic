import pytest

from pymantic.util import decode_literal, normalize_iri, quote_normalized_iri


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
