"""
tier5_tests - GS2 bytecode transport tests (parse and store only, no VM).

Exercises the pyReborn Tier 5 additions against server fixtures:
  - PLI_UPDATESCRIPT -> PLO_NPCWEAPONSCRIPT (weapon `qa_gs2weapon`)
  - PLI_UPDATECLASS  -> PLO_LOADSCRIPT bytecode form (class `qa_gs2class`)
  - PLI_UPDATEGANI   -> PLO_GANISCRIPT + PLO_LOADGANI (gani `qa_script`)
  - PLO_NPCBYTECODE synthetic parse. No server-side GS2 NPC fixture exists.
    The class/gani paths prove the shared RAWDATA framing.

Server fixtures (created for this suite, all with //#CLIENTSIDE GS2 code so
the server compiles client bytecode):
  weapons/weaponqa%095gs2weapon.txt, scripts/qa_gs2class.txt,
  world/qa_script.gani

Requires the Script.cpp getClientByteCode any_cast fix (working tree) -
the stock GServer beta4 terminates with std::bad_any_cast on any weapon
bytecode request.

Run: python -m game_tester --tier5
"""

from __future__ import annotations

import time
from typing import List, Tuple

from .game_bot import GameBot, Issue
from .reporter import TestResult


def _issue(sev: str, cat: str, desc: str) -> Issue:
    return Issue(timestamp=time.time(), severity=sev, category=cat, description=desc)


def _pump(bot: GameBot, seconds: float, until=None):
    deadline = time.time() + seconds
    while time.time() < deadline:
        bot.update(0.05)
        if until is not None and until():
            break


def test_weapon_bytecode(bot: GameBot) -> TestResult:
    """Request qa_gs2weapon's bytecode and assert the blob parses as a valid
    GS2 container (not just non-empty: GS2 bytecode contains raw 0x0a bytes,
    so a server sending PLO_NPCWEAPONSCRIPT without PLO_RAWDATA framing
    delivers a truncated blob that only container validation catches --
    fixed in the local GServer-v2 Weapon.cpp, upstream still affected)."""
    start = time.time()
    issues: List[Issue] = []
    c = bot.client

    c.request_weapon_bytecode("qa_gs2weapon")
    _pump(bot, 6.0, until=lambda: "qa_gs2weapon" in c.gs2_bytecode["weapon"])

    blob = c.gs2_bytecode["weapon"].get("qa_gs2weapon")
    header = c.gs2_script_headers.get("qa_gs2weapon", {})
    ok = bool(blob) and header.get("type") == "weapon"
    if not ok:
        issues.append(_issue("HIGH", "gs2", f"weapon bytecode missing: blob={blob and len(blob)} header={header}"))
    funcs = []
    if ok:
        try:
            from reborn_protocol.gs2 import parse_container
            container = parse_container(blob)
            funcs = [f.name for f in container.functions]
        except Exception as e:  # GS2ContainerError or anything else
            ok = False
            issues.append(_issue("HIGH", "gs2",
                                 f"weapon bytecode is not a valid GS2 container "
                                 f"(truncated PLO_NPCWEAPONSCRIPT? unframed-RAWDATA server bug): {e}"))
    return TestResult("gs2_weapon_bytecode", ok, time.time() - start,
                      f"blob={len(blob) if blob else 0}B header_type={header.get('type')} funcs={funcs}", issues)


def test_class_bytecode(bot: GameBot) -> TestResult:
    """Request qa_gs2class's bytecode (PLO_LOADSCRIPT bytecode form, arrives
    via RAWDATA - also validates raw-stream framing stays in sync)."""
    start = time.time()
    issues: List[Issue] = []
    c = bot.client

    c.request_class_bytecode("qa_gs2class")
    _pump(bot, 6.0, until=lambda: "qa_gs2class" in c.gs2_bytecode["class"])

    blob = c.gs2_bytecode["class"].get("qa_gs2class")
    header = c.gs2_script_headers.get("qa_gs2class", {})
    ok = bool(blob) and header.get("type") == "class"
    if not ok:
        issues.append(_issue("HIGH", "gs2", f"class bytecode missing: header={header}"))
    return TestResult("gs2_class_bytecode", ok, time.time() - start,
                      f"blob={len(blob) if blob else 0}B crc={header.get('crc', '')!r}", issues)


