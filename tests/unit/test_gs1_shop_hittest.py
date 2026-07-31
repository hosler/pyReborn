"""`testnpc`/`testplayer` and `mousex`/`mousey` — the two builtins classic
Bomber's shop ("Dryden's Wares") is built out of, and the shop itself.

Both were unimplemented on this client, and each broke the shop in its own way:

* `testnpc` fell through to UNSET (0.0), so the counter's
  `callnpc testnpc(56,26),GrabItemList,#v(this.shopmode)` ran npcs[0] instead
  of the item catalogue — `clientr.Shop_n/Shop_i/Shop_p` stayed empty and the
  menu drew one phantom row priced 0.
* `mousex`/`mousey` answered 0, which turns the counter's screen<->world
  conversion `mousescreenx - (mousex - playerx) * 16 + 24` into
  `cursor + playerx * 16 + 24` — about +(736, 584) pixels at the shop's
  position, i.e. the whole panel off the canvas.

The replay at the bottom drives the real scripts (bomber_lobby_shop fixture)
and pins both: real item names in `clientr.Shop_n` AND every GUI-band layer
inside the canvas. Either builtin regressing fails it.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

pygame.init()
pygame.display.set_mode((64, 64))   # _feed_gs1_input reads the mouse

from pyreborn import Client
from pyreborn.game.camera import Camera2D
from pyreborn.game.input import InputMixin
from pyreborn.gs1_client import ClientGS1

from .bomber_lobby_shop_fixture import (COUNTER_ID, CATALOGUE_ID, load_capture,
                                        load_scripts)

#: the canvas the live run that found this bug was measured on
CANVAS_W, CANVAS_H = 1270, 771


class _SentRecorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def _client(level="bomblobby.nw", board_tile=0):
    c = Client("localhost", 14900)
    c._authenticated = True
    c._protocol = _SentRecorder()
    c._current_level_name = level
    c.tiles = [board_tile] * 4096
    c._tiles_level_name = level
    return c


def _engine(npcs, level="bomblobby.nw"):
    """A ClientGS1 whose level holds `npcs` ({id -> npc dict}), each dict's
    "script" (if any) loaded as that NPC's program."""
    c = _client(level)
    for npc_id, npc in npcs.items():
        npc.setdefault("_level", level)
        c.npcs[npc_id] = npc
    gs1 = ClientGS1(c)
    for npc_id, npc in npcs.items():
        if npc.get("script"):
            gs1.load_script("npc_%d" % npc_id, npc["script"], npc_id=npc_id,
                            x=npc.get("x", 0), y=npc.get("y", 0))
    return c, gs1


def _this(gs1, npc_id):
    return gs1._progs["npc_%d" % npc_id]["scopes"]["this"]


# -- testnpc -----------------------------------------------------------------

def _shape_npcs(script):
    """Two shaped NPCs plus the probe NPC, ids out of level order so the
    npcs[] INDEX and the server id cannot be confused."""
    return {
        40: {"x": 10.0, "y": 20.0, "image": "-",
             "script": "if (playerenters) { setshape 1,32,32; }"},
        7: {"x": 45.0, "y": 35.0, "image": "-",
            "script": "if (playerenters) { setshape 1,96,16; }"},
        5: {"x": 0.0, "y": 0.0, "image": "-", "script": script},
    }


def test_testnpc_returns_the_npcs_array_index_not_the_npc_id():
    # sorted ids are [5, 7, 40] -> the 96x16 counter at (45,35) is index 1
    _c, gs1 = _engine(_shape_npcs("if (timeout) { this.n = testnpc(45,35); }"))
    gs1.trigger_event("playerenters")
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["n"] == 1.0


def test_testnpc_index_is_the_one_callnpc_wants():
    # The pin that matters: the index testnpc hands back has to select the same
    # NPC when it is fed straight into callnpc, as the shop counter does.
    npcs = _shape_npcs("if (timeout) { callnpc testnpc(10,20),POKE; }")
    npcs[40]["script"] += "\nif (POKE) { this.poked = 1; }"
    npcs[7]["script"] += "\nif (POKE) { this.poked = 1; }"
    _c, gs1 = _engine(npcs)
    gs1.trigger_event("playerenters")
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 40).get("poked") == 1.0
    assert "poked" not in _this(gs1, 7)


