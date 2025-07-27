# GMAP Movement Fix

## Problem
You were unable to move beyond the first level in GMAP mode. The player was bounded by 64x64 tiles even though the world coordinate system was implemented.

## Root Cause
The issue was in `classic_reborn_client.py` at line 1441:
```python
if 0 <= actual_x <= 63.5 and 0 <= actual_y <= 63.5:
    # Only send movement if within bounds
```

This check was preventing the client from sending movement commands when coordinates went outside the 0-64 range, effectively trapping the player in the current segment.

## Solution
Changed the condition to allow movement in GMAP mode regardless of coordinates:
```python
# Always send movement in GMAP mode, or check bounds in single level mode
should_send = is_gmap or (0 <= actual_x <= 63.5 and 0 <= actual_y <= 63.5)
if should_send:
    # Send movement
```

## How It Works Now

1. **GMAP Mode**: Movement is always sent, allowing coordinates to go beyond 64
2. **Single Level Mode**: Movement is still restricted to 0-64 as expected
3. **Boundary Crossing**: When you reach x=64 or y=64, the system:
   - Updates the segment coordinates
   - Wraps the position to the opposite side (e.g., x=64 becomes x=0.5)
   - Switches to the adjacent level
   - Continues movement seamlessly

## Testing
Run the test script to verify:
```bash
python testing/test_free_movement.py
```

Try moving continuously in any direction - you should now be able to move across the entire GMAP without getting stuck at boundaries.