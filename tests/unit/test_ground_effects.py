"""Lava damage, beds and water rules (TPlayer.cpp:5887-6055, :7350-7362)."""

import pytest

from offline_game import spy
from pyreborn import ground_effects as ge
from pyreborn.tiletypes import TILE_TYPES


def tile_of(kind):
    return next(i for i, t in enumerate(TILE_TYPES) if t == kind)


def test_oracle_constants():
    assert ge.LAVA_TILE_TYPES == (2, 9, 12)  # TPlayer.cpp:5898
    assert ge.LAVA_DAMAGE == 0.5  # DOUBLE_00402678, TInitStatics.cpp:1279
    assert ge.SLEEP_HEAL == 0.5  # DOUBLE_00402410, TInitStatics.cpp:1253
    assert ge.HP_TICKS == 100  # TPlayer.cpp:5906 / :7353 (> 100)
    assert ge.BED_TILE_TYPE == 4  # TPlayer.cpp:5942
    assert ge.BED_COLUMNS == (1.0, 2.0) and ge.BED_ROWS == (0.0, 0.5)
    assert ge.LAVA_SWIM_TILE_TYPE == 12  # TPlayer.cpp:6021 (0xc)


def test_tick_counter_fires_on_101st_tick_then_resets():
    counter = ge.TickCounter()
    assert counter.advance(100 * 0.05, True) == 0
    assert counter.advance(0.05, True) == 1  # the 101st tick
    assert counter.advance(100 * 0.05, True) == 0
    assert counter.advance(0.05, True) == 1


def test_tick_counter_inactive_tick_resets():
    counter = ge.TickCounter()
    counter.advance(60 * 0.05, True)
    counter.advance(0.05, False)
    assert counter.advance(100 * 0.05, True) == 0
    assert counter.advance(0.05, True) == 1


def test_tick_counter_accumulates_fractional_frames():
    counter = ge.TickCounter()
    fired = sum(counter.advance(1 / 60, True) for _ in range(61 * 5))
    assert fired == 1  # ~5.08 s of 20 Hz ticks is 101 ticks


def test_lava_types_and_bed_snap():
    assert [t for t in range(16) if ge.is_lava_type(t)] == [2, 9, 12]
    assert ge.bed_snap_y(20.0, True) == 20.0
    assert ge.bed_snap_y(20.25, True) == 20.0  # floorToInt(y + 0.0001)
    assert ge.bed_snap_y(20.0, False) == 20.0  # +0.5 then floor
    assert ge.bed_snap_y(20.75, False) == 21.0


@pytest.fixture
def new_game(make_game, monkeypatch):
    """A real offline game on an all-type-0 board at (20.0, 20.75), with a
    call-through spies on ``client.send_hearts``, ``_spawn_leaps``, the sound
    manager and the player animation (``hearts_calls``, ``leap_calls``,
    ``sound_calls``, ``anim_calls``)."""
    def build():
        game = make_game(player_xy=(20.0, 20.75), tiles=lambda tx, ty: 0,
                         hearts=3.0)
        # The server rounds a login position to half tiles; the tests want
        # the quarter-tile row the rules are pinned at.
        game.client.player.x, game.client.player.y = 20.0, 20.75
        game.hearts_calls = spy(monkeypatch, game.client, "send_hearts")
        game.leap_calls = spy(monkeypatch, game, "_spawn_leaps")
        game.sound_calls = spy(monkeypatch, game.sound_mgr, "play")
        game.anim_calls = spy(monkeypatch, game.player_anim, "set_animation")
        return game
    return build


def set_tile(game, x, y, tile):
    game.client.tiles[int(x) + int(y) * 64] = tile


def ground_tile(game, tile, dy=0.0):
    """Put `tile` under the (x+1.5, y+2.0+dy) sample point."""
    set_tile(game, game.client.x + 1.5, game.client.y + 2.0 + dy, tile)


@pytest.mark.parametrize("kind,hurts", [(2, True), (9, True), (12, True),
                                        (0, False), (6, False), (11, False), (8, False)])
def test_lava_damage_by_tile_type(kind, hurts, new_game):
    game = new_game()
    ground_tile(game, tile_of(kind))
    for _ in range(100):
        game._advance_ground_effects(0.05)
    assert game.client.player.hearts == 3.0
    game._advance_ground_effects(0.05)
    assert (game.client.player.hearts == 2.5) is hurts


def test_lava_samples_y_plus_two_not_two_and_a_half(new_game):
    game = new_game()  # y = 20.75: y+2.0 is row 22, y+2.5 is row 23
    ground_tile(game, tile_of(12), dy=0.5)  # lava only under y+2.5
    for _ in range(101):
        game._advance_ground_effects(0.05)
    assert game.client.player.hearts == 3.0
    ground_tile(game, tile_of(12))
    for _ in range(101):
        game._advance_ground_effects(0.05)
    assert game.client.player.hearts == 2.5


def test_lava_damage_is_reported_and_bypasses_swim_immunity(new_game):
    game = new_game()
    ground_tile(game, tile_of(12))
    game.client.player.animation = 'lava'  # no_hurt() is true while swimming
    for _ in range(101):
        game._advance_ground_effects(0.05)
    assert game.client.player.hearts == 2.5
    assert game.hearts_calls == [((), {})]


def test_lava_can_kill_and_stops_at_zero(new_game):
    game = new_game()
    game.client.player.hearts = 0.5
    ground_tile(game, tile_of(2))
    for _ in range(101):
        game._advance_ground_effects(0.05)
    assert game.client.player.hearts == 0.0


