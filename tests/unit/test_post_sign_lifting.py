"""Checks for lifting and throwing the standalone 2x2 post sign.

The post sign is row 1 of the reference client's liftable-object table
(pyreborn/liftobjects.py), reachable bare-handed. Wall signs share the art
family but are not a liftable pattern, so they stay readable.
"""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame

from pyreborn.game.actions import ActionsMixin
from pyreborn.game.collision import CollisionMixin
from pyreborn.game.render_effects import EffectsRenderMixin
from pyreborn.game.render_objects import LevelObjectsRenderMixin
from pyreborn.liftobjects import LIFT_OBJECTS, LIFT_REPLACE, match_lift_object
from pyreborn.player import Player
from pyreborn.tiletypes import TileType


POST_SIGN_TILES = (512, 513, 528, 529)
WALL_SIGN_TILES = (1384, 1385, 1400, 1401)


class _Recorder:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)


class _Anim:
    def set_animation(self, *args, **kwargs):
        pass


class _Gani:
    def parse(self, name):
        return object()


class _Harness(ActionsMixin, CollisionMixin, EffectsRenderMixin):
    def __init__(self):
        pygame.init()
        self.tiles = [77] * 4096
        self.grass_tile_id = 77
        self.client = SimpleNamespace(
            player=Player(x=0, y=0, direction=2), x=0, y=0,
            in_gmap_segment=False,
            get_current_level_from_position=lambda: "test.nw",
            modify_board=self._modify_board,
        )
        self.player_anim = _Anim()
        self.gani_parser = _Gani()
        self.sound_mgr = _Recorder()
        self.current_anim_name = "idle"
        self.world_surface = object()
        self.thrown_objects = []
        self.other_thrown_objects = []
        self.break_effects = []
        self._pushaway_velocity = (0.0, 0.0)
        self.sent = []

    def _modify_board(self, x, y, w, h, tiles):
        """Stand-in for Client.modify_board: patch locally, count the sends."""
        for row in range(h):
            for col in range(w):
                self.tiles[(y + row) * 64 + (x + col)] = tiles[row * w + col]
        self.sent.append((x, y, w, h, tuple(tiles)))
        return True

    def _get_tile_at(self, x, y):
        ix, iy = int(x), int(y)
        if 0 <= ix < 64 and 0 <= iy < 64:
            return self.tiles[iy * 64 + ix]
        return 77

    def _level_tiles_at(self, x, y):
        return "test.nw", self.tiles

    def _touch_points(self, direction):
        return [(10, 10)]

    def _update_and_render_other_thrown(self, dt, frame=None):
        pass

    def _apply_pushaway(self, dt):
        pass


class _SignPopupHarness(LevelObjectsRenderMixin):
    def __init__(self):
        self.client = SimpleNamespace(
            player=Player(x=10, y=10, direction=0),
            _current_level_name="test.nw",
            signs={"test.nw": {(11, 12): "read me"}},
            gmap_width=0,
            in_gmap_segment=False,
        )
        self.shown = []

    def _render_sign_popup(self, text):
        self.shown.append(text)


def _place_post_sign(game):
    for tile_id, (x, y) in zip(POST_SIGN_TILES,
                              ((10, 10), (11, 10), (10, 11), (11, 11))):
        game.tiles[y * 64 + x] = tile_id


def test_only_the_post_sign_pattern_matches():
    """A wall sign is not a liftable pattern, and neither is one stray tile."""
    game = _Harness()
    _place_post_sign(game)
    assert match_lift_object(game._get_tile_at, 10, 10, 0) is not None
    # Same tile ids, but only three of the four quadrants: no object.
    game.tiles[11 * 64 + 11] = 77
    assert match_lift_object(game._get_tile_at, 10, 10, 0) is None

    game = _Harness()
    for tile_id, (x, y) in zip(WALL_SIGN_TILES,
                               ((10, 10), (11, 10), (10, 11), (11, 11))):
        game.tiles[y * 64 + x] = tile_id
    assert match_lift_object(game._get_tile_at, 10, 10, 3) is None


def test_any_quadrant_of_the_object_finds_the_same_origin():
    """The touched tile can be any of the four corners."""
    game = _Harness()
    _place_post_sign(game)
    for x, y in ((10, 10), (11, 10), (10, 11), (11, 11)):
        match = match_lift_object(game._get_tile_at, x, y, 0)
        assert match is not None
        assert (match.origin_x, match.origin_y) == (10, 10)


def test_lift_writes_the_reference_replacement_tiles():
    """Each row has its OWN ground; lifting is not a fill with grass."""
    game = _Harness()
    _place_post_sign(game)

    assert game._lift_in_front(2) is True
    assert game.client.player.carried_object_type == "sign"
    assert game.client.player.carried_tile_ids == POST_SIGN_TILES

    tl, bl, tr, br = LIFT_REPLACE[1]
    assert [game.tiles[y * 64 + x] for x, y in
            ((10, 10), (11, 10), (10, 11), (11, 11))] == [tl, tr, bl, br]
    assert len(game.sent) == 4, "the lift has to reach the other players too"


def test_a_row_out_of_glove_reach_simply_does_not_match():
    """Glove power is an index ceiling, not a per-object requirement."""
    game = _Harness()
    heavy = LIFT_OBJECTS[4]
    for tile_id, (x, y) in zip((heavy[0], heavy[2], heavy[1], heavy[3]),
                               ((10, 10), (11, 10), (10, 11), (11, 11))):
        game.tiles[y * 64 + x] = tile_id

    assert match_lift_object(game._get_tile_at, 10, 10, 0) is None
    assert match_lift_object(game._get_tile_at, 10, 10, 3) is not None


def test_post_sign_grab_wins_over_reading_but_wall_sign_still_reads():
    game = _Harness()
    game._find_chest_in_front = lambda: None
    game._get_non_edge_door = lambda: None
    game.client.pickup_item = lambda *args: None
    shown = []
    game._show_dialogue = lambda text, **_options: shown.append(text)
    game._check_sign_nearby = lambda: "read me"

    _place_post_sign(game)
    game._try_grab()
    assert game.client.player.carried_object_type == "sign"
    assert shown == []

    game.client.player.throw_object()
    game.tiles[10 * 64 + 10] = WALL_SIGN_TILES[0]
    game._try_grab()
    assert game.client.player.is_carrying() is False
    assert shown == ["read me"]


def test_sign_auto_popup_at_classic_flush_up_position():
    game = _SignPopupHarness()
    game._check_and_render_signs()
    assert game.shown == ["read me"]


def test_thrown_post_sign_uses_smash_path():
    game = _Harness()
    game.client.player.pickup_object("sign", POST_SIGN_TILES, (10, 10))
    game._throw_object()

    assert game.thrown_objects[0]["type"] == "sign"
    game._update_and_render_thrown(1.0)
    assert game.thrown_objects == []
    assert len(game.break_effects) == 1
    assert game.break_effects[0]["colors"] == game.BREAK_COLORS["sign"]
    assert "crush.wav" in game.sound_mgr.played
