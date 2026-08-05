"""GS2 script-visible name surface vs. the reference client's tables.

Backs reborn-protocol-docs/docs/implementation/gs2-name-surface.md. Every
citation below was read in the decompiled reference at
Preagonal/FourPlay/quattroplay/ before it was written down.
"""
from types import SimpleNamespace

from reborn_protocol.gs2 import GS2Object, gs2_eq, to_num, to_str

from pyreborn.gs2_client import ClientGS2, _LayerImage, _NpcThisObject
from pyreborn.gs1_client import ClientGS1
from pyreborn.player import Player


def _runtime(**client_kwargs):
    """A ClientGS2 with a stub client and a live GS1 runtime, which is what
    the flag scopes and the shared player builtins resolve through."""
    client_kwargs.setdefault("player", Player())
    client_kwargs.setdefault("players", {})
    client_kwargs.setdefault("weapons", {})
    client_kwargs.setdefault("npcs", {})
    client_kwargs.setdefault("signs", {})
    client_kwargs.setdefault("items", {})
    client_kwargs.setdefault("bombs", {})
    client_kwargs.setdefault("active_explosions", [])
    client_kwargs.setdefault("board_layers", {})
    client_kwargs.setdefault("gmap_width", 0)
    client_kwargs.setdefault("gmap_height", 0)
    client_kwargs.setdefault("_current_level_name", "")
    client_kwargs.setdefault("x", 0.0)
    client_kwargs.setdefault("y", 0.0)
    client = SimpleNamespace(**client_kwargs)
    gs1 = ClientGS1(client)
    return ClientGS2(client, gs1)


def call(rt, name, args=(), obj=None):
    return rt.host.call_builtin(None, name, list(args), obj=obj)


# -- "actively wrong" #1: player.nick -----------------------------------------

def test_player_nick_is_read_only():
    """TPlayerProperties registers `nick` with a getter and a nullptr setter
    (quattroplay/src/TPlayerProperties.cpp:252-258), and that child entry
    REPLACES TServerPlayer's read/write one (:609) when the table is compiled
    (src/TProperties.cpp:117-129) -- so the write is a no-op on the local
    player."""
    rt = _runtime()
    rt.client.player.nickname = "Zelda"
    rt.player_object.set("nick", "Impostor")
    assert rt.client.player.nickname == "Zelda"
    assert rt.player_object.get("nick") == "Zelda"


def test_remote_player_nick_stays_writable():
    """Only the LOCAL player's entry is replaced. A TServerPlayer keeps the
    writable slot, so the read-only gate must not leak onto other players."""
    rt = _runtime(players={7: {"nickname": "Link", "level": "onmap.nw"}})
    entry = rt.script_player_object(7, rt.client.players[7])
    entry.set("nick", "Renamed")
    assert entry.get("nick") == "Renamed"


# -- "actively wrong" #2: client / clientr / serverr are the player ----------

def test_flag_scopes_resolve_player_properties():
    """resolveObjectMember binds client, clientr and serverr to
    `executingplayer` (src/TScriptMachine.cpp:5123-5130), so a name the player
    class registers reads that player's value instead of 0.0."""
    rt = _runtime(x=12.5, y=7.0)
    rt.client.player.nickname = "Link (Guild)"
    rt.client.player.account = "linkacct"
    assert rt.host.get_object("client").get("nick") == "Link (Guild)"
    assert rt.host.get_object("clientr").get("x") == 12.5
    assert rt.host.get_object("serverr").get("account") == "linkacct"
    # `server` is NOT one of the three aliases, so it stays a pure flag store
    assert rt.host.get_object("server").get("account") == ""


def test_flag_scopes_keep_flag_behaviour():
    """The player fallback is an EXTENSION: flags still read, write and
    shadow exactly as before, including a flag that shares a property name."""
    rt = _runtime()
    client_scope = rt.host.get_object("client")
    clientr = rt.host.get_object("clientr")
    serverr = rt.host.get_object("serverr")
    client_scope.set("myflag", "on")
    assert client_scope.get("myflag") == "on" and clientr.get("myflag") == "on"
    assert client_scope.get("neverset") == ""
    serverr.set("quest", "done")
    assert serverr.get("quest") == "done"
    assert rt.gs1._shared["server"]["serverr.quest"] == "done"
    # a flag wins over the player property it collides with, and the write
    # must not have moved the player
    clientr.set("x", 99)
    assert clientr.get("x") == 99
    assert rt.client.player.x == 0.0
    # ... and has() still reports flags only, so `with(client){...}` locals
    # do not get redirected into player properties
    assert clientr.has("myflag") and not clientr.has("nick")


