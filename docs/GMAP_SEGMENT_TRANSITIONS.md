# GMAP Segment Transitions

## Problem

When moving to the edge of a GMAP segment, the player is warped back to the opposite edge of the same segment instead of transitioning to the adjacent segment.

## Root Cause

The server handles GMAP segment transitions by:
1. Sending a `PLO_PLAYERWARP` packet when the player reaches a segment boundary
2. The warp positions the player at the opposite edge (e.g., x=62 when exiting west)
3. The server should also update the player's `GMAPLEVELX` and `GMAPLEVELY` properties

However, the current implementation has issues:
- The warp packet may have an empty level name for GMAP transitions
- The GMAPLEVELX/Y properties aren't being updated correctly
- The client doesn't know which segment it should be in after the warp

## Expected Behavior

When crossing a segment boundary:
1. Player position wraps (x=63 → x=0, y=0 → y=63, etc.)
2. GMAPLEVELX/Y properties update to reflect the new segment
3. Client requests and loads the new segment's level file
4. Renderer shows the new segment seamlessly

## Current Workaround

The Classic Reborn client attempts to:
- Parse segment coordinates from level names (e.g., "zlttp-d8.nw" → col=3, row=8)
- Track movement to detect boundary crossings
- Use the gmap_handler to estimate segment changes

## Proper Fix

The server needs to:
1. Send updated GMAPLEVELX/Y properties when warping between segments
2. Include the target level name in the warp packet
3. Ensure the client receives the level change notification

The client should:
1. Handle PLAYER_WARP events for GMAP transitions
2. Update the current level when segment changes occur
3. Request adjacent segments for the new position

## Implementation Status

- ✅ GMAP rendering works for adjacent segments
- ✅ Movement allows crossing boundaries in GMAP mode
- ❌ Server doesn't update GMAPLEVELX/Y on transitions
- ❌ Client doesn't change current level on segment transitions
- ⚠️ Partial workaround by parsing level names

## Testing

To test GMAP transitions:
1. Connect to a GMAP-enabled server (e.g., hastur)
2. Move to the edge of a segment
3. Check if GMAPLEVELX/Y properties update
4. Verify the current level changes to the new segment