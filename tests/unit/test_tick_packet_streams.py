"""What goes on the wire, in order, for scripted sessions under the tick model.

Each scenario drives the offline game one simulation tick per step with the
same per-tick inputs (held keys, key events, an optional hook that plays a
script's part) and records every outgoing packet at send time, decoded to
(packet, level the server has us on, x, y, direction, ...). The expected
streams were produced by the code before the fixed tick (one simulation step
per 0.05 s frame) and normalised for the one intended difference: position
packets that follow each other inside one tick are merged into one (the
reference sends its props once per tick, TAdventure.cpp:496 sendOutgoing).
Every remaining difference is listed next to its stream in EXPECTED.

The same driver runs at 30, 60 and 144 frames a second
(`test_streams_are_identical_at_30_60_and_144_fps`), so warps, links and seam
crossings are covered by the frame-rate independence check too.

``PYREBORN_STREAM_DUMP=<path>`` writes the recorded streams as JSON (used to
compare against an older tree, which this file also runs in: it falls back to
``frames(dt=0.05)`` where ``game.ticks`` does not exist).
"""
import json
import os
from collections import defaultdict

import pygame
import pytest
from reborn_protocol.props import PLAYER_PROPS, decode_value

import offline_game
from offline_game import key_event
from pyreborn.packets import PacketID

R, L, U, D = pygame.K_RIGHT, pygame.K_LEFT, pygame.K_UP, pygame.K_DOWN
SPACE, ENTER = pygame.K_SPACE, pygame.K_RETURN
LINK = "elsewhere.nw 32 28 2 4 10 12"
POSITION_PROPS = {"sprite", "x", "y", "x2", "y2"}


# == recording ==================================================================

def _props(data):
    out, pos = [], 0
    while pos < len(data):
        pid = data[pos] - 32
        desc = PLAYER_PROPS.get(pid)
        if desc is None:
            out.append(("raw", data[pos:].hex()))
            break
        value, pos = decode_value(desc, data, pos + 1)
        if isinstance(value, float):
            value = round(value, 4)
        out.append((desc.name.lower(), value))
    return out


def decode(pid, data, level):
    if pid == PacketID.PLI_PLAYERPROPS:
        return ["PROPS", level] + [list(p) for p in _props(data)]
    if pid == PacketID.PLI_LEVELWARP:
        return ["LEVELWARP", (data[0] - 32) / 2, (data[1] - 32) / 2,
                data[2:].decode("latin-1")]
    return [_PLI_NAMES.get(pid, str(pid)), level, data.hex()]


_PLI_NAMES = {int(v): k for k, v in sorted(vars(PacketID).items(), reverse=True)
              if k.startswith("PLI_") and isinstance(v, int)}


def is_position(entry):
    return entry[0] == "PROPS" and {p[0] for p in entry[2:]} <= POSITION_PROPS


def merge_positions(tick_packets):
    """Merge position-only PLAYERPROPS that follow each other in one tick:
    the union of their props, the later value winning."""
    out = []
    for entry in tick_packets:
        if out and is_position(entry) and is_position(out[-1]) \
                and entry[1] == out[-1][1]:
            merged = dict((p[0], p[1]) for p in out[-1][2:])
            order = [p[0] for p in out[-1][2:]]
            for name, value in entry[2:]:
                if name not in merged:
                    order.append(name)
                merged[name] = value
            out[-1] = out[-1][:2] + [[n, merged[n]] for n in order]
        else:
            out.append(entry)
    return out


