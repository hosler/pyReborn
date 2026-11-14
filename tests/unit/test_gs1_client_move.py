"""Client `move`, writes on another NPC or player, and the wire frames of the
script commands that send a position (reference: Preagonal/FourPlay/quattroplay/src).

`move dx,dy,time,options` is a queued `addNPCMove` (TServerNPCProperties.cpp:
558-561), not a position write: it is not gated, nothing is dropped, and
`doNPCMove` (TServerNPC.cpp:1628) steps the queue once per tick. A write on
`npcs[i]` or inside `with (npcs[i])` is the same property setter as on the
script's own NPC (TServerNPCProperties.cpp:334-345); `players[i].x = v` is
`TServerPlayerProperties.cpp:17-34`.
"""

import pytest

from pyreborn.gs1_client import ClientGS1
from pyreborn.gs1_client.frame import to_level
from pyreborn.npc_movement import tick_moves
from pyreborn.packets import PacketID

from .test_gs1_client_gmap_frame import (
    BARKEEP, CORNER, _gmap_client, _plain_client, _run, _where,
)


def _step(client, npc, ticks=1):
    """Run `ticks` simulation ticks of the NPC move queue."""
    for _ in range(ticks):
        tick_moves(client, npc["_move_clock"] + 0.05)


# -- queued, not teleported ------------------------------------------------------

def test_move_queues_and_leaves_the_position_alone_plain_level():
    client = _plain_client()
    _run(client, BARKEEP, "x = 5; y = 5; move 1,1,0.5,0;")
    npc = client.npcs[BARKEEP]
    assert (npc["x"], npc["y"], npc["world_x"], npc["world_y"]) == (5, 5, 5, 5)
    assert len(npc["_move_queue"]) == 1


def test_move_advances_per_tick_and_ends_on_target_plain_level():
    client = _plain_client()
    _run(client, BARKEEP, "x = 5; y = 5; move 1,1,0.5,0;")
    npc = client.npcs[BARKEEP]
    _step(client, npc, 5)
    assert (npc["x"], npc["world_x"]) == pytest.approx((5.5, 5.5))
    assert (npc["y"], npc["world_y"]) == pytest.approx((5.5, 5.5))
    _step(client, npc, 5)
    assert (npc["x"], npc["y"], npc["world_x"], npc["world_y"]) == pytest.approx(
        (6, 6, 6, 6))
    assert not npc["_move_queue"]


def test_move_in_a_non_origin_gmap_cell_ends_on_the_world_target():
    client = _gmap_client()
    _run(client, BARKEEP, "move 2,-1,0.5,0;")
    npc = client.npcs[BARKEEP]
    assert _where(npc) == (53.0, 43.0, 117.0, 107.0, 1, 1, "chicken1.nw")
    _step(client, npc, 10)
    assert _where(npc)[:4] == pytest.approx((55.0, 42.0, 119.0, 106.0))
    assert _where(npc)[4:] == (1, 1, "chicken1.nw")
    assert not npc["_move_queue"]


def test_a_script_reads_the_whole_map_position_while_the_move_runs():
    client = _gmap_client()
    gs1, this = _run(client, BARKEEP,
                     "if (created) { move 2,-1,0.5,0; }"
                     "if (timeout) { this.rx = x; this.ry = y; }")
    npc = client.npcs[BARKEEP]
    _step(client, npc, 5)
    gs1.trigger_event("timeout", name=f"npc_{BARKEEP}")
    assert (this["rx"], this["ry"]) == pytest.approx((118.0, 106.5))


def test_a_position_write_cancels_the_running_move():
    client = _gmap_client()
    gs1, _this = _run(client, BARKEEP,
                      "if (created) { move 8,0,1,0; }"
                      "if (timeout) { x = 100; }")
    npc = client.npcs[BARKEEP]
    _step(client, npc, 4)
    gs1.trigger_event("timeout", name=f"npc_{BARKEEP}")
    assert not npc.get("_move_queue")
    assert (npc["x"], npc["world_x"]) == (36.0, 100.0)


