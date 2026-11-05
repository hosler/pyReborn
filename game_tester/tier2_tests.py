"""
tier2_tests - Entity family (bomb/arrow/horse/firespy) protocol-parity tests.

Exercises the pyReborn Tier 2a/2b additions: bot0 places/fires/mounts an
entity, bot1 (on the same level) must see it appear via the matching
on_* callback, and removal (BOMBDEL/HORSEDEL) must clear it again.

Run: python -m game_tester --tier2
"""

from __future__ import annotations

import time
from typing import List, Tuple

from pyreborn.packets import PacketID

from .game_bot import GameBot, Issue
from .reporter import TestResult


def _issue(sev: str, cat: str, desc: str) -> Issue:
    return Issue(timestamp=time.time(), severity=sev, category=cat, description=desc)


def _pump(bot0: GameBot, bot1: GameBot, seconds: float, until=None):
    deadline = time.time() + seconds
    while time.time() < deadline:
        bot0.update(0.05)
        bot1.update(0.05)
        if until is not None and until():
            break


def test_bomb_relay(bot0: GameBot, bot1: GameBot) -> TestResult:
    """bot0 places a bomb. Bot1 must see it via on_bomb_add and self.bombs,
    then see it removed via on_bomb_del after bot0 detonates/removes it.

    Only fully testable without an NPC server: with one, msgPLI_BOMBADD takes
    the level->addBombFromClient path instead of relaying PLO_BOMBADD (see
    PlayerClientPackets.cpp), so the add-relay assertion is skipped there
    (bomb_del still relays unconditionally and is asserted either way)."""
    start = time.time()
    issues: List[Issue] = []
    seen = {}
    bot1.client.on_bomb_add = lambda info: seen.setdefault("add", info)
    bot1.client.on_bomb_del = lambda x, y: seen.setdefault("del", (x, y))
    npcserver = bot0.client.has_npc_server

    x, y = 40.0, 40.0
    bot0.client.put_bomb(x, y, power=1)
    _pump(bot0, bot1, 2.0 if npcserver else 5.0, until=lambda: "add" in seen)

    if npcserver:
        add_ok = True  # server-managed bombs: no PLO_BOMBADD relay by design
    else:
        add_ok = ("add" in seen and abs(seen["add"]["x"] - x) < 0.01
                  and abs(seen["add"]["y"] - y) < 0.01)
        if not add_ok:
            issues.append(_issue("HIGH", "entity",
                                 f"bomb_add not relayed/matched: {seen.get('add')}"))

    bot0.client.remove_bomb(x, y)
    _pump(bot0, bot1, 5.0, until=lambda: "del" in seen)
    del_ok = "del" in seen
    if not del_ok:
        issues.append(_issue("HIGH", "entity", "bomb_del not relayed"))

    bot1.client.on_bomb_add = None
    bot1.client.on_bomb_del = None

    passed = add_ok and del_ok
    details = (f"add={'skipped (npcserver)' if npcserver else seen.get('add')} "
               f"del={seen.get('del')}")
    return TestResult("bomb_relay", passed, time.time() - start, details, issues)


def _bomb_count(bot: GameBot) -> int:
    """Simulated bombs bot holds across every level bucket."""
    return sum(len(bucket) for bucket in bot.client.bombs.values())