class Recorder:
    """Records sent packets per tick, with the level the server has us on
    (replayed from our own LEVELWARPs, starting at the level we logged in to)."""

    def __init__(self, game):
        self.game = game
        self.loopback = game.client._protocol
        self.level = game.client.current_level_name
        self.mark = len(self.loopback.sent)
        self.ticks = []

    def take(self):
        sent = self.loopback.sent[self.mark:]
        self.mark = len(self.loopback.sent)
        out = []
        for pid, data in sent:
            if pid in (PacketID.PLI_WANTFILE, PacketID.PLI_UPDATEFILE,
                       PacketID.PLI_ADJACENTLEVEL, PacketID.PLI_UPDATEGANI,
                       PacketID.PLI_UPDATESCRIPT, PacketID.PLI_UPDATECLASS):
                continue      # asset/stream requests: order-free
            out.append(decode(pid, data, self.level))
            if pid == PacketID.PLI_LEVELWARP:
                self.level = data[2:].decode("latin-1")
        return out


def held_keys(monkeypatch):
    held = defaultdict(bool)
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: held)
    return held


def run_scenario(make_game, monkeypatch, scenario, fps=None):
    """Drive `scenario` one tick per plan entry; returns per-tick packets
    (merged) and the end state."""
    knobs, plan = scenario["knobs"], scenario["plan"]
    game = make_game(**knobs)
    held = held_keys(monkeypatch)
    if scenario.get("setup"):
        with offline_game._running(game):
            scenario["setup"](game)
    game.frames(1, dt=0.0)                      # settle the login stream
    rec = Recorder(game)
    per_tick = []
    has_ticks = hasattr(game, "ticks") and hasattr(game.clock, "sim_now")
    for index, step in enumerate(plan):
        if not step or isinstance(step[0], int):
            step = (step,)                  # a bare tuple of held keys
        keys, events, hook = (tuple(step) + (None, None))[:3]
        held.clear()
        held.update({k: True for k in keys or ()})
        if hook is not None:
            with offline_game._running(game):
                hook(game, index)
        evs = [key_event(*e) if isinstance(e, tuple) else key_event(e)
               for e in (events or ())]
        if not has_ticks:
            game.frames(1, dt=0.05, events=evs)
        elif fps is None:
            game.ticks(1, events=evs)
        else:
            start = game.clock.tick
            first = True
            while game.clock.tick == start:
                game.frames(1, dt=1.0 / fps, events=evs if first else None)
                first = False
        per_tick.append(merge_positions(rec.take()))
    client = game.client
    return {"ticks": per_tick,
            "client_level": client.current_level_name,
            "server_level": rec.level,
            "end": [round(client.x, 4), round(client.y, 4)]}


# == scenarios ===================================================================

def _wall_above(tx, ty):
    """Open ground with a blocking row at y = 26 (tile 4 blocks)."""
    return 4 if ty == 26 else 0


def _open(tx, ty):
    return 0


def _attach_to_npc(game):
    from pyreborn.attachments import attach
    attach(game.client, game.client.player, 101, send=True)


def _npc_drifts(game, index):
    npc = game.client.npcs[101]
    for axis in ("x", "world_x"):
        if axis in npc:
            npc[axis] = npc[axis] + 0.5


def _scripted_movement(game):
    game.gs1.default_movement = False


def _script_step(game, index):
    game.client.player.x += 0.25      # a script's `playerx += 0.25`


def _setlevel2(at):
    def hook(game, index):
        if index == at:
            game.arrival.pending_warp = ("elsewhere.nw", 10.0, 12.0)
    return hook


