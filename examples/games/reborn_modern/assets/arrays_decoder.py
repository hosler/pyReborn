#!/usr/bin/env python3

import struct
import io
import os
import binascii
import base64
import zlib
import numpy as np
from matplotlib import pyplot as plt
from PIL import Image

def decode_arrays_dat(file_path):
    """
    Decode the arrays.dat file which contains sprite/tileset metadata, blocking tile
    locations, and sprite construction data. Attempts multiple decoding methods.
    """
    with open(file_path, 'rb') as f:
        data = f.read()

    # Create buffer for easy reading
    buffer = io.BytesIO(data)

    # First check file size
    file_size = len(data)
    print(f"File size: {file_size} bytes")

    # Check if there's a header/magic number
    buffer.seek(0)
    header = buffer.read(4)
    print(f"First 4 bytes (possible header): {header.hex()}")

    # Create ASCII dump with both hex and ASCII representation
    print("\nASCII dump of first 1024 bytes (with hex):")
    for i in range(0, min(1024, len(data)), 16):
        chunk = data[i:i+16]
        hex_str = ' '.join(f'{b:02x}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        print(f"{i:04x}:  {hex_str:<47}  |{ascii_str}|")

    # Try multiple decoding methods
    print("\nAttempting multiple decoding methods...")

    # 1. Try Base64 decoding
    try_decode_base64(data)

    # 2. Try XOR with common keys
    try_xor_decode(data)

    # 3. Try byte shift decoding
    try_byte_shift(data)

    # 4. Try simple substitution
    try_substitution(data)

    # 5. Try various encoding schemes
    try_various_encodings(data)

    # Look for ASCII strings with more aggressive search
    # Use sliding window to find any potential strings
    min_string_length = 3  # Minimum characters to consider a string
    strings = []
    current_str = ""
    current_offset = 0

    for i, byte in enumerate(data):
        # Consider space and printable ASCII
        if 32 <= byte <= 126:
            if not current_str:  # Start of new string
                current_offset = i
            current_str += chr(byte)
        else:  # Non-ASCII character
            if len(current_str) >= min_string_length:
                strings.append((current_offset, current_str))
            current_str = ""

    # Don't forget the last string if file ends with ASCII
    if current_str and len(current_str) >= min_string_length:
        strings.append((current_offset, current_str))

    # Print found strings
    if strings:
        print(f"\nFound {len(strings)} ASCII strings:")
        for offset, string in strings:
            print(f"  Offset 0x{offset:04x}: {string}")
    else:
        print("\nNo meaningful ASCII strings found")

    # Try to parse as 2-byte values (little-endian)
    buffer.seek(0)
    values_16bit = []
    while True:
        try:
            value = struct.unpack('<H', buffer.read(2))[0]  # 2-byte little-endian unsigned short
            values_16bit.append(value)
        except struct.error:
            break

    print(f"\nFound {len(values_16bit)} 16-bit values")
    print(f"First 20 values: {values_16bit[:20]}")

    # Look for common patterns in the data that might indicate tile map structures
    # For blocking tiles, values are often sequential and grouped
    sequences = []
    current_seq = [values_16bit[0]]

    for i in range(1, len(values_16bit)):
        if values_16bit[i] == values_16bit[i-1] + 1 or values_16bit[i] == values_16bit[i-1] - 1:
            current_seq.append(values_16bit[i])
        else:
            if len(current_seq) >= 5:  # Only consider longer sequences
                sequences.append((len(current_seq), current_seq.copy()))
            current_seq = [values_16bit[i]]

    # Add the last sequence if it's long enough
    if len(current_seq) >= 5:
        sequences.append((len(current_seq), current_seq))

    # Sort by sequence length
    sequences.sort(reverse=True)

    print(f"\nFound {len(sequences)} sequences of consecutive values:")
    for i, (length, seq) in enumerate(sequences[:5]):  # Show top 5
        print(f"  Sequence {i+1}: Length {length}, Start: {seq[0]}, End: {seq[-1]}")
        print(f"    Sample: {seq[:10]}..." if len(seq) > 10 else f"    Full: {seq}")

    # Look for patterns that might indicate collision/blocking data
    # Collision data is often stored as groups of rectangles or coordinates
    rects = []
    i = 0
    while i < len(values_16bit) - 4:
        # Try to interpret as x,y,width,height rectangles
        if i + 4 <= len(values_16bit):
            x = values_16bit[i]
            y = values_16bit[i+1]
            w = values_16bit[i+2]
            h = values_16bit[i+3]

            # Check if these look like valid rectangle dimensions
            if 0 <= x < 1000 and 0 <= y < 1000 and 0 < w < 100 and 0 < h < 100:
                rects.append((x, y, w, h))
        i += 4

    if rects:
        print(f"\nPossible blocking rectangles found: {len(rects)}")
        print(f"Sample rectangles (x,y,w,h): {rects[:5]}")

        # Visualize the possible blocking rectangles
        plt.figure(figsize=(10, 10))
        ax = plt.gca()

        for x, y, w, h in rects[:50]:  # Show first 50 to avoid clutter
            rect = plt.Rectangle((x, y), w, h, fill=False, edgecolor='red')
            ax.add_patch(rect)

        # Set reasonable display limits
        max_x = max([r[0] + r[2] for r in rects[:50]]) if rects else 100
        max_y = max([r[1] + r[3] for r in rects[:50]]) if rects else 100
        plt.xlim(0, max_x + 10)
        plt.ylim(0, max_y + 10)

        plt.title('Potential Blocking Rectangles')
        plt.xlabel('X')
        plt.ylabel('Y')
        plt.grid(True)
        plt.savefig('arrays_blocking_rects.png')
        print("Saved blocking rectangles visualization to arrays_blocking_rects.png")

    # Look for possible coordinate data (x,y pairs)
    buffer.seek(0)
    coordinates = []
    while buffer.tell() < len(data) - 4:
        try:
            x = struct.unpack('<H', buffer.read(2))[0]
            y = struct.unpack('<H', buffer.read(2))[0]
            coordinates.append((x, y))
        except struct.error:
            break

    print(f"\nInterpreted as (x,y) coordinates:")
    print(f"Found {len(coordinates)} coordinate pairs")
    print(f"First 10 coordinate pairs: {coordinates[:10]}")

    # Attempt to visualize the coordinate data
    if coordinates:
        plt.figure(figsize=(10, 10))

        # Extract just the first 200 coordinates for visualization
        sample_coords = coordinates[:200]
        x_coords = [c[0] for c in sample_coords]
        y_coords = [c[1] for c in sample_coords]

        plt.scatter(x_coords, y_coords, alpha=0.7)
        plt.title('Coordinate Data Visualization')
        plt.xlabel('X coordinate')
        plt.ylabel('Y coordinate')
        plt.grid(True)

        # Save visualization
        plt.savefig('arrays_coordinates.png')
        print("\nSaved coordinate visualization to arrays_coordinates.png")

    # Try to find sprite definition data
    # Sprite definitions often contain sequences of small integers
    sprite_defs = []
    for i in range(0, len(values_16bit) - 10, 10):
        section = values_16bit[i:i+10]
        # Sprite data often has small values and some zeros
        if max(section) < 256 and 0 in section and sum(1 for v in section if v < 32) >= 5:
            sprite_defs.append((i, section))

    if sprite_defs:
        print(f"\nPossible sprite definitions found: {len(sprite_defs)}")
        print("Sample sprite definitions:")
        for i, (offset, def_data) in enumerate(sprite_defs[:5]):
            print(f"  Sprite {i+1} at offset {offset}: {def_data}")

    return {
        "file_size": file_size,
        "header": header.hex(),
        "strings": strings,
        "values_16bit": values_16bit[:100],
        "coordinates": coordinates[:50],
        "possible_rects": rects[:20],
        "sprite_defs": sprite_defs[:10]
    }


def try_decode_base64(data):
    """Try to decode the data as Base64"""
    print("\nAttempting Base64 decoding...")

    # First, check if data looks like Base64
    # Base64 uses A-Z, a-z, 0-9, +, /, and = for padding
    base64_chars = set(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=')
    data_chars = set(data)

    # Calculate percentage of Base64 characters
    base64_percentage = sum(1 for b in data if b in base64_chars) / len(data) * 100
    print(f"Base64 character percentage: {base64_percentage:.2f}%")

    # Try to decode sections that might be Base64
    # Start with the whole file
    try:
        decoded_data = base64.b64decode(data)
        print(f"Successfully Base64 decoded entire file: {len(decoded_data)} bytes")
        # Check if decoded data has ASCII strings
        check_for_ascii_strings(decoded_data, "Base64 decoded data")
        return decoded_data
    except Exception as e:
        print(f"Cannot decode entire file as Base64: {e}")

    # Try sliding window approach to find Base64 chunks
    for window_size in [64, 128, 256, 512]:
        for i in range(0, len(data) - window_size, window_size // 2):
            chunk = data[i:i+window_size]
            try:
                # Add padding if needed
                padding = b'=' * ((4 - len(chunk) % 4) % 4)
                padded_chunk = chunk + padding
                decoded = base64.b64decode(padded_chunk)
                if len(decoded) > 10:  # Only consider reasonably sized decodings
                    print(f"Possible Base64 chunk at offset {i}, decoded size: {len(decoded)} bytes")
                    # Check if decoded chunk has ASCII strings
                    if check_for_ascii_strings(decoded, f"Base64 chunk at offset {i}"):
                        print(f"Found meaningful data in Base64 chunk at offset {i}")
                        # Save this decoded chunk for further analysis
                        with open(f"decoded_base64_chunk_{i}.bin", "wb") as f:
                            f.write(decoded)
            except Exception:
                pass

    # Try a modified Base64 approach (some games use custom Base64 alphabets)
    # This is more advanced and would require knowledge of the specific encoding
    print("Note: Custom Base64 alphabets would require specific knowledge of the encoding")
    return None


def try_xor_decode(data):
    """Try XOR decoding with common keys"""
    print("\nAttempting XOR decoding with common keys...")

    # Common XOR keys used in simple encoding schemes
    common_keys = [0xFF, 0xAA, 0x55, 0x33, 0x3F, 0x7F, 0xF0, 0x0F, 0x80, 0x08, 0x42, 0x5A]

    for key in common_keys:
        # Apply XOR with the key
        decoded = bytearray()
        for b in data:
            decoded.append(b ^ key)

        # Check if the decoded data has more readable content
        if check_for_ascii_strings(decoded, f"XOR with 0x{key:02X}"):
            print(f"Found potential XOR encoding with key 0x{key:02X}")
            # Save this decoded data for further analysis
            with open(f"decoded_xor_0x{key:02X}.bin", "wb") as f:
                f.write(decoded)

    # Try multi-byte XOR keys
    for key_length in [2, 4]:
        # Try some common multi-byte XOR patterns
        patterns = [
            bytes([0xAA, 0x55] * (key_length // 2)),  # Alternating pattern
            bytes([0xFF, 0x00] * (key_length // 2)),  # Alternating pattern
            bytes([0x12, 0x34, 0x56, 0x78][:key_length]),  # Sequential values
            bytes([0xDE, 0xAD, 0xBE, 0xEF][:key_length])   # DEADBEEF pattern
        ]

        for pattern in patterns:
            # Apply multi-byte XOR
            decoded = bytearray()
            for i, b in enumerate(data):
                decoded.append(b ^ pattern[i % key_length])

            # Check if the decoded data has more readable content
            pattern_hex = ''.join(f'{b:02X}' for b in pattern)
            if check_for_ascii_strings(decoded, f"Multi-byte XOR with {pattern_hex}"):
                print(f"Found potential multi-byte XOR encoding with key {pattern_hex}")
                # Save this decoded data for further analysis
                with open(f"decoded_xor_{pattern_hex}.bin", "wb") as f:
                    f.write(decoded)

    return None


def try_byte_shift(data):
    """Try byte shifting/rotation decoding"""
    print("\nAttempting byte shift/rotation decoding...")

    # Try byte shifts (add/subtract constant)
    for shift in [1, 2, 4, 8, 16, 32, 64, 128]:
        # Addition
        decoded_add = bytearray()
        for b in data:
            decoded_add.append((b + shift) & 0xFF)  # Add shift, wrap around at 255

        # Subtraction
        decoded_sub = bytearray()
        for b in data:
            decoded_sub.append((b - shift) & 0xFF)  # Subtract shift, wrap around at 0

        # Check if any of these produce meaningful output
        if check_for_ascii_strings(decoded_add, f"Byte shift +{shift}"):
            print(f"Found potential byte shift encoding with +{shift}")
            with open(f"decoded_shift_plus_{shift}.bin", "wb") as f:
                f.write(decoded_add)

        if check_for_ascii_strings(decoded_sub, f"Byte shift -{shift}"):
            print(f"Found potential byte shift encoding with -{shift}")
            with open(f"decoded_shift_minus_{shift}.bin", "wb") as f:
                f.write(decoded_sub)

    # Try bit rotations
    for rotation in [1, 2, 3, 4, 5, 6, 7]:
        # Rotate left
        decoded_rol = bytearray()
        for b in data:
            # Rotate left by 'rotation' bits
            rol = ((b << rotation) | (b >> (8 - rotation))) & 0xFF
            decoded_rol.append(rol)

        # Rotate right
        decoded_ror = bytearray()
        for b in data:
            # Rotate right by 'rotation' bits
            ror = ((b >> rotation) | (b << (8 - rotation))) & 0xFF
            decoded_ror.append(ror)

        # Check if any of these produce meaningful output
        if check_for_ascii_strings(decoded_rol, f"Bit rotation left {rotation}"):
            print(f"Found potential bit rotation encoding with left {rotation}")
            with open(f"decoded_rol_{rotation}.bin", "wb") as f:
                f.write(decoded_rol)

        if check_for_ascii_strings(decoded_ror, f"Bit rotation right {rotation}"):
            print(f"Found potential bit rotation encoding with right {rotation}")
            with open(f"decoded_ror_{rotation}.bin", "wb") as f:
                f.write(decoded_ror)

    return None


def try_substitution(data):
    """Try simple substitution decoding"""
    print("\nAttempting substitution decoding...")

    # Try reversing byte order
    reversed_data = bytearray(data[::-1])
    if check_for_ascii_strings(reversed_data, "Reversed bytes"):
        print("Found potential reversed byte encoding")
        with open("decoded_reversed.bin", "wb") as f:
            f.write(reversed_data)

    # Try nibble swapping (swap high and low 4 bits)
    nibble_swapped = bytearray()
    for b in data:
        swapped = ((b >> 4) | ((b & 0x0F) << 4)) & 0xFF
        nibble_swapped.append(swapped)

    if check_for_ascii_strings(nibble_swapped, "Nibble swapped"):
        print("Found potential nibble swapped encoding")
        with open("decoded_nibble_swapped.bin", "wb") as f:
            f.write(nibble_swapped)

    # Try byte pair swapping
    if len(data) % 2 == 0:  # Only if data length is even
        pair_swapped = bytearray()
        for i in range(0, len(data), 2):
            if i+1 < len(data):
                pair_swapped.append(data[i+1])
                pair_swapped.append(data[i])

        if check_for_ascii_strings(pair_swapped, "Byte pair swapped"):
            print("Found potential byte pair swapped encoding")
            with open("decoded_pair_swapped.bin", "wb") as f:
                f.write(pair_swapped)

    return None


def try_various_encodings(data):
    """Try various encoding schemes"""
    print("\nAttempting various encoding schemes...")

    # Try to decompress using common algorithms
    # 1. zlib
    try:
        decompressed = zlib.decompress(data)
        print(f"Successfully decompressed with zlib: {len(decompressed)} bytes")
        check_for_ascii_strings(decompressed, "zlib decompressed")
        with open("decoded_zlib.bin", "wb") as f:
            f.write(decompressed)
    except Exception as e:
        print(f"zlib decompression failed: {e}")

    # 2. zlib with various window bits
    for wbits in [0, 8, 15, -8, -15]:  # Different window bits for zlib/gzip/deflate formats
        try:
            decompressed = zlib.decompress(data, wbits)
            print(f"Successfully decompressed with zlib (wbits={wbits}): {len(decompressed)} bytes")
            check_for_ascii_strings(decompressed, f"zlib decompressed (wbits={wbits})")
            with open(f"decoded_zlib_wbits_{wbits}.bin", "wb") as f:
                f.write(decompressed)
        except Exception:
            pass

    # Try with offset (some files have headers before compressed data)
    for offset in [2, 4, 8, 16, 32]:
        if len(data) > offset:
            try:
                decompressed = zlib.decompress(data[offset:])
                print(f"Successfully decompressed with zlib starting at offset {offset}: {len(decompressed)} bytes")
                check_for_ascii_strings(decompressed, f"zlib decompressed (offset={offset})")
                with open(f"decoded_zlib_offset_{offset}.bin", "wb") as f:
                    f.write(decompressed)
            except Exception:
                pass

    # Try with potential Reborn-specific encoding
    # This is speculative and based on patterns seen in other Reborn files
    print("\nAttempting Reborn-specific decoding (speculative)...")

    # 1. Try reading as 16-bit values and applying common transformations
    if len(data) >= 2:
        buffer = io.BytesIO(data)
        buffer.seek(0)

        values_16bit = []
        while buffer.tell() < len(data) - 1:
            try:
                value = struct.unpack('<H', buffer.read(2))[0]  # 2-byte little-endian unsigned short
                values_16bit.append(value)
            except struct.error:
                break

        # Try common transformations on 16-bit values
        # For example, interpret as offsets into another table
        if len(values_16bit) > 0:
            print(f"Found {len(values_16bit)} 16-bit values for transformation")

            # 1. Try interpreting as offsets (commonly used in sprite data)
            if max(values_16bit) < len(data):
                print("Values could be valid offsets into the file")

                # Extract data at each offset
                offset_data = []
                for offset in values_16bit[:20]:  # Just try the first 20
                    if offset < len(data) - 4:  # Ensure we can read at least 4 bytes
                        chunk = data[offset:offset+16]  # Take 16 bytes from each offset
                        offset_data.append((offset, chunk))

                print(f"Sample data from offsets:")
                for offset, chunk in offset_data[:5]:
                    hex_chunk = ' '.join(f'{b:02x}' for b in chunk)
                    ascii_chunk = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
                    print(f"  Offset 0x{offset:04x}: {hex_chunk} | {ascii_chunk}")

    return None


def check_for_ascii_strings(data, decode_method):
    """Check for ASCII strings in the data and return True if meaningful strings found"""
    # Look for ASCII strings
    min_string_length = 4  # Minimum characters to consider a string
    strings = []
    current_str = ""
    current_offset = 0

    for i, byte in enumerate(data):
        # Consider space and printable ASCII
        if 32 <= byte <= 126:
            if not current_str:  # Start of new string
                current_offset = i
            current_str += chr(byte)
        else:  # Non-ASCII character
            if len(current_str) >= min_string_length:
                strings.append((current_offset, current_str))
            current_str = ""

    # Don't forget the last string if data ends with ASCII
    if current_str and len(current_str) >= min_string_length:
        strings.append((current_offset, current_str))

    # Calculate ASCII percentage
    ascii_count = sum(1 for b in data if 32 <= b <= 126)
    ascii_percentage = (ascii_count / len(data)) * 100 if data else 0

    # Print results
    if strings:
        meaningful_strings = [s for _, s in strings if len(s) >= 5 and not all(c in '0123456789ABCDEFabcdef' for c in s)]
        if meaningful_strings:
            print(f"\n{decode_method}: Found {len(strings)} strings, {len(meaningful_strings)} appear meaningful")
            print(f"ASCII percentage: {ascii_percentage:.2f}%")

            # Print some sample strings
            for offset, string in strings[:10]:  # Just show first 10
                if len(string) >= 5 and not all(c in '0123456789ABCDEFabcdef' for c in string):
                    print(f"  Offset 0x{offset:04x}: {string}")

            return True

    return False


def create_ascii_visualization(tiles, width=64, height=64):
    """Create ASCII visualization of tile data"""
    lines = []
    lines.append(f"Tile Data Visualization ({width}x{height})")
    lines.append("=" * 40)

    # Create a mapping of common tile ranges to characters
    def tile_to_char(tile_id):
        if tile_id == 0:
            return '.'  # Empty
        elif 1 <= tile_id <= 15:
            return '#'  # Walls/blocks
        elif 16 <= tile_id <= 31:
            return '~'  # Water
        elif 32 <= tile_id <= 47:
            return '^'  # Trees/nature
        elif 48 <= tile_id <= 63:
            return ':'  # Ground/paths
        elif 64 <= tile_id <= 79:
            return '%'  # Special tiles
        else:
            return '?'  # Unknown

    # Create the visual
    for y in range(height):
        row = ""
        for x in range(width):
            idx = y * width + x
            if idx < len(tiles):
                char = tile_to_char(tiles[idx])
                row += char
            else:
                row += ' '
        lines.append(row)

    # Add legend
    lines.append("")
    lines.append("Legend:")
    lines.append("  . = Empty (0)")
    lines.append("  # = Walls/Blocks (1-15)")
    lines.append("  ~ = Water (16-31)")
    lines.append("  ^ = Trees/Nature (32-47)")
    lines.append("  : = Ground/Paths (48-63)")
    lines.append("  % = Special (64-79)")
    lines.append("  ? = Other (80+)")

    return "\n".join(lines)


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.realpath(__file__))
    file_path = os.path.join(script_dir, "arrays.dat")

    if os.path.exists(file_path):
        print(f"Decoding {file_path}...\n")
        result = decode_arrays_dat(file_path)

        # Check if arrays2.dat exists and compare if needed
        arrays2_path = os.path.join(script_dir, "arrays2.dat")
        if os.path.exists(arrays2_path):
            print("\n\nFound arrays2.dat - comparing files...")
            with open(arrays2_path, 'rb') as f:
                data2 = f.read()
            print(f"arrays2.dat size: {len(data2)} bytes")

            with open(file_path, 'rb') as f:
                data1 = f.read()

            # Basic comparison
            if data1 == data2:
                print("Files are identical")
            else:
                print("Files differ")
                # Find where they differ
                min_len = min(len(data1), len(data2))
                diff_positions = [i for i in range(min_len) if data1[i] != data2[i]]
                if diff_positions:
                    print(f"First difference at offset: 0x{diff_positions[0]:04x}")
                    print(f"Number of differences: {len(diff_positions)}")
                else:
                    print(f"One file is longer: arrays.dat={len(data1)} bytes, arrays2.dat={len(data2)} bytes")
    else:
        print(f"Error: File not found: {file_path}")