def test_leaving_lava_resets_the_timer(new_game):
    game = new_game()
    lava = tile_of(12)
    ground_tile(game, lava)
    for _ in range(90):
        game._advance_ground_effects(0.05)
    ground_tile(game, 0)
    game._advance_ground_effects(0.05)
    ground_tile(game, lava)
    for _ in range(100):
        game._advance_ground_effects(0.05)
    assert game.client.player.hearts == 3.0


def test_sleeping_heals_half_a_heart_per_101_ticks(new_game):
    game = new_game()
    game.client.player.hearts = 1.0
    game.current_anim_name = 'sleep'
    for _ in range(100):
        game._advance_ground_effects(0.05)
    assert game.hearts_calls == []
    game._advance_ground_effects(0.05)
    assert game.hearts_calls == [((1.5,), {})]


def test_sleeping_at_full_health_sends_nothing(new_game):
    game = new_game()
    game.current_anim_name = 'sleep'
    for _ in range(202):
        game._advance_ground_effects(0.05)
    assert game.hearts_calls == []


BED = tile_of(4)


def lay_bed(game, columns=(1, 2), rows=(0.0, 0.5)):
    for col in columns:
        for row in rows:
            set_tile(game, game.client.x + col, game.client.y + row, BED)


def test_bed_needs_both_columns(new_game):
    game = new_game()
    lay_bed(game, columns=(1,))
    game._test_sleeping()
    assert game.current_anim_name == 'idle'
    lay_bed(game, columns=(2,))
    game._test_sleeping()
    assert game.current_anim_name == 'sleep'


def test_bed_top_row_hit_snaps_down_to_tile(new_game):
    game = new_game()
    game.client.player.y = 20.25
    lay_bed(game, rows=(0.0,))
    game._test_sleeping()
    assert game.client.y == 20.0
    assert game.current_anim_name == 'sleep'


def test_bed_only_lower_row_hit_moves_half_a_tile_then_snaps(new_game):
    game = new_game()  # y = 20.75: row y is tile 20, row y+0.5 is tile 21
    game.client.player.y = 20.75
    for col in (1, 2):
        set_tile(game, game.client.x + col, game.client.y + 0.5, BED)
    game._test_sleeping()
    assert game.client.y == 21.0  # 20.75 + 0.5 = 21.25 -> floor


@pytest.mark.parametrize("setup", ["carrying", "sitting", "mode", "dead"])
def test_bed_refused_while(setup, new_game):
    game = new_game()
    lay_bed(game)
    player = game.client.player
    if setup == "carrying":
        player.pickup_object('bush', (1, 2, 3, 4), (0, 0))
    elif setup == "sitting":
        player.is_sitting = True
    elif setup == "mode":
        player.action_mode = 10
    else:
        object.__setattr__(player, 'hearts', 0.0)
    game._test_sleeping()
    assert game.current_anim_name == 'idle'


def test_bed_test_runs_on_key_release_and_level_entry_only(new_game):
    game = new_game()
    lay_bed(game)
    game._update_sleeping_state()  # level entry
    assert game.current_anim_name == 'sleep'
    game.current_anim_name = 'idle'
    game._update_sleeping_state()  # nothing changed: no re-test
    assert game.current_anim_name == 'idle'
    game.is_moving = True
    game._update_sleeping_state()
    game.is_moving = False
    game._update_sleeping_state()  # released
    assert game.current_anim_name == 'sleep'


# Water ------------------------------------------------------------------

def test_water_sampled_at_y_plus_two_not_two_and_a_half(new_game):
    game = new_game()
    set_tile(game, game.client.x + 1.5, game.client.y + 2.5, tile_of(11))
    game._update_swimming_state()
    assert not game.is_swimming
    ground_tile(game, tile_of(11))
    game._update_swimming_state()
    assert game.is_swimming


def test_lava_tile_swims_with_the_lava_gani(new_game):
    game = new_game()
    ground_tile(game, tile_of(12))
    game._update_swimming_state()
    assert game.is_swimming and game.current_anim_name == 'lava'
    ground_tile(game, tile_of(11))
    game._update_swimming_state()
    assert game.is_swimming and game.current_anim_name == 'swim'


def test_swimming_drops_the_carried_object(new_game):
    game = new_game()
    game.client.player.pickup_object('vase', (1, 2, 3, 4), (0, 0))
    ground_tile(game, tile_of(11))
    game._update_swimming_state()
    assert not game.client.player.is_carrying()
    assert len(game.thrown_objects) == 1
    assert game.current_anim_name == 'swim'


def test_swimming_blocks_sword_weapon_and_lift(new_game, monkeypatch):
    game = new_game()
    ground_tile(game, tile_of(11))
    game._update_swimming_state()
    swings = spy(monkeypatch, game.client, "sword_attack")
    game._swing_sword()
    assert swings == []

    def refuse():
        raise AssertionError("weapon use reached the inventory")
    monkeypatch.setattr(game.inventory_ui, "get_selected_weapon", refuse)
    game._use_weapon()  # returns before touching the inventory
    assert game._lift_in_front(2) is False


def test_sword_refused_when_facing_water_but_allowed_on_land(new_game,
                                                              monkeypatch):
    from pyreborn.liftobjects import LIFT_PROBE
    game = new_game()
    swings = spy(monkeypatch, game.client, "sword_attack")
    game.client.player.direction = 3
    ox, oy = LIFT_PROBE[3]  # laytest == lifttestd (TInitStatics.cpp:1548)
    set_tile(game, game.client.x + ox, game.client.y + oy, tile_of(11))
    game._swing_sword()
    assert swings == []
    set_tile(game, game.client.x + ox, game.client.y + oy, 0)
    game._swing_sword()
    assert swings == [((3,), {})]