def _scenarios():
    seam = dict(gmap=True, tiles=_open)
    return {
        "walk": {"knobs": dict(player_xy=(20.0, 30.0)),
                 "plan": [(R,)] * 4},
        "walk_then_stop": {"knobs": dict(player_xy=(20.0, 30.0)),
                           "plan": [(R,)] * 3 + [()] * 3},
        "direction_only": {"knobs": dict(player_xy=(30.0, 28.0),
                                         tiles=_wall_above),
                           "plan": [(U,)] * 6 + [(L,)] + [(U,)] * 2 + [()]},
        "door_link_plain": {"knobs": dict(player_xy=(30.0, 30.0), links=[LINK],
                                          extra_levels={"elsewhere.nw": None}),
                            "plan": [(R,)] * 4},
        "door_link_gmap": {"knobs": dict(player_xy=(30.0, 30.0), links=[LINK],
                                         extra_levels={"elsewhere.nw": None},
                                         gmap_segment=(1, 1), **seam),
                           "plan": [(R,)] * 4},
        "seam_right": {"knobs": dict(player_xy=(62.0, 30.0), **seam),
                       "plan": [(R,)] * 5},
        "seam_left": {"knobs": dict(player_xy=(1.0, 30.0), gmap_segment=(1, 0),
                                    **seam),
                      "plan": [(L,)] * 5},
        "seam_down": {"knobs": dict(player_xy=(30.0, 62.0), **seam),
                      "plan": [(D,)] * 5},
        "seam_up": {"knobs": dict(player_xy=(30.0, 1.0), gmap_segment=(0, 1),
                                  **seam),
                    "plan": [(U,)] * 5},
        "scripted_seam": {"knobs": dict(player_xy=(62.75, 30.0), **seam),
                          "setup": _scripted_movement,
                          "plan": [((), None, _script_step)] * 6},
        "setlevel2_while_walking": {
            "knobs": dict(player_xy=(20.0, 30.0),
                          extra_levels={"elsewhere.nw": None}),
            "plan": [((R,), None, _setlevel2(2))] * 5},
        "sword_while_walking": {"knobs": dict(player_xy=(20.0, 30.0)),
                                "plan": [(R,), (R,), ((R, SPACE), [SPACE]),
                                         (R,), (R,)]},
        "pickup_while_walking": {
            "knobs": dict(player_xy=(28.0, 30.0),
                          items=[(31.0, 31.0, offline_game.ITEM_GREENRUPEE)]),
            "plan": [(R,)] * 6},
        "chat_while_walking": {
            "knobs": dict(player_xy=(20.0, 30.0)),
            "plan": [(R,), ((R,), [ENTER]), ((R,), [(pygame.K_h, "h")]),
                     ((R,), [(pygame.K_i, "i")]), ((R,), [ENTER]), (R,),
                     (R,)]},
        "attached_to_moving_npc": {
            "knobs": dict(player_xy=(30.0, 30.0),
                          npcs=[dict(offline_game.IMAGE_NPC, x=31.0, y=31.0)]),
            "setup": _attach_to_npc,
            "plan": [((), None, _npc_drifts)] * 3
                    + [((R,), None, _npc_drifts)] * 2
                    + [((), None, _npc_drifts)]},
    }


SCENARIOS = _scenarios()


@pytest.fixture(scope="module")
def dump():
    out = {}
    yield out
    path = os.environ.get("PYREBORN_STREAM_DUMP")
    if path:
        with open(path, "w") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)




# == expected streams ==========================================================
#
# Per scenario: the end position, the level the client (and the server) has
# us on, and per tick the packets, decoded. Identical to the code before the
# tick model (one simulation step per 0.05 s frame, merged as above) except:
#
#   door_link_plain, door_link_gmap: before, the second half-tile step of the
#     tick went out AFTER the PLI_LEVELWARP, as a position on the destination
#     level (10.25, 12). A warp now ends the tick's movement (the reference
#     tests links once per tick, after the whole step, TPlayer.cpp:7375-7379).
#   scripted_seam: before, the script-position announce (GS2
#     _sync_script_position) skipped every other tick (its float throttle);
#     it now sends on every tick the position changed (ticks 1 and 3).

