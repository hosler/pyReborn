"""
gs2_tests - GS2 VM end-to-end suite (bytecode EXECUTION, unlike tier5 which
only tests transport).

Runs against either server: GServer-v2 serves these fixtures from
bin/servers/default/, pygserver from its own weapons/ + scripts/ (compiling the
clientside half with the same gs2test compiler -- see pygserver/pygserver/gs2.py).

Server fixtures (identical copies in both server directories):
  weapons/weaponqa%095gs2vm.txt   - weapon `qa_gs2vm`:
      onCreated: this.count=0, this.created=1, showimg(200,...), settimer
      onTimeout: this.count++ (re-arms until count==3)
      onActionqa2relay(a,b): this.relay = a@"-"@b
      qaSend(x,y): triggeraction(x,y,"qa2relay","ping")
      qaJoinHelper(n): join("qa_gs2vmclass"). Return qaDouble(n)
  scripts/qa_gs2vmclass.txt       - class with qaDouble(n)/qaGreet(name)

GS2 weapons stay OFF the suite accounts (login-time registration of a
compiled weapon segfaults upstream GServer, see tier5) -- bytecode is fetched
on demand via PLI_UPDATESCRIPT and loaded into the VM locally.

Run: python -m game_tester --gs2
"""

from __future__ import annotations

import glob
import os
import time
from typing import List

from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2
from reborn_protocol.gs2 import GS2VM

from .game_bot import GameBot, Issue
from .reporter import TestResult

WEAPON = "qa_gs2vm"
CLASS = "qa_gs2vmclass"

BASELINES_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "..", "GServer-v2", "build", "dependencies",
    "fc", "gs2parser-src", "tests", "baselines",
)


def _issue(sev: str, cat: str, desc: str) -> Issue:
    return Issue(timestamp=time.time(), severity=sev, category=cat, description=desc)


def _pump(bot: GameBot, seconds: float, until=None, rt2: ClientGS2 = None):
    deadline = time.time() + seconds
    last = time.time()
    while time.time() < deadline:
        bot.update(0.05)
        now = time.time()
        if rt2 is not None:
            rt2.process_timeouts(now - last)
        last = now
        if until is not None and until():
            break


def _setup_gs2(bot: GameBot) -> ClientGS2:
    """Attach a headless GS1 host + GS2 runtime to the bot's client (the same
    pair pygame_game wires up)."""
    gs1 = ClientGS1(bot.client)
    bot.client.gs1_host = gs1
    rt2 = ClientGS2(bot.client, gs1).attach()
    return rt2


def _fetch_weapon_vm(bot: GameBot, rt2: ClientGS2):
    c = bot.client
    if WEAPON not in c.gs2_bytecode["weapon"]:
        c.request_weapon_bytecode(WEAPON)
        _pump(bot, 6.0, until=lambda: WEAPON in c.gs2_bytecode["weapon"], rt2=rt2)
    # attach() loads arriving blobs automatically; cover the pre-attached case
    if rt2.vms["weapon"].get(WEAPON.lower()) is None and WEAPON in c.gs2_bytecode["weapon"]:
        rt2.load_bytecode("weapon", WEAPON, c.gs2_bytecode["weapon"][WEAPON])
    return rt2.vms["weapon"].get(WEAPON.lower())


def test_weapon_oncreated(bot: GameBot, rt2: ClientGS2) -> TestResult:
    """Weapon bytecode loads into the VM and onCreated's side effects are
    visible: this.created=1 and the showimg layer landed in the SHARED GS1
    layer store (same store the pygame renderer draws)."""
    start = time.time()
    issues: List[Issue] = []
    vm = _fetch_weapon_vm(bot, rt2)

    created = vm is not None and vm.this.get("created") == 1
    if not created:
        issues.append(_issue("HIGH", "gs2vm", f"onCreated did not run: vm={vm}"))

    imgs = rt2.gs1._weapon_imgs.get(f"gs2_weapon_{WEAPON.lower()}", {}) if rt2.gs1 else {}
    layer = imgs.get(200, {})
    shown = layer.get("image") == "qa_gs2.png" and layer.get("x") == 30
    if not shown:
        issues.append(_issue("HIGH", "gs2vm", f"showimg layer missing/wrong: {layer}"))

    ok = created and shown
    return TestResult("gs2vm_weapon_oncreated", ok, time.time() - start,
                      f"created={created} showimg={layer.get('image')}", issues)


