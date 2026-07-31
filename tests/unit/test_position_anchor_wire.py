"""The position anchor: what byte a given tile coordinate becomes on the wire,
and the guarantee that every local position change reaches the server.

Anchor (locked here so a refactor cannot drift it silently):

* A player's (x, y) is the TOP-LEFT of the 3x3-tile gani canvas. Bomber's own
  scripts confirm it from the content side -- ``onwall(playerx+1.5, playery+2)``
  is the collision-box centre and ``eye_bomber_idle0.gani`` puts the 32x32 BODY
  sprite at frame offset (8, 16), i.e. exactly the x+0.5..x+2.5 / y+1..y+3 box.
  GServer-v2 agrees: ``Player::getBoundingBox`` is
  ``{getGlobalPosition(), {48, 48, 48}}`` (server/include/object/Player.h:536).
* PLPROP_X/Y (classic) carry half-tiles, PLPROP_X2/Y2 pixels, and BOTH are
  ROUNDED, not truncated: the reference client sends
  ``floorToInt(tiles * units + 0.5)``
  (Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:3213-3216 and 3336-3339).

Regression (Bomber classic, 2026-07-25): positions written by a GS1 script --
the piano seat's ``playery-=.5`` / ``playery = playery + 1``, the stairs'
``playery+=.5`` -- were applied locally but only broadcast when a level had
called ``disabledefmovement``. On an ordinary level they never reached the
server, so we drew ourselves on the bench while every other player still saw
us in front of it: a vertical-only offset with X spot on.
"""

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn.packets import build_movement, build_hurt_response


def _props(data):
    """Decode a PLI_PLAYERPROPS payload of only known fixed-width props."""
    out = {}
    i = 0
    while i < len(data):
        pid = data[i] - 32
        if pid in (15, 16, 17, 2):
            out[pid] = data[i + 1] - 32
            i += 2
        elif pid in (78, 79):
            out[pid] = ((data[i + 1] - 32) << 7) | (data[i + 2] - 32)
            i += 3
        elif pid == 10:                       # GANI: length-prefixed string
            n = data[i + 1] - 32
            out[pid] = bytes(data[i + 2:i + 2 + n]).decode('latin-1')
            i += 2 + n
        else:                                  # pragma: no cover - guard
            raise AssertionError(f"unexpected prop {pid} at {i}")
    return out


# (tile coordinate, expected classic half-tile byte value)
#
# 22.0 -> 44 and 22.5 -> 45 are the exact bytes Bomber's arena grid produces
# (its cells snap playery to even tiles and playerx to even+0.5).  22.4/22.3
# are the ones truncation used to get wrong: int(22.4*2) == 44, but the real
# client rounds 44.8 up to 45.
@pytest.mark.parametrize("tiles,halftiles", [
    (0.0, 0), (22.0, 44), (22.5, 45), (22.25, 45), (22.4, 45), (22.24, 44),
    (17.0, 34), (10.5, 21), (63.5, 127),
])
def test_classic_x_y_are_rounded_half_tiles(tiles, halftiles):
    data = build_movement(tiles, tiles, direction=2, use_new_format=False)
    props = _props(data)
    assert props[15] == halftiles
    assert props[16] == halftiles
    # ...and the anchor is the raw coordinate: no +1.5 body-centre, no +2.5
    # stand-point, no half-tile bias baked in anywhere.
    assert props[15] == math.floor(tiles * 2 + 0.5)


@pytest.mark.parametrize("tiles,pixels", [
    (0.0, 0), (22.0, 352), (22.5, 360), (10.03, 160), (10.04, 161),
])
def test_modern_x2_y2_are_rounded_pixels(tiles, pixels):
    props = _props(build_movement(tiles, tiles, direction=2,
                                  use_new_format=True))
    assert props[78] == pixels << 1
    assert props[79] == pixels << 1


def test_classic_movement_is_the_exact_wire_bytes():
    """Byte-for-byte pin of one known position, so nothing about the frame
    (prop ids, order, +32 encoding, anchor) can drift unnoticed."""
    assert build_movement(10.5, 17.0, direction=2, use_new_format=False) == (
        bytes([17 + 32, 2 + 32, 15 + 32, 21 + 32, 16 + 32, 34 + 32]))


def test_hurt_response_uses_the_session_position_format():
    classic = _props(build_hurt_response(1.5, 10.5, 17.0, 2, "hurt",
                                         use_new_format=False))
    assert classic[15] == 21 and classic[16] == 34
    assert 78 not in classic and 79 not in classic

    modern = _props(build_hurt_response(1.5, 10.5, 17.0, 2, "hurt",
                                        use_new_format=True))
    assert modern[78] == (168 << 1) and modern[79] == (272 << 1)
    assert 15 not in modern and 16 not in modern

    # Health/animation are unchanged by the switch.
    assert classic[2] == modern[2] == 3
    assert classic[10] == modern[10] == "hurt"


# --- script-driven movement must reach the server ---------------------------

class _FakeProtocol:
    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b"", append_newline=True):
        self.sent.append((packet_id, bytes(data)))
        return True


class _FakePlayer:
    x = 15.5
    y = 40.5
    direction = 2


class _FakeClient:
    """Just enough Client surface for _sync_script_position."""
    connected = True
    _authenticated = True
    _use_pixel_props = False
    is_gmap = False
    _local_level_transition = ""

    def __init__(self):
        self._protocol = _FakeProtocol()
        self.player = _FakePlayer()
        self._last_sent_position = None

    # real implementations, copied by reference from Client
    from pyreborn.client import Client as _C
    _note_position_sent = _C._note_position_sent
    position_matches_wire = _C.position_matches_wire
    send_position = _C.send_position
    del _C


def _sync(client, default_movement):
    from pyreborn.gs2_client import ClientGS2

    class _Gs1:
        pass

    gs1 = _Gs1()
    gs1.default_movement = default_movement

    runtime = ClientGS2.__new__(ClientGS2)
    runtime.client = client
    runtime.gs1 = gs1
    runtime._pos_sync_last = None
    runtime._pos_sync_next = 0.0
    runtime._sync_script_position()
    return runtime


def test_script_position_is_broadcast_with_default_movement_on():
    """Bomber's piano seat writes playery while default movement is ON. The
    old gate skipped exactly that case."""
    client = _FakeClient()
    client.send_position()                       # walked here normally
    client._protocol.sent.clear()

    client.player.y -= 0.5                       # `playery-=.5` (sit)
    _sync(client, default_movement=True)

    assert len(client._protocol.sent) == 1, "script move never left the client"
    assert _props(client._protocol.sent[0][1])[16] == 80   # 40.0 tiles


def test_walking_does_not_double_report():
    """move_to already transmitted this exact position -- the script sync
    must stay quiet rather than duplicating every step."""
    client = _FakeClient()
    client.send_position()
    client._protocol.sent.clear()

    _sync(client, default_movement=True)
    assert client._protocol.sent == []


def test_script_position_still_broadcast_under_disabledefmovement():
    client = _FakeClient()
    client.send_position()
    client._protocol.sent.clear()

    client.player.x += 2.0
    _sync(client, default_movement=False)
    assert len(client._protocol.sent) == 1