EXPECTED = {
    'attached_to_moving_npc': {
        'end': (34.0, 30.0), 'level': 'fixture.nw',
        'ticks': [
            [('PROPS', 'fixture.nw', ('sprite', 2), ('x2', -1.0), ('y2', -1.0))],
            [('PROPS', 'fixture.nw', ('sprite', 2), ('x2', -1.0), ('y2', -1.0))],
            [('PROPS', 'fixture.nw', ('sprite', 2), ('x2', -1.0), ('y2', -1.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', -0.5), ('y2', -1.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 0.0), ('y2', -1.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 0.0), ('y2', -1.0))],
        ]},
    'chat_while_walking': {
        'end': (22.0, 30.0), 'level': 'fixture.nw',
        'ticks': [
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 20.5), ('y2', 30.0))],
            [],
            [],
            [],
            [('PROPS', 'fixture.nw', ('curchat', 'hi')),
             ('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 21.0), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 21.5), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 22.0), ('y2', 30.0))],
        ]},
    'direction_only': {
        'end': (29.5, 26.0), 'level': 'fixture.nw',
        'ticks': [
            [('PROPS', 'fixture.nw', ('sprite', 0), ('x2', 30.0), ('y2', 27.5))],
            [('PROPS', 'fixture.nw', ('sprite', 0), ('x2', 30.0), ('y2', 27.0))],
            [('PROPS', 'fixture.nw', ('sprite', 0), ('x2', 30.0), ('y2', 26.5))],
            [('PROPS', 'fixture.nw', ('sprite', 0), ('x2', 30.0), ('y2', 26.0))],
            [],
            [],
            [('PROPS', 'fixture.nw', ('sprite', 1), ('x2', 29.5), ('y2', 26.0))],
            [('PROPS', 'fixture.nw', ('sprite', 0), ('x2', 29.5), ('y2', 26.0))],
            [],
            [],
        ]},
    'door_link_gmap': {
        'end': (10.0, 12.0), 'level': 'elsewhere.nw',
        'ticks': [
            [('PROPS', 'fixture_d.nw', ('sprite', 3), ('x2', 30.25), ('y2', 30.0)),
             ('LEVELWARP', 10.0, 12.0, 'elsewhere.nw')],
            [],
            [],
            [],
        ]},
    'door_link_plain': {
        'end': (10.0, 12.0), 'level': 'elsewhere.nw',
        'ticks': [
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 30.25), ('y2', 30.0)),
             ('LEVELWARP', 10.0, 12.0, 'elsewhere.nw')],
            [],
            [],
            [],
        ]},
    'pickup_while_walking': {
        'end': (31.0, 30.0), 'level': 'fixture.nw',
        'ticks': [
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 28.5), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 29.0), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 29.5), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 30.0), ('y2', 30.0))],
            [('PLI_ITEMTAKE', 'fixture.nw', '5e5e'),
             ('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 30.5), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 31.0), ('y2', 30.0))],
        ]},
    'scripted_seam': {
        'end': (64.0, 30.0), 'level': 'fixture_b.nw',
        'ticks': [
            [('PROPS', 'fixture_a.nw', ('sprite', 2), ('x2', 62.75), ('y2', 30.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 2), ('x2', 63.0), ('y2', 30.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 2), ('x2', 63.25), ('y2', 30.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 2), ('x2', 63.5), ('y2', 30.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 2), ('x2', 63.75), ('y2', 30.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 2), ('x2', 0.0), ('y2', 30.0)),
             ('LEVELWARP', 0.0, 30.0, 'fixture_b.nw')],
        ]},
    'seam_down': {
        'end': (30.0, 64.5), 'level': 'fixture_c.nw',
        'ticks': [
            [('PROPS', 'fixture_a.nw', ('sprite', 2), ('x2', 30.0), ('y2', 62.5))],
            [('PROPS', 'fixture_a.nw', ('sprite', 2), ('x2', 30.0), ('y2', 63.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 2), ('x2', 30.0), ('y2', 63.5))],
            [('PROPS', 'fixture_a.nw', ('sprite', 2), ('x2', 30.0), ('y2', 64.0)),
             ('LEVELWARP', 30.0, 0.0, 'fixture_c.nw')],
            [('PROPS', 'fixture_c.nw', ('sprite', 2), ('x2', 30.0), ('y2', 0.5))],
        ]},
    'seam_left': {
        'end': (62.5, 30.0), 'level': 'fixture_a.nw',
        'ticks': [
            [('PROPS', 'fixture_b.nw', ('sprite', 1), ('x2', 0.5), ('y2', 30.0))],
            [('PROPS', 'fixture_b.nw', ('sprite', 1), ('x2', 0.0), ('y2', 30.0))],
            [('PROPS', 'fixture_b.nw', ('sprite', 1), ('x2', -0.25), ('y2', 30.0)),
             ('LEVELWARP', 63.5, 30.0, 'fixture_a.nw'),
             ('PROPS', 'fixture_a.nw', ('sprite', 1), ('x2', 63.5), ('y2', 30.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 1), ('x2', 63.0), ('y2', 30.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 1), ('x2', 62.5), ('y2', 30.0))],
        ]},
    'seam_right': {
        'end': (64.5, 30.0), 'level': 'fixture_b.nw',
        'ticks': [
            [('PROPS', 'fixture_a.nw', ('sprite', 3), ('x2', 62.5), ('y2', 30.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 3), ('x2', 63.0), ('y2', 30.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 3), ('x2', 63.5), ('y2', 30.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 3), ('x2', 64.0), ('y2', 30.0)),
             ('LEVELWARP', 0.0, 30.0, 'fixture_b.nw')],
            [('PROPS', 'fixture_b.nw', ('sprite', 3), ('x2', 0.5), ('y2', 30.0))],
        ]},
    'seam_up': {
        'end': (30.0, 62.5), 'level': 'fixture_a.nw',
        'ticks': [
            [('PROPS', 'fixture_c.nw', ('sprite', 0), ('x2', 30.0), ('y2', 0.5))],
            [('PROPS', 'fixture_c.nw', ('sprite', 0), ('x2', 30.0), ('y2', 0.0))],
            [('PROPS', 'fixture_c.nw', ('sprite', 0), ('x2', 30.0), ('y2', -0.25)),
             ('LEVELWARP', 30.0, 63.5, 'fixture_a.nw'),
             ('PROPS', 'fixture_a.nw', ('sprite', 0), ('x2', 30.0), ('y2', 63.5))],
            [('PROPS', 'fixture_a.nw', ('sprite', 0), ('x2', 30.0), ('y2', 63.0))],
            [('PROPS', 'fixture_a.nw', ('sprite', 0), ('x2', 30.0), ('y2', 62.5))],
        ]},
    'setlevel2_while_walking': {
        'end': (10.0, 12.0), 'level': 'elsewhere.nw',
        'ticks': [
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 20.5), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 21.0), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 21.5), ('y2', 30.0)),
             ('LEVELWARP', 10.0, 12.0, 'elsewhere.nw')],
            [],
            [],
        ]},
    'sword_while_walking': {
        'end': (21.0, 30.0), 'level': 'fixture.nw',
        'ticks': [
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 20.5), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 21.0), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('gani', 'sword'), ('sprite', 3), ('x2', 21.0), ('y2', 30.0)),
             ('PLI_HITOBJECTS', 'fixture.nw', '224f5f')],
            [],
            [],
        ]},
    'walk': {
        'end': (22.0, 30.0), 'level': 'fixture.nw',
        'ticks': [
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 20.5), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 21.0), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 21.5), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 22.0), ('y2', 30.0))],
        ]},
    'walk_then_stop': {
        'end': (21.5, 30.0), 'level': 'fixture.nw',
        'ticks': [
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 20.5), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 21.0), ('y2', 30.0))],
            [('PROPS', 'fixture.nw', ('sprite', 3), ('x2', 21.5), ('y2', 30.0))],
            [],
            [],
            [],
        ]},
}


