"""Re-entering somewhere we have already been must not wait on the server.

The transition hold freezes the framebuffer until the destination is
presentable, which is correct - but it used to wait for the server's
announcement even when everything needed to draw the destination was already
in hand. Measured against hastur.eevul.net:14912 (~180 ms base RTT) on
2026-07-25: 203 ms of frozen frames re-entering a house whose board was
cached, and 240 ms walking back out of it because the world grid had to be
re-downloaded.
"""

from pyreborn import Client
from pyreborn.packets import PacketID

_GMAP_FILE = (
    "GRMAP001\n"
    "WIDTH 2\n"
    "HEIGHT 1\n"
    "LEVELNAMES\n"
    '"west.nw","east.nw",\n'
    "LEVELNAMESEND\n"
)


class _ProtocolStub:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data):
        self.sent.append((packet_id, data))
        return True


def _client(level="outside.nw", x=30.0, y=30.0):
    client = Client("localhost", 14900)
    client._protocol = _ProtocolStub()
    client._authenticated = True
    client._current_level_name = level
    client._pending_level_name = level
    client.player.x = x
    client.player.y = y
    client.tiles = [1] * 4096
    client.levels[level] = client.tiles
    client._tiles_level_name = level
    return client


def test_cached_standalone_destination_releases_without_the_server():
    client = _client()
    client.levels["house.nw"] = [7] * 4096

    assert client.warp_to_level("house.nw", 30.5, 38.0)

    assert client._tiles_level_name == "house.nw"
    assert client._local_level_transition == "", \
        "a destination we can already draw must not freeze the view"
    assert client._local_level_transition_epoch == 1, \
        "the renderer still needs the epoch bump so it snaps rather than lerps"


def test_first_visit_still_holds_until_the_board_arrives():
    """The release above must not leak into a level we cannot draw yet."""
    client = _client()

    assert client.warp_to_level("house.nw", 30.5, 38.0)
    assert client._local_level_transition == "house.nw"

    client._handle_packet(PacketID.PLO_LEVELNAME, b"house.nw")
    client._handle_packet(PacketID.PLO_BOARDPACKET, bytes((7, 0)) * 4096)
    assert client._local_level_transition == ""


def _interior_client():
    """A client standing in an interior, having entered from a gmap whose
    file was downloaded earlier in the session."""
    client = _client(level="west.nw", x=10.0, y=10.0)
    client._received_files["world.gmap"] = _GMAP_FILE.encode()
    client.load_gmap(_GMAP_FILE)
    client.gmap_name = "world.gmap"
    client.levels["east.nw"] = [2] * 4096
    client._current_level_name = "house.nw"
    client.levels["house.nw"] = [3] * 4096
    client.tiles = client.levels["house.nw"]
    client._tiles_level_name = "house.nw"
    client._exit_gmap("house.nw")
    client.player.x, client.player.y = 30.5, 38.0
    return client


def test_gmap_reentry_restores_the_world_frame_without_a_round_trip():
    client = _interior_client()
    assert client.gmap_width == 0
    assert client._last_gmap_name == "world.gmap"

    assert client.warp_to_level("east.nw", 22.5, 33.0)

    assert client.in_gmap_segment, "world frame must be re-established"
    assert client.gmap_grid[(1, 0)] == "east.nw"
    # World coordinates, not the interim standalone local ones.
    assert (client.player.x, client.player.y) == (64 + 22.5, 33.0)
    assert client._local_level_transition == "", \
        "nothing left to wait for: grid restored and board cached"


def test_gmap_reentry_still_waits_when_the_file_was_never_downloaded():
    """Cold start inside an interior (logged in there): the .gmap has not
    been seen this session, so neither the grid nor the destination board is
    local and the hold has to stay engaged for the server. This is the one
    transition the client cannot shorten - it is pinned here so the
    round-trip-free paths above cannot be widened onto it by accident."""
    client = _client(level="house.nw", x=30.5, y=38.0)

    assert client.warp_to_level("east.nw", 22.5, 33.0)
    assert client.gmap_width == 0
    assert client._last_gmap_name == ""
    assert client._local_level_transition == "east.nw"


def test_level_name_reparses_a_gmap_we_already_hold():
    """Walking back onto the overworld re-announces the .gmap. Re-requesting
    the file costs another round trip for bytes that cannot have changed."""
    client = _interior_client()
    client._requested_gmap = ""
    client.gmap_grid.clear()
    client.gmap_width = 0
    client._current_level_name = "east.nw"
    before = list(client._protocol.sent)

    client._handle_packet(PacketID.PLO_LEVELNAME, b"world.gmap")

    assert client.gmap_width == 2
    assert client.gmap_name == "world.gmap"
    wantfile = [p for p in client._protocol.sent[len(before):]
                if p[0] == PacketID.PLI_WANTFILE]
    assert not wantfile, "the cached .gmap must not be re-requested"


def test_seam_crossing_points_the_active_board_at_the_new_segment():
    """gs2emu only streams a segment's board on the FIRST visit, so nothing
    else updates the active board when walking back into one - live-traced,
    it kept naming the previous segment for the rest of the session."""
    client = _client(level="west.nw", x=63.5, y=20.0)
    client.load_gmap(_GMAP_FILE)
    client._current_level_name = "west.nw"
    client.player.x, client.player.y = 63.5, 20.0
    client.levels["east.nw"] = [9] * 4096

    assert client.move(1, 0, step=0.5)

    assert client._current_level_name == "east.nw"
    assert client._tiles_level_name == "east.nw"
    assert client.tiles is client.levels["east.nw"]
