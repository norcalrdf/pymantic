#!/usr/bin/env python
"""Download the real-world benchmark datasets listed in datasets.json into
benchmarks/data/, check each download against its SHA-256, and unpack or
convert it into the file or directory benchmarks/inputs.py reads.

Run this once before benchmarking real data; it is safe to run again, and
skips datasets already in place unless --force is given.

    python benchmarks/fetch_data.py               # every dataset
    python benchmarks/fetch_data.py fhir-r5-examples doid
    python benchmarks/fetch_data.py --list

Every URL in datasets.json is pinned to a release or commit, so a checksum
mismatch means the upstream file changed or the download was damaged; the
script stops with both checksums and leaves the bad download as
<file>.mismatch for inspection. Datasets published only as RDF/XML are
converted to N-Triples with rdflib, which must be installed (pip install
rdflib).
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DOWNLOADS = os.path.join(DATA, "downloads")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(dataset, path):
    headers = {"User-Agent": "pymantic-benchmarks"}
    headers.update(dataset.get("headers", {}))
    request = urllib.request.Request(dataset["url"], headers=headers)
    partial = path + ".partial"
    with urllib.request.urlopen(request, timeout=120) as response, open(
        partial, "wb"
    ) as f:
        shutil.copyfileobj(response, f)
    os.replace(partial, path)


def unpack(dataset, path, target):
    post = dataset.get("post")
    if post is None:
        shutil.copyfile(path, target)
    elif post == "unzip":
        partial = target + ".partial"
        shutil.rmtree(partial, ignore_errors=True)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(partial)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(partial, target)
    elif post == "rdfxml-to-ntriples":
        try:
            import rdflib
        except ImportError:
            sys.exit(
                f"{dataset['name']}: converting RDF/XML needs rdflib (pip install rdflib)"
            )
        graph = rdflib.Graph()
        graph.parse(path, format="xml")
        graph.serialize(target + ".partial", format="nt", encoding="utf-8")
        os.replace(target + ".partial", target)
    else:
        sys.exit(f"{dataset['name']}: unknown post step {post!r} in datasets.json")


def fetch(dataset, force):
    target = os.path.join(DATA, dataset["target"])
    path = os.path.join(DOWNLOADS, dataset["download"])
    if os.path.exists(target) and not force:
        print(f"{dataset['name']:22} already in place")
        return
    if force or not os.path.exists(path) or sha256(path) != dataset["sha256"]:
        print(f"{dataset['name']:22} downloading {dataset['url']}", flush=True)
        download(dataset, path)
    actual = sha256(path)
    if actual != dataset["sha256"]:
        os.replace(path, path + ".mismatch")
        sys.exit(
            f"{dataset['name']}: SHA-256 mismatch for {dataset['url']}\n"
            f"  expected {dataset['sha256']}\n  got      {actual}\n"
            f"  download kept as {path}.mismatch"
        )
    print(f"{dataset['name']:22} checksum ok, writing {dataset['target']}", flush=True)
    unpack(dataset, path, target)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.splitlines()[2:]),
    )
    ap.add_argument("names", nargs="*", help="datasets to fetch (default: all)")
    ap.add_argument("--force", action="store_true", help="download and unpack again")
    ap.add_argument("--list", action="store_true", help="list datasets and exit")
    args = ap.parse_args()
    with open(os.path.join(HERE, "datasets.json")) as f:
        datasets = json.load(f)
    if args.list:
        for dataset in datasets:
            print(f"{dataset['name']:22} {dataset['about']}\n{'':22} {dataset['url']}")
        return
    known = {dataset["name"] for dataset in datasets}
    unknown = [name for name in args.names if name not in known]
    if unknown:
        sys.exit(f"unknown dataset(s) {', '.join(unknown)}; see --list")
    os.makedirs(DOWNLOADS, exist_ok=True)
    for dataset in datasets:
        if not args.names or dataset["name"] in args.names:
            fetch(dataset, args.force)


if __name__ == "__main__":
    main()