# == review findings (2026-11-12): what a position packet says is decided when
# == it is sent, never re-read from the player later in the tick =============

def _session(make_game, monkeypatch, name):
    return run_scenario(make_game, monkeypatch, SCENARIOS[name])


def _all(result):
    return [p for tick in result["ticks"] for p in tick]


def test_a_door_link_sends_the_step_onto_it_on_the_old_level(make_game,
                                                             monkeypatch):
    result = _session(make_game, monkeypatch, "door_link_plain")
    first = result["ticks"][0]
    assert first[0] == ["PROPS", "fixture.nw", ["sprite", 3], ["x2", 30.25],
                        ["y2", 30.0]]
    assert first[1] == ["LEVELWARP", 10.0, 12.0, "elsewhere.nw"]
    # The warp ends the tick's movement: nothing after it in that tick.
    assert first[2:] == []


def test_a_door_link_on_a_gmap_segment_sends_no_phantom_seam_crossing(
        make_game, monkeypatch):
    result = _session(make_game, monkeypatch, "door_link_gmap")
    warps = [p for p in _all(result) if p[0] == "LEVELWARP"]
    assert warps == [["LEVELWARP", 10.0, 12.0, "elsewhere.nw"]]
    assert result["ticks"][0][0][:2] == ["PROPS", "fixture_d.nw"]
    assert result["ticks"][0][0][3] == ["x2", 30.25]
    assert result["client_level"] == result["server_level"] == "elsewhere.nw"