# -- "actively wrong" #4: the level object -----------------------------------

def test_level_name_is_the_lower_cased_filename():
    """TServerLevel passes TFiles::lowerCaseFilename(levelName) to its
    TGraalVar base (src/TServerLevel.cpp:352-354). Before this, `level.name`
    was unanswered -- so `level.name == "somelevel.nw"` was true in EVERY
    level."""
    rt = _runtime(_current_level_name="OnLine_Start.nw")
    assert rt.level_object.get("name") == "online_start.nw"
    assert gs2_eq(rt.level_object.get("name"), "online_start.nw")
    assert not gs2_eq(rt.level_object.get("name"), "somewhere_else.nw")
    # gs2_compare's object-vs-string row reads the object's own name field,
    # so the bare-object spelling has to agree
    assert gs2_eq(rt.level_object, "online_start.nw")
    assert not gs2_eq(rt.level_object, "somewhere_else.nw")


def test_level_name_write_is_a_noop():
    """propfun_graalvar_name_w only assigns while the object is unnamed and
    unlinked (src/TGraalVarProperties.cpp:154-161)."""
    rt = _runtime(_current_level_name="level1.nw")
    rt.level_object.set("name", "hacked.nw")
    assert rt.level_object.get("name") == "level1.nw"


def test_level_span_is_64_or_map_segments_shifted():
    """propfun_serverlevel_width_r / _height_r: 0x40 off a map, else the
    map's segment count << 6 (src/TServerLevelProperties.cpp:43-53, :6-16)."""
    rt = _runtime()
    assert (rt.level_object.get("width"), rt.level_object.get("height")) == \
        (64.0, 64.0)
    rt.client.gmap_width, rt.client.gmap_height = 3, 5
    assert (rt.level_object.get("width"), rt.level_object.get("height")) == \
        (192.0, 320.0)


def test_level_remaining_properties_answer_their_shape():
    rt = _runtime()
    assert rt.level_object.get("tilelayercount") == 1.0
    rt.client.board_layers = {0: b"", 2: b""}
    assert rt.level_object.get("tilelayercount") == 3.0
    assert rt.level_object.get("joinedclasses") == []
    assert rt.level_object.get("scripterrors") == []
    for boolean in ("isnopkzone", "nopkzone", "issparringzone", "ispaused",
                    "initialized", "scriptlogmissingfunctions"):
        assert rt.level_object.get(boolean) == 0.0


def test_level_object_probes_index_their_lists():
    """testsign/testitem/testbomb/testexplo have raw-address bodies in the
    decompilation (src/TServerLevelProperties.cpp:254, :245, :227, :236), so
    only the (x, y) -> index-or-(-1) shape is oracle-backed."""
    rt = _runtime(_current_level_name="shop.nw")
    rt.client.signs = {"shop.nw": {(4.0, 9.0): "hi", (30.0, 2.0): "bye"}}
    rt.client.items = {"shop.nw": {(11.0, 3.0): "bomb"}}
    rt.client.items_in_level = lambda level: rt.client.items.get(level, {})
    rt.client.bombs = {"shop.nw": {(1.0, 1.0): {}}}
    rt.client.active_explosions = [{"x": 20.0, "y": 20.0}]
    level = rt.level_object
    assert call(rt, "testsign", [30.5, 2.5], obj=level) == 1.0
    assert call(rt, "testsign", [50, 50], obj=level) == -1.0
    assert call(rt, "testitem", [11.9, 3.1], obj=level) == 0.0
    assert call(rt, "testbomb", [1, 1], obj=level) == 0.0
    assert call(rt, "testexplo", [20, 20], obj=level) == 0.0
    assert call(rt, "testexplo", [0, 0], obj=level) == -1.0


# -- "actively wrong" #5: levelname alongside our own player.level -----------

def test_player_levelname_is_the_official_spelling():
    """No player class registers `level`. The reference spells it `levelname`
    (src/TServerPlayerProperties.cpp:573, getter :181). Our `level` extension
    stays, so both answer."""
    rt = _runtime(_current_level_name="onmap.nw")
    rt.client.player.level = "onmap.nw"
    assert rt.player_object.get("levelname") == "onmap.nw"
    assert gs2_eq(rt.player_object.get("level"), "onmap.nw")
    entry = rt.script_player_object(3, {"level": "elsewhere.nw"})
    assert entry.get("levelname") == "elsewhere.nw"


