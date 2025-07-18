# GMAP Tile Encoding Documentation

## Overview

GMAP (Graal Map) levels use a different tile encoding format in cached files compared to the wire protocol. This document explains the encoding differences and the correct decoding algorithm.

## Encoding Formats

### Wire Format (PLO_BOARDPACKET)
- **Format**: Raw binary data
- **Structure**: 8192 bytes (4096 tiles × 2 bytes per tile)
- **Encoding**: Little-endian 16-bit unsigned integers
- **Example**: Tile ID 632 = `0x0278` = bytes `[0x78, 0x02]`

### File Format (GLEVNW01)
- **Format**: Base64-encoded character pairs
- **Structure**: Text-based BOARD lines with encoded tile strings
- **Encoding**: Custom base64 using Graal's character set
- **Example**: Tile ID 632 = 'J4' (where J=9, 4=56 in the base64 charset)

## Base64 Character Set

Graal uses the standard base64 character set:
```
ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/
```

## Decoding Algorithm

### For GLEVNW01 Files

```python
def decode_tile_pair(char1, char2):
    """Decode a pair of characters to a tile ID"""
    base64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    
    idx1 = base64_chars.find(char1)
    idx2 = base64_chars.find(char2)
    
    if idx1 >= 0 and idx2 >= 0:
        # Correct formula: first_char * 64 + second_char
        tile_id = idx1 * 64 + idx2
        # Apply modulo to ensure valid range
        return tile_id % 1024
    else:
        return 0  # Invalid characters
```

### Common Tile Examples

| Tile ID | Base64 | Description |
|---------|---------|-------------|
| 0       | 'AA'    | Empty/void  |
| 632     | 'J4'    | Water       |
| 171     | 'Cr'    | Grass       |
| 170     | 'Cq'    | Grass       |
| 274     | 'ES'    | Path/road   |

## Implementation Notes

1. **Character Order**: The first character represents the higher-order bits (×64), the second character represents the lower-order bits.

2. **Modulo 1024**: Apply `% 1024` to ensure tile IDs stay within the valid range (0-1023).

3. **BOARD Line Format**: 
   ```
   BOARD x y width height tile_string
   ```
   Where `tile_string` contains the base64-encoded tile pairs.

4. **File Structure**: GLEVNW01 files contain 64 BOARD lines (one per row), each with 64 tiles (128 characters).

## Debugging Tips

- Water segments (like zlttp-c9.nw) contain only 'J4' repeated, which decodes to tile 632
- Use the formula `tile_id = char1_index * 64 + char2_index` to manually verify decoding
- The wire format and decoded file format should produce identical tile arrays

## Historical Context

The correct decoding formula was discovered through extensive testing and comparison of wire data (PLO_BOARDPACKET) with cached file data. The key insight was that the character order in the formula matters: the first character is multiplied by 64, not the second.