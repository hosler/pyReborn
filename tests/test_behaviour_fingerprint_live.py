"""This live test proves that the behavioral fingerprint detects a silent branch flip.

The opt-in test (`pytest -m live -s`) needs the public Login server and the
credentials in ~/.config/pyreborn/prefs.json. The test uses two PASSIVE
connections and makes no writes.

The fingerprint suite was built for this regression. On 2026-07-24,
`gs2_compare` let a GS2Object compare EQUAL to null, so Login's
`findweapon("-Rescripted/Serverlist") == null` was true for a weapon that WAS
found. Thus, `-Rescripted/IRC/Login3` skipped `initServerlist()`, and the client
built no GUI. The run had zero errors and zero warnings, and every other suite
was green.

The test reintroduces exactly that semantic at runtime. A monkeypatched
`gs2_compare` that falls through to the numeric compare, which reports 0.0 ==
0.0 for object-vs-null, supplies the semantic. The test asserts that the
fingerprint check FAILS and names the structural invariants that moved. Then,
the test asserts that the same check PASSES with the real, fixed comparison.

The test never edits reborn-protocol. `vm.py` does `from .values import
gs2_compare`. Thus, the binding in the vm module is the binding that matters.
"""

import json
import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

#: Both captures use the baseline's own observation window: the count bands
#: are calibrated for it, so a shorter run would fail for the wrong reason.
SERVER = "Login"


def _buggy_compare():
    """The pre-fix gs2_compare has no object-vs-non-object identity guard."""
    from reborn_protocol.gs2.values import (
        GS2Object, _casecmp, _numcmp, to_num)

    def compare(a, b):
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            if len(a) != len(b):
                return -1 if len(a) < len(b) else 1
            for x, y in zip(a, b):
                c = compare(x, y)
                if c:
                    return c
            return 0
        if isinstance(a, GS2Object) or isinstance(b, GS2Object):
            if isinstance(a, GS2Object) and isinstance(b, GS2Object):
                if a is b:
                    return 0
                return -1 if id(a) < id(b) else 1
            obj, other = (a, b) if isinstance(a, GS2Object) else (b, a)
            if isinstance(other, str):
                c = _casecmp(obj.name or "", other)
                return c if obj is a else -c
            # THE BUG: falls through, and to_num() is 0.0 for both an object
            # and null, so `findweapon(...) == null` is true when found.
        if isinstance(a, str) and isinstance(b, str):
            return _casecmp(a, b)
        return _numcmp(to_num(a), to_num(b))

    return compare


def _capture(name):
    from game_tester.behaviour_fingerprint import (
        capture_target, load_baselines, target_for)
    from pyreborn.prefs import Prefs

    baselines = load_baselines()
    entry = baselines["servers"].get(name)
    if entry is None:
        pytest.skip(f"no behaviour baseline recorded for {name!r}")
    prefs = Prefs.load()
    if not prefs.username:
        pytest.skip("no saved credentials in ~/.config/pyreborn")
    target = target_for(name, entry)
    return baselines, entry, capture_target(target, prefs.username, prefs.password)


def _maybe_dump(label, fingerprint):
    """PYREBORN_FINGERPRINT_DUMP=<dir> saves the raw captures.

    This setting produced tests/fixtures/fingerprint_login_*.json. The unit
    tests replay these offline copies.
    """
    directory = os.environ.get("PYREBORN_FINGERPRINT_DUMP")
    if not directory:
        return
    path = Path(directory) / f"fingerprint_{label}.json"
    path.write_text(json.dumps(fingerprint, indent=2, sort_keys=True) + "\n")
    print(f"    wrote {path}")


def _report(name, results):
    print(f"\n[BEHAVIOUR] {name}")
    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        print(f"    [{mark}] {result.name:<18} {result.actual}")
        if not result.passed:
            print(f"           expected {result.expected} "
                  f"(baseline {result.baseline})")


def test_fingerprint_catches_object_vs_null_regression(monkeypatch):
    from game_tester.behaviour_fingerprint import compare as compare_fingerprint
    from reborn_protocol.gs2 import values as gs2_values
    from reborn_protocol.gs2 import vm as gs2_vm

    broken = _buggy_compare()
    monkeypatch.setattr(gs2_values, "gs2_compare", broken)
    monkeypatch.setattr(gs2_vm, "gs2_compare", broken)

    _baselines, entry, fingerprint = _capture(SERVER)
    results = compare_fingerprint(fingerprint, entry)
    _maybe_dump("login_broken", fingerprint)
    _report(f"{SERVER} (gs2_compare object-vs-null bug re-introduced)", results)

    failed = {result.name for result in results if not result.passed}
    assert failed, "the fingerprint did not notice the broken Login GUI"
    # The signature of this specific outage: the GUI was never built.
    assert "gui_roots" in failed
    assert "gui_named" in failed
    assert "controls_present" in failed


def test_fingerprint_passes_with_fixed_compare():
    from game_tester.behaviour_fingerprint import compare as compare_fingerprint

    time.sleep(5.0)  # politeness: space the two remote connections
    _baselines, entry, fingerprint = _capture(SERVER)
    results = compare_fingerprint(fingerprint, entry)
    _maybe_dump("login_good", fingerprint)
    _report(f"{SERVER} (fixed tree)", results)
    assert [result.name for result in results if not result.passed] == []
