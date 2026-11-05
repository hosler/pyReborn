"""Client-side bomb simulation: fuses, chain detonation and self-damage.

The reference client owns all three (TServerLevel.cpp:1087-1130 putBomb,
:1310-1337 animateBombs, :1691-1725 explodeBomb, :1494-1500 putExplosion,
TExplosion.cpp:48-96 animate, TClient.cpp:3555-3620 for the receive side).
Time is monkeypatched so fuses expire at exact ticks.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyreborn import Client
from pyreborn.handlers.combat import (
    handle_bomb_add, handle_bomb_del, handle_explosion,
)
from pyreborn.packets import PacketID, parse_bomb_add, parse_explosion
from reborn_protocol import PacketBuilder

LEVEL = 'bombs.nw'


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr('time.time', c)
    return c


class Recorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b''):
        self.sent.append((int(packet_id), bytes(data)))
        return True


@pytest.fixture
def client(clock):
    c = Client('localhost', 14900)
    c._authenticated = True
    c._protocol = Recorder()
    c._current_level_name = LEVEL
    c.player.id = 3
    c.player.x = c.player.y = 5.0  # far from every blast below
    c.player.bombs = 5
    return c


def bomb_add_packet(owner, x, y, power=1, from_player=True, ticks=54):
    b = PacketBuilder()
    b.write_gshort(owner)
    b.write_gchar(int(x * 2))
    b.write_gchar(int(y * 2))
    b.write_gchar(power | (8 if from_player else 0))
    b.write_gchar(ticks)
    return b.build()


def explosion_packet(owner, radius, x, y, kind=1, from_player=False):
    b = PacketBuilder()
    b.write_gshort(owner)
    b.write_gchar(radius)
    b.write_gchar(int(x * 2))
    b.write_gchar(int(y * 2))
    b.write_gchar(kind | (8 if from_player else 0))
    return b.build()


def sent(client, packet_id):
    return [d for p, d in client._protocol.sent if p == int(packet_id)]


# -- wire layouts ----------------------------------------------------------

def test_bomb_add_exposes_owner_power_player_flag_and_ticks():
    info = parse_bomb_add(bomb_add_packet(7, 12.5, 20, power=3, from_player=True, ticks=54))
    assert (info['owner_id'], info['x'], info['y']) == (7, 12.5, 20.0)
    assert info['power'] == 3 and info['from_player'] is True and info['ticks'] == 54
    scripted = parse_bomb_add(bomb_add_packet(7, 1, 1, power=2, from_player=False))
    assert scripted['power'] == 2 and scripted['from_player'] is False


def test_explosion_layout_has_owner_id_and_type_flag():
    # TClient.cpp:3593-3620: type = flags & 7 (0 -> 1, >= 4 -> 3); bit 3 = owned.
    exp = parse_explosion(explosion_packet(300, 4, 10.5, 11, kind=3, from_player=True))
    assert exp == {'owner_id': 300, 'x': 10.5, 'y': 11.0, 'radius': 4,
                   'power': 3, 'from_player': True}
    assert parse_explosion(explosion_packet(1, 2, 1, 1, kind=0))['power'] == 1
    assert parse_explosion(explosion_packet(1, 2, 1, 1, kind=5))['power'] == 3
    assert parse_explosion(b'') == {}


# -- placement and the wire fuse ------------------------------------------

def test_put_bomb_sends_ticks_minus_5_and_keeps_full_fuse(client, clock):
    assert client.put_bomb(30.0, 30.0)
    data = sent(client, PacketID.PLI_BOMBADD)[0]
    assert data[2] - 32 == 1 | 8          # player-placed flag
    assert data[3] - 32 == 54             # counter 59 minus 5 (TServerLevel.cpp:1117)
    record = client.bombs[LEVEL][(30.0, 30.0)]
    assert record['fuse_s'] == pytest.approx(3.0)
    assert record['owner_id'] == 3 and record['from_player'] is True
    assert record['placed_at'] == clock.now


def test_short_fuse_is_not_reduced_and_gs1_path_has_no_player_flag(client):
    assert client.put_bomb(30.0, 30.0, 2, timer_ms=300, consume_ammo=False)
    data = sent(client, PacketID.PLI_BOMBADD)[0]
    assert data[2] - 32 == 2              # no |8 for a scripted bomb
    assert data[3] - 32 == 5              # ticks <= 5 are sent whole
    record = client.bombs[LEVEL][(30.0, 30.0)]
    assert record['fuse_s'] == pytest.approx(0.3) and record['from_player'] is False


def test_local_bomb_expires_at_its_full_fuse_remote_at_the_wire_fuse(client, clock):
    client.put_bomb(30.0, 30.0)
    handle_bomb_add(client, bomb_add_packet(9, 40, 40, ticks=54))
    client._tick_bomb_sims()
    assert len(client.bombs[LEVEL]) == 2
    clock.now += 2.74
    client._tick_bomb_sims()
    assert len(client.bombs[LEVEL]) == 2
    clock.now += 0.01                     # (54 + 1) * 50ms = 2.75s
    client._tick_bomb_sims()
    assert list(client.bombs[LEVEL]) == [(30.0, 30.0)]
    clock.now += 0.24
    client._tick_bomb_sims()
    assert list(client.bombs[LEVEL]) == [(30.0, 30.0)]
    clock.now += 0.01                     # 3.0s since placement
    client._tick_bomb_sims()
    assert client.bombs[LEVEL] == {}


def test_bomb_del_and_remove_bomb_stop_the_fuse_without_exploding(client, clock):
    exploded = Mock()
    client.on_bomb_exploded = exploded
    client.put_bomb(30.0, 30.0)
    handle_bomb_add(client, bomb_add_packet(9, 40, 40))
    client.remove_bomb(30.0, 30.0)
    b = PacketBuilder()
    b.write_gchar(80)
    b.write_gchar(80)
    handle_bomb_del(client, b.build())
    assert client.bombs[LEVEL] == {}
    clock.now += 10
    client._tick_bomb_sims()
    exploded.assert_not_called()


def test_echo_of_own_bomb_keeps_the_full_local_fuse(client):
    client.put_bomb(30.0, 30.0)
    handle_bomb_add(client, bomb_add_packet(3, 30, 30, ticks=54))
    assert client.bombs[LEVEL][(30.0, 30.0)]['fuse_s'] == pytest.approx(3.0)


def test_bombs_of_a_level_we_left_are_dropped_silently(client, clock):
    exploded = Mock()
    client.on_bomb_exploded = exploded
    client.put_bomb(30.0, 30.0)
    client._current_level_name = client._pending_level_name = 'elsewhere.nw'
    clock.now += 5
    client._tick_bomb_sims()
    assert client.bombs[LEVEL] == {}
    exploded.assert_not_called()


# -- chain detonation -------------------------------------------------------

def test_chain_detonation_hits_adjacent_bomb_and_spares_distant_one(client, clock):
    exploded = []
    client.on_bomb_exploded = lambda record, cells: exploded.append(record['wx'])
    client.put_bomb(30.0, 30.0, consume_ammo=False, timer_ms=500)
    client.put_bomb(32.0, 30.0, consume_ammo=False, timer_ms=60000)   # on A's arm
    client.put_bomb(50.0, 50.0, consume_ammo=False, timer_ms=60000)   # nowhere near
    clock.now += 0.5
    client._tick_bomb_sims()
    assert exploded == [30.0, 32.0]       # depth-first: A, then the one it lit
    assert list(client.bombs[LEVEL]) == [(50.0, 50.0)]


def test_chain_is_recursive_and_cannot_reenter(client, clock):
    exploded = []
    client.on_bomb_exploded = lambda record, cells: exploded.append(record['wx'])
    for x in (30.0, 32.0, 34.0, 36.0):    # each lies on the previous one's arm
        client.put_bomb(x, 30.0, consume_ammo=False, timer_ms=500 if x == 30.0 else 60000)
    clock.now += 0.5
    client._tick_bomb_sims()
    assert exploded == [30.0, 32.0, 34.0, 36.0]
    assert client.bombs[LEVEL] == {}


def test_callback_receives_every_cell_of_the_cross(client, clock):
    got = []
    client.on_bomb_exploded = lambda record, cells: got.append(cells)
    client.put_bomb(30.0, 30.0, 1, consume_ammo=False, timer_ms=100)
    clock.now += 0.1
    client._tick_bomb_sims()
    assert len(got[0]) == 9               # radius-2 cross: centre + 4 arms x 2


# -- self-damage ------------------------------------------------------------

def blast(client, x, y, radius=0, kind=1, owner=0, owned=False):
    handle_explosion(client, explosion_packet(owner, radius, x, y, kind, owned))


@pytest.mark.parametrize('px,py,hit', [
    (8.5, 8.0, True), (10.5, 10.0, True),     # inclusive 1.0 box edges
    (10.5, 8.0, True), (8.5, 10.0, True),
    (8.49, 9.0, False), (10.51, 9.0, False),
    (9.5, 7.99, False), (9.5, 10.01, False),
])
def test_self_damage_box_is_inclusive(client, px, py, hit):
    client.player.x, client.player.y = px, py
    hearts = client.player.hearts
    blast(client, 10.0, 10.0, radius=0)
    assert client.player.hearts == (hearts - 0.5 if hit else hearts)


def test_type_3_explosion_costs_a_full_heart(client):
    client.player.x, client.player.y = 9.5, 9.0
    hearts = client.player.hearts
    blast(client, 10.0, 10.0, radius=0, kind=3)
    assert client.player.hearts == hearts - 1.0
    assert sent(client, PacketID.PLI_PLAYERPROPS)   # hearts go out as a prop


def test_many_cells_in_one_explosion_hurt_once(client):
    client.player.x, client.player.y = 9.5, 9.0
    hurt = Mock()
    client.on_hurt = hurt
    hearts = client.player.hearts
    blast(client, 10.0, 10.0, radius=8)     # several arm cells overlap the player
    assert client.player.hearts == hearts - 0.5
    assert hurt.call_count == 1
    assert hurt.call_args.args[2] == 1      # damage type BOMB


def test_bomb_explosion_hurts_the_placer_too(client, clock):
    client.put_bomb(10.0, 10.0, timer_ms=100)
    client.player.x, client.player.y = 9.5, 9.0
    hearts = client.player.hearts
    clock.now += 0.1
    client._tick_bomb_sims()
    assert client.player.hearts == hearts - 0.5


def test_player_owned_bomb_attributes_the_hurt_to_its_owner(client, clock):
    hurt = Mock()
    client.on_hurt = hurt
    client.player.x, client.player.y = 9.5, 9.0
    handle_bomb_add(client, bomb_add_packet(8, 10, 10, ticks=2))
    clock.now += 1
    client._tick_bomb_sims()
    assert hurt.call_args.args[0] == 8


def test_knockback_follows_the_hitting_cells_direction(client):
    client.player.x, client.player.y = 11.5, 10.0   # right of the centre
    hurt = Mock()
    client.on_hurt = hurt
    blast(client, 10.0, 10.0, radius=2)
    # First overlapping cell in creation order is the centre (row 4 -> up).
    assert hurt.call_args.args[3:] == (0.0, -1.0)


@pytest.mark.parametrize('setup', ['ghost', 'dead', 'immune'])
def test_no_self_damage_when_ghost_dead_or_immune(client, clock, setup):
    client.player.x, client.player.y = 9.5, 9.0
    if setup == 'ghost':
        client.ghost_mode = 1
    elif setup == 'dead':
        client.player.hearts = 0
    else:
        client.respond_to_hurt(0.5)         # starts the 40-tick immunity
    hearts = client.player.hearts
    blast(client, 10.0, 10.0, radius=2)
    assert client.player.hearts == hearts


def test_no_self_damage_for_a_bomb_on_another_level(client, clock):
    client.player.x, client.player.y = 9.5, 9.0
    record = client._register_bomb(
        'other.nw', 10.0, 10.0, wx=10.0, wy=10.0, owner_id=9, from_player=True,
        power=1, fuse_s=1.0, placed_at=clock.now)
    hearts = client.player.hearts
    assert client._explode_bomb(record)
    assert client.player.hearts == hearts


def test_explosion_packet_chains_into_a_ticking_bomb(client, clock):
    exploded = []
    client.on_bomb_exploded = lambda record, cells: exploded.append(record['wx'])
    handle_bomb_add(client, bomb_add_packet(9, 14, 10, ticks=200))  # on the right arm tip
    handle_bomb_add(client, bomb_add_packet(9, 50, 50, ticks=200))
    client.player.x, client.player.y = 7.0, 9.0   # reached by A's left arm only
    hurt = Mock()
    client.on_hurt = hurt
    handle_explosion(client, explosion_packet(300, 2, 10, 10, 1, True))
    assert exploded == [14.0]
    assert list(client.bombs[LEVEL]) == [(50.0, 50.0)]
    assert hurt.call_args.args[0] == 300    # owner bit set -> attributed
    assert client.active_explosions        # presentation cells kept


def test_explosion_packet_without_owner_bit_is_unattributed(client):
    hurt = Mock()
    client.on_hurt = hurt
    client.player.x, client.player.y = 9.5, 9.0
    blast(client, 10.0, 10.0, radius=0, owner=300, owned=False)
    assert hurt.call_args.args[0] == 0


def test_knockback_is_defined_for_every_arm_sprite_row():
    from pyreborn.explosions import knockback
    assert all(len(knockback(row)) == 2 for row in range(9))