def test_testnpc_setshape_pixels_cover_the_right_tiles():
    # `setshape 1,96,16` is 6x1 TILES: (45,35)..(51,36) inclusive of both far
    # edges, and nothing past them.
    script = ("if (timeout) { this.a = testnpc(51,36); this.b = testnpc(52,35);"
              " this.c = testnpc(45,37); }")
    _c, gs1 = _engine(_shape_npcs(script))
    gs1.trigger_event("playerenters")
    gs1.trigger_npc_event(5, "timeout")
    scope = _this(gs1, 5)
    assert scope["a"] == 1.0            # far corner of the 6x1 box
    assert scope["b"] == -1.0
    assert scope["c"] == -1.0


def test_testnpc_misses_answer_minus_one():
    _c, gs1 = _engine(_shape_npcs("if (timeout) { this.n = testnpc(1,1); }"))
    gs1.trigger_event("playerenters")
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["n"] == -1.0


def test_testnpc_hits_a_character_npc_without_a_shape():
    # No setshape: a character NPC (gani/body/head) still has the feet-centred
    # 2x2 square, same as the server host.
    npcs = {9: {"x": 12.0, "y": 30.0, "image": "-", "gani": "idle"},
            5: {"x": 0.0, "y": 0.0, "image": "-",
                "script": "if (timeout) { this.a = testnpc(13,32);"
                          " this.b = testnpc(12,30); }"}}
    _c, gs1 = _engine(npcs)
    gs1.trigger_npc_event(5, "timeout")
    scope = _this(gs1, 5)
    assert scope["a"] == 1.0            # inside (12*16+8, 30*16+16)+32px
    assert scope["b"] == -1.0           # above/left of the feet box


def test_testnpc_hits_a_plain_image_npc_on_its_footprint():
    # A visible shapeless image NPC is hittable on its image footprint - the
    # same geometry that blocks and touches. This is what makes the classic
    # putnpc guard idiom work: GTA's `if (testnpc(19,17.5)<0) putnpc ...`
    # must SEE the barrel that is already there, or every level entry stacks
    # another copy onto the server (live-observed on adventurerpub.nw before
    # this rule). Hidden NPCs stay unhittable (isOnNPC bails on !visible),
    # and image "-" is the classic no-image placeholder (no footprint).
    npcs = {9: {"x": 12.0, "y": 30.0, "image": "koni_vase.png"},
            5: {"x": 0.0, "y": 0.0, "image": "-",
                "script": "if (timeout) { this.n = testnpc(13,31);"
                          " this.o = testnpc(15,33); this.p = testnpc(1,1); }"}}
    _c, gs1 = _engine(npcs)
    gs1.trigger_npc_event(5, "timeout")
    scope = _this(gs1, 5)
    assert scope["n"] == 1.0            # inside the default 2x2 footprint
    assert scope["o"] == -1.0           # outside it
    assert scope["p"] == -1.0           # "-" image NPC has no footprint


def test_testnpc_cannot_hit_a_hidden_image_npc():
    npcs = {9: {"x": 12.0, "y": 30.0, "image": "koni_vase.png",
                "visible": False},
            5: {"x": 0.0, "y": 0.0, "image": "-",
                "script": "if (timeout) { this.n = testnpc(13,31); }"}}
    _c, gs1 = _engine(npcs)
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["n"] == -1.0


def test_testnpc_without_both_coordinates_is_a_miss():
    _c, gs1 = _engine(_shape_npcs("if (timeout) { this.n = testnpc(45); }"))
    gs1.trigger_event("playerenters")
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["n"] == -1.0


# -- testplayer --------------------------------------------------------------

def test_testplayer_finds_the_local_player_at_index_zero():
    _c, gs1 = _engine({5: {"x": 0.0, "y": 0.0, "image": "-",
                           "script": "if (timeout) { this.n = testplayer(31,33); }"}})
    gs1.client.player.x, gs1.client.player.y = 30.0, 31.0
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["n"] == 0.0


def test_testplayer_misses_answer_minus_two():
    # -2 is what the server host answers (pygserver gs1_host.py:515 _test_at); the
    # reference client answers -1, and every real script only tests `< 0`.
    _c, gs1 = _engine({5: {"x": 0.0, "y": 0.0, "image": "-",
                           "script": "if (timeout) { this.n = testplayer(3,3); }"}})
    gs1.client.player.x, gs1.client.player.y = 30.0, 31.0
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["n"] == -2.0


# -- mousex / mousey ---------------------------------------------------------

_MOUSE_PROBE = ("if (timeout) { this.mx = mousex; this.my = mousey;"
                " this.sx = mousescreenx; this.sy = mousescreeny; }")


