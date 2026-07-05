#!/usr/bin/env python3
"""Test player interactions - sword, items, chat, etc."""

import os
import sys
import time

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

import pygame
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyreborn import Client
from pyreborn.pygame_game import GameClient, SCREEN_WIDTH, SCREEN_HEIGHT


def take_screenshot(screen, filename: str) -> Image.Image:
    data = pygame.image.tostring(screen, 'RGB')
    img = Image.frombytes('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), data)
    img.save(filename)
    return img


class InteractionTests:
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

        print(f"Ready at ({self.client.x:.1f}, {self.client.y:.1f})")
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
            return False

    # ========== TESTS ==========

    def test_sword_attack(self) -> bool:
        """Test sword attack sends packet."""
        # Just verify it doesn't crash
        for direction in [0, 1, 2, 3]:
            self.client.sword_attack(direction)
            self.client.update(timeout=0.05)
        return True

    def test_direction_change(self) -> bool:
        """Test player direction changes."""
        directions_tested = set()
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            self.client.move(dx, dy)
            self.client.update(timeout=0.05)
            directions_tested.add(self.client.player.direction)
        # Should have tested multiple directions
        return len(directions_tested) >= 2

    def test_chat_message(self) -> bool:
        """Test sending chat message."""
        result = self.client.say("Test message from automated test")
        self.client.update(timeout=0.1)
        return result

    def test_item_pickup_attempt(self) -> bool:
        """Test item pickup (may not find item)."""
        # Just verify it doesn't crash
        self.client.pickup_item()
        self.client.update(timeout=0.1)
        return True

    def test_bomb_drop(self) -> bool:
        """Test dropping a bomb."""
        # Just verify it doesn't crash
        self.client.drop_bomb(power=1)
        self.client.update(timeout=0.1)
        return True

    def test_shoot_arrow(self) -> bool:
        """Test shooting an arrow."""
        self.client.shoot(direction=0)
        self.client.update(timeout=0.1)
        return True

    def test_player_stats(self) -> bool:
        """Test player stats are populated."""
        p = self.client.player
        # Check various stats exist
        has_level = p.level is not None
        has_pos = p.x is not None and p.y is not None
        return has_level and has_pos

    def test_npc_count(self) -> bool:
        """Verify NPCs exist."""
        return len(self.client.npcs) > 0

    def test_other_players_dict(self) -> bool:
        """Verify other players dict exists."""
        # May be empty if no other players
        return isinstance(self.client.players, dict)

    def test_links_loaded(self) -> bool:
        """Test level links are loaded."""
        # Links may or may not exist
        return isinstance(self.client.links, dict)

    def test_warp_request(self) -> bool:
        """Test warp request doesn't crash."""
        # Just test it doesn't crash - actual warp depends on server
        try:
            self.client.warp_to_level("chicken1.nw", 32, 32)
            self.client.update(timeout=0.2)
            return True
        except:
            return False

    def test_flag_setting(self) -> bool:
        """Test setting a flag."""
        self.client.set_flag("test_flag", "test_value")
        self.client.update(timeout=0.1)
        return True

    def test_trigger_action(self) -> bool:
        """Test trigger action doesn't crash."""
        self.client.triggeraction("test_action")
        self.client.update(timeout=0.1)
        return True

    def test_continuous_movement(self) -> bool:
        """Test continuous movement for extended period."""
        for _ in range(200):
            self.client.move(1, 0)
            self.client.update(timeout=0.005)

        for _ in range(200):
            self.client.move(-1, 0)
            self.client.update(timeout=0.005)

        return self.client.x >= 0

    def test_visual_update(self) -> bool:
        """Test visual position updates."""
        self.game.visual_x = self.client.x
        self.game.visual_y = self.client.y

        for _ in range(50):
            self.client.move(1, 0)
            self.client.update(timeout=0.01)
            # Interpolate visual position
            dx = self.client.x - self.game.visual_x
            self.game.visual_x += dx * 0.2

        # Visual should have followed movement
        return abs(self.game.visual_x - self.client.x) < 10

    def test_multiple_renders(self) -> bool:
        """Test multiple frame renders."""
        for _ in range(100):
            self.client.update(timeout=0.005)
            self.game.visual_x = self.client.x
            self.game.visual_y = self.client.y
            self.game.screen.fill((34, 139, 34))
            self.game._get_world_surface()
            self.game._render_world()
            self.game._render_entities()
            pygame.display.flip()
        return True

    def test_screenshot_capture(self) -> bool:
        """Test screenshot capture works."""
        self.game.screen.fill((34, 139, 34))
        self.game._render_world()
        img = take_screenshot(self.game.screen, "/tmp/test_interaction_screenshot.png")
        return img is not None and img.size == (SCREEN_WIDTH, SCREEN_HEIGHT)


def run_tests():
    print("=" * 60)
    print("INTERACTION TESTS")
    print("=" * 60)

    runner = InteractionTests()

    if not runner.setup():
        print("Setup failed!")
        return False

    print("\nRunning tests...")
    print("-" * 60)

    tests = [
        ("Sword attack", runner.test_sword_attack),
        ("Direction change", runner.test_direction_change),
        ("Chat message", runner.test_chat_message),
        ("Item pickup attempt", runner.test_item_pickup_attempt),
        ("Bomb drop", runner.test_bomb_drop),
        ("Shoot arrow", runner.test_shoot_arrow),
        ("Player stats", runner.test_player_stats),
        ("NPC count", runner.test_npc_count),
        ("Other players dict", runner.test_other_players_dict),
        ("Links loaded", runner.test_links_loaded),
        ("Warp request", runner.test_warp_request),
        ("Flag setting", runner.test_flag_setting),
        ("Trigger action", runner.test_trigger_action),
        ("Continuous movement", runner.test_continuous_movement),
        ("Visual update", runner.test_visual_update),
        ("Multiple renders", runner.test_multiple_renders),
        ("Screenshot capture", runner.test_screenshot_capture),
    ]

    for name, test_func in tests:
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
