"""Client GS1 positions on a gmap are whole-map tiles (gs1_client/frame.py).

The reference client reads an NPC's `x` as `local + (mapX << 6)` and stores a
write as `x - (mapX << 6)` in the same cell
(Preagonal/FourPlay/quattroplay/src/TServerNPCProperties.cpp:331-345). An
NPC in segment (1, 1) of a 3x3 map at local (53, 43) therefore reads
(117, 107), and `x = 117.5; y = 106.5;` leaves it at local (53.5, 42.5),
world (117.5, 106.5), still in cell (1, 1) -- the live barkeep in
chicken1.nw. Off a gmap every value is the one the host returned before.
"""

from types import SimpleNamespace

import pytest

from pyreborn import Client
from pyreborn.gs1_client import ClientGS1
from pyreborn.npc_handler import place_npc
from pyreborn.packets import PacketID, build_baddy_hurt, build_item_add

_ITEM_GREENRUPEE = 0
BARKEEP = 7      # an NPC in the centre cell (1, 1)
CORNER = 8       # an NPC in the origin cell (0, 0)


class _SentRecorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def _gmap_client(*, connected=False):
    """A 3x3 gmap session, the player in chicken1.nw = cell (1, 1)."""
    client = Client("localhost", 14900)
    client.gmap_width = client.gmap_height = 3
    for gy in range(3):
        for gx in range(3):
            client.gmap_grid[(gx, gy)] = f"seg{gx}{gy}.nw"
    client.gmap_grid[(1, 1)] = "chicken1.nw"
    client._current_level_name = "chicken1.nw"
    client.player.x, client.player.y = 89.0, 74.0
    _add_npc(client, BARKEEP, 53.0, 43.0, (1, 1), "chicken1.nw")
    _add_npc(client, CORNER, 20.0, 22.0, (0, 0), "seg00.nw")
    if connected:
        client._authenticated = True
        client._protocol = _SentRecorder()
    return client


def _plain_client(*, connected=False):
    client = Client("localhost", 14900)
    client._current_level_name = "house.nw"
    client.player.x, client.player.y = 30.0, 30.0
    _add_npc(client, BARKEEP, 53.0, 43.0, None, "house.nw")
    if connected:
        client._authenticated = True
        client._protocol = _SentRecorder()
    return client


def _add_npc(client, npc_id, x, y, cell, level):
    npc = {"x": x, "y": y, "_level": level, "image": "-"}
    if cell is not None:
        npc["gmaplevelx"], npc["gmaplevely"] = cell
    place_npc(client.gmap_grid, npc)
    client.npcs[npc_id] = npc
    return npc


def _run(client, npc_id, code, event="created"):
    gs1 = ClientGS1(client)
    key = f"npc_{npc_id}"
    gs1.load_script(key, code, npc_id=npc_id)
    gs1.trigger_event(event, name=key)
    return gs1, gs1._progs[key]["scopes"]["this"]


def _where(npc):
    return (npc["x"], npc["y"], npc["world_x"], npc["world_y"],
            npc.get("gmaplevelx"), npc.get("gmaplevely"), npc["_level"])


# -- NPC x/y: read ------------------------------------------------------------

def test_npc_reads_whole_map_position_in_a_non_origin_cell():
    client = _gmap_client()
    _gs1, this = _run(client, BARKEEP, "this.rx = x; this.ry = y;")
    assert (this["rx"], this["ry"]) == (117.0, 107.0)


def test_npc_reads_local_position_in_the_origin_cell():
    client = _gmap_client()
    _gs1, this = _run(client, CORNER, "this.rx = x; this.ry = y;")
    assert (this["rx"], this["ry"]) == (20.0, 22.0)


def test_npc_distance_to_player_uses_one_frame():
    # The barkeep's own timeout test: abs(playerx - x) on the same map.
    client = _gmap_client()
    _gs1, this = _run(client, BARKEEP,
                      "this.dx = abs(playerx - x); this.dy = abs(playery - y);")
    assert (this["dx"], this["dy"]) == (28.0, 33.0)


def test_npcs_array_reads_whole_map_position():
    client = _gmap_client()
    _gs1, this = _run(client, CORNER,
                      "this.ax = npcs[0].x; this.ay = npcs[0].y;"
                      "this.bx = npcs[1].x; this.by = npcs[1].y;")
    # npcs[] is id order: BARKEEP (7) then CORNER (8)
    assert (this["ax"], this["ay"], this["bx"], this["by"]) == (
        117.0, 107.0, 20.0, 22.0)


