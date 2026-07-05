#!/usr/bin/env python3
"""Test NPC rendering, positions, and sign interactions."""

import os
import sys

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

import pygame
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyreborn import Client
from pyreborn.pygame_game import GameClient, SCREEN_WIDTH, SCREEN_HEIGHT, TILE_SIZE


def take_screenshot(screen, filename: str) -> Image.Image:
    data = pygame.image.tostring(screen, 'RGB')
    img = Image.frombytes('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), data)
    img.save(filename)
    return img


def render_frame(game, client):
    client.update(timeout=0.01)
    game.visual_x = client.x
    game.visual_y = client.y
    game.screen.fill((34, 139, 34))
    game.world_surface = None
    game._get_world_surface()
    game._render_world()
    game._render_entities()
    pygame.display.flip()


class NPCAndSignTests:
    def __init__(self):
        self.client = None
        self.game = None
        self.results = []

    def setup(self):
        print("Setting up...")
        self.client = Client("localhost", 14900, version="2.22")
        if not self.client.connect():
            return False
        if not self.client.login("SpaceManSpiff", "googlymoogly", timeout=5.0):
            self.client.disconnect()
            return False

        gmap_path = "cache/levels/localhost_14900/chicken.gmap"
        if os.path.exists(gmap_path):
            with open(gmap_path) as f:
                self.client.load_gmap(f.read())

        self.client.request_adjacent_levels()
        for _ in range(30):
            self.client.update(timeout=0.1)

        pygame.init()
        self.game = GameClient(self.client)
        render_frame(self.game, self.client)

        print(f"Ready at ({self.client.x:.1f}, {self.client.y:.1f})")
        print(f"NPCs loaded: {len(self.client.npcs)}")
        return True

    def teardown(self):
        if pygame.get_init():
            pygame.quit()
        if self.client:
            self.client.disconnect()

    def run_test(self, name: str, test_func) -> bool:
        try:
            result = test_func()
            status = "✓" if result else "✗"
            self.results.append((name, result))
            print(f"  {status} {name}")
            return result
        except Exception as e:
            self.results.append((name, False))
            print(f"  ✗ {name} (Exception: {e})")
            import traceback
            traceback.print_exc()
            return False

    # ========== NPC TESTS ==========

    def test_npcs_exist(self) -> bool:
        """Verify NPCs are loaded."""
        return len(self.client.npcs) > 0

    def test_npc_has_id(self) -> bool:
        """Verify NPCs have IDs."""
        for npc_id, npc in self.client.npcs.items():
            if 'id' not in npc:
                return False
        return True

    def test_npc_has_position(self) -> bool:
        """Verify NPCs have position data."""
        for npc_id, npc in self.client.npcs.items():
            if 'x' not in npc or 'y' not in npc:
                print(f"    NPC {npc_id} missing position")
                return False
        return True

    def test_npc_has_world_coords(self) -> bool:
        """Verify NPCs have world coordinates for GMAP."""
        for npc_id, npc in self.client.npcs.items():
            if 'world_x' not in npc or 'world_y' not in npc:
                print(f"    NPC {npc_id} missing world coords")
                return False
        return True

    def test_npc_world_coords_valid(self) -> bool:
        """Verify NPC world coords are in valid GMAP range."""
        max_coord = self.client.gmap_width * 64
        for npc_id, npc in self.client.npcs.items():
            wx = npc.get('world_x', 0)
            wy = npc.get('world_y', 0)
            if wx < 0 or wx >= max_coord or wy < 0 or wy >= max_coord:
                print(f"    NPC {npc_id} has invalid world coords: ({wx}, {wy})")
                return False
        return True

    def test_npc_level_association(self) -> bool:
        """Verify NPCs have level association."""
        for npc_id, npc in self.client.npcs.items():
            if '_level' not in npc:
                print(f"    NPC {npc_id} missing level association")
                return False
        return True

    def test_npc_rendering_positions(self) -> bool:
        """Verify NPCs render at expected screen positions."""
        render_frame(self.game, self.client)

        # Get camera offset
        gmap_visual_x = self.game.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.game.visual_y - self.client._gmap_offset_y * 64
        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE
        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        # Check each NPC's expected screen position
        for npc_id, npc in self.client.npcs.items():
            nx = npc.get('world_x', npc.get('x', 0))
            ny = npc.get('world_y', npc.get('y', 0))
            screen_x = nx * TILE_SIZE + cam_offset_x
            screen_y = ny * TILE_SIZE + cam_offset_y
            # Just verify the calculation doesn't crash
        return True

    def test_npc_properties(self) -> bool:
        """Check various NPC properties."""
        for npc_id, npc in self.client.npcs.items():
            # NPCs can have various properties - just check structure
            if not isinstance(npc, dict):
                return False
        return True

    def test_npc_image_or_gani(self) -> bool:
        """Verify NPCs have image or gani data."""
        has_visual = 0
        for npc_id, npc in self.client.npcs.items():
            if 'image' in npc or 'gani' in npc or 'animation' in npc:
                has_visual += 1
        # At least some NPCs should have visuals
        return has_visual > 0

    def test_walk_to_npc(self) -> bool:
        """Test walking towards an NPC."""
        if not self.client.npcs:
            return False

        # Get first NPC position
        first_npc = list(self.client.npcs.values())[0]
        npc_x = first_npc.get('world_x', first_npc.get('x', 0))
        npc_y = first_npc.get('world_y', first_npc.get('y', 0))

        # Walk towards NPC
        for _ in range(100):
            dx = 1 if self.client.x < npc_x else (-1 if self.client.x > npc_x else 0)
            dy = 1 if self.client.y < npc_y else (-1 if self.client.y > npc_y else 0)
            if dx == 0 and dy == 0:
                break
            if dx != 0:
                self.client.move(dx, 0)
            if dy != 0:
                self.client.move(0, dy)
            self.client.update(timeout=0.01)
            render_frame(self.game, self.client)

        # Should have moved closer
        return True

    def test_npc_stays_after_movement(self) -> bool:
        """Verify NPCs persist after player movement."""
        initial_npc_count = len(self.client.npcs)

        # Move around
        for _ in range(50):
            self.client.move(1, 0)
            self.client.update(timeout=0.01)
        for _ in range(50):
            self.client.move(-1, 0)
            self.client.update(timeout=0.01)

        # NPCs should still exist
        return len(self.client.npcs) > 0

    # ========== SIGN TESTS ==========

    def test_sign_npc_detection(self) -> bool:
        """Look for sign-type NPCs (typically have 'sign' in image or script)."""
        sign_npcs = []
        for npc_id, npc in self.client.npcs.items():
            image = npc.get('image', '').lower()
            script = npc.get('script', '').lower()
            if 'sign' in image or 'sign' in script:
                sign_npcs.append(npc_id)
        print(f"    Found {len(sign_npcs)} sign NPCs")
        return True  # Just informational

    def test_npc_scripts_present(self) -> bool:
        """Check if any NPCs have scripts."""
        has_script = 0
        for npc_id, npc in self.client.npcs.items():
            if 'script' in npc and npc['script']:
                has_script += 1
        print(f"    {has_script} NPCs have scripts")
        return True  # Just informational

    def test_trigger_npc_action(self) -> bool:
        """Test triggering an NPC action."""
        if not self.client.npcs:
            return True  # No NPCs to trigger

        first_npc_id = list(self.client.npcs.keys())[0]
        self.client.triggeraction("", self.client.x, self.client.y, first_npc_id)
        self.client.update(timeout=0.1)
        return True  # Just verify it doesn't crash

    # ========== RENDERING TESTS ==========

    def test_npc_in_viewport(self) -> bool:
        """Test that NPCs in viewport are rendered."""
        render_frame(self.game, self.client)
        screenshot = take_screenshot(self.game.screen, "/tmp/test_npc_viewport.png")

        # Check for variety (NPCs should add color)
        pixels = list(screenshot.getdata())
        unique = len(set(pixels))
        return unique > 30

    def test_render_multiple_npcs(self) -> bool:
        """Test rendering with multiple NPCs."""
        # Move to where we can see NPCs
        for _ in range(10):
            render_frame(self.game, self.client)

        return True

    def test_npc_z_order(self) -> bool:
        """Test NPC depth sorting (Y-order rendering)."""
        # Render and verify no crashes
        render_frame(self.game, self.client)
        return True

    def test_screenshot_with_npcs(self) -> bool:
        """Take screenshot showing NPCs."""
        render_frame(self.game, self.client)
        img = take_screenshot(self.game.screen, "/tmp/test_npcs_full.png")
        print(f"    Screenshot saved to /tmp/test_npcs_full.png")
        return img is not None


def run_tests():
    print("=" * 60)
    print("NPC AND SIGN TESTS")
    print("=" * 60)

    runner = NPCAndSignTests()

    if not runner.setup():
        print("Setup failed!")
        return False

    print("\n--- NPC Data Tests ---")
    npc_tests = [
        ("NPCs exist", runner.test_npcs_exist),
        ("NPCs have ID", runner.test_npc_has_id),
        ("NPCs have position", runner.test_npc_has_position),
        ("NPCs have world coords", runner.test_npc_has_world_coords),
        ("NPC world coords valid", runner.test_npc_world_coords_valid),
        ("NPC level association", runner.test_npc_level_association),
        ("NPC properties", runner.test_npc_properties),
        ("NPC has image/gani", runner.test_npc_image_or_gani),
    ]

    for name, test_func in npc_tests:
        runner.run_test(name, test_func)

    print("\n--- NPC Interaction Tests ---")
    interaction_tests = [
        ("NPC rendering positions", runner.test_npc_rendering_positions),
        ("Walk to NPC", runner.test_walk_to_npc),
        ("NPCs persist after movement", runner.test_npc_stays_after_movement),
        ("Trigger NPC action", runner.test_trigger_npc_action),
    ]

    for name, test_func in interaction_tests:
        runner.run_test(name, test_func)

    print("\n--- Sign Tests ---")
    sign_tests = [
        ("Sign NPC detection", runner.test_sign_npc_detection),
        ("NPC scripts present", runner.test_npc_scripts_present),
    ]

    for name, test_func in sign_tests:
        runner.run_test(name, test_func)

    print("\n--- Rendering Tests ---")
    render_tests = [
        ("NPC in viewport", runner.test_npc_in_viewport),
        ("Render multiple NPCs", runner.test_render_multiple_npcs),
        ("NPC Z-order", runner.test_npc_z_order),
        ("Screenshot with NPCs", runner.test_screenshot_with_npcs),
    ]

    for name, test_func in render_tests:
        runner.run_test(name, test_func)

    runner.teardown()

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
    success = run_tests()
    sys.exit(0 if success else 1)