def test_timeout_loop(bot: GameBot, rt2: ClientGS2) -> TestResult:
    """onCreated armed settimer(0.05). OnTimeout increments this.count and
    re-arms until it reaches 3 -- proves the settimer/onTimeout scheduling
    loop end-to-end."""
    start = time.time()
    issues: List[Issue] = []
    vm = _fetch_weapon_vm(bot, rt2)

    _pump(bot, 3.0, until=lambda: vm is not None and vm.this.get("count") == 3, rt2=rt2)
    count = vm.this.get("count") if vm is not None else None
    ok = count == 3
    if not ok:
        issues.append(_issue("HIGH", "gs2vm", f"onTimeout loop stopped at count={count}"))
    return TestResult("gs2vm_timeout_loop", ok, time.time() - start,
                      f"count={count} (want 3)", issues)


def test_class_join(bot: GameBot, rt2: ClientGS2) -> TestResult:
    """qaJoinHelper(n) joins qa_gs2vmclass at runtime and calls its qaDouble.
    First call triggers the PLI_UPDATECLASS request (join returns before the
    blob arrives -> method missing -> 0). Once the class bytecode lands the
    pending join resolves and the call works."""
    start = time.time()
    issues: List[Issue] = []
    vm = _fetch_weapon_vm(bot, rt2)
    if vm is None:
        return TestResult("gs2vm_class_join", False, time.time() - start,
                          "weapon vm missing", [_issue("HIGH", "gs2vm", "no weapon vm")])

    vm.call("qaJoinHelper", 21)     # kicks off the class request if needed
    _pump(bot, 6.0, until=lambda: rt2.vms["class"].get(CLASS) is not None, rt2=rt2)

    result = vm.call("qaJoinHelper", 21)
    greet = vm.call("qaGreet", "bot")   # joined method callable directly too
    ok = result == 42 and greet == "hi bot"
    if not ok:
        issues.append(_issue("HIGH", "gs2vm",
                             f"join/method-call failed: qaJoinHelper(21)={result!r} qaGreet={greet!r}"))
    return TestResult("gs2vm_class_join", ok, time.time() - start,
                      f"qaJoinHelper(21)={result} qaGreet(bot)={greet!r}", issues)


def test_triggeraction_roundtrip(host: str, port: int) -> TestResult:
    """Bot B's GS2 weapon calls triggeraction(...) (VM builtin -> real
    PLI_TRIGGERACTION). The server relays to bot A on the same level part.
    A's inbound PLO_TRIGGERACTION routing fires onActionqa2relay on A's VM,
    which records this.relay -- full client->server->client GS2 round-trip."""
    start = time.time()
    issues: List[Issue] = []
    bot_a = GameBot("testbot1", host, port)
    bot_b = GameBot("testbot2", host, port)
    try:
        if not bot_a.connect() or not bot_b.connect():
            return TestResult("gs2vm_triggeraction_roundtrip", False, 0.0,
                              "connect failed", [_issue("HIGH", "gs2vm", "connect failed")])
        rt2a = _setup_gs2(bot_a)
        rt2b = _setup_gs2(bot_b)
        vm_a = _fetch_weapon_vm(bot_a, rt2a)
        vm_b = _fetch_weapon_vm(bot_b, rt2b)
        if vm_a is None or vm_b is None:
            return TestResult("gs2vm_triggeraction_roundtrip", False, time.time() - start,
                              "weapon vm missing", [_issue("HIGH", "gs2vm", "no weapon vm")])

        # stand together so the level-part relay reaches A
        bot_a.walk_to(32, 32, timeout=6.0)
        bot_b.walk_to(33, 32, timeout=6.0)
        for _ in range(10):
            bot_a.update(0.05)
            bot_b.update(0.05)

        # B fires the weapon function that triggeractions at A's position.
        ax = bot_a.client.player.x
        ay = bot_a.client.player.y
        vm_b.call("qaSend", ax, ay)

        _pump(bot_a, 5.0, until=lambda: vm_a.this.get("relay") is not None, rt2=rt2a)
        for _ in range(4):
            bot_b.update(0.05)

        relay = vm_a.this.get("relay")
        ok = relay == "ping-"       # onActionqa2relay("ping", null) -> "ping-"
        if not ok:
            issues.append(_issue("HIGH", "gs2vm", f"relay not received/wrong: {relay!r}"))
        return TestResult("gs2vm_triggeraction_roundtrip", ok, time.time() - start,
                          f"this.relay={relay!r}", issues)
    finally:
        bot_a.disconnect()
        bot_b.disconnect()


