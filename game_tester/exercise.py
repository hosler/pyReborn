"""
exercise - A broad battery of client actions to provoke server packets.

Used by the packet-coverage harness. Each step is best-effort: a failure is
recorded as a note and the battery continues, so a single missing fixture does
not zero out the rest of the coverage run.

Behaviors are chosen to make the server emit as many distinct PLO types as
possible: login bookkeeping, level streaming, chat, combat, items/chests,
files, flags, trigger actions, and social packets (which need a second player).
"""

from __future__ import annotations

import time
from typing import List

from .game_bot import GameBot


def _step(notes: List[str], name: str, fn, verbose: bool):
    """Run one battery step, recording failures as notes instead of raising."""
    try:
        if verbose:
            print(f"  [exercise] {name}")
        fn()
    except Exception as e:  # noqa: BLE001 - best-effort battery
        notes.append(f"{name}: {type(e).__name__}: {e}")


def run_exercise_battery(bot: GameBot, verbose: bool = True) -> List[str]:
    """Drive `bot` through a wide range of actions. Returns failure notes."""
    notes: List[str] = []
    c = bot.client
    start_level = c._current_level_name or "onlinestartlocal.nw"

    # --- movement & basic props -------------------------------------------
    def _move():
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            bot.move(dx, dy)
        c.send_position()
    _step(notes, "movement", _move, verbose)

    _step(notes, "animation", lambda: (c.set_animation("idle"), bot.update(0.2)), verbose)
    _step(notes, "hearts", lambda: (c.send_hearts(3.0), bot.update(0.2)), verbose)

    # --- chat -------------------------------------------------------------
    _step(notes, "chat_toall", lambda: (c.say("coverage run"), bot.update(0.3)), verbose)
    _step(notes, "chat_bubble",
          lambda: (c.send_level_chat("bubble"), bot.update(0.3)), verbose)

    # --- combat / level effects -------------------------------------------
    _step(notes, "sword", lambda: (c.sword_attack(2), bot.update(0.3)), verbose)
    _step(notes, "bomb", lambda: (c.drop_bomb(1), bot.update(0.6)), verbose)
    _step(notes, "shoot", lambda: (c.shoot(2), bot.update(0.3)), verbose)
    _step(notes, "triggeraction",
          lambda: (c.triggeraction("gr.appletree", c.x, c.y), bot.update(0.3)), verbose)

    # --- flags ------------------------------------------------------------
    _step(notes, "flag_set",
          lambda: (c.set_flag("qa_cov", "1"), bot.update(0.2)), verbose)
    _step(notes, "flag_del",
          lambda: (c.del_flag("qa_cov"), bot.update(0.2)), verbose)

    # --- files ------------------------------------------------------------
    def _file_ok():
        c.request_file("onlinestartlocal.nw")
        deadline = time.time() + 6.0
        while time.time() < deadline and not c.has_file("onlinestartlocal.nw"):
            bot.update(0.1)
    _step(notes, "file_request", _file_ok, verbose)

    def _file_missing():
        c.request_file("definitely_missing_qa.gif")
        deadline = time.time() + 3.0
        while time.time() < deadline and not c.did_file_fail("definitely_missing_qa.gif"):
            bot.update(0.1)
    _step(notes, "file_missing", _file_missing, verbose)

    # --- level streaming: warp to the QA fixture and back -----------------
    def _warp_fixture():
        c.warp_to_level("qa_testlevel.nw", 30, 30)
        deadline = time.time() + 5.0
        while time.time() < deadline and c._current_level_name != "qa_testlevel.nw":
            bot.update(0.1)
        bot.update(0.6)
        # Hurt the fixture baddy (baddies respawn, so no persistent state).
        # NOTE: deliberately do NOT open the chest here - opened chests persist
        # per-account and would break the chest-dependent level_parsing QA test.
        for bid in list(c.baddies.keys()):
            c.hurt_baddy(bid, 1.0)
            bot.update(0.2)
    _step(notes, "warp_fixture", _warp_fixture, verbose)

    def _request_adjacent():
        c.request_adjacent_levels()
        bot.update(0.5)
    _step(notes, "request_adjacent", _request_adjacent, verbose)

    def _warp_back():
        c.warp_to_level(start_level, 30, 30)
        deadline = time.time() + 5.0
        while time.time() < deadline and c._current_level_name != start_level:
            bot.update(0.1)
        bot.update(0.4)
    _step(notes, "warp_back", _warp_back, verbose)

    # --- social packets: need a second player -----------------------------
    _step(notes, "social", lambda: _social_battery(bot, notes, verbose), verbose)

    return notes


def _social_battery(bot: GameBot, notes: List[str], verbose: bool):
    """Spawn a peer so the server emits OTHERPLPROPS / HURTPLAYER / PM to `bot`."""
    peer_name = "testbot2" if bot.name != "testbot2" else "testbot1"
    peer = GameBot(peer_name, bot.host, bot.port)
    if not peer.connect():
        notes.append("social: peer failed to connect")
        return
    try:
        c = bot.client
        # Put both in the same level so they see each other.
        level = c._current_level_name or "onlinestartlocal.nw"
        peer.client.warp_to_level(level, 32, 32)
        for _ in range(10):
            peer.update(0.1)
            bot.update(0.1)
        # Peer moves -> server sends OTHERPLPROPS to bot.
        for dx, dy in ((1, 0), (0, 1), (-1, 0)):
            peer.move(dx, dy)
            peer.client.send_position()
            bot.update(0.2)
        # Peer chats -> TOALL relay to bot.
        peer.client.say("peer hello")
        bot.update(0.3)
        # bot attacks peer -> HURTPLAYER round trip.
        pid = c.get_player_id_by_account(peer_name)
        if pid:
            c.attack_player(pid, 0.5)
            bot.update(0.3)
            # peer PMs bot.
            bpid = peer.client.get_player_id_by_account(bot.name)
            if bpid:
                peer.client.send_pm(bpid, "pm from peer")
                bot.update(0.3)
        else:
            notes.append("social: could not resolve peer player id")
    finally:
        peer.disconnect()
