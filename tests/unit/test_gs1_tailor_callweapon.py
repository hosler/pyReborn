"""Classic Bomber's tailor — the NPC "Jonah" and the `-tailor` weapon he calls.

Jonah could not be triggered at all, for two independent reasons, and once he
could the GUI he opens still came up wrong:

* he only calls `showcharacter`, never setshape/setshape2, so `NPCHandler` had
  no touch box for him at all and `playertouchsme` could never fire. Upstream
  gives a character NPC an implicit 2x2 box on its feet (NPC.h:540-552);
* `callweapon` — the one command his touch handler runs — was registered as a
  silent no-op in the FIRST dispatch stage, so the event was discarded;
* the client-version builtin was unimplemented (0), so the weapon's
  `o_cli = (graalversion < 2.211)` was true on a 2.22 session and the whole GUI
  drew in the legacy layout with the character preview skipped;
* the appearance message codes (`#3`, `#8`, `#C0`..) answered "" inside a
  weapon script, so `grab_Old()` snapshotted blanks and `Cancel()` reset the
  player's head, body and five colours to white.

Plus one thing found on the way in: `clientr.` flag writes were echoed to the
server as `client.` PLI_FLAGSETs, i.e. opening the bomber shop wrote three
scratch strings onto a live third-party account.

The replay at the bottom drives the real scripts (bomber_lobby_tailor fixture)
and pins the GUI that comes up. Everything here is offline.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn import Client
from pyreborn.gs1_client import ClientGS1, _NOOP, _color_name, _version_number
from pyreborn.npc_handler import NPCHandler

from .bomber_lobby_tailor_fixture import (JONAH_ID, load_capture,
                                         load_npc_script, load_weapon_script)

class _SentRecorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def _client(level="bomblobby.nw", version="2.22"):
    c = Client("localhost", 14900, version=version)
    c._authenticated = True
    c._protocol = _SentRecorder()
    c._current_level_name = level
    c.tiles = [0] * 4096
    c._tiles_level_name = level
    return c


# -- break 1: the character NPC's touch box ----------------------------------

def _handler(npcs, shapes=None):
    """An NPCHandler over `npcs` ({id -> npc dict}) with `shapes` standing in
    for what the GS1 engine recorded (id -> (w, h, flags))."""
    c = _client()
    c.entities.npcs.update(npcs)
    handler = NPCHandler(c)
    handler.gs1 = type("_Shapes", (), {"shapes": dict(shapes or {})})()
    handler.update_npcs()
    return handler


def test_character_npc_gets_an_implicit_touch_box():
    # 2x2 tiles at +(0.5, 1.0) from the NPC's own position — NPC.h:540-552's
    # {getGlobalPosition().translate(8, 16), {32, 32, 48}}.
    handler = _handler({7: {"x": 16.0, "y": 12.0, "image": "#c#"}})
    shape = handler.npc_shapes[7]
    assert (shape.x, shape.y, shape.width, shape.height) == (16.5, 13.0, 2, 2)


def test_client_side_showcharacter_also_counts_as_a_character():
    # Our own GS1 engine records showcharacter as is_character (the wire prop
    # only says "#c#" when the SERVER ran the command).
    handler = _handler({7: {"x": 16.0, "y": 12.0, "image": "-",
                            "is_character": True}})
    assert 7 in handler.npc_shapes


def test_shapeless_image_npc_gets_its_image_footprint_touch_box():
    # A shapeless IMAGE NPC is touchable on its image footprint (the same
    # geometry that blocks movement): reference touch dispatch and wall test
    # share TServerNPC::isOnNPC. The stub gs1 here has no npc_image_rect, so
    # no box; with the real engine attached the box appears (2x2 default for
    # an unsized image).
    handler = _handler({7: {"x": 16.0, "y": 12.0, "image": "sign.png"}})
    assert handler.npc_shapes == {}   # stub gs1: no image-rect provider

    c = _client()
    c.entities.npcs[7] = {"x": 16.0, "y": 12.0, "image": "sign.png"}
    gs1 = ClientGS1(c)
    handler = NPCHandler(c)
    handler.gs1 = gs1
    handler.update_npcs()
    shape = handler.npc_shapes[7]
    assert (shape.x, shape.y, shape.width, shape.height) == (16.0, 12.0, 2, 2)
    assert shape.is_point_inside(16.5, 12.5)
    assert not shape.is_point_inside(18.5, 12.5)


def test_script_shape_still_wins_over_the_character_box():
    handler = _handler({7: {"x": 16.0, "y": 12.0, "image": "#c#"}},
                       shapes={7: (4, 3, [22] * 12)})
    shape = handler.npc_shapes[7]
    assert (shape.x, shape.y, shape.width, shape.height) == (16.0, 12.0, 4, 3)


def test_character_box_is_solid_too():
    # The character box BLOCKS as well as touches: TServerNPC::isOnNPC's
    # character path is the same 2x2 rect at +(0.5, 1.0) the wall test walks
    # (TServerNPC.cpp:2106-2112), and the level wall test asks NPCs before
    # the board (TServerLevel::isOnWall). It never goes through the
    # setshape cell store, though — that stays script-shape-only.
    c = _client()
    c.entities.npcs[7] = {"x": 16.0, "y": 12.0, "image": "#c#"}
    gs1 = ClientGS1(c)
    handler = NPCHandler(c)
    handler.gs1 = gs1
    handler.update_npcs()
    assert 7 in handler.npc_shapes
    assert gs1._shape_blocks == set()
    assert gs1.is_wall(16.5, 13.0) is True    # inside the 2x2 feet box
    assert gs1.is_wall(16.0, 12.0) is False   # sprite corner, outside the box
    # ...and the probing NPC itself is excluded from its own onwall()
    assert gs1.is_wall(16.5, 13.0, exclude_npc=7) is False


def test_walking_into_a_character_npc_dispatches_playertouchsme():
    handler = _handler({7: {"x": 16.0, "y": 12.0, "image": "#c#",
                            "script": "if (playertouchsme) { hide; }"}})
    fired = []
    handler.on_playertouchsme = lambda npc_id, npc: fired.append(npc_id)
    # Player sprite top-left (16, 13) facing up: the up-probe row (y+1 = 14)
    # lands inside the box's rows 13-15, i.e. standing right below Jonah.
    handler.process_movement(16.0, 13.0, 0)
    assert fired == [7]
    # ...and one tile further back is out of reach again
    handler.touched_npcs = set()
    fired.clear()
    handler.process_movement(16.0, 15.0, 0)
    assert fired == []


# -- break 1: blast radius in the real level ---------------------------------

_LEVEL = os.path.join(os.path.dirname(__file__), '..', '..', '..',
                      'Preagonal', 'graal-bomber-gs1', 'world', 'bomblobby.nw')


@pytest.mark.skipif(not os.path.exists(_LEVEL),
                    reason="third-party bomber level checkout not present")
def test_only_one_lobby_npc_is_reached_by_the_new_box():
    """How many NPCs the implicit box can newly affect in the level it was
    found in: 3 of bomblobby's 54 NPCs are characters, and only one of those
    declares playertouchsme."""
    with open(_LEVEL, encoding='latin-1') as f:
        body = f.read()
    npcs = body.split("\nNPC ")[1:]
    characters = [n for n in npcs if "showcharacter" in n]
    assert (len(npcs), len(characters)) == (54, 3)
    assert sum("playertouchsme" in n for n in characters) == 1


# -- break 2: callweapon -----------------------------------------------------

def _weapon_engine(weapons, weapon_scripts=(), npc_script=None):
    """A ClientGS1 whose player holds `weapons` (in order), with the named
    weapon scripts loaded and, optionally, one NPC running `npc_script`."""
    c = _client()
    for name in weapons:
        c.weapons[name] = {"name": name, "image": ""}
    gs1 = ClientGS1(c)
    for name, src in dict(weapon_scripts).items():
        gs1.load_weapon(name, src)
    if npc_script is not None:
        c.entities.npcs[7] = {"x": 16.0, "y": 12.0, "image": "#c#",
                              "script": npc_script, "_level": "bomblobby.nw"}
        gs1.load_script("npc_7", npc_script, npc_id=7)
    return c, gs1


def test_callweapon_is_no_longer_a_noop():
    assert "callweapon" not in _NOOP


def test_callweapon_runs_the_indexed_weapons_event_with_params():
    # ['3.0', 'TailorSystem', 'true,18,9.5'] — the lexer's 'ESS' shape
    # (reborn_protocol/gs1/_tables.py:16). GS1 vars hold numbers unless a
    # command assigns a string, hence setstring for the flag param.
    script = ("if (ping) { setstring this.p0,#p(0); this.p1 = strtofloat(#p(1));"
              " this.p2 = strtofloat(#p(2)); }")
    _c, gs1 = _weapon_engine(["-a", "-b", "-c", "-tailor"],
                             {"-tailor": script},
                             "if (timeout) { callweapon 3,ping,true,18,9.5; }")
    gs1.trigger_npc_event(7, "timeout")
    scope = gs1._progs["weapon_-tailor"]["scopes"]["this"]
    assert (scope["p0"], scope["p1"], scope["p2"]) == ("true", 18.0, 9.5)


def test_callweapon_index_is_the_weaponscount_ordering():
    # The index the calling script derived from `#w(i)`/weaponscount has to
    # select the same weapon here, or the wrong script runs.
    scripts = {"-a": "if (ping) { this.hit = 1; }",
               "-tailor": "if (ping) { this.hit = 1; }"}
    _c, gs1 = _weapon_engine(["-a", "-b", "-c", "-tailor"], scripts,
                             "if (timeout) { for (this.i = 0; this.i <"
                             " weaponscount; this.i++) if"
                             " (strequals(#w(this.i),-tailor))"
                             " { callweapon this.i,ping; break; } }")
    gs1.trigger_npc_event(7, "timeout")
    assert gs1._progs["weapon_-tailor"]["scopes"]["this"].get("hit") == 1.0
    assert "hit" not in gs1._progs["weapon_-a"]["scopes"]["this"]


def test_callweapon_out_of_range_index_does_nothing():
    _c, gs1 = _weapon_engine(["-tailor"],
                             {"-tailor": "if (ping) { this.hit = 1; }"},
                             "if (timeout) { callweapon 9,ping; }")
    gs1.trigger_npc_event(7, "timeout")
    assert gs1._progs["weapon_-tailor"]["scopes"]["this"] == {}


def test_callweapon_restores_the_callers_projectile_params():
    # Same contract as callnpc: #p() belongs to the running event, and a
    # keypressed/actionprojectile2 handler must still see its own after the
    # call returns.
    _c, gs1 = _weapon_engine(["-tailor"],
                             {"-tailor": "if (ping) { setstring this.seen,#p(0); }"},
                             "if (actionprojectile2) { callweapon 0,ping,inner;"
                             " setstring this.after,#p(0); }")
    gs1.fire_projectile(["outer"])
    assert gs1._progs["weapon_-tailor"]["scopes"]["this"]["seen"] == "inner"
    assert gs1._progs["npc_7"]["scopes"]["this"]["after"] == "outer"


def test_callweapon_cycle_is_bounded():
    # Untrusted server script: two weapons that call each other must not
    # recurse until Python's own stack limit. Both hops go through
    # callweapon, so this pins ITS guard, not callnpc's.
    _c, gs1 = _weapon_engine(
        ["-a", "-b"],
        {"-a": "if (ping) { this.n++; callweapon 1,pong; }",
         "-b": "if (pong) { callweapon 0,ping; }"})
    gs1.call_weapon("-a", "ping")
    assert 1 <= gs1._progs["weapon_-a"]["scopes"]["this"]["n"] <= 8


# -- break 3: the client-version builtin -------------------------------------

def test_client_version_builtin_reports_the_negotiated_version():
    _c, gs1 = _weapon_engine(
        ["-tailor"],
        {"-tailor": "if (ping) { this.v = graalversion;"
                    " this.old = (graalversion < 2.211); }"})
    gs1.call_weapon("-tailor", "ping")
    scope = gs1._progs["weapon_-tailor"]["scopes"]["this"]
    assert scope["v"] == 2.22
    assert scope["old"] is False


@pytest.mark.parametrize("version,expected", [
    ("2.22", 2.22), ("1.411", 1.411), ("6.037", 6.037),
    ("6.037_linux", 6.037), ("", 0.0), (None, 0.0), ("nonsense", 0.0),
])
def test_version_number_parses_every_spelling(version, expected):
    assert _version_number(version) == expected


# -- break 4: appearance codes in a weapon script ----------------------------

def _look_engine(**player):
    c = _client()
    c.weapons["-tailor"] = {"name": "-tailor", "image": ""}
    for attr, value in player.items():
        setattr(c.player, attr, value)
    gs1 = ClientGS1(c)
    return c, gs1


_LOOK_PROBE = ("if (ping) { setstring this.head,#3; setstring this.body,#8;"
               " setstring this.sword,#1; setstring this.shield,#2;"
               " setstring this.c0,#C0; setstring this.c4,#C4; }")


def test_weapon_script_reads_the_players_look():
    _c, gs1 = _look_engine(head_image="head471.png", body_image="body20.png",
                           sword_image="sword2.png", shield_image="shield1.png",
                           colors=[2, 5, 12, 18, 12])
    gs1.load_weapon("-tailor", _LOOK_PROBE)
    gs1.call_weapon("-tailor", "ping")
    scope = gs1._progs["weapon_-tailor"]["scopes"]["this"]
    assert scope["head"] == "head471.png"
    assert scope["body"] == "body20.png"
    assert scope["sword"] == "sword2.png"
    assert scope["shield"] == "shield1.png"
    # NAMES, not indices: the tailor's grab_Old() matches #C0 against the
    # tokenized palette names. See the module docstring in gs1_client.py's
    # _color_name for why this direction was chosen.
    assert (scope["c0"], scope["c4"]) == ("orange", "brown")


def test_unknown_colors_read_empty_rather_than_white():
    _c, gs1 = _look_engine(colors=[])
    gs1.load_weapon("-tailor", _LOOK_PROBE)
    gs1.call_weapon("-tailor", "ping")
    assert gs1._progs["weapon_-tailor"]["scopes"]["this"]["c0"] == ""


def test_npc_source_still_wins_over_the_player():
    # An NPC script's bare #3/#C0 is the NPC's own look (setcharprop), not the
    # player's — "biasing to the initiator", GS1MessageCodes.cpp:281-287.
    c = _client()
    c.player.head_image = "head471.png"
    c.player.colors = [2, 5, 12, 18, 12]
    script = ("if (playerenters) { showcharacter; setcharprop #3,head99.png;"
              " setcharprop #C0,black; }\n"
              "if (timeout) { setstring this.head,#3; setstring this.c0,#C0; }")
    c.entities.npcs[7] = {"x": 16.0, "y": 12.0, "image": "-", "script": script,
                          "_level": "bomblobby.nw"}
    gs1 = ClientGS1(c)
    gs1.load_script("npc_7", script, npc_id=7)
    gs1.trigger_event("playerenters")
    gs1.trigger_npc_event(7, "timeout")
    scope = gs1._progs["npc_7"]["scopes"]["this"]
    assert (scope["head"], scope["c0"]) == ("head99.png", "black")


@pytest.mark.parametrize("stored,name", [
    (2, "orange"), ("2", "orange"), (2.0, "orange"),
    ("orange", "orange"), ("Orange", "orange"), ("cyan", "cynober"),
    (19, "transparent"), (99, ""), ("", ""), (None, ""), ("nonsense", ""),
])
def test_color_slots_read_back_as_names_however_they_were_written(stored, name):
    # The one genuine open question in this fix: reads answer the palette NAME
    # and writes take a name OR an index. That is what the tailor's own usage
    # demands (`strequals(#C0,#t(this.c))` against names, `setplayerprop
    # #C0,#v(this.dat[3])` writing an index) — it is NOT confirmed by a client
    # oracle, so it is pinned here to make a correction cheap.
    assert _color_name(stored) == name


def test_grab_old_snapshots_the_real_colors():
    """The consequence that made this matter: with blank codes the tailor's
    grab_Old() left o_color all-zero, so Cancel() painted the player white."""
    c = _client()
    c.player.head_image = "head471.png"
    c.player.body_image = "body20.png"
    c.player.colors = [2, 5, 12, 18, 12]
    c.weapons["-probe"] = {"name": "-probe", "image": ""}
    gs1 = ClientGS1(c)
    # grab_Old() is one of the weapon's functions; drive it on its own with an
    # extra event rather than through TailorSystem's whole entry path (which
    # the replay at the bottom covers).
    gs1.load_weapon("-probe", load_weapon_script()
                    + "\nif (grabprobe) { grab_Old(); }")
    gs1.call_weapon("-probe", "grabprobe")
    while any(c["remaining"] <= 0 for c in gs1._coros):
        gs1.process_coroutines(0.0)
    this = gs1._progs["weapon_-probe"]["scopes"]["this"]
    assert this["o_color"] == [2.0, 5.0, 12.0, 18.0, 12.0]


# -- break 5: clientr. writes stay local -------------------------------------

_FLAG_PROBE = """
if (ping) {
  setstring clientr.Shop_n,"Blue Bomb","Green Bomb";
  setstring client.tailor,"head471.png","body20.png";
  clientr.scratch = 5;
  client.kept = 6;
}
"""


def _flag_engine():
    c = _client()
    sent = []
    c.set_flag = lambda name, value: sent.append((name, value))
    c.weapons["-tailor"] = {"name": "-tailor", "image": ""}
    gs1 = ClientGS1(c)
    gs1.load_weapon("-tailor", _FLAG_PROBE)
    return gs1, sent


def test_only_client_scoped_flag_writes_transmit():
    gs1, sent = _flag_engine()
    gs1.call_weapon("-tailor", "ping")
    assert [name for name, _v in sent] == ["client.tailor", "client.kept"]


def test_clientr_writes_are_still_readable_locally():
    gs1, _sent = _flag_engine()
    gs1.call_weapon("-tailor", "ping")
    flags = gs1._shared["client"]
    assert flags["Shop_n"] == '"Blue Bomb","Green Bomb"'
    assert flags["scratch"] == 5.0


def test_a_clientr_read_does_not_suppress_the_following_client_write():
    # Nesting: a `clientr.` reference resolved while evaluating the write's own
    # value/index is resolved FIRST, so the outer `client.` reference (resolved
    # last, immediately before the store) must still decide that it is sent.
    src = ("if (ping) { clientr.i = 1; client.plain = clientr.i + 2;"
           " setstring client.text,#s(clientr.i); }")
    c = _client()
    sent = []
    c.set_flag = lambda name, value: sent.append((name, value))
    gs1 = ClientGS1(c)
    gs1.load_weapon("-probe", src)
    gs1.call_weapon("-probe", "ping")
    assert [name for name, _v in sent] == ["client.plain", "client.text"]


def test_received_flags_are_not_echoed_back():
    gs1, sent = _flag_engine()
    gs1.recv_flag("clientr.Shop_n", "x")
    gs1.recv_flag("client.pet", "squirrel")
    assert sent == []


# -- the whole path: touch Jonah, get the tailor GUI -------------------------

@pytest.fixture
def tailor():
    """The captured tailor, replayed offline: Jonah loaded on a walkable board
    with the weapon the player holds, `playerenters` fired, an NPCHandler
    watching for touches."""
    cap = load_capture()
    c = _client(cap["level"])
    c.player.x, c.player.y = cap["player_x"], cap["player_y"]
    c.player.head_image = cap["player_head"]
    c.player.body_image = cap["player_body"]
    c.player.colors = list(cap["player_colors"])
    for name in cap["weapons"]:
        c.weapons[name] = {"name": name, "image": ""}
    info = cap["npcs"][str(JONAH_ID)]
    npc_script = load_npc_script()
    c.entities.npcs[JONAH_ID] = {"x": info["x"], "y": info["y"],
                                 "image": info["image"], "script": npc_script,
                                 "_level": cap["level"]}
    gs1 = ClientGS1(c)
    gs1.screen_w, gs1.screen_h = cap["screen"]
    gs1.mouse_x, gs1.mouse_y = 700.0, 400.0
    gs1.mouse_world_source = lambda: (
        c.x + (gs1.mouse_x - gs1.screen_w / 2) / 16.0,
        c.y + (gs1.mouse_y - gs1.screen_h / 2) / 16.0)
    gs1.load_script("npc_%d" % JONAH_ID, npc_script, npc_id=JONAH_ID,
                    x=info["x"], y=info["y"])
    gs1.load_weapon(cap["weapon"], load_weapon_script())
    gs1.trigger_event("playerenters")
    while any(c["remaining"] <= 0 for c in gs1._coros):
        gs1.process_coroutines(0.0)
    handler = NPCHandler(c)
    handler.gs1 = gs1
    handler.on_playertouchsme = lambda npc_id, _npc: gs1.trigger_npc_event(
        npc_id, "playertouchsme")
    handler.update_npcs()
    return c, gs1, handler


def _tailor_layers(gs1):
    """The weapon's showimg/showani/showtext layer store."""
    return gs1._weapon_imgs.get("weapon_-tailor") or {}


