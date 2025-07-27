# GMAP Local Coordinate System

## Overview

The GMAP system has been simplified to always use local coordinates (0-64) for camera positioning and player movement. This eliminates coordinate conversion complexity while maintaining compatibility with the server protocol.

## Key Changes

### 1. Camera Always Uses Local Coordinates
- Camera position is based on player's local x,y (0-64 range)
- No more world coordinate conversions for camera
- Current level is rendered at (0,0), adjacent levels at relative offsets

### 2. Movement Always Uses Local Coordinates
- All movement calculations use local x,y
- Movement packets always send local coordinates to server
- Boundary crossing checks convert to world coordinates only for detection

### 3. Automatic x2/y2 Synchronization
- Player model property setters automatically update x2/y2 when x/y changes
- When x is set and gmaplevelx exists: x2 = gmaplevelx * 64 + x
- When y is set and gmaplevely exists: y2 = gmaplevely * 64 + y
- No manual x2/y2 updates needed in game code

### 4. Other Players Use World Coordinates
- Local player rendered using local coordinates
- Other players use their x2/y2 or calculated world position
- This allows proper rendering of players in adjacent segments

## Benefits

1. **Simpler Code** - No coordinate system switching based on mode
2. **Consistent Behavior** - Camera and movement always work the same way
3. **Automatic Sync** - x2/y2 maintained automatically by property setters
4. **Server Compatible** - Server expects local coordinates in movement packets

## Implementation Details

### Renderer Changes
```python
# Camera update - always local
self.camera_x = player_x - (VIEWPORT_TILES_X // 2)
self.camera_y = player_y - (VIEWPORT_TILES_Y // 2)

# Current level at origin
self._draw_level_at_offset(current_level, 0, 0, ...)

# Adjacent levels at relative offsets
relative_offset_x = (adj_col - current_col) * 64
relative_offset_y = (adj_row - current_row) * 64
self._draw_level_at_offset(adjacent_level, relative_offset_x, relative_offset_y, ...)
```

### Movement Changes
```python
# Always use local coordinates
current_x = self.game_state.local_player.x
current_y = self.game_state.local_player.y
new_x = current_x + dx * speed
new_y = current_y + dy * speed

# Update position - setter handles x2/y2
self.game_state.local_player.x = new_x
self.game_state.local_player.y = new_y

# Send to server
self.client.move_to(new_x, new_y, direction)
```

### Player Model Property Setters
```python
@x.setter
def x(self, value: float):
    self._x = value
    if self.gmaplevelx is not None:
        self._x2 = self.gmaplevelx * 64 + value
```

This design keeps the complexity in the player model where it belongs, while the game logic remains simple and consistent.