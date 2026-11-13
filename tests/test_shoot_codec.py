"""PLI_SHOOT / PLI_SHOOT2 builders and the PLO_SHOOT / PLO_SHOOT2 parser.

Reader mirrors GServer-v2 PlayerClientPackets.cpp msgPLI_SHOOT (:1329) and
msgPLI_SHOOT2 (:1379): sangle 0..220 = 0..2*pi, sanglez 110 = flat.
"""
import math

import pytest

from pyreborn.packets import PacketID
from pyreborn.packets import PacketReader
from pyreborn.packet_codec.gameplay import build_shoot, build_shoot_v1
from pyreborn.packet_codec.player import parse_shoot


def decode_v2(data):
    r = PacketReader(data)
    x, y, z = r.read_gshort(), r.read_gshort(), r.read_gshort()
    ox, oy = r.read_byte() - 32, r.read_byte() - 32
    sangle, sanglez, power, gravity = (r.read_gchar() for _ in range(4))
    gani = r.read_gstring_short()
    r.read_gchar()
    return dict(x=x, y=y, z=z, ox=ox, oy=oy, sangle=sangle, sanglez=sanglez,
                power=power, gravity=gravity, gani=gani, params=r.remaining())


def decode_v1(data):
    r = PacketReader(data)
    r.read_gint3()
    x, y, z = r.read_gchar(), r.read_gchar(), r.read_gchar()
    sangle, sanglez, power = (r.read_gchar() for _ in range(3))
    gani = r.read_gstring()
    return dict(x=x, y=y, z=z, sangle=sangle, sanglez=sanglez, power=power,
                gani=gani)


# pi/2 up, pi left, -pi/2 down, 0 right on the 220-step circle
ANGLES = [(math.pi / 2, 55), (math.pi, 110), (-math.pi / 2, 165), (0, 0)]


@pytest.mark.parametrize("angle,byte", ANGLES)
def test_v2_angle_bytes(angle, byte):
    assert decode_v2(build_shoot(5, 6, 0, angle, 20))['sangle'] == byte


@pytest.mark.parametrize("angle,byte", ANGLES)
def test_v1_angle_bytes(angle, byte):
    assert decode_v1(build_shoot_v1(5, 6, 0, angle, 20))['sangle'] == byte


def test_flat_shot_zangle_is_110():
    assert decode_v2(build_shoot(5, 6, 0, 0, 20))['sanglez'] == 110
    assert decode_v1(build_shoot_v1(5, 6, 0, 0, 20))['sanglez'] == 110


def test_zangle_extremes():
    assert decode_v2(build_shoot(0, 0, 0, 0, 1, zangle=math.pi / 2))['sanglez'] == 220
    assert decode_v2(build_shoot(0, 0, 0, 0, 1, zangle=-math.pi / 2))['sanglez'] == 0


def test_power_clamp_220():
    assert decode_v2(build_shoot(0, 0, 0, 0, 500))['power'] == 220
    assert decode_v2(build_shoot(0, 0, 0, 0, 150))['power'] == 150
    assert decode_v2(build_shoot(0, 0, 0, 0, -4))['power'] == 0
    assert decode_v1(build_shoot_v1(0, 0, 0, 0, 500))['power'] == 220


def test_v2_fields_roundtrip():
    d = decode_v2(build_shoot(3, 4, 0, 0, 7, gani="fireball", params="a,b", gravity=2))
    assert (d['x'], d['y'], d['z']) == (48, 64, 0)
    assert (d['ox'], d['oy'], d['gravity']) == (0, 0, 2)
    assert d['gani'] == b"fireball" or d['gani'] == "fireball"


@pytest.mark.parametrize("direction,byte", [(0, 55), (1, 110), (2, 165), (3, 0)])
def test_client_direction_mapping(make_client, direction, byte):
    client = make_client(player_xy=(10.0, 10.0))
    client.player.x, client.player.y, client.player.direction = 10.0, 10.0, 2
    before = len(client._protocol.sent)

    assert client.shoot(direction)

    shots = [data for pid, data in client._protocol.sent[before:]
             if pid == PacketID.PLI_SHOOT2]
    assert len(shots) == 1
    assert decode_v2(shots[0])['sangle'] == byte


def test_parse_shoot_v2_fields():
    body = b"\x20\x21" + build_shoot(3, 4, 0, math.pi / 2, 44, gani="arrow", params="p")
    info = parse_shoot(body, v2=True)
    assert info['shooter'] == 1
    assert (info['sangle'], info['sanglez'], info['power']) == (55, 110, 44)
    assert info['gani'] == "arrow" and info['params'] == "p"
    assert (info['x'], info['y']) == (3.0, 4.0)


def test_parse_shoot_v1_fields():
    body = b"\x20\x21" + build_shoot_v1(3, 4, 0, math.pi, 44, gani="arrow", params="p")
    info = parse_shoot(body, v2=False)
    assert (info['sangle'], info['sanglez'], info['power']) == (110, 110, 44)
    assert info['gani'] == "arrow" and (info['x'], info['y']) == (3.0, 4.0)


def test_packetid_alias_names_resolve():
    from pyreborn.packet_codec.common import PacketID
    assert PacketID.PLO_SHOWIMG == PacketID.PLO_SHOWIMGPLAYER == 32
    assert PacketID.PLO_SHOWIMGNPC == 166