def test_findnpc_reference_reads_and_writes_whole_map_position():
    client = _gmap_client()
    client.npcs[BARKEEP]["nickname"] = "barkeep"
    _gs1, this = _run(client, CORNER,
                      "with (findnpc(\"barkeep\")) { this.rx = x; x = 100; y = 90; }")
    assert this["rx"] == 117.0
    assert _where(client.npcs[BARKEEP]) == (
        36.0, 26.0, 100.0, 90.0, 1, 1, "chicken1.nw")


# -- NPC x/y: write -----------------------------------------------------------

def test_npc_write_lands_local_to_its_cell():
    client = _gmap_client()
    _run(client, BARKEEP, "x = 117.5; y = 106.5;")
    assert _where(client.npcs[BARKEEP]) == (
        53.5, 42.5, 117.5, 106.5, 1, 1, "chicken1.nw")


def test_npc_write_round_trips_through_a_read():
    client = _gmap_client()
    _gs1, this = _run(client, BARKEEP, "x = x + 1; this.rx = x;")
    assert this["rx"] == 118.0
    assert client.npcs[BARKEEP]["x"] == 54.0


def test_npc_write_in_the_origin_cell():
    client = _gmap_client()
    _run(client, CORNER, "x = 30; y = 31;")
    assert _where(client.npcs[CORNER]) == (30.0, 31.0, 30.0, 31.0, 0, 0, "seg00.nw")


@pytest.mark.parametrize("code,local,world", [
    # into cell (2, 1): the NPC keeps cell (1, 1) and a local past 63
    ("x = 140;", (76.0, 43.0), (140.0, 107.0)),
    # into cell (0, 1): a negative local, same cell
    ("x = 10;", (-54.0, 43.0), (10.0, 107.0)),
    # into cell (1, 2)
    ("y = 130;", (53.0, 66.0), (117.0, 130.0)),
])
def test_npc_write_into_another_cell_keeps_the_cell(code, local, world):
    # setlocalx stores whatever it is given (TGaniObject.cpp:1346-1358) and no
    # client code re-files a script-moved NPC, so the cell stays (1, 1).
    client = _gmap_client()
    _run(client, BARKEEP, code)
    assert _where(client.npcs[BARKEEP]) == (
        *local, *world, 1, 1, "chicken1.nw")


def test_non_gmap_npc_writes_apply_only_inside_the_level():
    # propfun_servernpc_x_w stores a write only for a map-owned NPC or a value
    # in 0 <= x < 64 (TServerNPCProperties.cpp:336, y at :343): off a gmap
    # `x = 70` is ignored, which the engine used to apply.
    client = _plain_client()
    _gs1, this = _run(client, BARKEEP, "this.rx = x; x = 70; y = 2.5; this.wx = x;")
    assert this["rx"] == 53.0
    assert this["wx"] == 53.0
    npc = client.npcs[BARKEEP]
    assert (npc["x"], npc["y"], npc["world_x"], npc["world_y"]) == (53.0, 2.5, 53.0, 2.5)


def test_npc_on_a_level_outside_the_loaded_gmap_stays_local():
    # An interior entered from the map: no cell, so its frame is local.
    client = _gmap_client()
    client._current_level_name = "house.nw"
    _add_npc(client, 9, 12.0, 14.0, None, "house.nw")
    _gs1, this = _run(client, 9, "this.rx = x; x = 13;")
    assert this["rx"] == 12.0
    assert (client.npcs[9]["x"], client.npcs[9]["world_x"]) == (13.0, 13.0)


# -- queries that compare an NPC position with script coordinates ------------

def test_testnpc_finds_a_shaped_npc_by_whole_map_tile():
    client = _gmap_client()
    gs1 = ClientGS1(client)
    gs1.shapes[BARKEEP] = (2.0, 2.0, ())
    host = gs1._host
    ctx = SimpleNamespace(this_obj=None)
    assert host.call_function("testnpc", [118.0, 108.0], ctx) == 0.0
    assert host.call_function("testnpc", [54.0, 44.0], ctx) == -1.0


def test_testnpc_finds_a_character_npc_by_whole_map_tile():
    client = _gmap_client()
    client.npcs[BARKEEP]["gani"] = "idle"
    host = ClientGS1(client)._host
    ctx = SimpleNamespace(this_obj=None)
    # the character square starts at (x + 0.5, y + 1)
    assert host.call_function("testnpc", [118.0, 109.0], ctx) == 0.0
    assert host.call_function("testnpc", [54.0, 45.0], ctx) == -1.0


