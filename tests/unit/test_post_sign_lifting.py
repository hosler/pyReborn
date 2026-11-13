"""Checks for lifting and throwing the standalone 2x2 post sign.

The post sign is row 1 of the reference client's liftable-object table
(pyreborn/liftobjects.py), reachable bare-handed. Wall signs share the art
family but are not a liftable pattern, so they stay readable.
"""

import pytest

from offline_game import spy
from pyreborn.liftobjects import LIFT_OBJECTS, LIFT_REPLACE, match_lift_object


POST_SIGN_TILES = (512, 513, 528, 529)
WALL_SIGN_TILES = (1384, 1385, 1400, 1401)
GRASS = 77


@pytest.fixture
def new_harness(make_game, monkeypatch):
    """``new_harness(**knobs)``: a real offline game on an all-grass board
    (tile 77) with the player at (0, 0) facing down and the lift probe fixed
    on tile (10, 10). ``game.tiles`` is the client's board, ``game.sent``
    the modify_board calls (call-through)."""
    def build(**knobs):
        knobs.setdefault('tiles', lambda tx, ty: GRASS)
        game = make_game(**knobs)
        game.tiles = game.client.tiles
        game.sent = spy(monkeypatch, game.client, 'modify_board')
        player = game.client.player
        player.x = player.y = 0.0
        player.direction = 2
        monkeypatch.setattr(game, '_touch_points', lambda direction: [(10, 10)])
        monkeypatch.setattr(game, '_lift_probe_tile', lambda direction: (10, 10))
        return game
    return build


def _place_post_sign(game):
    for tile_id, (x, y) in zip(POST_SIGN_TILES,
                              ((10, 10), (11, 10), (10, 11), (11, 11))):
        game.tiles[y * 64 + x] = tile_id


def test_only_the_post_sign_pattern_matches(new_harness):
    """A wall sign is not a liftable pattern, and neither is one stray tile."""
    game = new_harness()
    _place_post_sign(game)
    assert match_lift_object(game._get_tile_at, 10, 10, 0) is not None
    # Same tile ids, but only three of the four quadrants: no object.
    game.tiles[11 * 64 + 11] = 77
    assert match_lift_object(game._get_tile_at, 10, 10, 0) is None

    game = new_harness()
    for tile_id, (x, y) in zip(WALL_SIGN_TILES,
                               ((10, 10), (11, 10), (10, 11), (11, 11))):
        game.tiles[y * 64 + x] = tile_id
    assert match_lift_object(game._get_tile_at, 10, 10, 3) is None


def test_any_quadrant_of_the_object_finds_the_same_origin(new_harness):
    """The touched tile can be any of the four corners."""
    game = new_harness()
    _place_post_sign(game)
    for x, y in ((10, 10), (11, 10), (10, 11), (11, 11)):
        match = match_lift_object(game._get_tile_at, x, y, 0)
        assert match is not None
        assert (match.origin_x, match.origin_y) == (10, 10)


def test_lift_writes_the_reference_replacement_tiles(new_harness):
    """Each row has its OWN ground; lifting is not a fill with grass."""
    game = new_harness()
    _place_post_sign(game)

    assert game._lift_in_front(2) is True
    assert game.client.player.carried_object_type == "sign"
    assert game.client.player.carried_tile_ids == POST_SIGN_TILES

    tl, bl, tr, br = LIFT_REPLACE[1]
    assert [game.tiles[y * 64 + x] for x, y in
            ((10, 10), (11, 10), (10, 11), (11, 11))] == [tl, tr, bl, br]
    assert len(game.sent) == 4, "the lift has to reach the other players too"


def test_a_row_out_of_glove_reach_simply_does_not_match(new_harness):
    """Glove power is an index ceiling, not a per-object requirement."""
    game = new_harness()
    heavy = LIFT_OBJECTS[4]
    for tile_id, (x, y) in zip((heavy[0], heavy[2], heavy[1], heavy[3]),
                               ((10, 10), (11, 10), (10, 11), (11, 11))):
        game.tiles[y * 64 + x] = tile_id

    assert match_lift_object(game._get_tile_at, 10, 10, 0) is None
    assert match_lift_object(game._get_tile_at, 10, 10, 3) is not None


def test_post_sign_grab_wins_over_reading_but_wall_sign_still_reads(new_harness, monkeypatch):
    game = new_harness()
    monkeypatch.setattr(game, '_find_chest_in_front', lambda: None)
    monkeypatch.setattr(game, '_get_non_edge_door', lambda: None)
    monkeypatch.setattr(game.client, 'pickup_item', lambda *args: None)
    shown = []
    monkeypatch.setattr(game, '_show_dialogue',
                        lambda text, **_options: shown.append(text))
    monkeypatch.setattr(game, '_check_sign_nearby', lambda: "read me")

    _place_post_sign(game)
    game._try_grab()
    assert game.client.player.carried_object_type == "sign"
    assert shown == []

    game.client.player.throw_object()
    game.tiles[10 * 64 + 10] = WALL_SIGN_TILES[0]
    game._try_grab()
    assert game.client.player.is_carrying() is False
    assert shown == ["read me"]


def test_sign_auto_popup_at_classic_flush_up_position(new_harness, monkeypatch):
    game = new_harness(signs=[(11, 12, "read me")], player_xy=(10.0, 10.0))
    game.client.player.x = game.client.player.y = 10.0
    game.client.player.direction = 0
    shown = []
    monkeypatch.setattr(game, '_render_sign_popup', shown.append)
    game._check_and_render_signs()
    assert shown == ["read me\n"]    # the server ends every sign line with a newline


def test_thrown_post_sign_uses_smash_path(new_harness, monkeypatch):
    game = new_harness()
    plays = spy(monkeypatch, game.sound_mgr, "play")
    game.client.player.pickup_object("sign", POST_SIGN_TILES, (10, 10))
    game._throw_object()

    assert game.thrown_objects[0]["type"] == "sign"
    game._update_and_render_thrown(1.0)
    assert game.thrown_objects == []
    assert len(game.break_effects) == 1
    assert game.break_effects[0]["leap_type"] == 3
    assert game.break_effects[0]["tiles"] == POST_SIGN_TILES
    assert (("crush.wav",), {}) in plays
