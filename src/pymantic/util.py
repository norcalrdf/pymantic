"""Utility functions used throughout pymantic."""

__all__ = [
    "en",
    "de",
    "one_or_none",
    "normalize_iri",
    "quote_normalized_iri",
    "resolve_iri",
]

import re
from urllib.parse import quote


def en(value):
    """Returns an RDF literal from the en language for the given value."""
    from pymantic.primitives import Literal

    return Literal(value, language="en")


def de(value):
    """Returns an RDF literal from the de language for the given value."""
    from pymantic.primitives import Literal

    return Literal(value, language="de")


def one_or_none(values):
    """Fetch the first value from values, or None if values is empty. Raises
    ValueError if values has more than one thing in it."""
    if not values:
        return None
    if len(values) > 1:
        raise ValueError("Got more than one value.")
    return values[0]


percent_encoding_re = re.compile(
    r"(?:%(?![01][0-9a-fA-F])(?!20)[a-fA-F0-9][a-fA-F0-9])+"
)

reserved_in_iri = [
    "%",
    ":",
    "/",
    "?",
    "#",
    "[",
    "]",
    "@",
    "!",
    "$",
    "&",
    "'",
    "(",
    ")",
    "*",
    "+",
    ",",
    ";",
    "=",
]


def percent_decode(regmatch):
    encoded = b""
    for group in regmatch.group(0)[1:].split("%"):
        encoded += int(group, 16).to_bytes(1, "big")
    uni = encoded.decode("utf-8")
    for res in reserved_in_iri:
        uni = uni.replace(res, "%%%02X" % ord(res))
    return uni


def normalize_iri(iri):
    """Normalize an IRI using the Case Normalization (5.3.2.1) and
    Percent-Encoding Normalization (5.3.2.3) from RFC 3987. The IRI should be a
    unicode object."""

    return percent_encoding_re.sub(percent_decode, iri)


def percent_encode(char):
    return "".join("%%%02X" % char for char in char.encode("utf-8"))


def quote_normalized_iri(normalized_iri):
    """Percent-encode a normalized IRI; IE, all reserved characters are presumed
    to be themselves and not percent encoded. All other unsafe characters are
    percent-encoded."""
    normalized_uri = "".join(
        percent_encode(char) if ord(char) > 127 else char for char in normalized_iri
    )
    return quote(normalized_uri, safe="".join(reserved_in_iri))


# RFC 3986 appendix B. Groups 2, 4, 5, 7 and 9 are the scheme, authority,
# path, query and fragment; a group is None when its delimiter is absent.
IRI_REFERENCE_RE = re.compile(
    r"^(([^:/?#]+):)?(//([^/?#]*))?([^?#]*)(\?([^#]*))?(#(.*))?", re.DOTALL
)


def split_iri_reference(reference):
    """Split an IRI reference into its (scheme, authority, path, query,
    fragment) components. A component whose delimiter is absent is None,
    which RFC 3986 distinguishes from one that is present but empty."""
    match = IRI_REFERENCE_RE.match(reference)
    return (
        match.group(2),
        match.group(4),
        match.group(5),
        match.group(7),
        match.group(9),
    )


def remove_dot_segments(path):
    """Resolve the "." and ".." segments of `path` (RFC 3986 section 5.2.4).

    `output` holds one segment per entry, each with its leading "/" if it
    had one, so dropping the last segment is a pop."""
    output = []
    while path:
        if path.startswith("../"):
            path = path[3:]
        elif path.startswith("./"):
            path = path[2:]
        elif path.startswith("/./"):
            path = path[2:]
        elif path == "/.":
            path = "/"
        elif path.startswith("/../"):
            path = path[3:]
            if output:
                output.pop()
        elif path == "/..":
            path = "/"
            if output:
                output.pop()
        elif path in (".", ".."):
            path = ""
        else:
            end = path.find("/", 1)
            if end == -1:
                end = len(path)
            output.append(path[:end])
            path = path[end:]
    return "".join(output)


def merge_paths(base_authority, base_path, reference_path):
    """Append a relative path to the base path's directory (RFC 3986
    section 5.2.3)."""
    if base_authority is not None and base_path == "":
        return "/" + reference_path
    return base_path[: base_path.rfind("/") + 1] + reference_path


def resolve_iri(base, reference):
    """Resolve an IRI reference against a base IRI as a strict parser
    (RFC 3986 section 5.2), keeping empty path segments and an empty
    fragment intact. An absolute reference is returned as is, minus its
    dot segments, whatever `base` is."""
    scheme, authority, path, query, fragment = split_iri_reference(reference)
    if scheme is not None:
        path = remove_dot_segments(path)
    else:
        scheme, base_authority, base_path, base_query, _ = split_iri_reference(base)
        if authority is not None:
            path = remove_dot_segments(path)
        else:
            authority = base_authority
            if path == "":
                path = base_path
                if query is None:
                    query = base_query
            elif path.startswith("/"):
                path = remove_dot_segments(path)
            else:
                path = remove_dot_segments(merge_paths(base_authority, base_path, path))

    result = ""
    if scheme is not None:
        result += scheme + ":"
    if authority is not None:
        result += "//" + authority
    result += path
    if query is not None:
        result += "?" + query
    if fragment is not None:
        result += "#" + fragment
    return result


def smart_urljoin(base, url):
    """Resolve `url` against `base`; an alias of resolve_iri kept for
    backwards compatibility."""
    return resolve_iri(base, url)


def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"

    from itertools import zip_longest

    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)


ESCAPE_MAP = {
    "t": "\t",
    "b": "\b",
    "n": "\n",
    "r": "\r",
    "f": "\f",
    '"': '"',
    "'": "'",
    "\\": "\\",
}


ECHAR_MAP = {v: "\\" + k for k, v in ESCAPE_MAP.items()}


def process_escape(escape):
    escape = escape.group(0)[1:]

    if escape[0] in ("u", "U"):
        code_point = int(escape[1:], 16)
        # Turtle, N-Triples and N-Quads only allow Unicode scalar values in a
        # numeric escape; surrogate pairs cannot be written as two escapes.
        if 0xD800 <= code_point <= 0xDFFF:
            raise ValueError(
                "surrogate code point U+%04X is not allowed in a numeric "
                "escape: \\%s" % (code_point, escape)
            )
        if code_point > 0x10FFFF:
            raise ValueError(
                "code point U+%X is outside the Unicode range in a numeric "
                "escape: \\%s" % (code_point, escape)
            )
        return chr(code_point)
    else:
        return ESCAPE_MAP.get(escape[0], escape[0])


def decode_literal(literal):
    """Replace the ECHAR and UCHAR escapes of Turtle, N-Triples and N-Quads
    in `literal` with the characters they stand for. Raises ValueError for a
    numeric escape that does not denote a Unicode scalar value."""
    return re.sub(
        r"\\u[a-fA-F0-9]{4}|\\U[a-fA-F0-9]{8}|\\[^uU]",
        process_escape,
        literal,
    )
