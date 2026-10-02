"""The ``--index`` option of the benchmark scripts: which triple index class
Graph and Dataset build, to compare implementations on one source tree.

``sorted`` (the default) leaves pymantic as it is, so a script still runs on
a tree without the alternative index modules. Any other choice imports its
module and installs the class as ``pymantic.primitives.TripleIndex``, which
Graph and Dataset look up each time they build an index; call `use` before
loading any graph.
"""

import importlib

# Choice name to (module, class), or None for pymantic's own index.
INDEXES = {
    "sorted": None,
    "adjacency": ("pymantic.adjacency_index", "AdjacencyTripleIndex"),
}


def add_argument(parser):
    parser.add_argument(
        "--index",
        choices=list(INDEXES),
        default="sorted",
        help="triple index implementation for Graph and Dataset (default sorted)",
    )


def use(name):
    """Make Graph and Dataset build the index chosen by `name`."""
    choice = INDEXES[name]
    if choice is None:
        return
    import pymantic.primitives

    module, cls = choice
    pymantic.primitives.TripleIndex = getattr(importlib.import_module(module), cls)
    print(f"index: {module}.{cls}")
