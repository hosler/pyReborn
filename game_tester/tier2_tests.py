"""
tier2_tests - Entity family (bomb/arrow/horse/firespy) protocol-parity tests.

Exercises the pyReborn Tier 2a/2b additions: bot0 places/fires/mounts an
entity, bot1 (on the same level) must see it appear via the matching
on_* callback, and removal (BOMBDEL/HORSEDEL) must clear it again.

Run: python -m game_tester --tier2
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
import time
from typing import List, Tuple

from pyreborn.packets import PacketID, parse_player_props

from .game_bot import GameBot, Issue
from .reporter import TestResult
from .spar_fixture import SPAR_LEVEL, spar_fixture_ready


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
        if 0 < bot1.client.player.hearts < 1.0:
            # The previous run's kill test persists bot1 at 0.5 hearts on
            # pygserver. Heal first: hearts are client-authoritative.
            bot1.client.send_hearts(bot1.client.player.max_hearts)
            _pump(bot0, bot1, 0.5)
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


def test_bomb_kill_credits_killer(bot0: GameBot, bot1: GameBot) -> TestResult:
    """A fatal local bomb hit must claim its owner and update their kills."""
    start = time.time()
    issues: List[Issue] = []
    # Let the preceding damage test's hurt immunity expire.
    _pump(bot0, bot1, 2.1)
    if bot1.client.player.no_hurt() or not bot1.client.send_hearts(0.5):
        return TestResult("bomb_kill_credits_killer", False, time.time() - start,
                          "bot1 could not be prepared with 0.5 hearts",
                          [_issue("MEDIUM", "combat", "bomb kill precondition failed")])
    before = bot0.client.player.kills
    bot0.client.put_bomb(bot1.client.x, bot1.client.y, power=1, timer_ms=1500)
    _pump(bot0, bot1, 6.0, until=lambda: bot1.client.player.hearts <= 0)
    died = bot1.client.player.hearts <= 0
    _pump(bot0, bot1, 5.0, until=lambda: bot0.client.player.kills > before)
    after = bot0.client.player.kills
    credited = after == before + 1
    if not died:
        issues.append(_issue("HIGH", "combat", "bomb did not kill bot1"))
    if not credited:
        issues.append(_issue("HIGH", "combat",
                             f"bomb killer credit incorrect: {before} -> {after}"))
    return TestResult("bomb_kill_credits_killer", died and credited,
                      time.time() - start,
                      f"victim_died={died}, killer kills {before} -> {after}", issues)


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

    With an NPC server, assert that the client set is not relayed:
    GServer-v2 PlayerClientPackets.cpp msgPLI_FLAGSET keeps server.* local,
    and Server.cpp:1935 broadcasts only serverr.* changes in that mode."""
    start = time.time()
    issues: List[Issue] = []
    flag = "server.qa_tier2_flag"

    if bot0.client.has_npc_server:
        bot0.client.set_flag(flag, "1")
        _pump(bot0, bot1, 2.0)
        not_relayed = flag not in bot1.client.global_flags
        if not not_relayed:
            issues.append(_issue("HIGH", "flag",
                                 "npc-server mode: client server.* set relayed to bot1"))
        bot0.client.del_flag(flag)
        details = ("npc-server mode: client server.* set correctly not relayed"
                   if not_relayed else "npc-server mode: client server.* set incorrectly relayed")
        return TestResult("flagdel_relay", not_relayed, time.time() - start,
                          details, issues)

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


