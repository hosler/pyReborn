# GMAP Coordinate Synchronization System

This document explains how PyReborn and the Classic Reborn Client maintain synchronized coordinates between local segment positions (x/y) and world positions (x2/y2) in GMAP mode.

## Overview

In GMAP (large world) mode, player positions need to be tracked at two levels:
- **Local coordinates (x/y)**: Position within the current 64x64 tile segment (0-64)
- **World coordinates (x2/y2)**: Absolute position across the entire GMAP world

The client must maintain these in sync to ensure smooth transitions between segments and accurate position reporting to the server.

## Implementation

### 1. Player Model Properties (pyreborn/models/player.py)

The Player model uses property setters/getters to automatically synchronize coordinates:

```python
@property
def x(self) -> float:
    """Get local X coordinate (0-64 within segment)"""
    return self._x
    
@x.setter
def x(self, value: float):
    """Set local X coordinate and update world coordinate if in GMAP"""
    self._x = value
    # If in GMAP mode, update world coordinate
    if self.gmaplevelx is not None:
        self._x2 = self.gmaplevelx * 64 + value

@property
def x2(self) -> Optional[float]:
    """Get world X coordinate (across entire GMAP)"""
    return self._x2
    
@x2.setter
def x2(self, value: Optional[float]):
    """Set world X coordinate and update local coordinate"""
    self._x2 = value
    # Update local coordinate if world coordinate is set
    if value is not None:
        self._x = value % 64
        # Update GMAP segment if not set
        if self.gmaplevelx is None:
            self.gmaplevelx = int(value // 64)
```

### 2. Movement Protocol

The client uses different movement methods based on the mode:

- **Single Level Mode**: Uses `client.move_to(x, y)` which sends PLPROP_X and PLPROP_Y
- **GMAP Mode**: Uses `client.move_with_precision(x2, y2)` which sends PLPROP_X2 and PLPROP_Y2

```python
# In GMAP mode, use high precision coordinates
if self.gmap_handler.current_gmap:
    # The property setter will automatically update x/y and gmaplevel
    self.game_state.local_player.x2 = new_x
    self.game_state.local_player.y2 = new_y
    # Send world coordinates to server
    self.client.move_with_precision(new_x, new_y, 0.0, direction)
else:
    # Single level mode - just update x/y
    self.game_state.local_player.x = new_x
    self.game_state.local_player.y = new_y
    # Send local coordinates to server
    self.client.move_to(new_x, new_y, direction)
```

### 3. Server Properties

The server sends different properties based on the protocol version and mode:
- `PLPROP_X/Y`: Local segment coordinates (in half-tiles, divided by 2)
- `PLPROP_X2/Y2`: World coordinates for high precision movement
- `PLPROP_GMAPLEVELX/Y`: Current GMAP segment coordinates

When these properties are received, the Player model updates and maintains synchronization:

```python
elif prop == PlayerProp.PLPROP_GMAPLEVELX:
    old_gmaplevelx = self.gmaplevelx
    self.gmaplevelx = value
    # Update world coordinate if local coordinate is set
    if old_gmaplevelx != value:
        self._x2 = value * 64 + self.x
```

## Benefits

1. **Automatic Synchronization**: Setting x automatically updates x2 and vice versa
2. **Seamless Transitions**: World coordinates are maintained across segment boundaries
3. **Protocol Compatibility**: Works with both old (x/y) and new (x2/y2) server protocols
4. **Client Simplicity**: Game code doesn't need to manually track both coordinate systems

## Testing

To verify the synchronization is working:

1. Move near a segment boundary and check the debug output shows consistent coordinates
2. Use click-to-move across segment boundaries - player should maintain world position
3. Check that x2/y2 properties update when gmaplevelx/y changes
4. Verify smooth transitions without position jumps when crossing boundaries