def test_hitobjects_hits_an_npc_at_its_whole_map_position():
    client = _gmap_client()
    gs1 = ClientGS1(client)
    gs1.load_script("npc_7", "if (washit) { this.hit = 1; }", npc_id=BARKEEP)
    gs1.hit_objects_at(53.0, 43.0)
    assert "hit" not in gs1._progs["npc_7"]["scopes"]["this"]
    gs1.hit_objects_at(117.0, 107.0)
    assert gs1._progs["npc_7"]["scopes"]["this"]["hit"] == 1.0


def test_hitobjects_hurts_a_baddy_at_its_whole_map_position():
    client = _gmap_client(connected=True)
    client.baddies["chicken1.nw"] = {3: {"x": 10.0, "y": 12.0}}
    gs1 = ClientGS1(client)
    gs1.hit_objects_at(10.0, 12.0, power=1.5)
    assert not client._protocol.sent
    gs1.hit_objects_at(74.0, 76.0, power=1.5)
    assert (int(PacketID.PLI_BADDYHURT), build_baddy_hurt(3, 1.5)) in client._protocol.sent


def _explode_from_corner(client, at):
    """The corner NPC's putexplosion; the barkeep records its washit."""
    gs1 = ClientGS1(client)
    gs1.load_script("npc_7", "if (washit) { this.hit = 1; }", npc_id=BARKEEP)
    gs1.load_script("npc_8", f"putexplosion 1,{at};", npc_id=CORNER)
    gs1.trigger_event("created", name="npc_8")
    return gs1._progs["npc_7"]["scopes"]["this"]


def test_putexplosion_hits_npcs_and_explodes_at_the_whole_map_position():
    client = _gmap_client()
    calls = []
    client.make_explosion = lambda *a: calls.append(a[:2])
    this = _explode_from_corner(client, "117,107")
    assert calls == [(117.0, 107.0)]
    assert this["hit"] == 1.0


def test_putexplosion_misses_an_npc_at_its_local_position():
    client = _gmap_client()
    client.make_explosion = lambda *a: None
    assert "hit" not in _explode_from_corner(client, "53,43")


# -- baddies (compus[]) --------------------------------------------------------

def test_compus_array_and_testcompu_are_whole_map():
    client = _gmap_client()
    client.baddies["chicken1.nw"] = {3: {"x": 10.0, "y": 12.0}}
    _gs1, this = _run(client, BARKEEP,
                      "this.cx = compus[0].x; this.cy = compus[0].y;"
                      "this.hit = testcompu(74, 76); this.miss = testcompu(10, 12);")
    assert (this["cx"], this["cy"]) == (74.0, 76.0)
    assert (this["hit"], this["miss"]) == (3.0, -1.0)


def test_hitcompu_pushes_away_from_a_whole_map_source():
    client = _gmap_client(connected=True)
    client.baddies["chicken1.nw"] = {3: {"x": 10.0, "y": 12.0}}
    client.is_leader = False
    seen = []
    client.hurt_baddy = lambda bid, damage, hurt_dx, hurt_dy: seen.append(
        (bid, hurt_dx, hurt_dy))
    # source 2 tiles west of the baddy's whole-map position (74, 76)
    _run(client, BARKEEP, "hitcompu 0,2,72,76;")
    assert seen == [(3, 1.0, 0.0)]


def test_hitplayer_pushes_a_remote_player_away_from_a_whole_map_source():
    client = _gmap_client(connected=True)
    client.players[5] = {"x": 30.0, "y": 10.0, "world_x": 94.0, "world_y": 74.0,
                         "level": "chicken1.nw"}
    seen = []
    client.attack_player = lambda pid, damage, knockback_x, knockback_y: seen.append(
        (pid, knockback_x, knockback_y))
    _run(client, BARKEEP, "hitplayer 1,2,94,72;")
    assert seen == [(5, 0, 2)]


# -- placing in the player's level --------------------------------------------

def test_lay2_files_the_item_local_to_the_players_level():
    client = _gmap_client(connected=True)
    _run(client, BARKEEP, "lay2 greenrupee,100,80;")
    assert client.items["chicken1.nw"] == {(36.0, 16.0): "greenrupee"}