def test_move_is_not_gated_like_a_position_write():
    # A plain-level `x = 100` is ignored (the 0..64 gate); `move 100,0,...`
    # is not a write and travels all the way.
    client = _plain_client()
    _run(client, BARKEEP, "move 100,0,0.1,0;")
    npc = client.npcs[BARKEEP]
    _step(client, npc, 5)
    assert npc["x"] == pytest.approx(153.0)


# -- options bits and queue rules ---------------------------------------------------

def test_movementfinished_fires_at_the_end_with_option_8():
    client = _gmap_client()
    _gs1, this = _run(client, BARKEEP,
                      "if (created) { move 1,0,0.25,8; }"
                      "if (movementfinished) { this.done = x; }")
    npc = client.npcs[BARKEEP]
    _step(client, npc, 4)
    assert "done" not in this
    _step(client, npc, 1)
    assert this["done"] == pytest.approx(118.0)


def test_no_movementfinished_without_option_8():
    client = _gmap_client()
    _gs1, this = _run(client, BARKEEP,
                      "if (created) { move 1,0,0.25,0; }"
                      "if (movementfinished) { this.done = 1; }")
    _step(client, client.npcs[BARKEEP], 8)
    assert "done" not in this


def test_option_16_faces_the_move():
    client = _gmap_client()
    _run(client, BARKEEP, "move -3,0,0.5,16;")
    npc = client.npcs[BARKEEP]
    _step(client, npc, 1)
    assert npc["direction"] == 1
    _step(client, npc, 20)
    _run(client, BARKEEP, "move 0,3,0.5,16;")
    _step(client, npc, 1)
    assert npc["direction"] == 2


def test_option_4_stops_at_a_wall_and_drops_the_queue():
    # The probe point is the NPC's leading edge (facing down: bottom centre of
    # its 3x3 box), TServerNPC.cpp:1682-1749.
    client = _gmap_client()
    gs1, this = _run(client, BARKEEP,
                     "if (created) { move 4,0,1,12; }"
                     "if (movementfinished) { this.stopped = x; }")
    gs1.is_wall = lambda x, y, exclude_npc=None: x >= 119.0
    npc = client.npcs[BARKEEP]
    _step(client, npc, 6)
    assert npc["world_x"] == pytest.approx(117.4)
    assert not npc.get("_move_queue")
    assert this["stopped"] == pytest.approx(117.4)


def test_modes_0_and_1_squeeze_the_pending_durations_mode_2_does_not():
    client = _plain_client()
    _run(client, BARKEEP, "move 10,0,2,0; move 0,10,1,0;")
    first, second = client.npcs[BARKEEP]["_move_queue"]
    assert first["remaining"] == pytest.approx(2 / 3)
    assert second["remaining"] == pytest.approx(1 / 3)
    client = _plain_client()
    _run(client, BARKEEP, "move 10,0,2,0; move 0,10,1,2;")
    first, second = client.npcs[BARKEEP]["_move_queue"]
    assert (first["remaining"], second["remaining"]) == (2, 1)
    # mode 1 squeezes only when the queued deltas span more than 10 tiles
    client = _plain_client()
    _run(client, BARKEEP, "move 5,0,2,1; move 0,10,1,1;")
    assert [m["remaining"] for m in client.npcs[BARKEEP]["_move_queue"]] == [2, 1]
    client = _plain_client()
    _run(client, BARKEEP, "move 20,0,2,1; move 0,10,1,1;")
    assert [m["remaining"] for m in client.npcs[BARKEEP]["_move_queue"]] == (
        pytest.approx([2 / 3, 1 / 3]))


def test_the_hundred_and_first_move_flushes_the_queue_to_its_end():
    client = _plain_client()
    code = "x = 1; y = 1;" + "move 1,0,10,0;" * 101
    _run(client, BARKEEP, code)
    npc = client.npcs[BARKEEP]
    assert len(npc["_move_queue"]) == 1
    assert npc["x"] == 101.0   # 1 + the 100 queued deltas; the 101st is queued


def test_a_script_move_is_the_server_move_path():
    # Same queue, same stepper: a server PLO_MOVE-style record and a script
    # `move` of the same delta and time leave an NPC in the same place.
    from pyreborn.npc_movement import add_npc_move
    client = _gmap_client()
    _run(client, BARKEEP, "move 2,-1,0.5,0;")
    other = client.npcs[CORNER]
    add_npc_move(client, other, 2, -1, 0.5, 0)
    npc = client.npcs[BARKEEP]
    for _ in range(10):
        _step(client, npc)
        _step(client, other)
    assert (npc["x"] - 53.0, npc["y"] - 43.0) == pytest.approx(
        (other["x"] - 20.0, other["y"] - 22.0))


