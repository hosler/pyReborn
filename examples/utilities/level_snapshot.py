#!/usr/bin/env python3
"""
Level Snapshot Utility - creates PNG snapshots of Graal levels using tileset graphics
"""

import sys
import time
import os
from collections import Counter
sys.path.insert(0, '../..')

from pyreborn.client import RebornClient

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

def create_level_snapshot(level, tileset_path: str) -> Image.Image:
    """Create level snapshot using tileset graphics"""
    
    # Load tileset
    tileset = Image.open(tileset_path)
    
    # Get tile array from level
    tiles = level.get_board_tiles_array()
    
    # Create level image (64x64 tiles * 16 pixels = 1024x1024)
    level_image = Image.new('RGBA', (1024, 1024))
    
    # Render each tile
    for i, tile_id in enumerate(tiles):
        level_x = (i % 64) * 16
        level_y = (i // 64) * 16
        
        # Get tileset coordinates
        tx, ty, px, py = level.tile_to_tileset_coords(tile_id)
        
        # Extract and paste tile
        if px + 16 <= tileset.width and py + 16 <= tileset.height:
            tile = tileset.crop((px, py, px + 16, py + 16))
            level_image.paste(tile, (level_x, level_y))
    
    return level_image

def print_level_stats(level):
    """Print statistics about the level"""
    tiles = level.get_board_tiles_array()
    tile_counts = Counter(tiles)
    
    print(f"Level: {level.name}")
    print(f"Unique tiles: {len(tile_counts)}")
    print(f"Total tiles: {len(tiles)}")
    
    print("\nTop 5 most common tiles:")
    for i, (tile_id, count) in enumerate(tile_counts.most_common(5)):
        tx, ty, px, py = level.tile_to_tileset_coords(tile_id)
        percent = (count / len(tiles)) * 100
        print(f"  {i+1}. Tile {tile_id:4d}: {count:4d} uses ({percent:5.1f}%) - tileset({tx:2d},{ty:2d})")

def main():
    """Level snapshot utility"""
    print("Level Snapshot Utility")
    print("======================\n")
    
    if not PIL_AVAILABLE:
        print("❌ PIL/Pillow required! Install with: pip install Pillow")
        return 1
    
    # Check for tileset
    tileset_path = "../../Pics1formatwithcliffs.png"
    if not os.path.exists(tileset_path):
        print(f"❌ Tileset not found: {tileset_path}")
        print("   Download Pics1formatwithcliffs.png to the project root")
        return 1
    
    # Get output filename
    output_name = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    
    # Connect and capture
    client = RebornClient("localhost", 14900)
    
    print("1. Connecting...")
    if not client.connect():
        return 1
    
    print("2. Logging in...")
    if not client.login("snapshotbot", "1234"):
        return 1
    
    print("3. Waiting for level data...")
    time.sleep(5)
    
    level = client.level_manager.get_current_level()
    if not level or not hasattr(level, 'board_tiles_64x64'):
        print("❌ No level data!")
        return 1
    
    print("4. Analyzing level...")
    print_level_stats(level)
    
    print("\n5. Creating snapshot...")
    try:
        snapshot = create_level_snapshot(level, tileset_path)
        filename = f"{output_name}_{level.name}_{int(time.time())}.png"
        snapshot.save(filename)
        
        print(f"✅ Snapshot saved: {filename}")
        print(f"   Size: {snapshot.size[0]}x{snapshot.size[1]} pixels")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    client.disconnect()
    return 0

if __name__ == "__main__":
    sys.exit(main())