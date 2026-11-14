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
from pyreborn.packets import PacketID, build_bomb_del, parse_bomb_add, parse_explosion
from reborn_protocol import PacketBuilder
from .test_gs1_combat_family import _npc_gs1

LEVEL = 'bombs.nw'


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(sim_time, monkeypatch):
    c = Clock()
    sim_time(c)
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
    record = next(iter(client.bombs[LEVEL].values()))
    assert record['fuse_s'] == pytest.approx(3.0)
    assert record['owner_id'] == 3 and record['from_player'] is True
    assert record['placed_at'] == clock.now


def test_short_fuse_is_not_reduced_and_gs1_path_has_no_player_flag(client):
    assert client.put_bomb(30.0, 30.0, 2, timer_ms=300, consume_ammo=False)
    data = sent(client, PacketID.PLI_BOMBADD)[0]
    assert data[2] - 32 == 2              # no |8 for a scripted bomb
    assert data[3] - 32 == 5              # ticks <= 5 are sent whole
    record = next(iter(client.bombs[LEVEL].values()))
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
    assert [(b['x'], b['y']) for b in client.bombs[LEVEL].values()] == [(30.0, 30.0)]
    clock.now += 0.24
    client._tick_bomb_sims()
    assert [(b['x'], b['y']) for b in client.bombs[LEVEL].values()] == [(30.0, 30.0)]
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
    assert next(iter(client.bombs[LEVEL].values()))['fuse_s'] == pytest.approx(3.0)


@pytest.mark.parametrize('source', ['local', 'wire'])
def test_stacked_bombs_both_tick_and_explode_once(client, clock, source):
    exploded = []
    client.on_bomb_exploded = lambda record, cells: exploded.append(record)
    for _ in range(2):
        if source == 'local':
            assert client.put_bomb(30.5, 30.0, timer_ms=300, consume_ammo=False)
        else:
            handle_bomb_add(client, bomb_add_packet(9, 30.5, 30.0, ticks=5))
    records = list(client._bomb_records())
    assert len(records) == 2 and records[0] is not records[1]
    clock.now += .29
    client._tick_bomb_sims()
    assert not exploded and len(list(client._bomb_records())) == 2
    clock.now += .01
    client._tick_bomb_sims()
    assert [id(b) for b in exploded] == [id(b) for b in records]
    assert client.bombs[LEVEL] == {}
    client._tick_bomb_sims()
    assert len(exploded) == 2


def test_stacked_bombs_keep_independent_fuses_without_chain_detonation(client, clock):
    # Isolate animateBombs from the explosion probes to exercise both timers.
    client._explosion_cells = Mock(return_value=None)
    exploded = []
    client.on_bomb_exploded = lambda record, cells: exploded.append(record['bomb_id'])
    for fuse_ms in (300, 600):
        client.put_bomb(30.0, 30.0, timer_ms=fuse_ms, consume_ammo=False)
    first, second = list(client._bomb_records())
    clock.now += .3
    client._tick_bomb_sims()
    assert exploded == [first['bomb_id']]
    assert list(client._bomb_records()) == [second]
    clock.now += .3
    client._tick_bomb_sims()
    assert exploded == [first['bomb_id'], second['bomb_id']]
    assert client.bombs[LEVEL] == {}


def test_drop_removes_only_the_identical_stacked_record(client):
    for _ in range(2):
        client.put_bomb(30, 30, consume_ammo=False)
    first, second = list(client._bomb_records())
    assert not client._drop_bomb_record(dict(first))
    assert client._drop_bomb_record(second)
    assert list(client._bomb_records()) == [first]


@pytest.mark.parametrize('removal', ['wire', 'local'])
def test_bomb_del_removes_all_stacked_bombs_only_on_its_level(client, clock, removal):
    for owner in (8, 9):
        handle_bomb_add(client, bomb_add_packet(owner, 30.5, 30))
    handle_bomb_add(client, bomb_add_packet(9, 31, 30))
    neighbor = client._register_bomb(
        'neighbor.nw', 30.5, 30, wx=94.5, wy=30, owner_id=9,
        from_player=True, power=1, fuse_s=3, placed_at=clock.now)
    if removal == 'wire':
        handle_bomb_del(client, build_bomb_del(30.5, 30))
        assert not sent(client, PacketID.PLI_BOMBDEL)
    else:
        assert client.remove_bomb(30.5, 30)
        assert sent(client, PacketID.PLI_BOMBDEL) == [build_bomb_del(30.5, 30)]
    assert [(b['x'], b['y']) for b in client.bombs[LEVEL].values()] == [(31, 30)]
    assert list(client.bombs['neighbor.nw'].values()) == [neighbor]


