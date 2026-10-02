"""The --index option the benchmarks share: which triple index Graph and
Dataset build, so index implementations can be compared on one tree.

"sorted" leaves pymantic as it is and imports nothing, so the default runs
on any source tree, including ones from before the index existed.
"""

import importlib

# --index name -> (module, class) swapped in for pymantic.primitives.TripleIndex.
INDEXES = {
    "sorted": None,
    "btree": ("pymantic.btree_index", "BTreeTripleIndex"),
}


def add_argument(parser):
    parser.add_argument(
        "--index",
        choices=list(INDEXES),
        default="sorted",
        help="triple index implementation for Graph and Dataset (default sorted)",
    )


def use(name):
    """Make Graph and Dataset build the index called `name`."""
    target = INDEXES[name]
    if target is None:
        return
    import pymantic.primitives

    module, cls = target
    pymantic.primitives.TripleIndex = getattr(importlib.import_module(module), cls)
    print(f"index: {module}.{cls}")