def _spar_rating_test(host: str, port: int, accounts: Tuple[str, str],
                      same_ip: bool) -> TestResult:
    name = "spar_same_ip_no_rating_change" if same_ip else "spar_rating_updates"
    start = time.time()

    def skip(reason):
        return TestResult(name, False, time.time() - start, reason, skipped=True)

    if host not in ("localhost", "127.0.0.1"):
        return skip(f"source-IP spar QA needs an IPv4 loopback host, got {host}")
    source = "127.0.0.1" if same_ip else "127.0.0.2"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((source, 0))
    except OSError as exc:
        return skip(f"cannot bind source address {source}: {exc}")

    from .local_world import local_world_for
    world = local_world_for(host, port)
    levels_dir = (world.world_dir if world is not None else
                  Path(os.environ.get("PYGSERVER_LEVELS_DIR",
                       Path(__file__).resolve().parents[2] / "pygserver" / "levels")))
    # The arena NPC registers at server startup, so writing the level mid-run
    # cannot make this test pass. `qa_server start/run` provisions it before
    # launch and removes it on stop; a test that wrote it itself would only
    # leave it behind.
    if not spar_fixture_ready(levels_dir):
        return skip(f"{levels_dir / SPAR_LEVEL} is absent or stale; run this "
                    "through `qa_server run`, which provisions it at startup "
                    "and removes it on stop")

    # Dedicated accounts avoid racing the preceding suite's disconnect saves.
    # Reset before login, so reruns start at the server's 1500/350 defaults.
    from .test_scenarios import reset_account_position
    suffix = "_spar_same" if same_ip else "_spar"
    a, b = (account + suffix for account in accounts)
    reset_account_position(a)
    reset_account_position(b)
    bot0 = GameBot(a, host, port, source_address="127.0.0.1")
    bot1 = GameBot(b, host, port, source_address=source)
    bots = (bot0, bot1)
    ratings = [[], []]

    def rating(bot):
        return (bot.client.player.rating, bot.client.player.rating_deviation)

    def arena_ready(bot):
        client = bot.client
        return (client._current_level_name == SPAR_LEVEL
                and client._tiles_level_name == SPAR_LEVEL and bool(client.tiles)
                and any(npc.get('_level') == SPAR_LEVEL
                        and npc.get('script', '').lstrip().startswith('sparringzone')
                        for npc in client.npcs.values()))

    def sees_killer():
        # The client never learns its own player id (player.id stays 0), so
        # find the killer in the victim's roster by name. pygserver's level
        # entry props carry the nickname (the account name by default) but
        # not the account prop.
        return any(isinstance(info, dict)
                   and a in (info.get('account'), info.get('nickname'))
                   for info in bot1.client.players.values())

    try:
        if not bot0.connect() or not bot1.connect():
            return TestResult(name, False, time.time() - start,
                              f"spar login failed: {[bot.get_issues() for bot in bots]}")
        for bot, x in ((bot0, 26.0), (bot1, 30.0)):
            bot.client.warp_to_level(SPAR_LEVEL, x, 30.0)
        _pump(bot0, bot1, 8.0,
              until=lambda: all(arena_ready(bot) for bot in bots)
              and sees_killer())
        if not all(arena_ready(bot) for bot in bots):
            return skip(f"{SPAR_LEVEL} board/sparringzone NPC not received by both bots; "
                        "check the served world and restart to register the fixture NPC")
        if not sees_killer():
            return TestResult(name, False, time.time() - start,
                              "victim never received killer's player ID")
        before = [rating(bot) for bot in bots]
        if before != [(1500, 350), (1500, 350)]:
            return TestResult(name, False, time.time() - start,
                              f"rating fixture was not reset: {before}; check account directory")

        for i, bot in enumerate(bots):
            def record(data, i=i):
                props = parse_player_props(data)
                if 'rating' in props:
                    ratings[i].append(props['rating'])
            bot.client.on_packet[PacketID.PLO_PLAYERPROPS] = record

        # Same fatal local bomb/CLAIMPKER path as bomb_kill_credits_killer.
        _pump(bot0, bot1, 2.1)
        if bot1.client.player.no_hurt() or not bot1.client.send_hearts(0.5):
            return TestResult(name, False, time.time() - start,
                              "victim could not be prepared with 0.5 hearts")
        kills = bot0.client.player.kills
        deaths = bot1.client.player.deaths
        bot0.client.put_bomb(bot1.client.x, bot1.client.y, power=1, timer_ms=1500)
        _pump(bot0, bot1, 6.0, until=lambda: bot1.client.player.hearts <= 0)
        died = bot1.client.player.hearts <= 0
        # The victim's client names the killer and sends CLAIMPKER in the same
        # step the fatal hit lands, so this is the evidence that a fight
        # happened. The same-IP case has no server reply to wait for, and
        # without this a run with no fight at all would read as "no rating
        # change".
        hit_landed = bool(died and bot1.client._pker_claimed)
        # The real event is the rating change on the killer and the victim. A
        # death counter is no signal here: the reference server counts no
        # death and drops no item in a sparring zone (reference PlayerProps.cpp
        # :576-580 on origin/beta4; :567-571 in the local-beta4 checkout), so
        # `deaths` never moves. The same-IP case has no event to wait for; the
        # window below is its observation time.
        if not same_ip:
            _pump(bot0, bot1, 5.0, until=lambda: all(ratings))
        # Observe late credit, especially in the negative case.
        _pump(bot0, bot1, 2.0)
        after = [rating(bot) for bot in bots]
        deaths_unchanged = bot1.client.player.deaths == deaths    # not counted in a spar zone
        no_kill = bot0.client.player.kills == kills
        if same_ip:
            rating_ok = after == before and not any(ratings)
        else:
            rating_ok = (all(ratings) and after[0][0] > before[0][0]
                         and after[1][0] < before[1][0]
                         and all(0 < value[1] < old[1]
                                 for value, old in zip(after, before)))
        passed = bool(hit_landed and deaths_unchanged and no_kill and rating_ok)
        details = (f"sources=127.0.0.1/{source}, ratings {before} -> {after}, "
                   f"RATING packets={ratings}, victim_died={died}, hit_landed={hit_landed}, "
                   f"deaths {deaths}->{bot1.client.player.deaths}, "
                   f"killer kills {kills}->{bot0.client.player.kills}")
        issues = [] if passed else [_issue("HIGH", "spar", details)]
        return TestResult(name, passed, time.time() - start, details, issues)
    finally:
        for bot in bots:
            bot.disconnect()


