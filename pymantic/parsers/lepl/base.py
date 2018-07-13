import re

from pymantic.compat import (
    binary_type,
    unichr,
)

from ..base import (
    BaseParser,
    normalize_iri,
)


def discrete_pairs(iterable):
    "s -> (s0,s1), (s2,s3), (s4, s5), ..."
    previous = None
    for v in iterable:
        if previous is None:
            previous = v
        else:
            yield (previous, v)
            previous = None


unicode_re = re.compile(r'\\u([0-9A-Za-z]{4})|\\U([0-9A-Za-z]{8})')


def nt_unescape(nt_string):
    """Un-do nt escaping style."""
    if isinstance(nt_string, binary_type):
        nt_string = nt_string.decode('utf-8')

    nt_string = nt_string.replace('\\t', u'\u0009')
    nt_string = nt_string.replace('\\n', u'\u000A')
    nt_string = nt_string.replace('\\r', u'\u000D')
    nt_string = nt_string.replace('\\"', u'\u0022')
    nt_string = nt_string.replace('\\\\', u'\u005C')

    def chr_match(matchobj):
        ordinal = matchobj.group(1) or matchobj.group(2)
        return unichr(int(ordinal, 16))

    nt_string = unicode_re.sub(chr_match, nt_string)
    return nt_string


class BaseLeplParser(BaseParser):
    def parse(self, f, sink=None):
        if sink is None:
            sink = self._make_graph()
        self._prepare_parse(sink)
        self.document.parse_file(f)
        self._cleanup_parse()

        return sink

    def parse_string(self, string, sink=None):
        from pymantic.compat.moves import cStringIO as StringIO

        if isinstance(string, binary_type):
            string = string.decode('utf8')

        if sink is None:
            sink = self._make_graph()
        self._prepare_parse(sink)
        self.document.parse(StringIO(string))
        self._cleanup_parse()

        return sink
