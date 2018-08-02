from pymantic.compat import (
    binary_type,
)


class LarkParser(object):
    """Provide a consistent interface for parsing serialized RDF using one
    of the lark parsers.
    """
    def __init__(self, lark):
        self.lark = lark

    def line_by_line_parser(self, stream):
        for line in stream:  # Equivalent to readline
            if line:
                yield next(self.lark.parse(line))

    def parse(self, string_or_stream, graph=None):
        """Parse a string or file-like object into RDF primitives and add
        them to either the provided graph or a new graph.
        """
        tf = self.lark.options.transformer

        try:
            if graph is None:
                graph = tf._make_graph()

            tf._prepare_parse(graph)

            if hasattr(string_or_stream, 'readline'):
                triples = self.line_by_line_parser(string_or_stream)
            else:
                # Presume string.
                triples = self.lark.parse(string_or_stream)

            graph.addAll(triples)
        finally:
            tf._cleanup_parse()

        return graph

    def parse_string(self, string_or_bytes, graph=None):
        """Parse a string, decoding it from bytes to UTF-8 if necessary.
        """
        if isinstance(string_or_bytes, binary_type):
            string = string_or_bytes.decode('utf-8')
        else:
            string = string_or_bytes

        return self.parse(string, graph)