def test_spar_rating_updates(host="localhost", port=14900,
                             accounts=("testbot1", "testbot2")) -> TestResult:
    """Different loopback source IPs must receive opposite rating changes."""
    return _spar_rating_test(host, port, accounts, same_ip=False)


def test_spar_same_ip_no_rating_change(host="localhost", port=14900,
                                      accounts=("testbot1", "testbot2")) -> TestResult:
    """The faithful same-IP guard must suppress both RATING updates."""
    return _spar_rating_test(host, port, accounts, same_ip=True)


def run_tier2_tests(host: str = "localhost", port: int = 14900,
                    accounts: Tuple[str, str] = ("testbot1", "testbot2")
                    ) -> List[TestResult]:
    """Connect bots and run the tier 2 (entity family relay) suite."""
    results: List[TestResult] = []
    a, b = accounts

    # pygserver persists the bomb bag. Four bombs per run drained testbot1
    # to 0 over a few runs against one server and the chain test's second
    # put_bomb silently refused to fire. Restock like the base suite does.
    from .test_scenarios import reset_account_position
    reset_account_position(a)
    reset_account_position(b)

    bot0 = GameBot(a, host, port)
    bot1 = GameBot(b, host, port)
    try:
        if not bot0.connect():
            return [TestResult("tier2_connect", False, 0.0, f"{a} failed to connect", [])]
        if not bot1.connect():
            return [TestResult("tier2_multi_connect", False, 0.0, f"{b} failed to connect", [])]

        for test in (test_bomb_relay, test_bomb_damage, test_bomb_chain,
                     test_bomb_kill_credits_killer, test_arrow_relay,
                     test_horse_relay, test_flagdel_relay):
            try:
                results.append(test(bot0, bot1))
            except Exception as e:  # noqa: BLE001
                results.append(TestResult(test.__name__, False, 0.0, f"Exception: {e}", []))
    finally:
        bot0.disconnect()
        bot1.disconnect()

    for test in (test_spar_rating_updates, test_spar_same_ip_no_rating_change):
        try:
            results.append(test(host, port, accounts))
        except Exception as exc:
            results.append(TestResult(test.__name__[5:], False,
                                      0.0, f"Exception: {exc}"))
    return results