def test_inbound_action_routing(bot: GameBot, rt2: ClientGS2) -> TestResult:
    """Local check of the PLO_TRIGGERACTION -> onAction<name> path (no second
    player needed): inject the action the way client.py routes it."""
    start = time.time()
    issues: List[Issue] = []
    vm = _fetch_weapon_vm(bot, rt2)
    if vm is None:
        return TestResult("gs2vm_action_routing", False, time.time() - start,
                          "weapon vm missing", [_issue("HIGH", "gs2vm", "no weapon vm")])
    vm.this.set("relay", None)
    rt2.handle_triggeraction("qa2relay,alpha,beta")
    relay = vm.this.get("relay")
    ok = relay == "alpha-beta"
    if not ok:
        issues.append(_issue("HIGH", "gs2vm", f"onActionqa2relay got {relay!r}"))
    return TestResult("gs2vm_action_routing", ok, time.time() - start,
                      f"this.relay={relay!r}", issues)


def test_corpus_coverage() -> TestResult:
    """Every gs2parser baseline .bytecode executes (toplevel + every function,
    argless) with zero exceptions escaping the VM. Prints the opcode/builtin
    coverage summary -- the honest progress metric."""
    start = time.time()
    issues: List[Issue] = []
    files = sorted(glob.glob(os.path.join(BASELINES_ROOT, "**", "*.bytecode"), recursive=True))
    if not files:
        return TestResult("gs2vm_corpus", False, 0.0, "baselines not found",
                          [_issue("HIGH", "gs2vm", f"no baselines under {BASELINES_ROOT}")])

    import logging
    logging.disable(logging.CRITICAL)
    crashes = 0
    try:
        for path in files:
            try:
                with open(path, "rb") as fh:
                    vm = GS2VM(fh.read(), name=os.path.basename(path))
                vm.max_ops = 60_000
                vm.run_toplevel()
                for fname in list(vm.functions):
                    vm.call(fname)
            except Exception as e:  # must never happen
                crashes += 1
                issues.append(_issue("HIGH", "gs2vm", f"{os.path.basename(path)}: {e}"))
    finally:
        logging.disable(logging.NOTSET)

    rep = GS2VM.coverage_report()
    seen = len(rep["seen_ops"])
    unimpl = len(rep["seen_not_implemented"])
    print(f"    corpus: {len(files)} scripts, {seen} distinct ops seen, "
          f"{unimpl} unimplemented, {len(rep['builtins_missing'])} missing builtins")
    ok = crashes == 0 and unimpl == 0
    return TestResult("gs2vm_corpus", ok, time.time() - start,
                      f"{len(files)} scripts, crashes={crashes}, "
                      f"ops seen={seen}, unimplemented={unimpl}", issues)


def run_gs2_tests(host: str = "localhost", port: int = 14900,
                  account: str = "testbot1") -> List[TestResult]:
    """Run the GS2 VM suite: single-bot fixture tests, the two-client
    triggeraction round-trip, and the offline corpus coverage check."""
    results: List[TestResult] = []
    bot = GameBot(account, host, port)
    try:
        if not bot.connect():
            return [TestResult("gs2vm_connect", False, 0.0,
                               f"{account} failed to connect", [])]
        rt2 = _setup_gs2(bot)
        for test in (test_weapon_oncreated, test_timeout_loop,
                     test_class_join, test_inbound_action_routing):
            try:
                results.append(test(bot, rt2))
            except Exception as e:  # noqa: BLE001
                results.append(TestResult(test.__name__, False, 0.0, f"Exception: {e}", []))
    finally:
        bot.disconnect()

    try:
        results.append(test_triggeraction_roundtrip(host, port))
    except Exception as e:  # noqa: BLE001
        results.append(TestResult("gs2vm_triggeraction_roundtrip", False, 0.0,
                                  f"Exception: {e}", []))

    try:
        results.append(test_corpus_coverage())
    except Exception as e:  # noqa: BLE001
        results.append(TestResult("gs2vm_corpus", False, 0.0, f"Exception: {e}", []))

    return results