def test_a_scripted_seam_crossing_sends_one_levelwarp(make_game, monkeypatch):
    result = _session(make_game, monkeypatch, "scripted_seam")
    warps = [p for p in _all(result) if p[0] == "LEVELWARP"]
    assert warps == [["LEVELWARP", 0.0, 30.0, "fixture_b.nw"]]
    assert result["client_level"] == result["server_level"] == "fixture_b.nw"


def test_a_script_move_in_the_tick_of_a_door_warp_is_sent_the_tick_after(
        make_game, monkeypatch):
    """The warp ended that tick's movement, so the script-position announce
    could not send; it must not record the position as announced, or the
    next tick sees an unchanged snapshot and never sends it."""
    # A link to another segment of the same gmap opens no local level
    # transition, which is the other gate of the script-position announce.
    scenario = {"knobs": dict(player_xy=(30.0, 30.0), gmap=True, tiles=_open,
                              links=["fixture_d.nw 32 28 2 4 10 12"]),
                "plan": [(R,)] + [()] * 4}

    def setup(game):
        original = game.gs2.process_coroutines
        fired = []

        def process_coroutines(dt):
            client = game.client
            if client.tick_movement_ended and not fired:
                fired.append(True)
                client.player.y += 0.5          # a script's `playery += 0.5`
            return original(dt)
        game.gs2.process_coroutines = process_coroutines
    scenario["setup"] = setup
    result = run_scenario(make_game, monkeypatch, scenario)
    warp_tick = result["ticks"][0]
    assert warp_tick[-1][0] == "LEVELWARP"
    later = [p for tick in result["ticks"][1:] for p in tick]
    positions = [p for p in later if p[0] == "PROPS"]
    assert positions, "the script's position never reached the wire"
    assert any(["y2", 12.5] in p[2:]
               for p in positions)


def test_a_script_warp_sends_the_last_step_on_the_old_level(make_game,
                                                           monkeypatch):
    result = _session(make_game, monkeypatch, "setlevel2_while_walking")
    tick = result["ticks"][2]
    assert tick[0] == ["PROPS", "fixture.nw", ["sprite", 3], ["x2", 21.5],
                       ["y2", 30.0]]
    assert tick[1] == ["LEVELWARP", 10.0, 12.0, "elsewhere.nw"]
    assert tick[2:] == []


