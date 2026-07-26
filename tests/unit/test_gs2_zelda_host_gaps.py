"""Host surface the live Zelda: A Link to the Past server exercises.

Call sites are in the server's own scripts (third-party checkout, read-only:
Preagonal/graal-lttp) and the shapes are pinned against the reference
engine's script bindings (Preagonal/FourPlay, quattroplay/src).
"""

from types import SimpleNamespace

from reborn_protocol.gs2 import GS2Object, GS2VM, NOT_HANDLED
from reborn_protocol.gs2.container import GS2Container

from game_tester.server_crawl import classify_host_call
from pyreborn.gs2_client import ClientGS2, GS2ClientHost


def call(rt, name, args=(), obj=None, vm=None):
    return rt.host.call_builtin(vm, name, list(args), obj=obj)


def _weapon_vm(rt, key="-player/movement"):
    vm = GS2VM(GS2Container(), name=f"weapon:{key}")
    vm._gs2_kind, vm._gs2_key = "weapon", key
    vm._gs2_owner = ("weapon", key)
    rt.vms["weapon"][key] = vm
    return vm


# -- findnearestplayers ----------------------------------------------------

def _combat_client():
    local = SimpleNamespace(x=30.0, y=30.0, gani="zlttp_idle", account="me",
                            nickname="Me", id=1, direction=2)
    players = {
        3: {"x": 40.0, "y": 30.0, "account": "far", "nickname": "Far",
            "ani": "zlttp_idle", "direction": 1, "sword_power": 2},
        2: {"x": 31.0, "y": 30.0, "account": "near", "nickname": "Near",
            "ani": "zlttp_sword", "direction": 3, "sword_power": 4},
    }
    return SimpleNamespace(player=local, players=players, x=30.0, y=30.0)


def test_findnearestplayers_returns_objects_nearest_first_including_self():
    # weapon-Player_Movement.txt:732 CheckHurt:
    #   for (temp.i: findnearestplayers(player.x+1.5, player.y+2))
    rt = ClientGS2(_combat_client())
    found = call(rt, "findnearestplayers", [31.5, 32.0])
    assert [item.get("account") for item in found] == ["me", "near", "far"]
    # self is the very object `pl != player` compares against
    assert found[0] is rt.player_object
    # ...and the same remote object comes back on the next call (identity is
    # what -Serverlist_Observer's `if (temp.pl != player)` needs)
    assert call(rt, "findnearestplayers", [31.5, 32.0])[1] is found[1]


def test_findnearestplayers_entries_expose_the_combat_members():
    rt = ClientGS2(_combat_client())
    near = call(rt, "findnearestplayers", [31.5, 32.0])[1]
    # `i.ani.name == "zlttp_sword"`, `i.dir`, `i.swordpower`, `i.account`
    assert near.get("ani").get("name") == "zlttp_sword"
    assert str(near.get("ani")) == "zlttp_sword"
    assert near.get("dir") == 3 and near.get("swordpower") == 4
    assert (near.get("x"), near.get("y")) == (31.0, 30.0)
    # the local player's animation answers `.name` the same way
    assert rt.player_object.get("ani").get("name") == "zlttp_idle"


def test_findnearestplayers_forgets_players_who_left():
    client = _combat_client()
    rt = ClientGS2(client)
    call(rt, "findnearestplayers", [30, 30])
    del client.players[3]
    found = call(rt, "findnearestplayers", [30, 30])
    assert [item.get("account") for item in found] == ["me", "near"]
    assert set(rt._script_players) == {2}


def test_findnearestplayers_is_not_getnearestplayers():
    """Same sort, different PAYLOAD: findnearestplayers hands back the
    player objects, getnearestplayers the players[] indices
    (TInitStatics.cpp:2088 vs :2067 -- the latter emits
    players->indexOf(entry) per sorted entry). Both rank the same list,
    ourselves included: RenderNicks (weapon-Player_Movement.txt:88-91)
    indexes players[] with the result and then branches on whether the
    entry is us."""
    rt = ClientGS2(_combat_client())
    indices = call(rt, "getnearestplayers", [31.5, 32.0])
    assert indices == [0.0, 2.0, 1.0]
    players = rt.player_list_objects()
    assert [players[int(i)].get("account") for i in indices] == \
        ["me", "near", "far"]
    assert [p.get("account") for p in
            call(rt, "findnearestplayers", [31.5, 32.0])] == \
        ["me", "near", "far"]


