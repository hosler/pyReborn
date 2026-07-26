"""A level change we announced must not be un-done by the server's echo.

Both a GMAP seam crossing (`Client.enter_gmap_segment`) and a door/script warp
(`Client.warp_to_level`) tell the server where we went with PLI_LEVELWARP. One
round trip later the server replies with PLO_PLAYERWARP/PLAYERWARP2 carrying
those same coordinates, re-quantised to half-tiles. Adopting them rewinds the
player by whatever they walked during the round trip.

Live-traced on hastur.eevul.net:14912 (zlttp.gmap, ~180 ms base RTT) on
2026-07-25: 1.83 tiles / 29 px backwards at a seam (5.1 tiles on a slower
sample) and 3.34 tiles / 53 px walking out of a door, once per transition.
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


def _gchar(value: int) -> int:
    return value + 32


def _warp2(x: float, y: float, gmap_x: int, gmap_y: int, level: str) -> bytes:
    """PLO_PLAYERWARP2 body: x, y, z, gmap_x, gmap_y (gchar) then the name."""
    return bytes((_gchar(int(x * 2)), _gchar(int(y * 2)), _gchar(0),
                  _gchar(gmap_x), _gchar(gmap_y))) + level.encode()


def _warp(x: float, y: float, level: str) -> bytes:
    return bytes((_gchar(int(x * 2)), _gchar(int(y * 2)))) + level.encode()


def _client(level="west.nw", x=30.0, y=30.0):
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


def _gmap_client():
    client = _client(level="west.nw", x=63.5, y=20.0)
    client.load_gmap(_GMAP_FILE)
    client.levels["east.nw"] = [2] * 4096
    client._current_level_name = "west.nw"
    client.player.x, client.player.y = 63.5, 20.0
    return client


def test_seam_echo_does_not_rewind_the_player():
    client = _gmap_client()

    # Cross west -> east, then keep walking for the length of a round trip.
    assert client.move(1, 0, step=0.5)
    assert client._current_level_name == "east.nw"
    for _ in range(4):
        client.move(1, 0, step=0.5)
    walked_to = (client.player.x, client.player.y)
    assert walked_to[0] > 64.0

    # The server's acknowledgement replays the crossing coordinates.
    client._handle_packet(PacketID.PLO_PLAYERWARP2,
                          _warp2(0.0, 20.0, 1, 0, "world.gmap"))

    assert (client.player.x, client.player.y) == walked_to
    # The bookkeeping in the packet is still adopted.
    assert (client._gmap_spawn_x, client._gmap_spawn_y) == (1, 0)
    assert client._current_level_name == "east.nw"


def test_seam_echo_is_one_shot():
    """Only the acknowledgement is absorbed; a later reposition still moves
    the player, so a server-side unstick/script warp is never swallowed."""
    client = _gmap_client()
    assert client.move(1, 0, step=0.5)
    client.move(1, 0, step=0.5)

    client._handle_packet(PacketID.PLO_PLAYERWARP2,
                          _warp2(0.0, 20.0, 1, 0, "world.gmap"))
    client._handle_packet(PacketID.PLO_PLAYERWARP2,
                          _warp2(40.0, 12.0, 1, 0, "world.gmap"))

    assert (client.player.x, client.player.y) == (64 + 40.0, 12.0)


def test_unannounced_server_warp_still_teleports():
    client = _gmap_client()

    client._handle_packet(PacketID.PLO_PLAYERWARP2,
                          _warp2(8.0, 9.0, 1, 0, "world.gmap"))

    assert (client.player.x, client.player.y) == (64 + 8.0, 9.0)


def test_door_warp_echo_does_not_rewind_the_player():
    client = _client(level="house.nw", x=30.5, y=37.5)
    client.levels["outside.nw"] = [3] * 4096

    assert client.warp_to_level("outside.nw", 22.5, 33.0)
    # Walk on while the acknowledgement is in flight.
    client.player.y = 36.5

    client._handle_packet(PacketID.PLO_PLAYERWARP,
                          _warp(22.5, 33.0, "outside.nw"))

    assert (client.player.x, client.player.y) == (22.5, 36.5)


def test_gmap_named_warp_is_not_read_as_a_rejection():
    """Warping onto a gmap segment is confirmed by the WORLD's name, not the
    segment's. Treating that as "the server warped us elsewhere" rolled the
    warp back and tore down the transition hold (live-traced walking out of
    zlttp-linkshouse.nw: PLO_PLAYERWARP2 (5, 6) "zlttp.gmap" against a
    pending zlttp-d6.nw)."""
    client = _client(level="house.nw", x=29.5, y=38.0)
    client.load_gmap(_GMAP_FILE)
    client._exit_gmap("house.nw")
    client.levels["east.nw"] = [4] * 4096

    assert client.warp_to_level("east.nw", 22.5, 33.0)
    assert client._awaiting_warp_confirm == "east.nw"
    assert client._local_level_transition == "east.nw"

    client._handle_packet(PacketID.PLO_PLAYERWARP2,
                          _warp2(22.5, 33.0, 1, 0, "world.gmap"))

    assert client._current_level_name == "east.nw", "rolled back to house.nw"
    # The rollback also tore down the hold, which is what let the camera
    # render the interim standalone frame and then jump into world coords.
    assert client._local_level_transition == "east.nw"


def test_warp_named_for_another_level_is_still_a_rejection():
    client = _client(level="outside.nw", x=30.0, y=30.0)

    assert client.warp_to_level("missing.nw", 5.0, 6.0)
    client._handle_packet(PacketID.PLO_PLAYERWARP,
                          _warp(30.0, 30.0, "elsewhere.nw"))

    assert client._current_level_name == "outside.nw"
    assert (client.player.x, client.player.y) == (30.0, 30.0)