@pytest.mark.parametrize('x,matches', [
    (30.24, True), (30.24994, True), (30.24996, False), (30.25, False),
    (29.75, True), (29.74994, False),
])
def test_remove_bombs_uses_reference_half_tile_rounding(client, x, matches):
    for _ in range(2):
        client.put_bomb(30, 30, consume_ammo=False)
    removed = client._remove_bombs_at(LEVEL, x, 30)
    assert len(removed) == (2 if matches else 0)
    assert len(client.bombs[LEVEL]) == (0 if matches else 2)


def test_stacked_local_echoes_consume_one_pending_placement_each(client):
    for _ in range(2):
        client.put_bomb(30, 30)
    first, second = list(client._bomb_records())
    handle_bomb_add(client, bomb_add_packet(9, 30, 30))
    assert len(client.bombs[LEVEL]) == 3  # another owner's bomb must append
    handle_bomb_add(client, bomb_add_packet(3, 30, 30))
    assert first['echoed'] and not second.get('echoed')
    handle_bomb_add(client, bomb_add_packet(3, 30, 30))
    assert second['echoed'] and len(client.bombs[LEVEL]) == 3
    assert first['fuse_s'] == second['fuse_s'] == pytest.approx(3)
    handle_bomb_add(client, bomb_add_packet(3, 30, 30))
    assert len(client.bombs[LEVEL]) == 4  # no pending echo remains


def test_placement_ids_are_client_wide_and_never_reused(client, clock):
    client.put_bomb(30, 30, consume_ammo=False)
    first = next(iter(client._bomb_records()))
    neighbor = client._register_bomb(
        'neighbor.nw', 30, 30, wx=94, wy=30, owner_id=9,
        from_player=True, power=1, fuse_s=3, placed_at=clock.now)
    client._remove_bombs_at(LEVEL, 30, 30)
    client.put_bomb(30, 30, consume_ammo=False)
    latest = next(iter(client.bombs[LEVEL].values()))
    assert first['bomb_id'] < neighbor['bomb_id'] < latest['bomb_id']


def test_gs1_bombs_array_keeps_stacked_bombs_in_placement_order(client):
    gs1 = _npc_gs1(client, 5, """if (playertouchsme) {
        this.n = bombscount;
        this.first = bombs[0].power;
        this.middle = bombs[1].power;
        this.last = bombs[2].power;
        this.x0 = bombs[0].x;
        this.x2 = bombs[2].x;
    }""")
    for x, power in ((30, 1), (40, 3), (30, 2)):
        client.put_bomb(x, 30, power=power, consume_ammo=False)
    gs1.trigger_npc_event(5, 'playertouchsme')
    scope = gs1._progs['npc_5']['scopes']['this']
    assert [scope.get(k) for k in ('n', 'first', 'middle', 'last')] == [3, 1, 3, 2]
    assert scope.get('x0') == scope.get('x2') == 30


def test_gs1_removebomb_removes_the_whole_stack_and_sends_once(client):
    gs1 = _npc_gs1(client, 5, 'if (playertouchsme) { removebomb 2; }')
    for x in (30, 40, 30):
        client.put_bomb(x, 30, consume_ammo=False)
    gs1.trigger_npc_event(5, 'playertouchsme')
    assert [b['x'] for b in client._bomb_records()] == [40]
    assert sent(client, PacketID.PLI_BOMBDEL) == [build_bomb_del(30, 30)]


def test_gs1_explodebomb_removes_the_selected_object_before_chaining(client):
    gs1 = _npc_gs1(client, 5, 'if (playertouchsme) { explodebomb 1; }')
    for _ in range(2):
        client.put_bomb(30, 30, consume_ammo=False)
    first, second = list(client._bomb_records())
    # Disable chain probes so the unselected object survives this explosion.
    client._explosion_cells = Mock(return_value=None)
    exploded = Mock()
    client.on_bomb_exploded = exploded
    gs1.trigger_npc_event(5, 'playertouchsme')
    assert exploded.call_args.args[0] is second
    assert list(client._bomb_records()) == [first]
    assert sent(client, PacketID.PLI_BOMBDEL) == [build_bomb_del(30, 30)]


def test_bombs_of_a_level_we_left_are_dropped_silently(client, clock):
    exploded = Mock()
    client.on_bomb_exploded = exploded
    client.put_bomb(30.0, 30.0)
    client._current_level_name = client._level_scope = 'elsewhere.nw'
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
    assert [(b['x'], b['y']) for b in client.bombs[LEVEL].values()] == [(50.0, 50.0)]


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
    assert [(b['x'], b['y']) for b in client.bombs[LEVEL].values()] == [(50.0, 50.0)]
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
