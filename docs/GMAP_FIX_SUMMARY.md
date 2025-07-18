# GMAP Tile Rendering Fix Summary

## Problem
Adjacent GMAP levels were rendering with incorrect tiles, showing a "looping" pattern where tiles would repeat incorrectly across segments.

## Root Cause
The GLEVNW01 file format uses a base64 encoding for tile data, and the decoding formula was incorrect. The character order in the formula was reversed.

## Solution
Fixed the tile decoding formula in `pyreborn/level_parser.py` line 194:

### Before (Incorrect)
```python
tile_id = idx2 * 64 + idx1  # This was wrong!
```

### After (Correct)
```python
tile_id = idx1 * 64 + idx2  # First char × 64 + second char
```

## Verification
- Water tiles ('J4') now correctly decode to tile ID 632
- All tiles remain within the valid range (0-1023) with modulo applied
- Adjacent GMAP segments render with the correct tiles matching the wire protocol data

## Files Changed
- `pyreborn/level_parser.py` - Fixed the decoding formula in `_decode_board_string()` method

## Documentation Added
- `docs/GMAP_TILE_ENCODING.md` - Comprehensive documentation of the encoding formats and decoding algorithm

## Testing
The fix was verified by:
1. Comparing PLO_BOARDPACKET (wire) data with decoded GLEVNW01 (file) data
2. Testing with the Classic Reborn client on the hastur server
3. Confirming adjacent levels render correctly without tile looping