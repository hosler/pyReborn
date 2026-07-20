"""Checks for lifting and throwing the standalone 2x2 post sign."""

import json
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
from pyreborn.game.constants import TILE_CORRECTIONS_FILE
from pyreborn.game.render_effects import EffectsRenderMixin
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
        with open(TILE_CORRECTIONS_FILE, encoding="utf-8") as source:
            self.tile_corrections = {int(k): v for k, v in json.load(source).items()}
        self.tiles = [77] * 4096
        self.grass_tile_id = 77
        self.client = SimpleNamespace(
            player=Player(x=0, y=0, direction=2), x=0, y=0,
            in_gmap_segment=False,
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

    def _get_tile_at(self, x, y):
        ix, iy = int(x), int(y)
        if 0 <= ix < 64 and 0 <= iy < 64:
            return self.tiles[iy * 64 + ix]
        return 77

    def _level_tiles_at(self, x, y):
        return "test.nw", self.tiles

    def _touch_points(self, direction):
        return [(10, 10)]

    def _update_and_render_other_thrown(self, dt):
        pass

    def _apply_pushaway(self, dt):
        pass


def _place_post_sign(game):
    for tile_id, (x, y) in zip(POST_SIGN_TILES,
                              ((10, 10), (11, 10), (10, 11), (11, 11))):
        game.tiles[y * 64 + x] = tile_id


def test_only_post_sign_tiles_are_classified_liftable():
    game = _Harness()
    assert all(game._is_tile_liftable(tile_id) for tile_id in POST_SIGN_TILES)
    assert all(not game._is_tile_liftable(tile_id) for tile_id in WALL_SIGN_TILES)
    assert game._get_liftable_name(512) == "sign"
    assert game._get_tile_lift_power(512) == 0


def test_lift_replaces_all_post_sign_quadrants_with_ground():
    game = _Harness()
    _place_post_sign(game)

    assert game._lift_in_front(2) is True
    assert game.client.player.carried_object_type == "sign"
    assert game.client.player.carried_tile_ids == POST_SIGN_TILES
    assert [game.tiles[y * 64 + x] for x, y in
            ((10, 10), (11, 10), (10, 11), (11, 11))] == [77] * 4


def test_post_sign_grab_wins_over_reading_but_wall_sign_still_reads():
    game = _Harness()
    game._find_chest_in_front = lambda: None
    game._get_non_edge_door = lambda: None
    game.client.pickup_item = lambda *args: None
    shown = []
    game._show_dialogue = shown.append
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
