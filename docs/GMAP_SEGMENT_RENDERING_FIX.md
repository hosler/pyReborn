# GMAP Segment Rendering Fix

## Problem
GMAP segments were appearing in the wrong visual positions:
- Left segments appeared on the right side
- Right segments appeared on the left side  
- Top/bottom segments were correct

## Root Cause
The renderer was drawing segments at their absolute world coordinates instead of relative positions around the current segment. This caused visual misalignment because:

1. **Coordinate System**: Segments use column-letter notation (a=0, b=1, c=2, d=3, e=4, etc.)
2. **Visual Expectation**: Players expect left arrow to go to visually left segment
3. **Actual Behavior**: Left arrow went to segment with smaller X coordinate, but it appeared on the right

## Solution
Fixed the renderer coordinate calculation in `renderer.py`:

```python
# OLD (wrong):
world_offset_x = current_col * 64 + (dx * 64)

# NEW (correct):
world_offset_x = current_col * 64 + (-dx * 64)
```

## Key Insight
The visual coordinate system needs to be **inverted** from the logical coordinate system:
- `dx = -1` (west segment) should appear on the **left** visually
- `dx = +1` (east segment) should appear on the **right** visually

By using `-dx * 64` instead of `dx * 64`, we achieve correct visual alignment.

## Result
✅ **West segments** (c8) now appear on the left side
✅ **East segments** (e8) now appear on the right side  
✅ **North segments** (d7) appear above
✅ **South segments** (d9) appear below

The 3x3 grid of segments now renders correctly around the current segment.