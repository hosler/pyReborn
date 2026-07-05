#!/usr/bin/env python3
"""Visual test for GMAP rendering - verifies tiles and NPCs render correctly."""

import os
import sys

# Set dummy video driver before importing pygame
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

import pytest
pytest.importorskip("pygame")  # live scripts need the full client stack
pytest.importorskip("PIL")
import pygame
import pytest
from PIL import Image
import io

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyreborn import Client
from pyreborn.pygame_game import GameClient, SCREEN_WIDTH, SCREEN_HEIGHT, TILE_SIZE

# Standalone script against a hand-started server on a hardcoded host:port
# (see run_visual_test() below) - opt-in only, not run by bare `pytest`.
pytestmark = pytest.mark.live


def take_screenshot(screen) -> Image.Image:
    """Capture pygame screen as PIL Image."""
    data = pygame.image.tostring(screen, 'RGB')
    return Image.frombytes('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), data)


def analyze_screenshot(img: Image.Image) -> dict:
    """Analyze screenshot for visual correctness."""
    pixels = list(img.getdata())
    width, height = img.size

    # Count unique colors
    unique_colors = set(pixels)

    # Check center area (where player should be)
    center_x, center_y = width // 2, height // 2
    center_region = []
    for dy in range(-32, 33):
        for dx in range(-32, 33):
            px = center_x + dx
            py = center_y + dy
            if 0 <= px < width and 0 <= py < height:
                center_region.append(img.getpixel((px, py)))
    center_colors = set(center_region)

    # Check corners (should have tile content, not blank)
    corners = [
        img.getpixel((50, 50)),
        img.getpixel((width - 50, 50)),
        img.getpixel((50, height - 50)),
        img.getpixel((width - 50, height - 50)),
    ]

    # Count non-green pixels (green is default background)
    green_bg = (34, 139, 34)  # Forest green background
    non_green = sum(1 for p in pixels if p != green_bg)

    return {
        'total_pixels': len(pixels),
        'unique_colors': len(unique_colors),
        'center_colors': len(center_colors),
        'non_green_pixels': non_green,
        'non_green_percent': (non_green / len(pixels)) * 100,
        'corners': corners,
        'has_tiles': non_green > len(pixels) * 0.1,  # >10% non-green = tiles rendered
        'has_player_area': len(center_colors) > 3,  # Center should have variety
    }


def run_visual_test():
    """Run visual test and return results."""
    print("=" * 60)
    print("VISUAL TEST: GMAP Rendering")
    print("=" * 60)

    # Connect to server
    host, port = "localhost", 14900
    print(f"\n1. Connecting to {host}:{port}...")

    client = Client(host, port, version="2.22")
    if not client.connect():
        print("   FAIL: Could not connect to server")
        return False
    print("   OK: Connected")

    # Login
    print("\n2. Logging in as SpaceManSpiff...")
    if not client.login("SpaceManSpiff", "googlymoogly", timeout=5.0):
        print("   FAIL: Login failed")
        client.disconnect()
        return False
    print(f"   OK: Logged in at ({client.x:.1f}, {client.y:.1f})")

    # Load GMAP
    print("\n3. Loading GMAP...")
    gmap_path = f"cache/levels/{host}_{port}/chicken.gmap"
    if os.path.exists(gmap_path):
        with open(gmap_path) as f:
            client.load_gmap(f.read())
        print(f"   OK: Loaded {client.gmap_width}x{client.gmap_height} grid")
        print(f"   Current level: {client._current_level_name}")
        print(f"   World position: ({client.x:.1f}, {client.y:.1f})")
    else:
        print(f"   WARN: GMAP file not found at {gmap_path}")

    # Request adjacent levels
    print("\n4. Loading adjacent levels...")
    count = client.request_adjacent_levels()
    for _ in range(20):
        client.update(timeout=0.1)
    print(f"   OK: Loaded {len(client.levels)} levels")

    # Check NPC world coords
    print("\n5. Checking NPC coordinates...")
    npcs_with_world = sum(1 for npc in client.npcs.values() if 'world_x' in npc)
    print(f"   Total NPCs: {len(client.npcs)}")
    print(f"   NPCs with world coords: {npcs_with_world}")
    if client.npcs:
        sample_npc = list(client.npcs.values())[0]
        print(f"   Sample NPC: local=({sample_npc.get('x')}, {sample_npc.get('y')}), "
              f"world=({sample_npc.get('world_x')}, {sample_npc.get('world_y')})")

    # Create game client and render a few frames
    print("\n6. Rendering frames...")
    pygame.init()
    game = GameClient(client)

    # Run a few frames to let rendering stabilize
    for i in range(10):
        client.update(timeout=0.01)
        game.screen.fill((34, 139, 34))
        game._get_world_surface()  # Force world surface creation
        game._render_world()
        game._render_entities()
        pygame.display.flip()

    # Take screenshot
    print("\n7. Taking screenshot...")
    screenshot = take_screenshot(game.screen)
    screenshot_path = "/tmp/gmap_visual_test.png"
    screenshot.save(screenshot_path)
    print(f"   Saved to {screenshot_path}")

    # Analyze
    print("\n8. Analyzing screenshot...")
    analysis = analyze_screenshot(screenshot)
    print(f"   Unique colors: {analysis['unique_colors']}")
    print(f"   Non-green pixels: {analysis['non_green_percent']:.1f}%")
    print(f"   Center area colors: {analysis['center_colors']}")
    print(f"   Has tiles rendered: {analysis['has_tiles']}")
    print(f"   Has player area: {analysis['has_player_area']}")

    # Cleanup
    pygame.quit()
    client.disconnect()

    # Results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    tests_passed = 0
    tests_total = 0

    # Test 1: Level correctly identified
    tests_total += 1
    if client._current_level_name == "chicken1.nw":
        print("✓ Level correctly identified as chicken1.nw")
        tests_passed += 1
    else:
        print(f"✗ Level incorrectly identified as {client._current_level_name} (expected chicken1.nw)")

    # Test 2: World coords calculated
    tests_total += 1
    if client.x >= 64 and client.y >= 64:
        print(f"✓ Player world coords correct: ({client.x:.1f}, {client.y:.1f})")
        tests_passed += 1
    else:
        print(f"✗ Player coords look like local, not world: ({client.x:.1f}, {client.y:.1f})")

    # Test 3: NPC world coords
    tests_total += 1
    if npcs_with_world == len(client.npcs) and len(client.npcs) > 0:
        print(f"✓ All {npcs_with_world} NPCs have world coords")
        tests_passed += 1
    else:
        print(f"✗ Only {npcs_with_world}/{len(client.npcs)} NPCs have world coords")

    # Test 4: Tiles rendered
    tests_total += 1
    if analysis['has_tiles']:
        print(f"✓ Tiles rendered ({analysis['non_green_percent']:.1f}% non-background)")
        tests_passed += 1
    else:
        print(f"✗ Tiles not rendered (only {analysis['non_green_percent']:.1f}% non-background)")

    # Test 5: Sufficient color variety (indicates proper rendering)
    tests_total += 1
    if analysis['unique_colors'] > 20:
        print(f"✓ Good color variety ({analysis['unique_colors']} unique colors)")
        tests_passed += 1
    else:
        print(f"✗ Low color variety ({analysis['unique_colors']} unique colors)")

    print(f"\nPassed: {tests_passed}/{tests_total}")
    print("=" * 60)

    return tests_passed == tests_total


if __name__ == "__main__":
    success = run_visual_test()
    sys.exit(0 if success else 1)
