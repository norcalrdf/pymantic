# RDFC-1.0 test suite inputs

Upstream repository: https://github.com/w3c/rdf-canon
Upstream commit: 15619df2fda7a4ca88308733789b6774517f9638 (2026-02-24)

The `*-in.nq` files are the input files of `tests/rdfc10/` in the upstream
checkout, copied unchanged. `LICENCE.md` is the upstream licence file.

The expected outputs (`*-rdfc10.nq`) and the manifest are deliberately not
vendored: pymantic does not implement RDFC-1.0 and does not run its test
suite. The inputs are used only as adversarial fixtures for
`pymantic.compare` (see docs/graph-comparison.rst), driven by
tests/test_compare_rdfc10.py.