def _finish_ready_slices(gs1):
    # Tailor GUI construction is larger than one cooperative slice.  Tests
    # asserting its completed state drain only preemption continuations;
    # numeric sleeps retain their one-per-frame timing.
    while any(c["remaining"] <= 0 for c in gs1._coros):
        gs1.process_coroutines(0.0)


def test_touching_jonah_opens_the_tailor(tailor):
    c, gs1, handler = tailor
    # walk up to him from below, facing up (playerdir 0), no grab key held
    c.player.direction = 0
    handler.process_movement(c.player.x, c.player.y, 0)
    gs1.process_coroutines(0.05)
    _finish_ready_slices(gs1)
    layers = _tailor_layers(gs1)
    # the panel, the character preview (400 + the 399 showani) and the
    # 410-418 outlined selector, all in the GUI band (vis >= 4)
    assert 401 in layers
    assert {400, 399} <= set(layers)
    assert set(range(410, 419)) <= set(layers)
    assert {layers[i]["vis"] for i in range(410, 419)} == {5, 6}
    assert layers[401]["vis"] == 4
    # ...and they have CONTENT, not just existence: the 9-copy outlined label
    # of the selected row, its highlighted centre copy, and the value column
    # showing the player's actual head.
    assert {layers[i]["text"] for i in range(410, 419)} == {"Head"}
    assert layers[414]["vis"] == 6 and layers[414]["colors"] == (1.0, 1.0, 1.0, 1.0)
    assert {layers[i]["text"] for i in range(420, 429)} == {"head471.png"}
    assert layers[400]["image"] == "eye_plattail-gui.png"
    assert layers[400]["part"] == (0, 0, 58, 76)