def test_findnearestplayer_singular_returns_only_the_winner():
    # weapon-Player_Movement.txt:848 (lift): temp.pl = findnearestplayer(px,py)
    rt = ClientGS2(_combat_client())
    assert call(rt, "findnearestplayer", [40.0, 32.0]).get("account") == "far"
    empty = ClientGS2(SimpleNamespace(player=None, players={}))
    assert call(empty, "findnearestplayer", [0, 0]) == 0.0


# -- getstringkeys ---------------------------------------------------------

def _flag_runtime(flags):
    rt = ClientGS2()
    rt.gs1 = SimpleNamespace(_shared={"client": dict(flags), "server": {}})
    return rt


def test_getstringkeys_lists_matching_flags_with_the_prefix_stripped():
    # weapon-Player_Functions.txt:222 addMinorFlag:
    #   temp.chk = getstringkeys("clientr.minorflags_").size();
    rt = _flag_runtime({"minorflags_zora": 1, "minorflags_bomb": "yes",
                        "majorflags_hookshot": 1})
    assert call(rt, "getstringkeys", ["clientr.minorflags_"]) == ["bomb", "zora"]
    # the scope token is optional: our stores key player flags unprefixed
    assert call(rt, "getstringkeys", ["minorflags_"]) == ["bomb", "zora"]


def test_getstringkeys_drops_empty_and_zero_flags():
    rt = _flag_runtime({"stat_a": 3, "stat_b": 0, "stat_c": "", "stat_d": "x"})
    assert call(rt, "getstringkeys", ["client.stat_"]) == ["a", "d"]


def test_getstringkeys_reads_the_server_scopes_too():
    rt = _flag_runtime({})
    rt.gs1._shared["server"] = {"bombrm_1": 1, "serverr.lobby_2": 1}
    assert call(rt, "getstringkeys", ["server.bombrm_"]) == ["1"]
    assert call(rt, "getstringkeys", ["serverr.lobby_"]) == ["2"]


# -- getcallstack ----------------------------------------------------------

def test_getcallstack_is_empty_until_the_vm_publishes_frames():
    """The reference binding returns an empty array as well (quattroplay
    TInitStatics.cpp:2242), and both live call sites survive it."""
    rt = ClientGS2()
    vm = _weapon_vm(rt)
    assert call(rt, "getcallstack", vm=vm) == []
    assert call(rt, "getcallstack", obj=vm.this, vm=vm) == []


def test_getcallstack_entry_shape_when_frames_exist():
    rt = ClientGS2()
    vm = _weapon_vm(rt)
    caller = GS2VM(GS2Container(), name="weapon:-npc")
    caller.this = GS2Object(name="-NPC/Deleter")
    vm.call_stack = [(caller, "onCreated"), (vm, "destroy")]
    stack = call(rt, "getcallstack", vm=vm)
    # `stack[stack.size()-2].scriptcallobject.name` -> the CALLER
    assert stack[len(stack) - 2].get("scriptcallobject").name == "-NPC/Deleter"
    assert stack[-1].get("name") == "destroy"


# -- isinclass / leave -----------------------------------------------------

def _joined_runtime():
    rt = ClientGS2()
    weapon = _weapon_vm(rt, "gui_user")
    class_vm = GS2VM(GS2Container(), name="class:gui_builder")
    class_vm._gs2_kind, class_vm._gs2_key = "class", "gui_builder"
    rt.vms["class"]["gui_builder"] = class_vm
    assert rt.join_class(weapon, "gui_builder")
    return rt, weapon