# -- the offline game: a move over real ticks ----------------------------------------

def test_move_runs_over_real_ticks_in_a_gmap_cell(make_game):
    script = "if (created) { move 4,0,1,0; }"
    game = make_game(gmap=True, gmap_segment=(1, 1), player_xy=(100.0, 100.0),
                     npcs=[{"id": 123, "x": 10.0, "y": 10.0,
                            "image": "pics1.png", "script": script}])
    npc = game.client.npcs[123]
    start_world = npc["world_x"]
    assert npc["_move_queue"] and npc["x"] == 10.0
    game.ticks(10)
    assert npc["x"] == pytest.approx(12.0, abs=0.25)
    assert npc["world_x"] == pytest.approx(start_world + 2.0, abs=0.25)
    game.ticks(20)
    assert not npc["_move_queue"]
    assert (npc["x"], npc["y"]) == pytest.approx((14.0, 10.0))
    assert npc["world_x"] == pytest.approx(start_world + 4.0)
    # blocking and touch read the moved footprint
    runtime = game.gs1
    rect = runtime.npc_image_rect(npc)
    assert rect[0] == pytest.approx(npc["world_x"])
    assert runtime.npc_blocks_at(npc["world_x"] + 0.5, npc["world_y"] + 0.5)
    assert not runtime.npc_blocks_at(start_world + 0.5, npc["world_y"] + 0.5)


# -- writes on another NPC ---------------------------------------------------------

def test_npcs_index_write_is_the_same_setter_as_on_the_own_npc():
    client = _gmap_client()
    _run(client, CORNER, "npcs[0].x = 100; npcs[0].y = 90;")
    assert _where(client.npcs[BARKEEP]) == (
        36.0, 26.0, 100.0, 90.0, 1, 1, "chicken1.nw")


def test_with_npcs_index_reads_and_writes_whole_map():
    client = _gmap_client()
    _gs1, this = _run(client, CORNER,
                      "with (npcs[0]) { this.rx = x; x = 100; y = 90; }")
    assert this["rx"] == 117.0
    assert _where(client.npcs[BARKEEP]) == (
        36.0, 26.0, 100.0, 90.0, 1, 1, "chicken1.nw")


def test_write_on_another_npc_keeps_the_plain_level_gate():
    client = _plain_client()
    _run(client, BARKEEP, "x = 10; y = 10;")
    client.npcs[CORNER] = {"x": 1.0, "y": 1.0, "_level": "house.nw", "image": "-"}
    _run(client, BARKEEP, "npcs[1].x = 100; npcs[1].y = 12;")
    assert (client.npcs[CORNER]["x"], client.npcs[CORNER]["y"]) == (1.0, 12.0)


def test_write_on_another_npc_drops_its_queued_moves():
    client = _gmap_client()
    _run(client, BARKEEP, "move 5,0,2,0;")
    assert client.npcs[BARKEEP]["_move_queue"]
    _run(client, CORNER, "npcs[0].x = 100;")
    assert not client.npcs[BARKEEP].get("_move_queue")


def test_with_a_missing_npcs_index_does_not_run_the_block():
    client = _gmap_client()
    _gs1, this = _run(client, CORNER, "with (npcs[9]) { this.ran = 1; x = 5; }")
    assert "ran" not in this
    assert client.npcs[CORNER]["x"] == 20.0


# -- players[i].x ------------------------------------------------------------------

def _remote(client, level, x=10.0, y=10.0):
    client.players[3] = {"x": x, "y": y, "level": level, "account": "bob"}
    return client.players[3]


def test_players_index_write_moves_a_remote_record_on_a_gmap():
    # TServerPlayerProperties.cpp:230-241 + :17-34: the player is stored at
    # value - (mapX << 6); a map player is not clamped.
    client = _gmap_client()
    op = _remote(client, "chicken1.nw")
    op["world_x"], op["world_y"] = 74.0, 74.0
    _gs1, this = _run(client, CORNER,
                      "players[1].x = 100; players[1].y = 90; this.r = players[1].x;")
    assert (op["x"], op["y"], op["world_x"], op["world_y"]) == (36.0, 26.0, 100.0, 90.0)
    assert this["r"] == 100.0