def test_lay_files_one_item_in_the_players_level_and_tells_the_server():
    # Where `lay` puts the item (the NPC's centre moved to an edge by the
    # player's side, TServerNPCProperties.cpp:502-548) needs the NPC's pixel
    # size, which this client cannot always know: see the survey's recorded
    # divergence. What is pinned is that the level's copy and the wire agree.
    client = _gmap_client(connected=True)
    _run(client, BARKEEP, "lay greenrupee;")
    assert list(client.items["chicken1.nw"].values()) == ["greenrupee"]
    ((x, y),) = client.items["chicken1.nw"]
    sent = [data for pid, data in client._protocol.sent
            if pid == int(PacketID.PLI_ITEMADD)]
    assert sent == [build_item_add(x, y, _ITEM_GREENRUPEE)]


@pytest.mark.parametrize("code,local,removed", [
    # past the east edge of the player's cell (1, 1): local 76
    ("lay2 greenrupee,140,100;", (76.0, 36.0), True),
    # west of it: local -44, which the wire carries wrapped (TClient.cpp:976-980),
    # so the echo names 84 and misses the item at -44, as the reference's
    # removeExtra compares local half-tiles (TServerLevel.cpp:2769-2770)
    ("lay2 greenrupee,20,100;", (-44.0, 36.0), False),
])
def test_lay2_outside_the_players_cell_and_its_itemdel(code, local, removed):
    # The reference files the item at x - (level.mapX << 6), unwrapped, and
    # sends that local (TServerLevel.cpp:1348-1349, :1392). The server echoes
    # the wire's own bytes in PLO_ITEMDEL, so the echo must find the item.
    client = _gmap_client(connected=True)
    _run(client, BARKEEP, code)
    assert client.items["chicken1.nw"] == {local: "greenrupee"}
    sent = [data for pid, data in client._protocol.sent
            if pid == int(PacketID.PLI_ITEMADD)]
    assert sent == [build_item_add(*local, _ITEM_GREENRUPEE)]
    client._handle_packet(PacketID.PLO_ITEMDEL, sent[0][:2])
    assert client.items["chicken1.nw"] == ({} if removed else {local: "greenrupee"})


def test_lay2_off_a_gmap_is_unchanged():
    client = _plain_client(connected=True)
    _run(client, BARKEEP, "lay2 greenrupee,40,20;")
    assert client.items["house.nw"] == {(40.0, 20.0): "greenrupee"}


@pytest.mark.parametrize("make,probe", [
    (_gmap_client, (118.0, 108.0)),
    (_plain_client, (54.0, 44.0)),
])
def test_putbomb_water_probe_uses_the_board_frame(make, probe):
    client = make()
    gs1 = ClientGS1(client)
    probes = []
    gs1.is_water_at = lambda x, y: probes.append((x, y)) or False
    gs1.load_script("npc_7", "putbomb 1,117,107;", npc_id=BARKEEP)
    gs1.trigger_event("created", name="npc_7")
    assert probes == [probe]


@pytest.mark.parametrize("make,probe", [
    (_gmap_client, (89.0, 74.0)),
    (_plain_client, (30.0, 30.0)),
])
def test_playerswimming_probes_the_player_tile_in_the_board_frame(make, probe):
    client = make()
    gs1 = ClientGS1(client)
    probes = []
    gs1.is_water_at = lambda x, y: probes.append((x, y)) or False
    host = gs1._host
    assert host.get_builtin("playerswimming", [], SimpleNamespace(this_obj=None)) is False
    assert probes == [probe]


def test_take_reaches_an_item_of_the_players_level_by_whole_map_distance():
    # The item list is level-local; reach is measured whole-map from the NPC.
    client = _gmap_client(connected=True)
    client.items["chicken1.nw"] = {(53.0, 45.0): "greenrupee",
                                   (10.0, 10.0): "greenrupee"}
    _run(client, BARKEEP, "take greenrupee;")
    assert client.items["chicken1.nw"] == {(10.0, 10.0): "greenrupee"}


# -- a script that runs before the .gmap arrives ------------------------------
#
# An NPC's cell comes straight from props 0x29/0x2a whether or not a map is
# loaded (TServerNPC.cpp:1271-1282 -> setMapX :407-409) and `x` reads
# local + (mapX << 6) (TServerNPCProperties.cpp:331). A disk-cached map loads
# before the NPC packets (unsorted.cpp:2530-2532); an uncached one arrives
# later and updateMapPos re-stamps the NPCs' cells without touching their
# local (unsorted.cpp:2574-2587, TServerLevel.cpp:946-953).

