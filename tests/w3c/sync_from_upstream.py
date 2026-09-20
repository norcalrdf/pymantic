#!/usr/bin/env python
"""Refresh the vendored W3C RDF test suites from an rdf-tests checkout.

Use this when the W3C updates https://github.com/w3c/rdf-tests and we want
the new tests. It copies the six suites tests/test_w3c.py runs (Turtle,
N-Triples and N-Quads for RDF 1.1 and RDF 1.2), keeps the upstream directory
layout so relative ``mf:include`` links in the manifests still resolve, and
records the upstream commit in UPSTREAM.md so the vendored copy is
reproducible.

    python tests/w3c/sync_from_upstream.py /path/to/rdf-tests

Each suite directory under tests/w3c is deleted and recreated, so files
removed upstream disappear here too. Implementation reports, test archives
and the HTML report template are left out because the harness never reads
them. After syncing, run pytest and update tests/w3c/expected_failures.txt
for any new tests that fail.
"""

import argparse
import datetime
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
UPSTREAM_REPO = "https://github.com/w3c/rdf-tests"

# Paths relative to the rdf-tests checkout root, mirrored under tests/w3c.
SUITES = [
    "rdf/rdf11/rdf-n-triples",
    "rdf/rdf11/rdf-n-quads",
    "rdf/rdf11/rdf-turtle",
    "rdf/rdf12/rdf-n-triples",
    "rdf/rdf12/rdf-n-quads",
    "rdf/rdf12/rdf-turtle",
]
LICENSE_FILE = "LICENSE.md"
EXCLUDED_NAMES = {"reports", "template.haml"}
EXCLUDED_SUFFIXES = (".zip", ".tar.gz")


def excluded(directory, names):
    """shutil.copytree ignore callback: drop reports, archives and templates."""
    return {n for n in names if n in EXCLUDED_NAMES or n.endswith(EXCLUDED_SUFFIXES)}


def git_output(checkout, *args):
    try:
        return subprocess.run(
            ["git", "-C", str(checkout), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as e:
        sys.exit("error: git %s failed in %s: %s" % (" ".join(args), checkout, e))


def write_upstream_md(commit, commit_date):
    (HERE / "UPSTREAM.md").write_text(
        "# Vendored W3C RDF test suites\n"
        "\n"
        "Upstream repository: %s\n"
        "Upstream commit: %s (%s)\n"
        "Synced on: %s\n"
        "\n"
        "Directories under `rdf11/` and `rdf12/` mirror `rdf/rdf11/` and\n"
        "`rdf/rdf12/` in the upstream checkout. `LICENSE.md` is the upstream\n"
        "license file. Do not edit the vendored files by hand; run\n"
        "`sync_from_upstream.py` against a fresh checkout instead.\n"
        % (UPSTREAM_REPO, commit, commit_date, datetime.date.today().isoformat())
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "checkout", type=pathlib.Path, help="path to a git checkout of rdf-tests"
    )
    args = parser.parse_args(argv)
    checkout = args.checkout.resolve()

    for suite in SUITES:
        if not (checkout / suite / "manifest.ttl").is_file():
            sys.exit(
                "error: %s has no %s/manifest.ttl; is it an rdf-tests checkout?"
                % (checkout, suite)
            )
    if not (checkout / LICENSE_FILE).is_file():
        sys.exit("error: %s has no %s" % (checkout, LICENSE_FILE))

    commit = git_output(checkout, "rev-parse", "HEAD")
    commit_date = git_output(checkout, "log", "-1", "--format=%cs")

    for suite in SUITES:
        dest = HERE / pathlib.Path(suite).relative_to("rdf")
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(checkout / suite, dest, ignore=excluded)
        print("synced %s" % dest.relative_to(HERE))
    shutil.copyfile(checkout / LICENSE_FILE, HERE / LICENSE_FILE)
    write_upstream_md(commit, commit_date)
    print("upstream commit %s (%s)" % (commit, commit_date))


if __name__ == "__main__":
    main()