def test_mouse_world_reads_the_runtime_hook():
    _c, gs1 = _engine({5: {"x": 0.0, "y": 0.0, "image": "-",
                           "script": _MOUSE_PROBE}})
    gs1.mouse_x, gs1.mouse_y = 700.0, 400.0
    gs1.mouse_world_source = lambda: (50.0625, 36.90625)
    gs1.trigger_npc_event(5, "timeout")
    scope = _this(gs1, 5)
    assert (scope["mx"], scope["my"]) == (50.0625, 36.90625)
    assert (scope["sx"], scope["sy"]) == (700.0, 400.0)


def test_mouse_world_falls_back_to_the_player_position():
    # Unset hook (headless): mousex == playerx exactly, so the shop's
    # `mousescreenx - (mousex - playerx) * 16 + 24` collapses to cursor + 24
    # instead of running off the canvas.
    script = ("if (timeout) { this.mx = mousex; this.my = mousey;"
              " this.pos = mousescreenx - (mousex - playerx) * 16 + 24; }")
    _c, gs1 = _engine({5: {"x": 0.0, "y": 0.0, "image": "-", "script": script}})
    gs1.client.player.x, gs1.client.player.y = 46.0, 36.0
    gs1.mouse_x, gs1.mouse_y = 700.0, 400.0
    gs1.trigger_npc_event(5, "timeout")
    scope = _this(gs1, 5)
    assert (scope["mx"], scope["my"]) == (46.0, 36.0)
    assert scope["pos"] == 724.0


def test_a_broken_mouse_hook_falls_back_instead_of_killing_the_script():
    def _boom():
        raise RuntimeError("no camera")

    _c, gs1 = _engine({5: {"x": 0.0, "y": 0.0, "image": "-",
                           "script": _MOUSE_PROBE}})
    gs1.client.player.x, gs1.client.player.y = 46.0, 36.0
    gs1.mouse_world_source = _boom
    gs1.trigger_npc_event(5, "timeout")
    assert (_this(gs1, 5)["mx"], _this(gs1, 5)["my"]) == (46.0, 36.0)


# -- the pygame input wiring -------------------------------------------------

class _ScaledViewport:
    """A letterboxed viewport: the virtual canvas is drawn at half scale,
    offset (20, 10) into the window."""

    @staticmethod
    def window_to_virtual(wx, wy):
        return ((wx - 20) / 2.0, (wy - 10) / 2.0)


class _FeedKeys:
    """pygame.key.get_pressed() stand-in: nothing held."""

    def __getitem__(self, key):
        return False

    def __len__(self):
        return 512


class _FeedHarness(InputMixin):
    """Minimal GameClient stand-in for _feed_gs1_input's screen/mouse sync."""

    def __init__(self, gs1):
        self.gs1 = gs1
        self.screen = pygame.Surface((320, 240))
        self.viewport = _ScaledViewport()
        self.camera = Camera2D(320, 240, 16)
        self._vk_cache = {}


def _feed(gs1, window_pos):
    harness = _FeedHarness(gs1)
    orig = pygame.mouse.get_pos
    pygame.mouse.get_pos = lambda: window_pos
    try:
        harness._feed_gs1_input(_FeedKeys())
    finally:
        pygame.mouse.get_pos = orig
    return harness


def test_input_feeds_the_mouse_in_virtual_canvas_pixels():
    # screen_w/h is the CANVAS, so mousescreenx/y must be too — raw window
    # pixels are a different frame under a letterboxed viewport.
    gs1 = ClientGS1(client=None)
    _feed(gs1, (120, 90))
    assert (gs1.screen_w, gs1.screen_h) == (320, 240)
    assert (gs1.mouse_x, gs1.mouse_y) == (50.0, 40.0)


def test_input_wires_the_mouse_world_hook_to_the_camera():
    c = _client()
    c.player.x, c.player.y = 30.0, 20.0
    gs1 = ClientGS1(c)
    harness = _feed(gs1, (120, 90))
    harness.camera.set_center(30.0, 20.0)
    orig = pygame.mouse.get_pos
    pygame.mouse.get_pos = lambda: (120, 90)
    try:
        assert gs1.mouse_world() == harness.camera.screen_to_world(50.0, 40.0)
    finally:
        pygame.mouse.get_pos = orig


# -- the live shop replay ----------------------------------------------------

