"""Small offline GS1 builders shared by unit tests."""

from pyreborn import Client


class _SentRecorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def _client(level="room0.nw", board_tile=0x278):
    c = Client("localhost", 14900)
    c._authenticated = True
    c._protocol = _SentRecorder()
    c._current_level_name = level
    c.tiles = [board_tile] * 4096
    c._tiles_level_name = level
    return c


def _this(gs1, npc_id):
    return gs1._progs["npc_%d" % npc_id]["scopes"]["this"]