_GMAP_FILE = "chicken.gmap"
_GMAP_TEXT = ("GRMAP001\nWIDTH 3\nHEIGHT 3\nLEVELNAMES\n"
              + ",".join(f'"seg{gx}{gy}.nw"' if (gx, gy) != (1, 1)
                        else '"chicken1.nw"'
                        for gy in range(3) for gx in range(3))
              + "\nLEVELNAMESEND\n")
_STAR = 91       # a server-global NPC id


def _gint3(v):
    return bytes([((v >> 14) & 0x7F) + 32, ((v >> 7) & 0x7F) + 32,
                  (v & 0x7F) + 32])


def _npc_props(npc_id, **props):
    from reborn_protocol.props import NPC_PROPS, encode_value
    by_name = {d.name: d for d in NPC_PROPS.values()}
    pairs = sorted(((by_name[name], value) for name, value in props.items()),
                   key=lambda pair: pair[0].id)
    return _gint3(npc_id) + b"".join(
        bytes([desc.id + 32]) + encode_value(desc, value)
        for desc, value in pairs)


def _file_packet(name, data, mod_time=7):
    encoded = name.encode("latin-1")
    stamp = bytes(((mod_time >> s) & 0x7F) + 32 for s in (28, 21, 14, 7, 0))
    return stamp + bytes([len(encoded) + 32]) + encoded + data


def _pre_grid_client(monkeypatch, tmp_path):
    """A connected Client standing in chicken1.nw with no grid yet."""
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    client = Client("localhost", 14900)
    client._authenticated = True
    client._protocol = _SentRecorder()
    client._current_level_name = "chicken1.nw"
    client.player.x, client.player.y = 25.0, 10.0
    return client


def _snapshot(client, gs1):
    """(local, world, read) of the star NPC, the read through a script."""
    npc = client.npcs[_STAR]
    gs1.load_script("read", "this.rx = x; this.ry = y;", npc_id=_STAR)
    gs1.trigger_event("created", name="read")
    this = gs1._progs["read"]["scopes"]["this"]
    return ((npc["x"], npc["y"]), (npc["world_x"], npc["world_y"]),
            (this["rx"], this["ry"]))


def _write(gs1, code):
    gs1.load_script("write", code, npc_id=_STAR)
    gs1.trigger_event("created", name="write")


def _deliver_gmap(client, *, revalidate):
    if revalidate:
        client._handle_packet(PacketID.PLO_FILEUPTODATE, _GMAP_FILE.encode())
    else:
        client._handle_packet(
            PacketID.PLO_FILE, _file_packet(_GMAP_FILE, _GMAP_TEXT.encode()))
    assert client.gmap_width == 3, "the grid must be loaded now"


@pytest.mark.parametrize("revalidate", [False, True],
                         ids=["downloaded", "uptodate"])
def test_script_write_before_the_grid_keeps_local_and_world(
        monkeypatch, tmp_path, revalidate):
    # A map-owned NPC (SETACTIVELEVEL <gmap>) in cell (1, 1): its write
    # applies before the map loads, lands local to its cell, and loading the
    # map moves nothing.
    client = _pre_grid_client(monkeypatch, tmp_path)
    if revalidate:
        warm = Client("localhost", 14900)
        warm._authenticated = True
        warm._protocol = _SentRecorder()
        warm._current_level_name = "chicken1.nw"
        warm._handle_packet(PacketID.PLO_FILE,
                            _file_packet(_GMAP_FILE, _GMAP_TEXT.encode()))
    client._handle_packet(PacketID.PLO_SETACTIVELEVEL, _GMAP_FILE.encode())
    client._handle_packet(PacketID.PLO_NPCPROPS, _npc_props(
        _STAR, X2=53.0, Y2=43.0, GMAPLEVELX=1, GMAPLEVELY=1))
    gs1 = ClientGS1(client)
    assert client.gmap_width == 0
    assert _snapshot(client, gs1) == (
        (53.0, 43.0), (117.0, 107.0), (117.0, 107.0))
    _write(gs1, "x = 117.5; y = 106.5;")
    expected = ((53.5, 42.5), (117.5, 106.5), (117.5, 106.5))
    assert _snapshot(client, gs1) == expected
    _deliver_gmap(client, revalidate=revalidate)
    assert _snapshot(client, gs1) == expected
    assert (client.npcs[_STAR]["gmaplevelx"],
            client.npcs[_STAR]["gmaplevely"]) == (1, 1)


