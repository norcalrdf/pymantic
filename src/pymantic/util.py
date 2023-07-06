"""Utility functions used throughout pymantic."""

__all__ = ['en', 'de', 'one_or_none', 'normalize_iri', 'quote_normalized_iri',]

import re
from .compat.moves.urllib.parse import quote
from .compat import int2byte

def en(value):
    """Returns an RDF literal from the en language for the given value."""
    from pymantic.primitives import Literal
    return Literal(value, language='en')

def de(value):
    """Returns an RDF literal from the de language for the given value."""
    from pymantic.primitives import Literal
    return Literal(value, language='de')

def one_or_none(values):
    """Fetch the first value from values, or None if values is empty. Raises
    ValueError if values has more than one thing in it."""
    if not values:
        return None
    if len(values) > 1:
        raise ValueError('Got more than one value.')
    return values[0]

percent_encoding_re = re.compile(r'(?:%(?![01][0-9a-fA-F])(?!20)[a-fA-F0-9][a-fA-F0-9])+')

reserved_in_iri = ["%", ":", "/", "?", "#", "[", "]", "@", "!", "$", "&", "'",\
                   "(", ")", "*", "+", ",", ";", "="]

def percent_decode(regmatch):
    encoded = b''
    for group in regmatch.group(0)[1:].split('%'):
        encoded += int2byte(int(group, 16))
    uni = encoded.decode('utf-8')
    for res in reserved_in_iri:
        uni = uni.replace(res, '%%%02X' % ord(res))
    return uni

def normalize_iri(iri):
    """Normalize an IRI using the Case Normalization (5.3.2.1) and
    Percent-Encoding Normalization (5.3.2.3) from RFC 3987. The IRI should be a
    unicode object."""

    return percent_encoding_re.sub(percent_decode, iri)

def percent_encode(char):
    from .compat import ordbyte

    return ''.join('%%%02X' % ordbyte(char) for char in char.encode('utf-8'))

def quote_normalized_iri(normalized_iri):
    """Percent-encode a normalized IRI; IE, all reserved characters are presumed
    to be themselves and not percent encoded. All other unsafe characters are
    percent-encoded."""
    normalized_uri = ''.join(percent_encode(char) if ord(char) > 127 else char for\
                             char in normalized_iri)
    return quote(normalized_uri, safe=''.join(reserved_in_iri))


def smart_urljoin(base, url):
    """urljoin, only an empty fragment from the relative(?) URL will be
    preserved.
    """
    from .compat.moves.urllib.parse import urljoin

    joined = urljoin(base, url)
    if url.endswith('#') and not joined.endswith('#'):
        joined += '#'
    return joined


def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"

    from .compat.moves import zip_longest
    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)


ESCAPE_MAP = {
    't': '\t',
    'b': '\b',
    'n': '\n',
    'r': '\r',
    'f': '\f',
    '"': '\"',
    "'": "\'",
    "\\": "\\",
}


ECHAR_MAP = {
    v: '\\' + k for k, v in ESCAPE_MAP.items()
}


def process_escape(escape):
    from .compat import unichr

    escape = escape.group(0)[1:]

    if escape[0] in ('u', 'U'):
        return unichr(int(escape[1:], 16))
    else:
        return ESCAPE_MAP.get(escape[0], escape[0])


def decode_literal(literal):
    return re.sub(
        r'\\u[a-fA-F0-9]{4}|\\U[a-fA-F0-9]{8}|\\[^uU]',
        process_escape,
        literal,
    )