# -- T1: the empty-string rule ------------------------------------------------

def test_unsourced_string_names_answer_the_empty_string():
    """THE bug T1 exists for: an unanswered name resolves to Number 0.0
    (src/TScriptStackEntry.cpp:228-229) and a Number/String compare
    strtofloat()s the string (src/TScriptMachine.cpp:1463), so it equals
    every non-numeric literal. `""` compares through compareIgnoreCase.

    Shown here on one representative per surface. The assertion that matters
    is the NEGATIVE one -- these must not equal an arbitrary word."""
    rt = _runtime(_current_level_name="x.nw")
    representatives = {
        "installedlanguages": rt.host.get_object("installedlanguages"),
        # the option store is NOT a representative here: the reference seeds
        # every $pref:: entry, so those answer their seed (see
        # test_option_store_answers_the_reference_seeds). The cookie is the
        # one option that really is empty.
        "graalplugincookie": rt.host.get_object("graalplugincookie"),
        "emoticonchar": rt.host.get_object("emoticonchar"),
        "player.language": rt.player_object.get("language"),
        "player.name": rt.player_object.get("name"),
        "other.aniparams": rt.script_player_object(1, {}).get("aniparams"),
    }
    for name, value in representatives.items():
        assert value == "", name
        assert not gs2_eq(value, "somestring"), name
    # an unanswered name (None -> 0.0) doesn't equal words either, since
    # strtofloat("somestring") is -1.0 — seeding is about matching the
    # reference's seeded values, not about dodging a phantom equality
    assert not gs2_eq(None, "somestring")


def test_unsourced_names_have_non_empty_defaults_where_the_reference_does():
    """spritesimage / statusimage are pre-seeded, not blank
    (src/TInitStatics.cpp:4809-4813)."""
    rt = _runtime()
    assert rt.host.get_object("spritesimage") == "sprites.png"
    assert rt.host.get_object("statusimage") == "state.png"


def test_option_store_answers_the_reference_seeds():
    """The `$pref::` option store is T4 (no persistence here), but the
    reference SEEDS every entry at startup and content reads the seeds, so ""
    would be as wrong as nothing. Verified at src/TInitStatics.cpp:4777,
    :4789, :4790, :4841, :4981, :4983, :4984."""
    rt = _runtime()
    for style in ("defaultguistyle", "externalguistyle"):
        assert rt.host.get_object("$pref::video::" + style) == \
            "toon_small.wba"
    assert rt.host.get_object("$pref::video::screenshotformat") == "PNG"
    assert rt.host.get_object("$pref::graal::language") == "English"
    assert rt.host.get_object("$pref::graal::defaultfontname") == "Arial"
    assert rt.host.get_object("$pref::graal::utf8fontfile") == \
        "DroidSansFallback.ttf"
    # credential policy, not the reference's `false` -- this client never
    # stores passwords for a script
    assert rt.host.get_object("$pref::graal::dontsavepasswords") == 1.0


def test_default_font_size_is_24_so_lttp_nick_labels_are_visible():
    """A NUMERIC T1 miss, invisible to the `== "literal"` rule the top-down
    sweep used. graal-lttp weapons/weapon-Player_Movement.txt:101 computes
    `zoom = $pref::graal::defaultfontsize/24;` and draws every nearby
    player's nick at that zoom (:93). Unanswered the name is 0, so zoom is 0
    and nothing renders. The reference seeds 0x18 == 24
    (src/TInitStatics.cpp:4981), which makes the ratio exactly 1."""
    rt = _runtime()
    size = rt.host.get_object("$pref::graal::defaultfontsize")
    assert size == 24.0
    assert to_num(size) / 24 == 1.0


def test_npc_this_inherited_strings_answer():
    rt = _runtime(npcs={5: {"nickname": "Guard (Watch)"}})
    npc_this = _NpcThisObject(rt, ("npc", 5))
    for name in ("account", "communityname", "platform", "head", "body",
                 "shield", "sword", "name"):
        assert npc_this.get(name) == "", name
        assert not gs2_eq(npc_this.get(name), "somestring")
    # guild is derived from the nick, exactly as TServerPlayer::setNick does
    assert npc_this.get("guild") == "Watch"


