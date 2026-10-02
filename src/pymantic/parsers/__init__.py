from importlib.util import find_spec

from .lark import (
    linetrig_parser,
    nquads_parser,
    ntriples_parser,
    turtle_parser,
)

__all__ = ["ntriples_parser", "nquads_parser", "linetrig_parser", "turtle_parser"]

# JSON-LD support depends on pyld, an optional extra, so it is imported only
# when asked for, and star imports offer it only when pyld is installed.
if find_spec("pyld") is not None:
    __all__.append("jsonld_parser")


def __getattr__(name):
    if name == "jsonld_parser":
        from .jsonld import jsonld_parser

        return jsonld_parser
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