def test_isinclass_and_leave_follow_the_joiners_class_list():
    # class:gui_builder built(): this.leave("gui_builder") then
    # echo(... this.isinclass("gui_builder")) -- the echo shows it gone.
    rt, weapon = _joined_runtime()
    assert call(rt, "isinclass", ["gui_builder"], obj=weapon.this, vm=weapon) == 1.0
    call(rt, "leave", ["gui_builder"], obj=weapon.this, vm=weapon)
    assert call(rt, "isinclass", ["gui_builder"], obj=weapon.this, vm=weapon) == 0.0
    assert weapon.joined == []


def test_leave_from_inside_the_class_instance_detaches_the_joiner():
    rt, weapon = _joined_runtime()
    instance = weapon.joined[0]
    assert call(rt, "isinclass", ["gui_builder"], vm=instance) == 1.0
    call(rt, "leave", ["gui_builder"], vm=instance)
    assert weapon.joined == []
    assert call(rt, "isinclass", ["gui_builder"], vm=instance) == 0.0


def test_leave_clears_a_join_still_waiting_on_bytecode():
    rt = ClientGS2()
    weapon = _weapon_vm(rt, "waiting")
    assert not rt.join_class(weapon, "absent")
    assert rt._pending_joins["absent"] == [weapon]
    call(rt, "leave", ["absent"], vm=weapon)
    assert "absent" not in rt._pending_joins


# -- GS2 -> GS1 caption text -----------------------------------------------

def test_gs2_numbers_reaching_gs1_captions_use_the_gs2_print_rule():
    """The engines print numbers differently on purpose (GS2: "%.9f"
    trimmed; GS1/GServer: the shortest round-tripping repr), so a bare
    number a GS2 script passes as caption text must be converted at the
    bridge -- otherwise showtext(.., 2/3) draws 0.6666666666666666 where the
    reference client draws 0.666666667."""
    args = ClientGS2._gs1_args("showtext", [0, 30.0, 20.0, "arial", "", 2 / 3])
    assert args[5] == "0.666666667"
    assert args[1] == 30.0 and args[2] == 20.0     # coordinates stay numeric
    assert ClientGS2._gs1_args("say2", [1 / 3])[0] == "0.333333333"
    # values under the machine's epsilon print as a plain "0"
    assert ClientGS2._gs1_args("showtext", [0, 0, 0, "a", "", 0.00005])[5] == "0"
    # commands with no caption argument are passed through untouched
    assert ClientGS2._gs1_args("showimg", [1, "x.png", 2 / 3]) == [1, "x.png", 2 / 3]


# -- classification --------------------------------------------------------

def test_new_zelda_calls_classify_as_implemented():
    surface = set(GS2ClientHost.host_surface())
    stubbed = set(GS2ClientHost.stubbed)
    for name in ("findnearestplayers", "findnearestplayer", "getstringkeys",
                 "getcallstack", "isinclass", "leave"):
        assert classify_host_call(name, surface, stubbed) == "implemented"


def test_len_is_deliberately_not_a_host_call():
    """`clientr.stat_swordslashed.len()` (weapon-Player_Functions.txt:223)
    stays a gap ON PURPOSE: the official compiler lowers only `.length()`
    to an opcode (GS2Compiler.cs:1373) and neither the reference engine's
    var properties nor its gsfunctions table binds `len`, so the reference
    client leaves that call unresolved too. Implementing it here would make
    pyReborn show a chat bubble the real client never shows."""
    assert "len" not in {name.casefold() for name in GS2ClientHost.host_surface()}
    assert call(ClientGS2(), "len", obj="abcd") is NOT_HANDLED


# -- player.attr[] / .colors[] on remote players ---------------------------

