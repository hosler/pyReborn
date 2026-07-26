"""GS1 scripts must never run against a board the client does not hold.

`tiles[x,y]` used to answer 0.0 whenever `client.tiles` was empty, and
`_reload_level_scripts` fired `playerenters` without checking the board had
arrived. GS1 has no "unknown tile" value, so 0.0 reads as ordinary floor — and
classic Bomber's room0.nw acts on that reading destructively: ResetObj deletes
every wall-mounted (`-7`) furniture entry whose tile isn't the wall id 0x278,
and Delete() writes the shortened catalog straight back to `server.room<N>`.
Boardless, that wipes the player's real, persistent room.

The npc_91 replay below is the actual captured script (see
bomber_room0_fixture); the third case shows the deletion is real, so the first
case is a guard doing work rather than a vacuous pass.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn import Client
from pyreborn.gs1_client import ClientGS1, GS1NoBoard
from pyreborn.game.setup import SetupMixin

from .bomber_room0_fixture import load_script


class _SentRecorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def _client(board_tile=None, level="room0.nw"):
    """A connected client on `level`. `board_tile` None = the board has not
    arrived yet (the state right after a warp); otherwise a uniform board."""
    c = Client("localhost", 14900)
    c._authenticated = True
    c._protocol = _SentRecorder()
    c._current_level_name = level
    if board_tile is not None:
        c.tiles = [board_tile] * 4096
        c._tiles_level_name = level
    return c


# -- tiles[x,y] --------------------------------------------------------------

def test_board_ready_rejects_missing_and_stale_boards():
    gs1 = ClientGS1(_client())
    assert gs1.board_ready() is False
    # A first-visit warp leaves the PREVIOUS level's board active: equally
    # unusable, and answering from it would read another room's walls.
    gs1.client.tiles = [0x278] * 4096
    gs1.client._tiles_level_name = "room1.nw"
    assert gs1.board_ready() is False
    gs1.client._tiles_level_name = "room0.nw"
    assert gs1.board_ready() is True


def test_tiles_read_without_board_raises_instead_of_answering():
    gs1 = ClientGS1(_client())
    ctx = SimpleNamespace(this_obj=None)
    with pytest.raises(GS1NoBoard):
        gs1._host.get_builtin("tiles", [10, 5], ctx)


def test_script_cannot_observe_a_walkable_tile_before_the_board_arrives():
    src = "if (timeout) { this.t = tiles[10,5]; this.done = 1; }"
    gs1 = ClientGS1(_client())
    gs1.load_script("probe", src, npc_id=0)
    gs1.trigger_npc_event(0, "timeout")
    this = gs1._progs["probe"]["scopes"]["this"]
    # aborted at the read: no tile value, and nothing after it ran
    assert "t" not in this
    assert "done" not in this

    gs1 = ClientGS1(_client(board_tile=0))
    gs1.load_script("probe", src, npc_id=0)
    gs1.trigger_npc_event(0, "timeout")
    this = gs1._progs["probe"]["scopes"]["this"]
    assert this["t"] == 0.0 and this["done"] == 1.0


# -- the live room0 furniture catalog ---------------------------------------

#: One wall-mounted object (type 47) at tile (10, 5). Room strings are
#: "<header>,<3 chars per object>" with each char `ascii - 33` (room0.nw's
#: Load()); shape table entry -7 marks the tile wall-mounted (ResetObj).
_ROOM = "1," + chr(33 + 47) + chr(33 + 10) + chr(33 + 5)


def _room0_engine(board_tile):
    c = _client(board_tile)
    gs1 = ClientGS1(c)
    gs1._flags["RoomID"] = 0.0
    gs1._shared["server"].recv("server.room0", _ROOM)
    gs1._shared["server"].recv("server.room0*", "")
    gs1._shared["client"].recv("clientr.rm_o47b", "1,-7")
    src = load_script(91)
    c.npcs[91] = {"x": 0.0, "y": 0.0, "script": src}
    gs1.load_script("npc_91", src, npc_id=91, x=0, y=0)
    return c, gs1


def _room_flag_sends(client):
    return [d for pid, d in client._protocol.sent if b"server.room0" in d]


def test_resetobj_deletes_wall_furniture_when_the_tile_is_not_a_wall():
    # The hazard, demonstrated: a real board that says "no wall here" is a
    # legitimate delete, and it goes out on the wire.
    client, gs1 = _room0_engine(board_tile=0)
    gs1.trigger_npc_event(91, "timeout")
    assert gs1._shared["server"]["room0"] == "1,"
    assert _room_flag_sends(client)


def test_resetobj_keeps_wall_furniture_when_the_tile_is_a_wall():
    client, gs1 = _room0_engine(board_tile=0x278)
    gs1.trigger_npc_event(91, "timeout")
    assert gs1._shared["server"]["room0"] == _ROOM
    assert not _room_flag_sends(client)


def test_resetobj_cannot_delete_anything_before_the_board_arrives():
    client, gs1 = _room0_engine(board_tile=None)
    gs1.trigger_npc_event(91, "timeout")
    assert gs1._shared["server"]["room0"] == _ROOM
    assert not _room_flag_sends(client)


def test_the_old_zero_answer_would_have_deleted(monkeypatch):
    # Pins WHY tiles[] must refuse: with the board still missing but the old
    # "0.0 means unknown" answer restored, the same run destroys the room.
    client, gs1 = _room0_engine(board_tile=None)
    monkeypatch.setattr(gs1, "board_ready", lambda: True)
    gs1.trigger_npc_event(91, "timeout")
    assert gs1._shared["server"]["room0"] == "1,"


# -- playerenters ------------------------------------------------------------

class _EnterHarness(SetupMixin):
    """GameClient stand-in for the reload slice, stubbing the render/NPC
    machinery _reload_level_scripts also touches (mirrors
    test_level_reload_effects.py's _ReloadHarness)."""

    def __init__(self, client, gs1):
        self.client = client
        self.gs1 = gs1
        self.tileset_mgr = SimpleNamespace(set_current_level=lambda name: None)
        self.npc_handler = SimpleNamespace(update_npcs=lambda: None)
        self.visual_x = self.visual_y = 0.0
        self.world_surface = None
        self._gs1_level = None
        self._level_change_pending = None

    def _load_npc_scripts(self):
        for npc_id, npc in self.client.npcs.items():
            self.gs1.load_script("npc_%d" % npc_id, npc['script'], npc_id=npc_id)


_PROBE = "if (playerenters) { this.entered = 1; }"


def _entering_engine(board_tile):
    c = _client(board_tile)
    c.npcs[7] = {"x": 1.0, "y": 1.0, "script": _PROBE}
    gs1 = ClientGS1(c)
    return c, gs1, _EnterHarness(c, gs1)


def _probe_scope(gs1):
    return gs1._progs["npc_7"]["scopes"]["this"]


def test_playerenters_does_not_fire_before_the_board_arrives():
    c, gs1, game = _entering_engine(board_tile=None)
    game._reload_level_scripts("room0.nw")
    assert "entered" not in _probe_scope(gs1)
    assert game._gs1_playerenters_pending is True


def test_playerenters_fires_once_the_board_arrives():
    c, gs1, game = _entering_engine(board_tile=None)
    game._reload_level_scripts("room0.nw")
    # board lands (PLO_BOARDPACKET), next frame's level check replays the reload
    c.tiles = [0] * 4096
    c._tiles_level_name = "room0.nw"
    game._check_level_change()
    assert _probe_scope(gs1)["entered"] == 1.0
    assert game._gs1_playerenters_pending is False


def test_late_streamed_npcs_do_not_get_a_boardless_playerenters():
    c, gs1, game = _entering_engine(board_tile=None)
    game._gs1_level = "room0.nw"
    game._load_new_npcs()
    assert "npc_7" not in gs1.scripts


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
