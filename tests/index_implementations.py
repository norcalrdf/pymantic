"""The triple index implementations the index tests run against."""

from pymantic import offset_index
from pymantic.adjacency_index import AdjacencyTripleIndex
from pymantic.dict_index import NestedDictTripleIndex
from pymantic.offset_index import OffsetTripleIndex
from pymantic.triple_index import TripleIndex

# One entry per implementation under test. The offsets-small-folds variant
# lowers DELTA_MIN so small graphs fold, leaving rows in main, dead rows and
# delta rows all in play.
INDEXES = [
    "sorted",
    "offsets",
    "offsets-small-folds",
    "dict",
    "adjacency",
]


def index_class_named(name, monkeypatch):
    """The index class for an entry of INDEXES, with any variant's constants
    set through `monkeypatch`."""
    if name == "sorted":
        return TripleIndex
    if name == "dict":
        return NestedDictTripleIndex
    if name == "adjacency":
        return AdjacencyTripleIndex
    if name == "offsets-small-folds":
        monkeypatch.setattr(offset_index, "DELTA_MIN", 4)
    return OffsetTripleIndex