def test_the_tailor_uses_the_modern_layout(tailor):
    # o_cli == 0 on a 2.22 session: no -31x/+64y shift, preview drawn.
    c, gs1, handler = tailor
    c.player.direction = 0
    handler.process_movement(c.player.x, c.player.y, 0)
    gs1.process_coroutines(0.05)
    _finish_ready_slices(gs1)
    layers = _tailor_layers(gs1)
    this = gs1._progs["weapon_-tailor"]["scopes"]["this"]
    assert layers[401]["x"] == this["xx"] - 70
    assert layers[410]["y"] == this["yy"] - 5


def test_the_tailor_snapshots_the_players_look(tailor):
    c, gs1, handler = tailor
    c.player.direction = 0
    handler.process_movement(c.player.x, c.player.y, 0)
    gs1.process_coroutines(0.05)
    _finish_ready_slices(gs1)
    this = gs1._progs["weapon_-tailor"]["scopes"]["this"]
    # o_color is what Cancel() restores: the player's real colours, not zeros
    assert this["o_color"] == [2.0, 5.0, 12.0, 18.0, 12.0]
    # head471.png/body20.png parsed back into the selector positions
    assert (this["dat"][1], this["dat"][2]) == (471.0, 20.0)


def test_the_tailor_responds_to_the_arrow_keys(tailor):
    # The GUI is a `while (TailorActive == 1) { ... sleep 0.05; }` loop, so it
    # only works if the whole path keeps running frame after frame: hold right
    # to advance the head, then tap down to move to the Body row.
    c, gs1, handler = tailor
    c.player.direction = 0
    handler.process_movement(c.player.x, c.player.y, 0)
    gs1.process_coroutines(0.05)
    _finish_ready_slices(gs1)
    for frame in range(30):
        gs1.keys_dir = {3} if frame < 10 else ({2} if frame in (12, 13) else set())
        gs1.advance_input_frame()
        gs1.process_coroutines(0.05)
        _finish_ready_slices(gs1)
    this = gs1._progs["weapon_-tailor"]["scopes"]["this"]
    assert this["dat"][0] == 1.0             # the Body row is selected
    assert this["dat"][1] > 471.0            # the head advanced past the start
    layers = _tailor_layers(gs1)
    assert layers[414]["text"] == "Body"
    assert layers[424]["text"] == "body20.png"


def test_the_tailor_replay_reports_no_script_errors(tailor, capsys):
    import pyreborn.gs1_client as gs1_mod
    gs1_mod._GS1_ERR_SEEN.clear()
    c, gs1, handler = tailor
    c.player.direction = 0
    handler.process_movement(c.player.x, c.player.y, 0)
    for _ in range(4):
        gs1.process_coroutines(0.05)
    assert [line for line in capsys.readouterr().err.splitlines()
            if line.startswith("[GS1]")] == []


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