def test_remote_player_attr_reads_that_players_gattribs():
    """Zelda's lift loop polls `pl.attr[3] == player.account` on the player
    it just asked the server to pick up (weapon-Player_Movement.txt:858), and
    packs the carried player's appearance from `pl.headimg`/`pl.colors[0..4]`
    (:201-208). attr is ONE-BASED with a permanently empty cell 0 -- the
    reference builds it that way (FourPlay TGaniObject.cpp:332-344 adds an
    empty var first, then TGaniParam(this, i) for i = 1..30) -- which is why
    the script guards `pl.attr[0] != null`."""
    client = _combat_client()
    client.players[2]["gattrib3"] = "me"
    client.players[2]["gattrib30"] = "last"
    client.players[2]["colors"] = [3, 4, 5, 6, 7]
    rt = ClientGS2(client)
    near = call(rt, "findnearestplayer", [32.5, 32.0])
    assert near.get("account") == "near"
    assert near.get("attr").get("3") == "me"
    assert near.get("attr").get("30") == "last"
    assert near.get("attr").get("0") is None        # always null, by design
    assert near.get("attr").get("31") is None       # out of range
    assert near.get("attr").get("7") == ""          # unset slot, not null
    assert [near.get("colors").get(str(i)) for i in range(5)] == \
        [3.0, 4.0, 5.0, 6.0, 7.0]


def test_remote_player_attr_follows_a_re_created_record():
    """The view is bound to the player ID, not to one record dict, so it
    keeps working after client.players[id] is rebuilt."""
    client = _combat_client()
    rt = ClientGS2(client)
    attr = call(rt, "findnearestplayer", [32.5, 32.0]).get("attr")
    client.players[2] = {"x": 31.0, "y": 30.0, "account": "near",
                         "gattrib3": "fresh"}
    assert attr.get("3") == "fresh"


def test_local_player_attr_writes_go_to_the_one_shared_gattrib_store():
    """`player.attr[3] = ...` is how Zelda publishes what it is carrying, so
    it has to reach the wire -- through the same single writer GS1's
    `setplayerprop #P3` uses, or the two engines disagree."""
    from pyreborn.gs1_client import ClientGS1
    sent = []
    client = _combat_client()
    client.set_gattrib = lambda index, value: sent.append((index, value))
    gs1 = ClientGS1(client)
    rt = ClientGS2(client, gs1)
    rt.player_object.get("attr").set("3", "zlttp_lift-bush.png")
    assert sent == [(3, "zlttp_lift-bush.png")]
    assert gs1._player_props["P3"] == "zlttp_lift-bush.png"
    assert rt.player_object.get("attr").get("3") == "zlttp_lift-bush.png"


def test_writing_another_players_attr_sends_nothing():
    """Another player's attributes are server-owned: keep the local copy
    consistent for the rest of the frame, put nothing on the wire."""
    sent = []
    client = _combat_client()
    client.set_gattrib = lambda index, value: sent.append((index, value))
    rt = ClientGS2(client)
    call(rt, "findnearestplayer", [32.5, 32.0]).get("attr").set("3", "x")
    assert client.players[2]["gattrib3"] == "x"
    assert sent == []


# -- string-valued identity properties -------------------------------------

def test_string_identity_properties_never_read_as_an_unset_member():
    """An unset member reads as None, and None compares EQUAL to any
    non-numeric string (both coerce to 0), so every `player.<prop> ==
    "<literal>"` in real content fires. Live-measured on Login: 48
    player.platform comparisons per 25s session, which hid the taskbar
    (weapon-Rescripted_Serverlist.txt:336, :2247) and ran the serverlist's
    update loop on the iPhone's 1 Hz timer (:405)."""
    import pyreborn.gs2_client as gs2_client_module
    rt = ClientGS2(_combat_client())
    player = rt.player_object
    assert player.get("platform") == gs2_client_module.PLATFORM_NAME
    assert player.get("platform") not in ("linuxstream", "iphone", "android")
    assert player.get("communityname") == ""


def test_guild_is_derived_from_the_nickname_for_local_and_remote_players():
    """Reference TServerPlayer::setNick (TServerPlayer.cpp:300-340) keeps the
    text between the first '(' and the next ')'. era/GTA content
    string-compares guilds ~534 times."""
    client = _combat_client()
    client.player.nickname = "Me (Events Team)"
    client.players[2]["nickname"] = "Near"
    rt = ClientGS2(client)
    assert rt.player_object.get("guild") == "Events Team"
    assert call(rt, "findplayer", ["near"]).get("guild") == ""


