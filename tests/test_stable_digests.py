"""Term codes and stable serializer output must not move without a
deliberate re-record (see tests/stable_digests.py)."""

from tests.stable_digests import digests, recorded


def test_term_codes_unchanged():
    assert digests(ids=())["term_codes"] == recorded()["term_codes"]


def test_stable_outputs_unchanged():
    then = recorded()["outputs"]
    now = digests(set(then))["outputs"]
    changed = sorted(k for k in then if now.get(k) != then[k])
    assert not changed, changed[:10]
