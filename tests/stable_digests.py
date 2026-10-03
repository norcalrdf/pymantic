"""Pin term codes and stable serializer output across the RDF 1.2 work.

``tests/fixtures/stable_digests.json`` records the term code of a fixed set
of literals and a SHA-256 of the ``stable=True`` output for every W3C input
pymantic parses correctly. tests/test_stable_digests.py compares the current
code against it.

Re-record only when a change is meant to move digests; the test then shows
exactly which.

    python -m tests.stable_digests --write   # record the fixture
    python -m tests.stable_digests           # list differences; exit 1 if any
"""

import argparse
import hashlib
from io import StringIO
import json
import pathlib
import sys

from pymantic.compare import term_code, term_key
from pymantic.primitives import XSD, Dataset, Literal, NamedNode
from pymantic.serializers import (
    serialize_nquads,
    serialize_ntriples,
    serialize_turtle,
)
from tests.test_w3c import ENTRIES, EXPECTED_FAILURES, parse_action

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "stable_digests.json"

LITERALS = [
    Literal(""),
    Literal("chat"),
    Literal("chat", "fr"),
    Literal("chat", "EN-gb"),
    Literal("5", datatype=XSD("integer")),
    Literal('a"b\\c\nd\te'),
    Literal("café 日本 \U0001f600"),
    Literal("\x00\x7f"),
    Literal("x", datatype=NamedNode("http://example/dt")),
]


def corpus(ids=None):
    """(test id, parsed graph or dataset) for every Turtle eval, positive
    syntax and positive C14N test that pymantic is not expected to fail.
    With ``ids``, only those tests are parsed."""
    return [
        (entry.id, parse_action(entry))
        for entry in ENTRIES
        if (
            entry.kind == "TestTurtleEval"
            or entry.kind.endswith("PositiveSyntax")
            or entry.kind.endswith("PositiveC14N")
        )
        and entry.id not in EXPECTED_FAILURES
        and (ids is None or entry.id in ids)
    ]


def sha256_hex(serialize, data):
    out = StringIO()
    serialize(data, out, stable=True)
    return hashlib.sha256(out.getvalue().encode("utf-8")).hexdigest()


def digests(ids=None):
    """The JSON-ready record. With ``ids``, outputs cover only those test
    ids: tests that start passing later join the corpus, and their output is
    not pinned."""
    outputs = {}
    for test_id, data in corpus(ids):
        if isinstance(data, Dataset):
            outputs[test_id] = {"nq": sha256_hex(serialize_nquads, data)}
        else:
            outputs[test_id] = {
                "nt": sha256_hex(serialize_ntriples, data),
                "ttl": sha256_hex(serialize_turtle, data),
            }
    return {
        "term_codes": {term_key(lit): term_code(term_key(lit)) for lit in LITERALS},
        "outputs": outputs,
    }


def recorded():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--write", action="store_true", help="write the fixture from the current code"
    )
    args = parser.parse_args()
    if args.write:
        record = digests()
        FIXTURE.write_text(
            json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        print("wrote %s: %d outputs" % (FIXTURE, len(record["outputs"])))
        return
    then = recorded()
    now = digests(set(then["outputs"]))
    changed = sorted(
        k for k, v in then["outputs"].items() if now["outputs"].get(k) != v
    )
    codes_differ = now["term_codes"] != then["term_codes"]
    if codes_differ:
        print("term codes differ")
    print("%d of %d outputs differ" % (len(changed), len(then["outputs"])))
    for test_id in changed[:10]:
        print("  " + test_id)
    if changed or codes_differ:
        sys.exit(1)


if __name__ == "__main__":
    main()