# -- bare `weapons` / player.weapons ---------------------------------------

def _weapon_client():
    local = SimpleNamespace(x=30.0, y=30.0, account="me", nickname="Me", id=1,
                            direction=2)
    weapons = {
        "*System": {"image": ""},
        "-Player/Movement": {"image": ""},
        "Hammer": {"image": "zlttp_hammer.png"},
        "Bomb": {"image": "bcbomb.png"},
    }
    return SimpleNamespace(player=local, players={}, x=30.0, y=30.0,
                           weapons=weapons)


def test_bare_weapons_global_is_the_players_weapon_list():
    """`weapons` is a read-only global on the client function table returning
    activeplayer->weapons (TInitStatics.cpp:2700-2703, bound at :2784), so a
    bare reference must resolve without a `player.` qualifier. Zelda's
    secondary fire is the only path to a weapon's onWeaponFired:
    `findweapon(weapons[selectedweapon].name).trigger("onweaponfired", null)`
    (Preagonal/graal-lttp/weapons/weapon-Player_Movement.txt:473)."""
    rt = ClientGS2(_weapon_client())
    bare = rt.host.get_object("weapons")
    assert [w.get("name") for w in bare] == [
        "*System", "-Player/Movement", "Hammer", "Bomb"]
    assert bare[2].get("image") == "zlttp_hammer.png"
    assert [w.get("name") for w in rt.player_object.get("weapons")] == \
        [w.get("name") for w in bare]


def test_findweapon_on_a_bare_weapons_entry_reaches_the_weapon_vm():
    """The chain the D key walks: weapons[i].name -> findweapon -> the
    weapon's this-object, which is what `.trigger()` needs. An unresolved
    `weapons` made findweapon("") return 0.0, and the trigger then landed on
    a number -- reported as "unknown method trigger()"."""
    rt = ClientGS2(_weapon_client())
    vm = _weapon_vm(rt, "hammer")
    name = rt.host.get_object("weapons")[2].get("name")
    assert call(rt, "findweapon", [name]) is vm.this
    assert call(rt, "findweapon", [""]) == 0.0


# -- tiletype: both spellings, gmap-aware ----------------------------------

def _tile_probe_rt(tile_source):
    from pyreborn.gs1_client import ClientGS1
    client = _weapon_client()
    client.tiles = None
    client.npcs, client.level_links = {}, {}
    gs1 = ClientGS1(client)
    gs1.tile_source = tile_source
    return ClientGS2(client, gs1)


def test_tiletype_resolves_gmap_world_coordinates():
    """It must answer from the GS1 host, whose tile_at prefers the client's
    gmap-aware segment lookup. A host-local `0 <= x < 64` version answers 0
    for every coordinate on Zelda's 10x10 gmap, silently telling the movement
    engine that no chair, bed or ledge exists anywhere."""
    from pyreborn.tiletypes import get_tile_type
    chair = next(t for t in range(4096) if get_tile_type(t) == 3)
    rt = _tile_probe_rt(lambda x, y: chair if (int(x), int(y)) == (297, 355)
                        else 0)
    assert call(rt, "tiletype", [297, 355]) == 3.0
    assert call(rt, "tiletype", [298, 355]) == 0.0


def test_level_tiletype_member_form_routes_like_the_bare_call():
    """`level.tiletype(x, y)` is the member spelling of the same TServerLevel
    probe (weapon-Player_Movement.txt:369-370; the bare form is at :451).
    The obj-method block exits NOT_HANDLED, so without an explicit route the
    member form was 198 "unknown method" misses per second of live play."""
    from pyreborn.tiletypes import get_tile_type
    chair = next(t for t in range(4096) if get_tile_type(t) == 3)
    rt = _tile_probe_rt(lambda x, y: chair if (int(x), int(y)) == (297, 355)
                        else 0)
    level = rt.player_object.get("level")
    assert call(rt, "tiletype", [297, 355], obj=level) == 3.0
    assert call(rt, "onwater", [297, 355], obj=level) is False
