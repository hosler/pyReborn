#!/usr/bin/env python3
"""Test walking between adjacent levels in a GMAP."""

import os
import sys

# Set dummy video driver before importing pygame
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

import pygame
import pytest
from PIL import Image

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyreborn import Client
from pyreborn.pygame_game import GameClient, SCREEN_WIDTH, SCREEN_HEIGHT, TILE_SIZE

# Standalone script against a hand-started server on a hardcoded host:port
# (see run_level_transition_test() below) - opt-in only, not run by bare `pytest`.
pytestmark = pytest.mark.live


def take_screenshot(screen, filename: str):
    """Capture pygame screen as PIL Image and save."""
    data = pygame.image.tostring(screen, 'RGB')
    img = Image.frombytes('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), data)
    img.save(filename)
    return img


def get_grid_position(x: float, y: float) -> tuple:
    """Get GMAP grid position from world coords."""
    return (int(x // 64), int(y // 64))


def run_level_transition_test():
    """Test walking between levels."""
    print("=" * 60)
    print("TEST: Level Transitions in GMAP")
    print("=" * 60)

    # Connect
    host, port = "localhost", 14900
    print(f"\n1. Connecting to {host}:{port}...")
    client = Client(host, port, version="2.22")
    if not client.connect():
        print("   FAIL: Could not connect")
        return False
    print("   OK: Connected")

    # Login
    print("\n2. Logging in...")
    if not client.login("SpaceManSpiff", "googlymoogly", timeout=5.0):
        print("   FAIL: Login failed")
        client.disconnect()
        return False

    initial_pos = (client.x, client.y)
    print(f"   OK: Logged in at ({client.x:.1f}, {client.y:.1f})")

    # Load GMAP
    print("\n3. Loading GMAP...")
    gmap_path = f"cache/levels/{host}_{port}/chicken.gmap"
    if os.path.exists(gmap_path):
        with open(gmap_path) as f:
            client.load_gmap(f.read())
        print(f"   OK: Loaded {client.gmap_width}x{client.gmap_height} grid")
    else:
        print(f"   FAIL: GMAP not found at {gmap_path}")
        client.disconnect()
        return False

    # Request all levels
    print("\n4. Loading all levels...")
    client.request_adjacent_levels()
    for _ in range(30):
        client.update(timeout=0.1)
    print(f"   OK: Loaded {len(client.levels)} levels")

    # Initialize pygame
    print("\n5. Initializing game client...")
    pygame.init()
    game = GameClient(client)

    # Get starting position info
    start_level = client._current_level_name
    start_grid = get_grid_position(client.x, client.y)
    print(f"   Starting level: {start_level}")
    print(f"   Starting grid position: {start_grid}")
    print(f"   Starting world coords: ({client.x:.1f}, {client.y:.1f})")

    # Take initial screenshot
    for _ in range(5):
        client.update(timeout=0.01)
        game.screen.fill((34, 139, 34))
        game._get_world_surface()
        game._render_world()
        game._render_entities()
        pygame.display.flip()
    take_screenshot(game.screen, "/tmp/level_test_start.png")
    print("   Saved /tmp/level_test_start.png")

    # Determine which direction to walk to reach an adjacent level
    # Grid (1,1) is center (chicken1.nw)
    # We want to walk to cross a level boundary
    print("\n6. Walking to adjacent level...")

    # Calculate distance to nearest level boundary
    local_x = client.x % 64
    local_y = client.y % 64
    print(f"   Local position in level: ({local_x:.1f}, {local_y:.1f})")

    # Decide direction - go towards edge with shortest distance
    # If local_x < 32, go left (towards x=0); else go right (towards x=64)
    # If local_y < 32, go up (towards y=0); else go down (towards y=64)

    target_direction = None
    steps_needed = 0

    if local_x < 32 and start_grid[0] > 0:
        # Go left
        target_direction = "left"
        steps_needed = int(local_x / 0.25) + 10  # Extra steps to cross boundary
        dx, dy = -1, 0
    elif local_x >= 32 and start_grid[0] < client.gmap_width - 1:
        # Go right
        target_direction = "right"
        steps_needed = int((64 - local_x) / 0.25) + 10
        dx, dy = 1, 0
    elif local_y < 32 and start_grid[1] > 0:
        # Go up
        target_direction = "up"
        steps_needed = int(local_y / 0.25) + 10
        dx, dy = 0, -1
    else:
        # Go down
        target_direction = "down"
        steps_needed = int((64 - local_y) / 0.25) + 10
        dx, dy = 0, 1

    print(f"   Walking {target_direction} for ~{steps_needed} steps...")

    # Walk!
    move_count = 0
    level_changed = False
    new_level = None

    for step in range(steps_needed):
        # Move
        client.move(dx, dy)
        client.update(timeout=0.01)

        # Update visual position
        game.visual_x = client.x
        game.visual_y = client.y

        # Render frame
        game.screen.fill((34, 139, 34))
        game._get_world_surface()
        game._render_world()
        game._render_entities()
        pygame.display.flip()

        move_count += 1

        # Check if we crossed a level boundary
        current_grid = get_grid_position(client.x, client.y)
        if current_grid != start_grid:
            level_changed = True
            new_level = client.get_current_level_from_position()
            print(f"   Crossed boundary at step {step}!")
            print(f"   New grid position: {current_grid}")
            print(f"   New world coords: ({client.x:.1f}, {client.y:.1f})")
            break

    # Take screenshot after walking
    take_screenshot(game.screen, "/tmp/level_test_after_walk.png")
    print(f"   Saved /tmp/level_test_after_walk.png")
    print(f"   Total moves: {move_count}")

    # Verify results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    tests_passed = 0
    tests_total = 0

    # Test 1: Level boundary crossed
    tests_total += 1
    end_grid = get_grid_position(client.x, client.y)
    if end_grid != start_grid:
        print(f"✓ Crossed level boundary: {start_grid} -> {end_grid}")
        tests_passed += 1
    else:
        print(f"✗ Did not cross boundary (still at {start_grid})")

    # Test 2: New level correctly identified
    tests_total += 1
    expected_level = client.gmap_grid.get(end_grid)
    actual_level = client.get_current_level_from_position()
    if expected_level and actual_level == expected_level:
        print(f"✓ New level correctly identified: {actual_level}")
        tests_passed += 1
    else:
        print(f"✗ Level mismatch: expected {expected_level}, got {actual_level}")

    # Test 3: New level has tiles loaded
    tests_total += 1
    if expected_level and expected_level in client.levels:
        tiles = client.levels[expected_level]
        non_zero_tiles = sum(1 for t in tiles if t != 0)
        print(f"✓ New level tiles loaded: {expected_level} ({non_zero_tiles} non-zero tiles)")
        tests_passed += 1
    else:
        print(f"✗ New level tiles not loaded: {expected_level}")

    # Test 4: World coordinates are correct for new grid
    tests_total += 1
    expected_x_range = (end_grid[0] * 64, (end_grid[0] + 1) * 64)
    expected_y_range = (end_grid[1] * 64, (end_grid[1] + 1) * 64)
    if expected_x_range[0] <= client.x < expected_x_range[1] and \
       expected_y_range[0] <= client.y < expected_y_range[1]:
        print(f"✓ World coords in correct range for grid {end_grid}")
        tests_passed += 1
    else:
        print(f"✗ World coords ({client.x:.1f}, {client.y:.1f}) not in expected range")

    # Test 5: Can continue walking in new level
    tests_total += 1
    old_pos = (client.x, client.y)
    for _ in range(10):
        client.move(dx, dy)
        client.update(timeout=0.01)
    new_pos = (client.x, client.y)
    if old_pos != new_pos:
        print(f"✓ Can continue walking in new level")
        tests_passed += 1
    else:
        print(f"✗ Movement stopped in new level")

    # Cleanup
    pygame.quit()
    client.disconnect()

    print(f"\nPassed: {tests_passed}/{tests_total}")
    print("=" * 60)

    return tests_passed == tests_total


if __name__ == "__main__":
    success = run_level_transition_test()
    sys.exit(0 if success else 1)
