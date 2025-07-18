# GMAP (Giant Map) Understanding

## Key Concepts

1. **GMaps are ONE giant level** - Not a collection of separate levels
2. **Individual .nw files are segments** - Each level file is just a piece of the larger map
3. **Client behaves as single level** - From the client's perspective, you're always in one big level

## How GMaps Work

### Level Streaming
- When gmaps are enabled, the server streams level data as you move
- Client must request level files using `PLI_WANTFILE` for each segment
- GMAP file (e.g., `world.gmap`) contains the structure and level names
- Level segments are named like: `gmapname_XX-YY.nw` where XX and YY are segment coordinates

### Player Position Tracking
The client tracks position using special properties:
- **GMAPLEVELX** - Which X segment of the gmap you're in
- **GMAPLEVELY** - Which Y segment of the gmap you're in  
- **X2** - Pixel X position within the entire gmap
- **Y2** - Pixel Y position within the entire gmap
- **Z2** - Pixel Z position (height/layer)

### Example
If a gmap is made of 3x3 level segments:
```
[0,0] [1,0] [2,0]
[0,1] [1,1] [2,1]  
[0,2] [1,2] [2,2]
```

Being at GMAPLEVELX=1, GMAPLEVELY=1 means you're in the center segment.
X2/Y2 would be your absolute pixel position across the entire 192x192 tile area (3 levels × 64 tiles each).

## Implementation Notes

1. When receiving gmap level data, don't treat segments as separate levels
2. Track the player's gmap segment position  
3. Handle seamless transitions between segments
4. Request the .gmap file when entering a gmap to get structure info
5. Request adjacent level files (.nw) as the player moves between segments
6. Level files are requested using standard file requests, not PLI_ADJACENTLEVEL

## Minimap Support

The minimap has special support for gmaps:
- Shows the entire gmap grid structure
- Highlights current segment in yellow
- Shows player position within the segment
- Displays gmap dimensions (e.g., "GMAP [1,2] of 3x3")
- Other players are shown if they have gmap position data

Toggle minimap with the M key.