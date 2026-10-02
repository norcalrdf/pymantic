"""JSON-LD support is the optional jsonld extra.

Which tests here run depends on whether pyld is installed. The tox
environments without the extra (core, pypy312 and the pyodide ones) run the
tests that need it missing, and also run the rest of the suite without it.
"""

from importlib import import_module
from importlib.util import find_spec
import pytest

PYLD_INSTALLED = find_spec("pyld") is not None

without_pyld = pytest.mark.skipif(
    PYLD_INSTALLED, reason="needs pyld to be missing; run tox -e core"
)
with_pyld = pytest.mark.skipif(not PYLD_INSTALLED, reason="needs the jsonld extra")

MISSING_EXTRA_MESSAGE = (
    "JSON-LD support requires pyld; install it with: pip install 'pymantic[jsonld]'"
)


def star_import_parsers():
    namespace = {}
    exec("from pymantic.parsers import *", namespace)
    return sorted(name for name in namespace if name.endswith("_parser"))


@without_pyld
def test_star_import_omits_jsonld_parser_without_pyld():
    assert star_import_parsers() == [
        "linetrig_parser",
        "nquads_parser",
        "ntriples_parser",
        "turtle_parser",
    ]


@with_pyld
def test_star_import_includes_jsonld_parser_with_pyld():
    assert star_import_parsers() == [
        "jsonld_parser",
        "linetrig_parser",
        "nquads_parser",
        "ntriples_parser",
        "turtle_parser",
    ]


@without_pyld
def test_jsonld_parser_attribute_names_the_extra_when_pyld_is_missing():
    with pytest.raises(ImportError) as raised:
        from pymantic.parsers import jsonld_parser  # noqa: F401
    assert str(raised.value) == MISSING_EXTRA_MESSAGE


@without_pyld
def test_jsonld_module_names_the_extra_when_pyld_is_missing():
    with pytest.raises(ImportError) as raised:
        import_module("pymantic.parsers.jsonld")
    assert str(raised.value) == MISSING_EXTRA_MESSAGE