def test_players_index_write_clamps_off_a_map_for_an_npc_script():
    client = _plain_client()
    op = _remote(client, "house.nw")
    _run(client, BARKEEP, "players[1].x = 100; players[1].y = -5;")
    assert (op["x"], op["y"]) == (64.0, -1.0)


def test_a_weapon_script_writes_a_remote_player_unclamped():
    client = _plain_client()
    op = _remote(client, "house.nw")
    gs1 = ClientGS1(client)
    gs1.load_weapon("Mover", "if (weaponfired) { players[1].x = 100; }")
    gs1.trigger_event("weaponfired", name="weapon_Mover")
    assert op["x"] == 100.0


def test_with_findplayer_x_write_moves_the_remote_record():
    client = _gmap_client()
    op = _remote(client, "chicken1.nw")
    op["world_x"] = 74.0
    _run(client, CORNER, 'with (findplayer("bob")) { x = 100; }')
    assert (op["x"], op["world_x"]) == (36.0, 100.0)


def _real_server_remote(client):
    """A remote player as the real servers report it: the `.gmap` file as the
    level, the cell in the GMAPLEVELX/Y props, the whole-map tile in world_x."""
    client.players[3] = {"x": 10.0, "y": 10.0, "level": "chicken.gmap",
                         "gmaplevelx": 1, "gmaplevely": 1,
                         "world_x": 74.0, "world_y": 74.0, "account": "bob"}
    return client.players[3]


def test_players_index_write_uses_the_cell_props_of_a_real_server_record():
    client = _gmap_client()
    op = _real_server_remote(client)
    _gs1, this = _run(client, CORNER,
                      "players[1].x = 100; players[1].y = 90; this.r = players[1].x;")
    assert (op["x"], op["y"], op["world_x"], op["world_y"]) == (36.0, 26.0, 100.0, 90.0)
    assert this["r"] == 100.0


def test_with_findplayer_write_and_read_use_the_cell_props_of_a_real_server_record():
    client = _gmap_client()
    op = _real_server_remote(client)
    del op["world_x"], op["world_y"]
    _gs1, this = _run(client, CORNER,
                      'with (findplayer("bob")) { this.rx = x; x = 100; this.wx = x; }')
    assert (this["rx"], this["wx"]) == (74.0, 100.0)
    assert (op["x"], op["world_x"]) == (36.0, 100.0)


# -- wire frames ------------------------------------------------------------------

def _wire(game, packet_id):
    return [data for pid, data in game.client._protocol.sent
            if pid == int(packet_id)]


def _gmap_game_with_script(make_game, script):
    return make_game(gmap=True, gmap_segment=(1, 1), player_xy=(100.0, 100.0),
                     npcs=[{"id": 123, "x": 10.0, "y": 10.0, "image": "-",
                            "script": script}])


def _half_tiles(data, offset):
    return data[offset] - 32, data[offset + 1] - 32


def test_triggeraction_sends_the_position_local_to_the_players_level(make_game):
    # TInitStatics.cpp:3974-3977 + TClient.cpp:4338-4362: x - (mapX << 6),
    # clamped to 0..110; the receiver adds the sender's level origin
    # (GServer-v2 PlayerClientPackets.cpp:1056-1058).
    game = _gmap_game_with_script(
        make_game, "if (created) { triggeraction 117.5,107,alpha;"
                   " triggeraction 300,20,beta; }")
    packets = _wire(game, PacketID.PLI_TRIGGERACTION)
    by_action = {p[5:].decode(): _half_tiles(p, 3) for p in packets}
    assert by_action["alpha"] == (107, 86)        # 53.5, 43
    assert by_action["beta"] == (220, 0)          # clamped to 110, then y < 0


