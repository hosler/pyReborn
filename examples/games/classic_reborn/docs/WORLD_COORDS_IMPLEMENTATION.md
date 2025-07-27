# World Coordinate System Implementation

## Overview

We've implemented a world coordinate system for GMAP movement that allows free movement across the entire map without being bounded by 64x64 tile segments.

## Changes Made

### 1. Physics System (`physics.py`)
- Updated `can_move_to()` to accept world coordinates in GMAP mode
- Modified collision detection to convert world coords to segment + local coords
- Updated helper methods (`check_tile_at_position`, `is_in_water`, `is_on_chair`) to support world coordinates

### 2. Movement Handling (`classic_reborn_client.py`)
- `handle_movement()` now calculates movement in world coordinates for GMAPs
- Converts between world and local coordinates as needed
- Maintains backward compatibility for single-level mode

### 3. Water Detection
- Updated water status checking to use world coordinates in GMAP mode
- Properly handles cross-segment water detection

### 4. Spawn Fix
- Updated spawn position validation to use world coordinates
- Ensures players don't spawn on blocking tiles across segment boundaries

## How It Works

### World Coordinates
- World X = (segment_x * 64) + local_x
- World Y = (segment_y * 64) + local_y

### Movement Flow
1. Player input received
2. Calculate new position in world coordinates
3. Check collision using world coordinates
4. Convert back to local coordinates for the target segment
5. Update player position and handle segment transitions

### Collision Detection
1. For each collision point, calculate which segment it's in
2. Load the appropriate level data for that segment
3. Check tile collision in that segment's local coordinates

## Benefits

1. **Seamless Movement**: Players can move freely across the entire GMAP without hitting invisible boundaries
2. **Consistent Physics**: Collision detection works across segment boundaries
3. **Better User Experience**: No more getting stuck at segment edges

## Testing

Use the test script to verify the implementation:
```bash
python testing/test_world_coords.py
```

This will test movement across boundaries and log world coordinates to verify the system is working correctly.