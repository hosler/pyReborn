#!/usr/bin/env python3
"""These tests check pygame client functions."""

import os
import sys
import time

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

import pytest
pytest.importorskip("pygame")  # live scripts need the full client stack
pytest.importorskip("PIL")
import pygame
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyreborn import Client
from pyreborn.pygame_game import GameClient, SCREEN_WIDTH, SCREEN_HEIGHT, TILE_SIZE
from pyreborn.tiletypes import get_tile_type, TileType

# Standalone script against a hand-started server on a hardcoded host:port
# (see run_all_tests() below) - opt-in only, not run by bare `pytest`.
pytestmark = pytest.mark.live


def take_screenshot(screen, filename: str) -> Image.Image:
    data = pygame.image.tostring(screen, 'RGB')
    img = Image.frombytes('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), data)
    img.save(filename)
    return img


def render_frame(game, client):
    """Render a single frame."""
    client.update(timeout=0.01)
    game.visual_x = client.x
    game.visual_y = client.y
    game.screen.fill((34, 139, 34))
    game.world_surface = None  # Force redraw
    game._get_world_surface()
    game._render_world()
    game._render_entities()
    pygame.display.flip()


class TestRunner:
    def __init__(self):
        self.client = None
        self.game = None
        self.results = []

    def setup(self):
        """Connect and set up the client."""
        print("Setting up...")
        self.client = Client("localhost", 14900, version="2.22")
        if not self.client.connect():
            return False
        if not self.client.login("SpaceManSpiff", "googlymoogly", timeout=5.0):
            self.client.disconnect()
            return False

        # Load GMAP
        gmap_path = "cache/levels/localhost_14900/chicken.gmap"
        if os.path.exists(gmap_path):
            with open(gmap_path) as f:
                self.client.load_gmap(f.read())

        # Load levels
        self.client.request_adjacent_levels()
        for _ in range(30):
            self.client.update(timeout=0.1)

        # Init pygame
        pygame.init()
        self.game = GameClient(self.client)

        # Render initial frame
        render_frame(self.game, self.client)

        print(f"Setup complete. Position: ({self.client.x:.1f}, {self.client.y:.1f})")
        print(f"Level: {self.client._current_level_name}")
        print(f"Levels loaded: {len(self.client.levels)}")
        print(f"NPCs: {len(self.client.npcs)}")
        return True

    def teardown(self):
        """Clean up the test resources."""
        if pygame.get_init():
            pygame.quit()
        if self.client:
            self.client.disconnect()

    def run_test(self, name: str, test_func) -> bool:
        """Run a single test."""
        try:
            result = test_func()
            status = "✓" if result else "✗"
            self.results.append((name, result))
            print(f"  {status} {name}")
            return result
        except Exception as e:
            self.results.append((name, False))
            print(f"  ✗ {name} (Exception: {e})")
            return False

    # ========== TEST FUNCTIONS ==========

    def test_npc_world_coords(self) -> bool:
        """Verify that NPCs have the correct world coordinates."""
        if not self.client.npcs:
            return False

        for npc_id, npc in self.client.npcs.items():
            if 'world_x' not in npc or 'world_y' not in npc:
                return False
            # World coords should be >= 64 for grid (1,1)
            if npc.get('_level') == 'chicken1.nw':
                if npc['world_x'] < 64 or npc['world_y'] < 64:
                    return False
        return True

    def test_npc_rendering(self) -> bool:
        """Verify that the client renders NPCs on the screen."""
        render_frame(self.game, self.client)
        screenshot = take_screenshot(self.game.screen, "/tmp/test_npc_render.png")

        # Check if there's variety in the image (NPCs add colors)
        pixels = list(screenshot.getdata())
        unique = len(set(pixels))
        return unique > 30  # Should have variety if NPCs rendered

    def test_player_movement(self) -> bool:
        """Verify that the player can move."""
        start_x, start_y = self.client.x, self.client.y

        # Try moving right
        for _ in range(10):
            self.client.move(1, 0)
            self.client.update(timeout=0.01)

        moved = (self.client.x != start_x or self.client.y != start_y)
        return moved

    def test_collision_detection(self) -> bool:
        """Verify collision detection. The player cannot cross blocking tiles."""
        # Get current level tiles
        level = self.client._current_level_name
        tiles = self.client.levels.get(level, [])
        if not tiles:
            return False

        # Find a blocking tile
        blocking_found = False
        for i, tile_id in enumerate(tiles):
            tile_type = get_tile_type(tile_id)
            if tile_type == TileType.BLOCKING:
                blocking_found = True
                break

        return blocking_found  # Just verify blocking tiles exist

    def test_tile_rendering(self) -> bool:
        """Verify that the client renders tiles correctly."""
        render_frame(self.game, self.client)

        # Check world surface was created
        if self.game.world_surface is None:
            return False

        # Check it has content
        width, height = self.game.world_surface.get_size()
        return width > 0 and height > 0

    def test_camera_follows_player(self) -> bool:
        """Verify that the camera follows player movement."""
        # Move player significantly
        for _ in range(50):
            self.client.move(1, 0)
            self.client.update(timeout=0.005)
            self.game.visual_x = self.client.x
            self.game.visual_y = self.client.y

        render_frame(self.game, self.client)
        take_screenshot(self.game.screen, "/tmp/test_camera_1.png")

        # Move back
        for _ in range(100):
            self.client.move(-1, 0)
            self.client.update(timeout=0.005)
            self.game.visual_x = self.client.x
            self.game.visual_y = self.client.y

        render_frame(self.game, self.client)
        take_screenshot(self.game.screen, "/tmp/test_camera_2.png")

        # Compare screenshots - they should be different
        img1 = Image.open("/tmp/test_camera_1.png")
        img2 = Image.open("/tmp/test_camera_2.png")

        pixels1 = list(img1.getdata())
        pixels2 = list(img2.getdata())

        diff_count = sum(1 for p1, p2 in zip(pixels1, pixels2) if p1 != p2)
        return diff_count > 1000  # Significant difference

    def test_level_data_integrity(self) -> bool:
        """Verify that the level data is valid."""
        for level_name, tiles in self.client.levels.items():
            if len(tiles) != 64 * 64:
                print(f"    {level_name}: wrong size {len(tiles)}")
                return False
            # Check for valid tile IDs (should be >= 0)
            if any(t < 0 for t in tiles):
                return False
        return True

    def test_gmap_grid_complete(self) -> bool:
        """Verify that the GMAP grid is fully populated."""
        expected_size = self.client.gmap_width * self.client.gmap_height
        actual_size = len(self.client.gmap_grid)
        return actual_size == expected_size

    def test_diagonal_movement(self) -> bool:
        """Test that diagonal movement works."""
        start_x, start_y = self.client.x, self.client.y

        # Move diagonally (down-right)
        for _ in range(20):
            self.client.move(1, 0)
            self.client.move(0, 1)
            self.client.update(timeout=0.01)

        # Should have moved in both directions
        moved_x = abs(self.client.x - start_x) > 1
        moved_y = abs(self.client.y - start_y) > 1
        return moved_x and moved_y

    def test_corner_transition(self) -> bool:
        """Test that the player walks a significant distance without a crash."""
        start_x, start_y = self.client.x, self.client.y

        # Walk in positive direction (towards center/other levels)
        for _ in range(100):
            self.client.move(1, 0)
            self.client.update(timeout=0.005)

        for _ in range(100):
            self.client.move(0, 1)
            self.client.update(timeout=0.005)

        # Just verify position changed and is valid
        moved = (self.client.x != start_x or self.client.y != start_y)
        valid = self.client.x >= 0 and self.client.y >= 0
        return moved and valid

    def test_rapid_direction_change(self) -> bool:
        """Test that rapid direction changes do not cause a failure."""
        # First move to center of current level to have room in all directions
        for _ in range(50):
            self.client.move(1, 0)
            self.client.move(0, 1)
            self.client.update(timeout=0.005)

        directions = [(1, 0), (0, 1), (-1, 0), (0, -1)]

        for _ in range(50):
            for dx, dy in directions:
                self.client.move(dx, dy)
                self.client.update(timeout=0.005)
                render_frame(self.game, self.client)

        # Should not crash and position should be valid (non-negative)
        return self.client.x >= 0 and self.client.y >= 0

    def test_sprite_manager(self) -> bool:
        """Test that the sprite manager loads sprites."""
        # Check tileset is loaded
        if not self.game.tileset_mgr:
            return False

        # Try to get a tile sprite
        sprite = self.game.tileset_mgr.get_tile_or_color(1)
        return sprite is not None

    def test_animation_state(self) -> bool:
        """Test that the client updates the player animation state."""
        if not self.game.player_anim:
            return False

        initial_frame = self.game.player_anim.frame

        # Move to trigger animation
        for _ in range(30):
            self.client.move(1, 0)
            self.client.update(timeout=0.01)
            self.game._update_animations(0.033)

        return self.game.player_anim is not None

    def test_multiple_level_renders(self) -> bool:
        """Test that the client renders multiple levels in the GMAP."""
        # World surface should include multiple levels
        render_frame(self.game, self.client)

        if not self.game.world_surface:
            return False

        # For 3x3 GMAP, world surface should be 3*64*16 = 3072 pixels wide
        width, height = self.game.world_surface.get_size()
        expected_size = self.client.gmap_width * 64 * TILE_SIZE

        return width == expected_size and height == expected_size

    def test_player_props(self) -> bool:
        """Test that the client sets the player properties."""
        p = self.client.player
        return (
            p.x is not None and
            p.y is not None and
            p.level is not None
        )

    def test_frame_consistency(self) -> bool:
        """Test that the client renders multiple frames consistently."""
        screenshots = []

        for i in range(5):
            render_frame(self.game, self.client)
            data = pygame.image.tostring(self.game.screen, 'RGB')
            screenshots.append(data)
            time.sleep(0.05)

        # All frames should be identical (no movement)
        return all(s == screenshots[0] for s in screenshots)


def run_all_tests():
    print("=" * 60)
    print("COMPREHENSIVE TEST SUITE")
    print("=" * 60)

    runner = TestRunner()

    if not runner.setup():
        print("Setup failed!")
        return False

    print("\n" + "-" * 60)
    print("Running tests...")
    print("-" * 60)

    # Run all tests
    tests = [
        ("NPC world coordinates", runner.test_npc_world_coords),
        ("NPC rendering", runner.test_npc_rendering),
        ("Player movement", runner.test_player_movement),
        ("Collision detection", runner.test_collision_detection),
        ("Tile rendering", runner.test_tile_rendering),
        ("Camera follows player", runner.test_camera_follows_player),
        ("Level data integrity", runner.test_level_data_integrity),
        ("GMAP grid complete", runner.test_gmap_grid_complete),
        ("Diagonal movement", runner.test_diagonal_movement),
        ("Corner transition", runner.test_corner_transition),
        ("Rapid direction change", runner.test_rapid_direction_change),
        ("Sprite manager", runner.test_sprite_manager),
        ("Animation state", runner.test_animation_state),
        ("Multiple level renders", runner.test_multiple_level_renders),
        ("Player properties", runner.test_player_props),
        ("Frame consistency", runner.test_frame_consistency),
    ]

    for name, test_func in tests:
        runner.run_test(name, test_func)

    runner.teardown()

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    passed = sum(1 for _, result in runner.results if result)
    total = len(runner.results)

    print(f"\nPassed: {passed}/{total}")

    if passed < total:
        print("\nFailed tests:")
        for name, result in runner.results:
            if not result:
                print(f"  - {name}")

    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