def test_bomb_damage(bot0: GameBot, bot1: GameBot) -> TestResult:
    """bot0 bombs the tile bot1 stands on. The reference client owns the fuse
    and the damage (TServerLevel.cpp:1310-1337, TExplosion.cpp:48-96), so after
    the fuse bot1's own simulation must drop its hearts by 0.5 with NO
    PLO_HURTPLAYER on the wire."""
    start = time.time()
    issues: List[Issue] = []
    hurt_packets: List[bytes] = []
    hurt_callbacks: List[tuple] = []
    previous_on_hurt = bot1.client.on_hurt

    def record_hurt(*args):
        hurt_callbacks.append(args)
        if previous_on_hurt:
            previous_on_hurt(*args)

    bot1.client.on_packet[PacketID.PLO_HURTPLAYER] = hurt_packets.append
    bot1.client.on_hurt = record_hurt
    try:
        _pump(bot0, bot1, 1.0)
        if bot1.client.player.no_hurt() or bot1.client.player.hearts < 1.0:
            return TestResult("bomb_damage", False, time.time() - start,
                              f"bot1 cannot be hurt (hearts={bot1.client.player.hearts})",
                              [_issue("MEDIUM", "combat", "bomb_damage precondition failed")])
        before = bot1.client.player.hearts
        x, y = bot1.client.x, bot1.client.y
        bot0.client.put_bomb(x, y, power=1, timer_ms=1500)
        _pump(bot0, bot1, 6.0,
              until=lambda: bot1.client.player.hearts < before)
        _pump(bot0, bot1, 0.5)            # a late server hurt would show up here
    finally:
        bot1.client.on_packet.pop(PacketID.PLO_HURTPLAYER, None)
        bot1.client.on_hurt = previous_on_hurt

    after = bot1.client.player.hearts
    dropped = abs((before - after) - 0.5) < 1e-6
    no_server_hurt = not hurt_packets
    if not dropped:
        issues.append(_issue("HIGH", "combat",
                             f"bomb did not cost bot1 0.5 hearts: {before} -> {after}"))
    if not no_server_hurt:
        issues.append(_issue("HIGH", "combat",
                             f"server still sent PLO_HURTPLAYER x{len(hurt_packets)}"))
    return TestResult("bomb_damage", dropped and no_server_hurt, time.time() - start,
                      f"hearts {before} -> {after}, hurt_packets={len(hurt_packets)}, "
                      f"on_hurt={hurt_callbacks[:1]}", issues)


def test_bomb_chain(bot0: GameBot, bot1: GameBot) -> TestResult:
    """Two bombs: the second has a long fuse and sits on the first one's arm.
    Chain detonation is local (TServerLevel.cpp:1494-1500), so right after the
    first fuse bot1 must have dropped both from its registry."""
    start = time.time()
    issues: List[Issue] = []
    ax, ay, bx, by = 44.0, 44.0, 46.0, 44.0
    base = _bomb_count(bot1)
    bot0.client.put_bomb(ax, ay, power=1, timer_ms=1500)
    bot0.client.put_bomb(bx, by, power=1, timer_ms=30000)
    _pump(bot0, bot1, 5.0, until=lambda: _bomb_count(bot1) >= base + 2)
    both_seen = _bomb_count(bot1) >= base + 2
    if not both_seen:
        issues.append(_issue("HIGH", "entity", "bot1 never saw both bombs"))

    # Wait out the first fuse only; the second would live another ~30s.
    _pump(bot0, bot1, 4.0, until=lambda: _bomb_count(bot1) <= base)
    _pump(bot0, bot1, 0.3)
    left = _bomb_count(bot1) - base
    chained = both_seen and left <= 0
    if both_seen and not chained:
        issues.append(_issue("HIGH", "combat",
                             f"{left} bomb(s) survived the first fuse: no chain detonation"))
    bot0.client.remove_bomb(bx, by)       # leave nothing behind on the server
    return TestResult("bomb_chain", chained, time.time() - start,
                      f"both_seen={both_seen} left_in_bot1_registry={left}", issues)


def test_arrow_relay(bot0: GameBot, bot1: GameBot) -> TestResult:
    """bot0 fires an arrow. Bot1 must see it via on_arrow_add."""
    start = time.time()
    issues: List[Issue] = []
    seen = {}
    bot1.client.on_arrow_add = lambda info: seen.setdefault("add", info)

    x, y = 41.0, 41.0
    bot0.client.shoot_arrow(x, y, direction=2, power=2)
    _pump(bot0, bot1, 5.0, until=lambda: "add" in seen)

    ok = "add" in seen and abs(seen["add"]["x"] - x) < 0.01 and seen["add"].get("power") == 2
    if not ok:
        issues.append(_issue("HIGH", "entity", f"arrow_add not relayed/matched: {seen.get('add')}"))

    bot1.client.on_arrow_add = None
    return TestResult("arrow_relay", ok, time.time() - start, f"add={seen.get('add')}", issues)