def test_showimg_handle_strings_answer():
    """TShowImg registers 13 string-typed properties
    (src/TShowImgProperties.cpp:144-558). An unwritten one used to read
    0.0."""
    layer = _LayerImage(200, {"image": "block.png"})
    for name in ("text", "font", "style", "position", "shadowoffset",
                 "shadowcolor", "code", "attachoffset", "movementvector",
                 "sound", "rotationcenter"):
        assert layer.get(name) == "", name
        assert not gs2_eq(layer.get(name), "somestring")
    assert layer.get("image") == "block.png"


def test_new_object_carries_its_constructor_name():
    rt = _runtime()
    obj = rt.host.create_object("TStaticVar", "MyThing")
    assert obj.get("name") == "MyThing"
    assert not gs2_eq(rt.host.create_object("TStaticVar", None).get("name"),
                      "somestring")


# -- T2 ----------------------------------------------------------------------

def test_testnpc_and_testplayer_route_to_the_gs1_probe():
    """Already implemented in gs1_client._test_at, just absent from the GS2
    routing table -- so every GS2 spelling read 0.0, i.e. "hit npcs[0]", for
    a probe whose miss value is negative (src/TInitStatics.cpp:4278 body
    :3880-3900. Src/TServerLevelProperties.cpp:263)."""
    rt = _runtime(npcs={1: {"x": 10.0, "y": 10.0, "image": "sign.png"}})
    rt.gs1.shapes[1] = (2, 2)       # setshape box, in tiles
    assert call(rt, "testnpc", [10.5, 10.5]) == 0.0
    assert call(rt, "testnpc", [40, 40]) == -1.0
    assert call(rt, "testnpc", [40, 40], obj=rt.level_object) == -1.0
    assert call(rt, "testplayer", [40, 40]) == -2.0


def test_freezetime_setter_quantises_and_clamps():
    """propfun_player_freezetime_w: int(seconds * 20 + 1e-4) ticks, capped at
    600 (== 30 s), negatives freeze for nothing
    (src/TPlayerProperties.cpp:20-37)."""
    rt = _runtime()
    rt.player_object.set("freezetime", 900)
    assert rt.player_object.get("freezetime") <= 30.0
    assert rt.player_object.get("freezetime") > 29.0
    rt.player_object.set("freezetime", 0.03)     # under one tick -> nothing
    assert rt.player_object.get("freezetime") == -1.0
    rt.player_object.set("freezetime", 2.0)
    assert 1.9 < rt.player_object.get("freezetime") <= 2.0
    rt.player_object.set("freezetime", -5)
    assert rt.player_object.get("freezetime") == -1.0


def test_zoomfactor_is_clamped_to_the_reference_range():
    """value <= 16.0 ? max(value, 1.0) : 16.0 (src/TPlayerProperties.cpp:41-49,
    with FLOAT_0040231c = 16.0 / FLOAT_004022c0 = 1.0 at
    src/TInitStatics.cpp:1221,1226)."""
    rt = _runtime()
    camera = SimpleNamespace(zoom=1.0)
    rt.game_shell = SimpleNamespace(camera=camera, inventory_ui=None,
                                    walk_speed=4.0)
    rt.player_object.set("zoomfactor", 100)
    assert camera.zoom == 16.0 and rt.player_object.get("zoomfactor") == 16.0
    rt.player_object.set("zoomfactor", -3)
    assert camera.zoom == 1.0
    rt.player_object.set("zoomfactor", 2.5)
    assert camera.zoom == 2.5


def test_selectedweapon_write_is_bounds_checked():
    """propfun_gsfunctionsclient_selectedweapon_w ignores a negative index or
    one past the end of the weapon array, and adopts the sword slot when that
    is still unselected (src/TInitStatics.cpp:2662-2668)."""
    rt = _runtime(weapons={"bomb": {}, "bow": {}})
    inventory = SimpleNamespace(selected_weapon_idx=0, cursor_weapon_idx=0)
    rt.game_shell = SimpleNamespace(inventory_ui=inventory, camera=None)
    rt.globals_store["selectedweapon"] = 1
    assert inventory.selected_weapon_idx == 1
    assert rt.host.get_object("selectedweapon") == 1.0
    assert rt.host.get_object("selectedsword") == 1.0
    rt.globals_store["selectedweapon"] = 9      # past the end -> ignored
    assert inventory.selected_weapon_idx == 1
    rt.globals_store["selectedweapon"] = -1     # negative -> ignored
    assert inventory.selected_weapon_idx == 1
    # and the write never leaks into the globals dict, which _lookup consults
    # before the host and would otherwise answer forever
    assert "selectedweapon" not in dict(rt.globals_store)


