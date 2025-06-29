# Graal Movement System Guide

## Overview

This guide explains how player movement works in Graal and how to implement it using the Python client.

## Movement Functions

### move_to(x: float, y: float, direction: int = 2)

Moves the player to a specific position on the map.

```python
client.move_to(30.5, 25.0, direction=2)
```

**Parameters:**
- `x`: X coordinate (0-127.5 tiles)
- `y`: Y coordinate (0-127.5 tiles)  
- `direction`: Facing direction (0=up, 1=left, 2=down, 3=right)

### move_by(dx: float, dy: float, current_x: float, current_y: float)

Moves the player by a relative amount from current position.

```python
client.move_by(1.0, 0, current_x=30, current_y=30)  # Move 1 tile right
```

## Coordinate System

Graal uses a **tile-based coordinate system**:
- Each level is made up of tiles (usually 64x64 tiles)
- Coordinates can have 0.5 precision (half-tile movement)
- Position (30, 30) means tile 30 across, tile 30 down

### Old Format (v2.22 clients)
- Positions stored as `position * 2` in a single byte
- Range: 0-127.5 tiles (0-255 when doubled)
- This is what our client uses

### New Format (v2.30+ clients)  
- Positions stored as `position * 16` in 16-bit value
- Allows pixel-perfect movement (1/16 tile precision)

## Direction System

The sprite/direction value encodes both facing direction and animation:

```
Direction = sprite % 4
Animation = sprite / 4
```

**Directions:**
- 0 = Up (north)
- 1 = Left (west)
- 2 = Down (south)
- 3 = Right (east)

## Movement Packet Structure

Movement uses PLI_PLAYERPROPS with position properties:

```
[PLI_PLAYERPROPS + 32]
[PLPROP_X + 32][1 + 32][x_value + 32]
[PLPROP_Y + 32][1 + 32][y_value + 32]
[PLPROP_SPRITE + 32][1 + 32][direction + 32]
[newline]
```

## Example Movement Patterns

### 1. Square Patrol
```python
def patrol_square(x, y, size=5):
    """Move in a square pattern"""
    # Right
    for i in range(size):
        x += 1
        client.move_to(x, y, direction=3)
        time.sleep(0.5)
    
    # Down
    for i in range(size):
        y += 1
        client.move_to(x, y, direction=2)
        time.sleep(0.5)
        
    # Left
    for i in range(size):
        x -= 1
        client.move_to(x, y, direction=1)
        time.sleep(0.5)
        
    # Up
    for i in range(size):
        y -= 1
        client.move_to(x, y, direction=0)
        time.sleep(0.5)
```

### 2. Circular Movement
```python
def move_circle(center_x, center_y, radius=3):
    """Move in a circle"""
    import math
    
    steps = 16
    for i in range(steps):
        angle = (2 * math.pi * i) / steps
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        
        client.move_to(x, y)
        time.sleep(0.3)
```

### 3. Follow Path
```python
def follow_waypoints(waypoints):
    """Follow a list of waypoints"""
    for x, y in waypoints:
        client.move_to(x, y)
        time.sleep(0.5)

# Example path
path = [(30, 30), (35, 30), (35, 35), (30, 35), (30, 30)]
follow_waypoints(path)
```

## Movement Tips

1. **Smooth Movement**: Send updates every 0.2-0.5 seconds for smooth appearance
2. **Half-Tile Steps**: Use 0.5 increments for smoother movement
3. **Direction Updates**: Always update direction when moving
4. **Bounds Checking**: Keep positions within valid range (0-127.5)
5. **Server Validation**: Server may reject invalid movements

## Complete Example

```python
import time
from graal_debug_client import GraalDebugClient

# Connect
client = GraalDebugClient("localhost", 14900)
client.connect()
client.login("username", "password")

# Wait for login
time.sleep(2)

# Set starting position
x, y = 30.0, 30.0

# Move in a pattern
for i in range(10):
    # Move right
    x += 0.5
    client.move_to(x, y, direction=3)
    time.sleep(0.3)
    
    # Move down
    y += 0.5  
    client.move_to(x, y, direction=2)
    time.sleep(0.3)

# Set chat to show we're done
client.set_chat("Movement complete!")
```

## Server-Side Considerations

1. **Collision Detection**: Server checks for walls, NPCs, etc.
2. **Level Boundaries**: Server enforces level bounds
3. **Movement Speed**: Server may limit movement speed
4. **Position Broadcasting**: Server sends your position to other players
5. **Touch Events**: Movement can trigger NPC touch events

## Advanced Topics

- **Warping**: Use PLI_LEVELWARP for instant position changes
- **Level Transitions**: Special handling at level edges
- **Gmaps**: Large world navigation across multiple levels
- **Animation**: Combine movement with GANI animations
- **Pathfinding**: Implement A* or similar for intelligent movement

This movement system provides the foundation for creating bots, automated players, or custom game clients that can navigate the Graal world.