def test_horse_relay(bot0: GameBot, bot1: GameBot) -> TestResult:
    """bot0 mounts a horse. Bot1 must see it via on_horse_add, then see it
    removed via on_horse_del."""
    start = time.time()
    issues: List[Issue] = []
    seen = {}
    bot1.client.on_horse_add = lambda info: seen.setdefault("add", info)
    bot1.client.on_horse_del = lambda x, y: seen.setdefault("del", (x, y))

    x, y = 42.0, 42.0
    bot0.client.mount_horse(x, y, image="horse.png", direction=1)
    _pump(bot0, bot1, 5.0, until=lambda: "add" in seen)

    add_ok = "add" in seen and abs(seen["add"]["x"] - x) < 0.01 and seen["add"]["image"] == "horse.png"
    if not add_ok:
        issues.append(_issue("HIGH", "entity", f"horse_add not relayed/matched: {seen.get('add')}"))

    bot0.client.remove_horse(x, y)
    _pump(bot0, bot1, 5.0, until=lambda: "del" in seen)
    del_ok = "del" in seen
    if not del_ok:
        issues.append(_issue("HIGH", "entity", "horse_del not relayed"))

    bot1.client.on_horse_add = None
    bot1.client.on_horse_del = None

    passed = add_ok and del_ok
    return TestResult("horse_relay", passed, time.time() - start,
                      f"add={seen.get('add')} del={seen.get('del')}", issues)


def test_flagdel_relay(bot0: GameBot, bot1: GameBot) -> TestResult:
    """bot0 sets then deletes a server.* flag. Bot1 must see both the set
    (existing PLO_FLAGSET coverage) and the delete (PLO_FLAGDEL, new).

    Only testable without an NPC server: with one, clients cannot set server.*
    flags at all (msgPLI_FLAGSET: "If we have an npc-server, clients cannot set
    server flags"), so the whole test is skipped there."""
    start = time.time()
    issues: List[Issue] = []
    flag = "server.qa_tier2_flag"

    if bot0.client.has_npc_server:
        return TestResult("flagdel_relay", True, time.time() - start,
                          "skipped: npc-server active, clients can't set server.* flags",
                          issues)

    bot0.client.set_flag(flag, "1")
    _pump(bot0, bot1, 5.0, until=lambda: flag in bot1.client.global_flags)
    set_ok = flag in bot1.client.global_flags
    if not set_ok:
        issues.append(_issue("HIGH", "flag", "flag set not relayed to bot1"))

    bot0.client.del_flag(flag)
    _pump(bot0, bot1, 5.0, until=lambda: flag not in bot1.client.global_flags)
    del_ok = flag not in bot1.client.global_flags
    if not del_ok:
        issues.append(_issue("HIGH", "flag", "PLO_FLAGDEL not relayed/handled"))

    passed = set_ok and del_ok
    return TestResult("flagdel_relay", passed, time.time() - start,
                      f"set_ok={set_ok} del_ok={del_ok}", issues)


def run_tier2_tests(host: str = "localhost", port: int = 14900,
                    accounts: Tuple[str, str] = ("testbot1", "testbot2")
                    ) -> List[TestResult]:
    """Connect bots and run the tier 2 (entity family relay) suite."""
    results: List[TestResult] = []
    a, b = accounts

    bot0 = GameBot(a, host, port)
    bot1 = GameBot(b, host, port)
    try:
        if not bot0.connect():
            return [TestResult("tier2_connect", False, 0.0, f"{a} failed to connect", [])]
        if not bot1.connect():
            return [TestResult("tier2_multi_connect", False, 0.0, f"{b} failed to connect", [])]

        for test in (test_bomb_relay, test_bomb_damage, test_bomb_chain, test_arrow_relay, test_horse_relay, test_flagdel_relay):
            try:
                results.append(test(bot0, bot1))
            except Exception as e:  # noqa: BLE001
                results.append(TestResult(test.__name__, False, 0.0, f"Exception: {e}", []))
    finally:
        bot0.disconnect()
        bot1.disconnect()

    return results