def test_selectedweapon_reads_minus_one_with_no_weapons():
    rt = _runtime()
    assert rt.host.get_object("selectedweapon") == -1.0
    assert rt.host.get_object("selectedsword") == -1.0


def test_player_stat_members_bridge_to_the_client():
    rt = _runtime()
    rt.client.player.hearts, rt.client.player.max_hearts = 2.5, 5.0
    rt.client.player.glove_power = 2
    rt.client.player.horse_image = "horse1.png"
    assert rt.player_object.get("hp") == 2.5
    assert rt.player_object.get("maxhp") == 5.0
    assert rt.player_object.get("glovepower") == 2.0
    assert rt.player_object.get("horseimg") == "horse1.png"
    rt.player_object.set("glovepower", -4)      # setter floors at 0
    assert rt.client.player.glove_power == 0
    rt.player_object.set("maxhp", 99)           # RO in the reference
    assert rt.client.player.max_hearts == 5.0


def test_player_ani_reads_the_animation_field():
    """player.ani was permanently "".

    `_PLAYER_MEMBER_ATTR["ani"]` pointed at `gani`, which is the key the
    REMOTE-player record dicts use (packets.parse_other_player). The local
    Player dataclass keeps it in `.animation` and nothing ever sets `.gani`.
    So every `player.ani == "idle"` / "walk" / "sword" branch in content was
    dead, and `player.ani = "x"` landed on an attribute no one reads."""
    rt = _runtime()
    rt.client.player.animation = "walk"
    assert to_str(rt.player_object.get("ani")) == "walk"
    assert gs2_eq(rt.player_object.get("ani"), "walk")
    assert not gs2_eq(rt.player_object.get("ani"), "idle")
    rt.player_object.set("ani", "sword")
    assert rt.client.player.animation == "sword"
    assert to_str(rt.player_object.get("gani")) == "sword"


def test_player_state_flags_come_from_the_gs1_host():
    rt = _runtime()
    assert rt.player_object.get("online") is True
    assert rt.player_object.get("onhorse") is False
    rt.client.player.horse_image = "horse1.png"
    assert rt.player_object.get("onhorse") is True


def test_gani_transform_defaults_are_the_identity_transform():
    """The reference getters are raw addresses (src/TGaniObjectProperties.cpp:
    199-289), so only the names/types are oracle-backed. The point of the
    defaults is that an unwritten slot is not a zero scale."""
    rt = _runtime()
    assert rt.player_object.get("zoom") == 1.0
    assert rt.player_object.get("alpha") == 1.0
    assert rt.player_object.get("rotation") == 0.0
    rt.player_object.set("zoom", 2.0)
    assert rt.player_object.get("zoom") == 2.0


def test_carry_map_and_attachment_globals():
    rt = _runtime()
    assert rt.host.get_object("iscarrying") is False
    assert rt.host.get_object("isonmap") is False
    rt.client.gmap_width = 4
    assert rt.host.get_object("isonmap") is True
    # levelorgx/y are the attach target's LOCAL x/y, 0 when nothing is
    # attached (src/TInitStatics.cpp:2433-2455) -- pyReborn models no
    # attachment, so 0.0 is the reference's own answer here
    assert rt.host.get_object("levelorgx") == 0.0
    assert rt.host.get_object("levelorgy") == 0.0
    assert rt.host.get_object("allfeatures") == 65535.0
    assert rt.host.get_object("allrenderobjecttypes") == 63.0


def test_worldxy_is_the_inverse_of_screenxy():
    """floor(arg + 1e-4) then screenToWorldX/Y (src/TInitStatics.cpp:
    3906-3921). worldx genuinely ignores its second argument."""
    rt = _runtime()

    class _Camera:
        def screen_to_world(self, sx, sy):
            return (sx / 16.0, sy / 16.0)

    rt.game_shell = SimpleNamespace(camera=_Camera(), inventory_ui=None)
    assert call(rt, "worldx", [32.0, 999.0]) == 2.0
    assert call(rt, "worldy", [32.0, 64.0]) == 4.0


def test_mouse_button_globals_report_the_mask():
    rt = _runtime()
    assert rt.host.get_object("mousebuttons") == 0.0
    rt.gs1.mouse_left = True
    assert rt.host.get_object("mousebuttons") == 1.0
    assert rt.host.get_object("mousebuttonsglobal") == 1.0
    assert rt.host.get_object("rightmousebutton") is False
    assert rt.host.get_object("mousewheeldelta") == 0.0