def test_gani_bytecode(bot: GameBot) -> TestResult:
    """Request qa_script's gani bytecode: PLO_GANISCRIPT (blob) then
    PLO_LOADGANI (setbackto registration)."""
    start = time.time()
    issues: List[Issue] = []
    c = bot.client

    c.request_gani_bytecode("qa_script")
    _pump(bot, 6.0, until=lambda: "qa_script" in c.gs2_bytecode["gani"]
          and "qa_script" in c.gani_setbackto)

    blob = c.gs2_bytecode["gani"].get("qa_script")
    loadgani = "qa_script" in c.gani_setbackto
    ok = bool(blob) and loadgani
    if not blob:
        issues.append(_issue("HIGH", "gs2", "PLO_GANISCRIPT blob missing"))
    if not loadgani:
        issues.append(_issue("HIGH", "gs2", "PLO_LOADGANI not handled"))
    return TestResult("gs2_gani_bytecode", ok, time.time() - start,
                      f"blob={len(blob) if blob else 0}B loadgani={loadgani}", issues)


def test_framing_after_bytecode(bot: GameBot) -> TestResult:
    """After all the RAWDATA-framed bytecode blobs, normal traffic must still
    round-trip (no stream desync): chat + movement."""
    start = time.time()
    issues: List[Issue] = []
    c = bot.client

    sx = c.player.x
    for _ in range(4):
        c.move(1, 0)
        bot.update(0.1)
    moved = c.player.x != sx

    c.say("tier5 framing check")
    _pump(bot, 0.5)
    ok = moved and c.connected
    if not ok:
        issues.append(_issue("HIGH", "gs2", f"stream desync: moved={moved} connected={c.connected}"))
    return TestResult("gs2_framing_intact", ok, time.time() - start,
                      f"moved={moved} connected={c.connected}", issues)


def test_npc_bytecode_synthetic(bot: GameBot) -> TestResult:
    """Byte-exact synthetic PLO_NPCBYTECODE parse (Level.cpp sendNPCsToPlayer
    writes {GINT3 npc_id}{raw bytecode})."""
    start = time.time()
    issues: List[Issue] = []
    from pyreborn.packets import parse_npc_bytecode

    def gint3(v):
        return bytes([((v >> 14) & 0x7F) + 32, ((v >> 7) & 0x7F) + 32, (v & 0x7F) + 32])

    blob = bytes(range(256))  # all byte values incl 0x0A/0x00 - no loss allowed
    info = parse_npc_bytecode(gint3(4242) + blob)
    ok = info["npc_id"] == 4242 and info["bytecode"] == blob
    if not ok:
        issues.append(_issue("HIGH", "gs2", f"npc bytecode parse mismatch: {info['npc_id']}"))
    return TestResult("gs2_npc_bytecode_synthetic", ok, time.time() - start,
                      f"id={info['npc_id']} blob={len(info['bytecode'])}B", issues)


def run_tier5_tests(host: str = "localhost", port: int = 14900,
                    account: str = "testbot1") -> List[TestResult]:
    """Connect one bot and run the tier 5 (GS2 bytecode transport) suite."""
    results: List[TestResult] = []
    bot = GameBot(account, host, port)
    try:
        if not bot.connect():
            return [TestResult("tier5_connect", False, 0.0,
                               f"{account} failed to connect", [])]
        for test in (test_weapon_bytecode, test_class_bytecode,
                     test_gani_bytecode, test_framing_after_bytecode,
                     test_npc_bytecode_synthetic):
            try:
                results.append(test(bot))
            except Exception as e:  # noqa: BLE001
                results.append(TestResult(test.__name__, False, 0.0, f"Exception: {e}", []))
    finally:
        bot.disconnect()
    return results