@pytest.mark.parametrize("revalidate", [False, True],
                         ids=["downloaded", "uptodate"])
def test_ignored_write_before_the_grid_stays_ignored_after_it(
        monkeypatch, tmp_path, revalidate):
    # An NPC of a plain segment is not map-owned before the map loads, so
    # `x = 117.5` is ignored (TServerNPCProperties.cpp:336, :343); the map
    # arriving later does not apply it either, nor move the local.
    client = _pre_grid_client(monkeypatch, tmp_path)
    if revalidate:
        warm = Client("localhost", 14900)
        warm._authenticated = True
        warm._protocol = _SentRecorder()
        warm._current_level_name = "chicken1.nw"
        warm._handle_packet(PacketID.PLO_FILE,
                            _file_packet(_GMAP_FILE, _GMAP_TEXT.encode()))
    client._handle_packet(PacketID.PLO_SETACTIVELEVEL, b"chicken1.nw")
    client._handle_packet(PacketID.PLO_NPCPROPS, _npc_props(
        _STAR, X2=53.5, Y2=42.5, GMAPLEVELX=1, GMAPLEVELY=1))
    gs1 = ClientGS1(client)
    expected = ((53.5, 42.5), (117.5, 106.5), (117.5, 106.5))
    assert _snapshot(client, gs1) == expected
    _write(gs1, "x = 117.5; y = 106.5;")
    assert _snapshot(client, gs1) == expected
    _deliver_gmap(client, revalidate=revalidate)
    assert _snapshot(client, gs1) == expected


def test_cell_props_after_a_script_write_keep_the_written_local(
        monkeypatch, tmp_path):
    # Local first, cell later: the write (0 <= x < 64 passes the plain-level
    # rule) stays the local; the cell props add their origin to the world and
    # to the read-back without moving it.
    client = _pre_grid_client(monkeypatch, tmp_path)
    client._handle_packet(PacketID.PLO_SETACTIVELEVEL, b"chicken1.nw")
    client._handle_packet(PacketID.PLO_NPCPROPS, _npc_props(
        _STAR, X2=53.0, Y2=43.0))
    gs1 = ClientGS1(client)
    assert _snapshot(client, gs1) == (
        (53.0, 43.0), (53.0, 43.0), (53.0, 43.0))
    _write(gs1, "x = 20.5; y = 10.5;")
    assert _snapshot(client, gs1) == (
        (20.5, 10.5), (20.5, 10.5), (20.5, 10.5))
    client._handle_packet(PacketID.PLO_NPCPROPS, _npc_props(
        _STAR, GMAPLEVELX=1, GMAPLEVELY=1))
    assert _snapshot(client, gs1) == (
        (20.5, 10.5), (84.5, 74.5), (84.5, 74.5))
    client._handle_packet(
        PacketID.PLO_FILE, _file_packet(_GMAP_FILE, _GMAP_TEXT.encode()))
    assert _snapshot(client, gs1) == (
        (20.5, 10.5), (84.5, 74.5), (84.5, 74.5))


# -- the write gate -----------------------------------------------------------

def test_write_gate_map_owned_applies_a_large_write_and_not_yet_owned_ignores_it():
    owned = _gmap_client()
    owned.npcs[BARKEEP]["_map_owned"] = True
    owned.gmap_grid.clear()            # the same NPC, no grid yet
    _run(owned, BARKEEP, "x = 117.5;")
    assert owned.npcs[BARKEEP]["x"] == 53.5
    plain = _gmap_client()
    plain.gmap_grid.clear()
    plain.npcs[BARKEEP]["_level"] = "chicken1.nw"
    plain.npcs[BARKEEP]["_map_owned"] = False
    _run(plain, BARKEEP, "x = 117.5;")
    assert plain.npcs[BARKEEP]["x"] == 53.0


def test_write_gate_a_segment_of_the_loaded_grid_is_map_owned():
    # Loading the map re-adds every NPC of a segment to it
    # (TServerLevel.cpp:951-953), so the same write applies once it is there.
    client = _gmap_client()
    assert not client.npcs[BARKEEP].get("_map_owned")
    _run(client, BARKEEP, "x = 140;")
    assert client.npcs[BARKEEP]["x"] == 76.0


@pytest.mark.parametrize("code,x", [
    ("x = 0;", 0.0), ("x = 63.5;", 63.5), ("x = 64;", 53.0), ("x = -0.5;", 53.0),
    ("x = 70;", 53.0), ("x = 12;", 12.0)])
