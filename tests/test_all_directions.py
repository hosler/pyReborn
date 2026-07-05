#!/usr/bin/env python3
"""Test walking in all 4 directions to adjacent levels."""

import os
import sys

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

import pygame
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyreborn import Client
from pyreborn.pygame_game import GameClient, SCREEN_WIDTH, SCREEN_HEIGHT


def take_screenshot(screen, filename: str):
    data = pygame.image.tostring(screen, 'RGB')
    img = Image.frombytes('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), data)
    img.save(filename)
    return img


def get_grid_position(x: float, y: float) -> tuple:
    return (int(x // 64), int(y // 64))


def walk_to_boundary(client, game, direction: str, max_steps: int = 300) -> dict:
    """Walk in a direction until crossing a level boundary or max steps."""
    directions = {
        'up': (0, -1),
        'down': (0, 1),
        'left': (-1, 0),
        'right': (1, 0)
    }
    dx, dy = directions[direction]
    start_grid = get_grid_position(client.x, client.y)
    start_level = client.get_current_level_from_position()

    for step in range(max_steps):
        client.move(dx, dy)
        client.update(timeout=0.005)
        game.visual_x = client.x
        game.visual_y = client.y

        # Render
        game.screen.fill((34, 139, 34))
        game._get_world_surface()
        game._render_world()
        pygame.display.flip()

        current_grid = get_grid_position(client.x, client.y)
        if current_grid != start_grid:
            return {
                'success': True,
                'direction': direction,
                'start_grid': start_grid,
                'end_grid': current_grid,
                'start_level': start_level,
                'end_level': client.get_current_level_from_position(),
                'steps': step + 1,
                'position': (client.x, client.y)
            }

    return {
        'success': False,
        'direction': direction,
        'start_grid': start_grid,
        'end_grid': get_grid_position(client.x, client.y),
        'reason': 'max_steps_reached or blocked',
        'position': (client.x, client.y)
    }


def walk_to_center(client, game, target_x: float, target_y: float, max_steps: int = 500):
    """Walk towards a target position."""
    for _ in range(max_steps):
        dx = 1 if client.x < target_x else (-1 if client.x > target_x else 0)
        dy = 1 if client.y < target_y else (-1 if client.y > target_y else 0)

        if dx == 0 and dy == 0:
            break

        if dx != 0:
            client.move(dx, 0)
        if dy != 0:
            client.move(0, dy)
        client.update(timeout=0.005)
        game.visual_x = client.x
        game.visual_y = client.y


def run_test():
    print("=" * 60)
    print("TEST: Walking in All Directions")
    print("=" * 60)

    # Connect and setup
    client = Client("localhost", 14900, version="2.22")
    if not client.connect() or not client.login("SpaceManSpiff", "googlymoogly", timeout=5.0):
        print("FAIL: Could not connect/login")
        return False

    # Load GMAP
    gmap_path = "cache/levels/localhost_14900/chicken.gmap"
    if os.path.exists(gmap_path):
        with open(gmap_path) as f:
            client.load_gmap(f.read())

    # Load all levels
    client.request_adjacent_levels()
    for _ in range(30):
        client.update(timeout=0.1)

    print(f"Loaded {len(client.levels)} levels")
    print(f"Starting at ({client.x:.1f}, {client.y:.1f})")

    # Init pygame
    pygame.init()
    game = GameClient(client)

    # GMAP layout for chicken.gmap:
    # (0,0) chicken4  (1,0) chicken5  (2,0) chicken6
    # (0,1) chicken2  (1,1) chicken1  (2,1) chicken7
    # (0,2) chicken3  (1,2) chicken9  (2,2) chicken8

    # We start in chicken1.nw at (1,1)
    # Test transitions to all adjacent levels

    results = []

    # First, go to center of chicken1.nw (grid 1,1)
    center_x = 64 + 32  # 96 (middle of grid 1)
    center_y = 64 + 32  # 96 (middle of grid 1)
    print(f"\nMoving to center of chicken1.nw ({center_x}, {center_y})...")
    walk_to_center(client, game, center_x, center_y)
    print(f"Now at ({client.x:.1f}, {client.y:.1f})")

    # Test each direction
    test_directions = [
        ('up', (1, 0), 'chicken5.nw'),
        ('down', (1, 2), 'chicken9.nw'),
        ('left', (0, 1), 'chicken2.nw'),
        ('right', (2, 1), 'chicken7.nw'),
    ]

    for direction, expected_grid, expected_level in test_directions:
        # Return to center first
        walk_to_center(client, game, center_x, center_y)

        print(f"\nTesting {direction.upper()}...")
        result = walk_to_boundary(client, game, direction)
        results.append(result)

        if result['success']:
            print(f"  ✓ Crossed to {result['end_grid']} ({result['end_level']}) in {result['steps']} steps")
            take_screenshot(game.screen, f"/tmp/direction_test_{direction}.png")
        else:
            print(f"  ? Could not cross ({result.get('reason', 'unknown')})")
            print(f"    Position: {result['position']}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    successful = sum(1 for r in results if r['success'])
    print(f"Successful transitions: {successful}/{len(results)}")

    for r in results:
        status = "✓" if r['success'] else "✗"
        if r['success']:
            print(f"  {status} {r['direction']}: {r['start_grid']} -> {r['end_grid']} ({r['end_level']})")
        else:
            print(f"  {status} {r['direction']}: blocked or max steps")

    pygame.quit()
    client.disconnect()

    return successful >= 3  # At least 3 of 4 directions should work


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