@pytest.fixture
def shop():
    """The captured shop, replayed offline: both NPCs loaded on a walkable
    board, the account flags the scripts read seeded, `playerenters` fired.

    The mouse hook models the client's camera with the player centred on a
    1270x771 canvas — that is the frame the counter converts through, and the
    only thing the panel's position depends on."""
    cap = load_capture()
    c = _client(cap["level"])
    c.player.x, c.player.y = cap["player_x"], cap["player_y"]
    c.player.direction = 0              # the touch handler needs playerdir == 0
    scripts = load_scripts()
    for npc_id, src in scripts.items():
        info = cap["npcs"][str(npc_id)]
        c.npcs[npc_id] = {"x": info["x"], "y": info["y"], "image": info["image"],
                          "script": src, "_level": cap["level"]}
    gs1 = ClientGS1(c)
    gs1.screen_w, gs1.screen_h = CANVAS_W, CANVAS_H
    gs1.mouse_x, gs1.mouse_y = 700.0, 400.0
    gs1.mouse_world_source = lambda: (
        c.x + (gs1.mouse_x - CANVAS_W / 2) / 16.0,
        c.y + (gs1.mouse_y - CANVAS_H / 2) / 16.0)
    # Win,Lose,Draw,3,4,5,6,Coins (bomblobby.nw:942) and the 4 appearance
    # slot pairs BombSkin,Decal,DecalColor,Explosion (:943).
    gs1.recv_flag("client.data", "0,0,0,0,0,0,0,200,0")
    gs1.recv_flag("client.mod", "00000000")
    calls = []
    inner = gs1.call_npc

    def _spy(npc_id, event, params=()):
        calls.append((npc_id, event, list(params)))
        return inner(npc_id, event, params)

    gs1.call_npc = _spy
    for npc_id, src in scripts.items():
        gs1.load_script("npc_%d" % npc_id, src, npc_id=npc_id,
                        x=c.npcs[npc_id]["x"], y=c.npcs[npc_id]["y"])
    gs1.trigger_event("playerenters")
    return c, gs1, calls


def _open_shop(gs1):
    """Touch the counter facing up, then hold the accept key (4 = D) until the
    catalogue has been fetched and the item menu has drawn."""
    gs1.trigger_npc_event(COUNTER_ID, "playertouchsme")
    for tick in range(6):
        gs1.keys_dir = {4} if tick else set()
        gs1.process_coroutines(0.05)
        # The menu construction is deliberately allowed to span frames now;
        # finish its zero-delay slices before inspecting the completed panel,
        # without advancing any numeric sleep a second time in this tick.
        while any(c["remaining"] <= 0 for c in gs1._coros):
            gs1.process_coroutines(0.0)


def _gui_layers(client, npc_id):
    """The counter's GUI-band layers: explicit vis>=4, i.e. SCREEN-pixel coords
    (game/render_entities.py _layer_is_gui)."""
    imgs = client.npcs[npc_id].get("imgs") or {}
    return {idx: rec for idx, rec in imgs.items()
            if rec.get("vis_set") and rec.get("vis", 4) >= 4}


def test_shop_reaches_its_catalogue_npc(shop):
    _c, gs1, calls = shop
    _open_shop(gs1)
    assert (CATALOGUE_ID, "GrabItemList", ["3"]) in calls
    assert not any(npc_id == COUNTER_ID for npc_id, _e, _p in calls)


def test_shop_lists_real_items(shop):
    _c, gs1, _calls = shop
    _open_shop(gs1)
    flags = gs1._shared["client"]
    assert flags.get("Shop_n", "").startswith('"Blue Bomb","Green Bomb"')
    assert flags.get("Shop_p") == "0,40,40,40,40,40,60,60,60"
    assert flags.get("Shop_i", "").startswith("00-1-1-1,01-1-1-1")
    # the menu's 4-row view window, filled from sarraylen(clientr.Shop_n)
    assert _this(gs1, COUNTER_ID)["iView"] == [0.0, 1.0, 2.0, 3.0]


def test_shop_panel_lands_on_the_canvas(shop):
    c, gs1, _calls = shop
    _open_shop(gs1)
    # this.pos is the PLAYER's screen pixel + 24 whatever the cursor does —
    # that is the whole point of the mousescreen/mouse pair.
    assert _this(gs1, COUNTER_ID)["pos"] == [659.0, 409.0]
    layers = _gui_layers(c, COUNTER_ID)
    assert len(layers) == 95            # the full item menu drew
    offscreen = {idx: (rec.get("x"), rec.get("y"))
                 for idx, rec in layers.items()
                 if not (0 <= rec.get("x", 0) < CANVAS_W
                         and 0 <= rec.get("y", 0) < CANVAS_H)}
    assert offscreen == {}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