def test_write_gate_on_a_plain_level_is_zero_to_sixty_four(code, x):
    client = _plain_client()
    _run(client, BARKEEP, code)
    assert client.npcs[BARKEEP]["x"] == x


def test_a_map_in_the_download_cache_loads_before_the_npc_packets(
        monkeypatch, tmp_path):
    # PLO_LEVELNAME <gmap> with a copy on disk builds the grid at once (the
    # reference loads a map it holds before the NPCs, unsorted.cpp:2530) and
    # still asks the server to confirm it.
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    warm = Client("localhost", 14900)
    warm._authenticated = True
    warm._protocol = _SentRecorder()
    warm._current_level_name = "chicken1.nw"
    warm._handle_packet(PacketID.PLO_FILE,
                        _file_packet(_GMAP_FILE, _GMAP_TEXT.encode()))
    client = Client("localhost", 14900)
    client._authenticated = True
    client._protocol = _SentRecorder()
    client._handle_packet(PacketID.PLO_LEVELNAME, _GMAP_FILE.encode())
    assert client.gmap_width == 3
    asked = [pid for pid, _ in client._protocol.sent]
    assert int(PacketID.PLI_UPDATEFILE) in asked
    client._handle_packet(PacketID.PLO_FILEUPTODATE, _GMAP_FILE.encode())
    assert client.gmap_width == 3


def test_uptodate_after_adoption_does_not_reset_the_player(
        monkeypatch, tmp_path):
    # Real order on a warm cache: PLAYERWARP2 (spawn cell (1, 1)), LEVELNAME
    # <gmap> (adopts the cached copy), the player walks on to cell (2, 1),
    # then the revalidation answer FILEUPTODATE. Adopting again would make
    # load_gmap put the level name and position back at the spawn cell.
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    warm = Client("localhost", 14900)
    warm._authenticated = True
    warm._protocol = _SentRecorder()
    warm._current_level_name = "chicken1.nw"
    warm._handle_packet(PacketID.PLO_FILE,
                        _file_packet(_GMAP_FILE, _GMAP_TEXT.encode()))
    client = Client("localhost", 14900)
    client._authenticated = True
    client._protocol = _SentRecorder()
    warp = bytes([20 * 2 + 32, 10 * 2 + 32, 32, 1 + 32, 1 + 32])
    client._handle_packet(PacketID.PLO_PLAYERWARP2,
                          warp + _GMAP_FILE.encode())
    client._handle_packet(PacketID.PLO_LEVELNAME, _GMAP_FILE.encode())
    assert client.gmap_width == 3
    assert client._current_level_name == "chicken1.nw"
    client.player.x, client.player.y = 150.0, 80.0
    client._current_level_name = "seg21.nw"
    grid = dict(client.gmap_grid)
    client._handle_packet(PacketID.PLO_FILEUPTODATE, _GMAP_FILE.encode())
    assert client._current_level_name == "seg21.nw"
    assert (client.player.x, client.player.y) == (150.0, 80.0)
    assert client.gmap_grid == grid


# -- GS2 shares the NPC position rule -----------------------------------------
#
# One property table serves both script languages
# (TServerNPCProperties.cpp:1245), so a GS2 `this.x` on an NPC is the same
# whole-map read and gated write as the GS1 `x`.

def _gs2_this(client, npc_id):
    from pyreborn.gs2_client import ClientGS2
    from pyreborn.gs2_client.objects import _NpcThisObject
    return _NpcThisObject(ClientGS2(client, ClientGS1(client)),
                          ("npc", npc_id))


def test_gs2_npc_reads_whole_map_position_in_a_non_origin_cell():
    client = _gmap_client()
    this = _gs2_this(client, BARKEEP)
    assert (this.get("x"), this.get("y")) == (117.0, 107.0)
    assert (_gs2_this(client, CORNER).get("x"),) == (20.0,)


def test_gs2_npc_write_lands_local_to_its_cell():
    client = _gmap_client()
    this = _gs2_this(client, BARKEEP)
    this.set("x", 117.5)
    this.set("y", 106.5)
    assert _where(client.npcs[BARKEEP]) == (
        53.5, 42.5, 117.5, 106.5, 1, 1, "chicken1.nw")
    assert (this.get("x"), this.get("y")) == (117.5, 106.5)


