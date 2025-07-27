# Player Properties Debug Window

A real-time debug window that shows the current player properties and flashes when they are sent to or received from the server.

## Usage

1. **Toggle Window**: Press `F5` to show/hide the window
2. **Drag Window**: Click and drag the title bar to move it
3. **Watch Properties**: The window shows key player properties in real-time

## Properties Displayed

- **NICKNAME**: Player's display name
- **CURLEVEL**: Current level (GMAP name for GMAP levels)
- **X/Y**: Local coordinates (0-64 within segment)
- **X2/Y2**: World coordinates (for GMAP navigation)
- **GMAPLEVELX/Y**: Current GMAP segment position
- **SPRITE**: Direction/facing (UP, DOWN, LEFT, RIGHT)
- **GANI**: Current animation (idle, walk, sword, etc.)
- **CHAT**: Current chat bubble text
- **STATUS**: Player status flags
- **CARRY**: What the player is carrying
- **HP/MAXHP**: Health points
- **RUPEES/BOMBS/ARROWS**: Item counts

## Visual Feedback

### Flash Colors
- **Green Flash**: Property was SENT to server
- **Blue Flash**: Property was RECEIVED from server (currently limited)

The flash fades out over 0.5 seconds, giving you immediate visual feedback about network traffic.

## Implementation Notes

### Sent Properties
The window hooks into PyReborn's action system to detect when properties are sent. This includes:
- Movement (X, Y, X2, Y2, SPRITE)
- Animation changes (GANI)
- Level changes (CURLEVEL, GMAPLEVELX/Y)
- Chat messages
- Appearance changes

### Received Properties
Currently limited - PyReborn doesn't expose individual property IDs in the update events, so the window can't flash specific properties when received. This is a limitation of the current PyReborn event system.

## Use Cases

1. **Debug GMAP Navigation**: Watch CURLEVEL, GMAPLEVELX/Y change as you move between segments
2. **Monitor Movement**: See X/Y and X2/Y2 update in real-time
3. **Verify Protocol**: Ensure properties are being sent when expected
4. **Debug Animations**: Watch GANI property change with animations
5. **Network Activity**: See the pattern of property updates

## Example

When moving in a GMAP:
- X, Y, X2, Y2, SPRITE flash green as movement is sent
- When crossing segment boundaries:
  - CURLEVEL stays as the GMAP name (e.g., "world.gmap")
  - GMAPLEVELX/Y flash green as new segment position is sent

This helps verify that the GMAP protocol is working correctly!