def test_hitobjects_sends_local_and_nothing_outside_the_level(make_game):
    # TInitStatics.cpp:3417-3421 (x - origin) and TClient.cpp:1462-1464
    # (outside 0..64 nothing is sent).
    game = _gmap_game_with_script(
        make_game, "if (created) { hitobjects 1,117.5,107; hitobjects 1,10,10; }")
    packets = _wire(game, PacketID.PLI_HITOBJECTS)
    assert len(packets) == 1
    assert _half_tiles(packets[0], 1) == (107, 86)


def test_putcomp_sends_the_position_local_to_the_players_level(make_game):
    # GServer-v2 msgPLI_BADDYADD files the baddy in the sender's level at the
    # wire position modulo 64 (PlayerClientPackets.cpp:550-565, Extents.h:432).
    game = _gmap_game_with_script(
        make_game, "if (created) { putcomp graysoldier,126.5,107; }")
    packets = _wire(game, PacketID.PLI_BADDYADD)
    assert len(packets) == 1
    assert _half_tiles(packets[0], 0) == (125, 86)   # 62.5, 43


def test_to_level_is_the_frame_the_three_commands_share():
    client = _gmap_client()
    assert to_level(client, 117.5, 107.0) == (53.5, 43.0)


# -- survey items: bombs[] without a game, findplayer, lay ----------------------

def test_bombs_array_without_a_game_reads_whole_map():
    client = _gmap_client()
    client.bombs["chicken1.nw"] = {1: {"x": 10.0, "y": 12.0, "power": 1}}
    _gs1, this = _run(client, CORNER, "this.bx = bombs[0].x; this.by = bombs[0].y;")
    assert (this["bx"], this["by"]) == (74.0, 76.0)


def test_findplayer_reference_reads_whole_map():
    client = _gmap_client()
    _remote(client, "chicken1.nw")
    _gs1, this = _run(client, CORNER,
                      'with (findplayer("bob")) { this.rx = x; this.ry = y; }')
    assert (this["rx"], this["ry"]) == (74.0, 74.0)


@pytest.mark.parametrize("npc_xy,expected", [
    ((53.0, 43.0), (53.5, 46.0)),     # level of the player's feet or lower: bottom edge
    ((10.0, 20.0), (10.5, 23.0)),     # above, far to the left: bottom edge
    ((30.0, 20.0), (33.0, 20.5)),     # above, centred on the player: right edge, above centre
    ((28.0, 20.0), (31.0, 20.5)),     # above, nearly centred: top-right
])
def test_lay_files_the_item_at_the_npc_edge_the_player_faces(npc_xy, expected):
    # TServerNPCProperties.cpp:502-548; the player stands at (30, 30), the NPC
    # has no image (3x3 tiles).
    from pyreborn.packets import build_item_add
    client = _plain_client(connected=True)
    client.npcs[BARKEEP]["x"], client.npcs[BARKEEP]["y"] = npc_xy
    _run(client, BARKEEP, "lay bombs;")
    sent = [d for pid, d in client._protocol.sent
            if pid == int(PacketID.PLI_ITEMADD)]
    assert sent == [build_item_add(*expected, 3)]


def test_option_64_picks_the_default_animation_of_a_character_npc():
    # TServerNPC.cpp:1781-1832: idle / walkslow (< 0.5 tile per tick) / walk.
    client = _gmap_client()
    client.npcs[BARKEEP]["image"] = "#c#"
    _run(client, BARKEEP, "move 4,0,1,64;")
    npc = client.npcs[BARKEEP]
    _step(client, npc, 1)
    assert npc["gani"] == "walkslow,"
    _step(client, npc, 25)
    assert npc["gani"] == "idle,"


def test_mount_horse_on_a_gmap_sends_the_level_local_position(make_game):
    # GServer-v2 msgPLI_HORSEADD adds the sender's sub-level origin to the wire
    # position (PlayerClientPackets.cpp:269), so the builder wraps the world
    # position of mount_horse into the level: world (100, 100) in cell (1, 1)
    # is local 36, half-tiles 72.
    game = make_game(gmap=True, gmap_segment=(1, 1), player_xy=(100.0, 100.0))
    game.client.mount_horse()
    packets = _wire(game, PacketID.PLI_HORSEADD)
    assert len(packets) == 1
    assert packets[0][:2] == bytes([104, 104])
    assert _half_tiles(packets[0], 0) == (72, 72)