def test_gs2_npc_write_is_gated_like_gs1_on_a_plain_level():
    client = _plain_client()
    this = _gs2_this(client, BARKEEP)
    this.set("x", 12.0)
    this.set("y", 63.5)
    assert (client.npcs[BARKEEP]["x"], client.npcs[BARKEEP]["y"]) == (12.0, 63.5)
    for bad in (70.0, -10.0, 64.0):
        this.set("x", bad)
        this.set("y", bad)
    assert (client.npcs[BARKEEP]["x"], client.npcs[BARKEEP]["y"]) == (12.0, 63.5)


def test_gs2_npc_write_matches_the_gs1_result():
    gs1_client = _gmap_client()
    _run(gs1_client, BARKEEP, "x = 100; y = 90;")
    gs2_client = _gmap_client()
    this = _gs2_this(gs2_client, BARKEEP)
    this.set("x", 100.0)
    this.set("y", 90.0)
    assert _where(gs2_client.npcs[BARKEEP]) == _where(gs1_client.npcs[BARKEEP])


def test_gs2_findnpcbyid_returns_the_npc_this_the_rule_reads_through():
    client = _gmap_client()
    this = _gs2_this(client, BARKEEP)
    this._rt2.vms["npc"][BARKEEP] = SimpleNamespace(this=this)
    found = this._rt2.host.call_builtin(None, "findnpcbyid", [BARKEEP])
    assert found is this and found.get("x") == 117.0


def test_gs2_weapon_this_is_not_an_npc_and_is_untouched():
    from pyreborn.gs2_client import ClientGS2
    from pyreborn.gs2_client.objects_player import _ThisObject
    client = _gmap_client()
    weapon = _ThisObject(ClientGS2(client, ClientGS1(client)),
                         ("weapon", "tool"))
    weapon.set("x", 117.5)
    weapon.set("y", 300.0)
    assert (weapon.get("x"), weapon.get("y")) == (117.5, 300.0)
    assert _where(client.npcs[BARKEEP]) == (
        53.0, 43.0, 117.0, 107.0, 1, 1, "chicken1.nw")


# -- a script write drops the NPC's queued server moves -----------------------

_QUEUED = {"x": 20.0, "y": 20.0, "dx": -33.0, "dy": -23.0, "remaining": 1.0}


@pytest.mark.parametrize("value", [12.0, -10.0], ids=["applied", "ignored"])
def test_a_script_write_drops_queued_moves(value):
    client = _plain_client()
    npc = client.npcs[BARKEEP]
    npc["_move_queue"] = [dict(_QUEUED)]
    _gs2_this(client, BARKEEP).set("x", value)
    assert not npc.get("_move_queue")
    npc["_move_queue"] = [dict(_QUEUED)]
    _run(client, BARKEEP, f"y = {value};")
    assert not npc.get("_move_queue")
    assert npc["x"] == (12.0 if value == 12.0 else 53.0)


# -- a derived cell follows a newly adopted grid ------------------------------

def test_a_cell_stamped_from_a_cached_grid_follows_the_new_grid():
    client = Client("localhost", 14900)
    client._current_level_name = "chicken1.nw"
    grid_b = ("GRMAP001\nWIDTH 3\nHEIGHT 3\nLEVELNAMES\n"
              + ",".join('"chicken1.nw"' if (gx, gy) == (2, 0)
                         else f'"seg{gx}{gy}.nw"'
                         for gy in range(3) for gx in range(3))
              + "\nLEVELNAMESEND\n")
    derived = {"x": 10.0, "y": 12.0, "_level": "chicken1.nw", "image": "-",
               "_cell_derived": False}
    sent = {"x": 10.0, "y": 12.0, "_level": "chicken1.nw", "image": "-",
            "gmaplevelx": 0, "gmaplevely": 2, "_cell_derived": False}
    place_npc(client.gmap_grid, derived)
    place_npc(client.gmap_grid, sent)
    client.npcs[1], client.npcs[2] = derived, sent
    client.load_gmap(_GMAP_TEXT)
    assert (derived["gmaplevelx"], derived["gmaplevely"]) == (1, 1)
    assert (derived["world_x"], derived["world_y"]) == (74.0, 76.0)
    client.load_gmap(grid_b)
    assert (derived["gmaplevelx"], derived["gmaplevely"]) == (2, 0)
    assert (derived["world_x"], derived["world_y"]) == (138.0, 12.0)
    assert (sent["gmaplevelx"], sent["gmaplevely"]) == (0, 2)
    assert (sent["world_x"], sent["world_y"]) == (10.0, 140.0)