def test_an_attached_position_is_relative_to_the_npc_when_it_is_sent(
        make_client):
    """sync_attachment runs when send_position is called, as without a tick:
    an NPC that moves later in the same tick does not change what was sent."""
    from pyreborn.attachments import attach
    client = make_client(npcs=[dict(offline_game.IMAGE_NPC, x=31.0, y=31.0)])
    attach(client, client.player, 101, send=True)
    mark = len(client._protocol.sent)
    with client.movement_batch():
        client.send_position()
        npc = client.npcs[101]
        for axis in ("x", "world_x"):
            if axis in npc:
                npc[axis] = npc[axis] + 3.0
    sent = [decode(pid, data, "")[2:] for pid, data in client._protocol.sent[mark:]
            if pid == PacketID.PLI_PLAYERPROPS]
    assert sent == [[["sprite", client.player.direction], ["x2", -1.0],
                     ["y2", -1.0]]]


# == the streams ===================================================================

def as_expected(result):
    """A recorded run in EXPECTED's shape (tuples)."""
    return {"end": tuple(result["end"]), "level": result["client_level"],
            "ticks": [[tuple(tuple(p) if isinstance(p, list) else p
                             for p in entry) for entry in tick]
                      for tick in result["ticks"]]}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_stream(make_game, monkeypatch, dump, name):
    result = run_scenario(make_game, monkeypatch, SCENARIOS[name])
    dump[name] = result
    assert result["client_level"] == result["server_level"]
    assert as_expected(result) == EXPECTED[name]


FPS_SCENARIOS = ["door_link_plain", "door_link_gmap", "seam_right",
                 "seam_left", "seam_up", "seam_down", "scripted_seam",
                 "setlevel2_while_walking", "sword_while_walking",
                 "chat_while_walking", "attached_to_moving_npc"]


@pytest.mark.parametrize("name", FPS_SCENARIOS)
def test_streams_are_identical_at_30_60_and_144_fps(make_game, monkeypatch,
                                                     name):
    """Warps, links and seam crossings send the same packets in the same
    ticks whatever the frame rate."""
    runs = {fps: as_expected(run_scenario(make_game, monkeypatch,
                                          SCENARIOS[name], fps=fps))
            for fps in (30, 60, 144)}
    assert runs[30] == runs[60] == runs[144] == EXPECTED[name]


def _sent_since(client, mark):
    return [decode(pid, data, "")
            for pid, data in client._protocol.sent[mark:]]


def test_positions_in_one_batch_merge_prop_by_prop_later_value_wins(
        make_client):
    from pyreborn.packets import build_movement
    client = make_client(player_xy=(20.0, 30.0))
    mark = len(client._protocol.sent)
    with client.movement_batch():
        client._send_position_props(build_movement(20.5, 30.0, 3,
                                                   use_new_format=True))
        # A packet with a subset (X2 only) and one with Y2 first: the union.
        client._send_position_props(bytes([78 + 32]) + build_movement(
            21.0, 30.0, 3, use_new_format=True)[3:5])
        client._send_position_props(build_movement(21.0, 29.5, 0,
                                                   use_new_format=True))
        assert client._protocol.sent[mark:] == []
    assert _sent_since(client, mark) == [
        ["PROPS", "", ["sprite", 0], ["x2", 21.0], ["y2", 29.5]]]


def test_any_other_packet_sends_the_held_position_first(make_client):
    client = make_client(player_xy=(20.0, 30.0))
    mark = len(client._protocol.sent)
    with client.movement_batch():
        client.move(1, 0)
        client.say("hi")
        client.move(1, 0)
    kinds = [entry[0] for entry in _sent_since(client, mark)]
    assert kinds == ["PROPS", "PLI_TOALL", "PROPS"]


def test_a_warp_ends_the_batch_movement(make_client):
    client = make_client(player_xy=(20.0, 30.0),
                         extra_levels={"elsewhere.nw": None})
    mark = len(client._protocol.sent)
    with client.movement_batch():
        assert client.move(1, 0)
        assert client.warp_to_level("elsewhere.nw", 10.0, 12.0)
        assert not client.move(1, 0)
        assert not client.send_position()
    sent = _sent_since(client, mark)
    assert [entry[0] for entry in sent] == ["PROPS", "LEVELWARP"]
    assert sent[0][3] == ["x2", 20.25]
