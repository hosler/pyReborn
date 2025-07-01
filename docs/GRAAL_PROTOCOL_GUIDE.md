# GServer Protocol Implementation Guide

A comprehensive guide to implementing the Graal Reborn protocol, based on the PyReborn library implementation.

## Table of Contents

1. [Overview](#overview)
2. [Connection Setup](#connection-setup)
3. [Encryption (ENCRYPT_GEN_5)](#encryption-encrypt_gen_5)
4. [Packet Structure](#packet-structure)
5. [Login Process](#login-process)
6. [Player Properties](#player-properties)
7. [Chat System](#chat-system)
8. [Movement and Actions](#movement-and-actions)
9. [File Transfers](#file-transfers)
10. [Complete Packet Reference](#complete-packet-reference)

---

## Overview

The GServer protocol is a TCP-based protocol using partial packet encryption with compression. All data is encoded using Graal's +32 offset encoding to avoid control characters.

### Key Protocol Features:
- **TCP Socket Communication** on port 14900 (default)
- **ENCRYPT_GEN_5** - Partial packet encryption
- **Multiple Compression Types**: UNCOMPRESSED, ZLIB, BZ2
- **Graal Encoding**: All bytes use +32 offset to avoid 0x00-0x1F range
- **Packet Streaming**: Multiple packets can be bundled in one TCP send

---

## Connection Setup

### 1. TCP Connection
```python
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("server_host", 14900))
```

### 2. Encryption Key Generation
```python
import random
encryption_key = random.randint(0, 255)
```

### 3. Codec Initialization
```python
from pyreborn.encryption import GraalEncryption

# Separate codecs for send/receive to maintain independent state
out_codec = GraalEncryption(encryption_key)
in_codec = GraalEncryption(encryption_key)
```

---

## Encryption (ENCRYPT_GEN_5)

ENCRYPT_GEN_5 is a partial packet encryption system that only encrypts the first X bytes of each packet based on compression type.

### Encryption Parameters
```python
class GraalEncryption:
    def __init__(self, key: int = 0):
        self.key = key
        self.iterator = 0x4A80B38        # Fixed starting value
        self.limit = -1                  # Encryption limit
        self.multiplier = 0x8088405      # LCG multiplier
```

### Encryption Limits by Compression Type
| Compression Type | Value | Encrypted Bytes |
|-----------------|-------|-----------------|
| UNCOMPRESSED    | 0x02  | 48 bytes (12 * 4) |
| ZLIB            | 0x04  | 16 bytes (4 * 4)  |
| BZ2             | 0x06  | 16 bytes (4 * 4)  |

### Encryption Algorithm
```python
def encrypt(self, data: bytes) -> bytes:
    """ENCRYPT_GEN_5 implementation"""
    result = bytearray(data)
    
    # Determine bytes to encrypt based on limit
    if self.limit < 0:
        bytes_to_encrypt = len(data)  # No limit
    elif self.limit == 0:
        return bytes(result)  # Don't encrypt anything
    else:
        bytes_to_encrypt = min(len(data), self.limit * 4)
    
    for i in range(bytes_to_encrypt):
        if i % 4 == 0:
            if self.limit == 0:
                break
            # Update iterator using Linear Congruential Generator
            self.iterator = (self.iterator * self.multiplier + self.key) & 0xFFFFFFFF
            if self.limit > 0:
                self.limit -= 1
        
        # XOR with iterator bytes
        iterator_bytes = struct.pack('<I', self.iterator)
        result[i] ^= iterator_bytes[i % 4]
    
    return bytes(result)

def decrypt(self, data: bytes) -> bytes:
    """Decryption is identical to encryption for XOR"""
    return self.encrypt(data)
```

### Per-Packet Encryption Setup
**IMPORTANT**: Each packet must use a fresh codec with the correct limit while maintaining iterator state:

```python
def encrypt_packet(data: bytes, compression_type: int, main_codec: GraalEncryption):
    # Create new codec for this packet
    packet_codec = GraalEncryption(main_codec.key)
    packet_codec.iterator = main_codec.iterator  # Copy current state
    packet_codec.limit_from_type(compression_type)  # Set limit for this packet
    
    # Encrypt
    encrypted = packet_codec.encrypt(data)
    
    # Update main codec state
    main_codec.iterator = packet_codec.iterator
    
    return encrypted
```

---

## Packet Structure

### TCP Packet Format
```
[Length (2 bytes, big-endian)][Compression Type (1 byte)][Encrypted Data]
```

### Compressed Data Format (after decryption and decompression)
```
[Packet1][Packet2]...[PacketN]
```

### Individual Packet Format
```
[Packet ID + 32 (1 byte)][Packet Data][0x0A (newline terminator)]
```

### Example: Complete Packet Flow
```python
# 1. Create packet data
packet_data = create_player_props_packet(nickname="TestPlayer")

# 2. Determine compression
if len(packet_data) <= 55:
    compression_type = 0x02  # UNCOMPRESSED
    compressed_data = packet_data
else:
    compression_type = 0x04  # ZLIB
    compressed_data = zlib.compress(packet_data)

# 3. Encrypt with per-packet codec
encrypted_data = encrypt_packet(compressed_data, compression_type, out_codec)

# 4. Build final TCP packet
tcp_packet = struct.pack('>H', len(encrypted_data) + 1) + \
             bytes([compression_type]) + encrypted_data

# 5. Send
socket.sendall(tcp_packet)
```

---

## Login Process

### Login Packet Format (PLI_LOGIN = 2)
```
[PLI_LOGIN + 32 (0x22)][PLTYPE_CLIENT3 + 32 (0x57)][Encryption Key + 32]
[Version String][0x0A][Account][0x0A][Password][0x0A][Identity][0x0A]
```

### Login Implementation
```python
class LoginPacket:
    def __init__(self, account: str, password: str, encryption_key: int):
        self.account = account
        self.password = password
        self.encryption_key = encryption_key
    
    def to_bytes(self) -> bytes:
        packet = bytearray()
        
        # Packet ID and type
        packet.append(2 + 32)   # PLI_LOGIN
        packet.append(37 + 32)  # PLTYPE_CLIENT3
        
        # Encryption key
        packet.append((self.encryption_key + 32) & 0xFF)
        
        # Version string
        packet.extend(b'GNW03014\n')  # Client version
        
        # Credentials
        packet.extend(self.account.encode('ascii') + b'\n')
        packet.extend(self.password.encode('ascii') + b'\n')
        
        # Identity string
        packet.extend(b'PC,,,,,Python\n')
        
        return bytes(packet)
```

### Login Response Sequence
1. **PLO_SIGNATURE (25)** - Login accepted, contains server info
2. **PLO_HASNPCSERVER (44)** - Server capabilities
3. **PLO_PLAYERPROPS (9)** - Your player's initial properties
4. **PLO_PLAYERWARP (14)** - Warp to starting level
5. **Various setup packets** - Weapons, levels, etc.

---

## Player Properties

Player properties use a stream format where each property has an ID and type-specific data.

### Property Stream Format
```
[PLPROP_ID + 32][Property-specific data]...
```

### Property Types and Formats

#### Single Byte Properties
```python
# Examples: PLPROP_X (15), PLPROP_Y (16), PLPROP_SPRITE (17)
# Format: [ID + 32][Value + 32]
def write_single_byte_prop(prop_id: int, value: int) -> bytes:
    return bytes([prop_id + 32, value + 32])
```

#### String Properties
```python
# Examples: PLPROP_NICKNAME (0), PLPROP_CURCHAT (12)
# Format: [ID + 32][Length + 32][String data]
def write_string_prop(prop_id: int, value: str) -> bytes:
    data = value.encode('ascii')
    return bytes([prop_id + 32, len(data) + 32]) + data
```

#### Special Properties
```python
# PLPROP_HEADGIF (11) - Uses +100 length encoding
def write_headgif_prop(image: str) -> bytes:
    data = image.encode('ascii')
    return bytes([11 + 32, len(data) + 100]) + data

# PLPROP_SWORDPOWER (8) - Contains power level and image
def write_swordpower_prop(power: int, image: str) -> bytes:
    data = image.encode('ascii')
    total_length = len(data) + 1
    return bytes([8 + 32, total_length + 32, power + 30]) + data

# PLPROP_COLORS (13) - 5 color bytes
def write_colors_prop(colors: list) -> bytes:
    result = bytes([13 + 32])
    for color in colors[:5]:
        result += bytes([color + 32])
    return result
```

### Complete Player Properties Packet
```python
class PlayerPropsPacket:
    def __init__(self):
        self.properties = {}
    
    def add_property(self, prop_id: PlayerProp, value):
        self.properties[prop_id] = value
    
    def to_bytes(self) -> bytes:
        packet = bytearray([9 + 32])  # PLI_PLAYERPROPS
        
        for prop_id, value in self.properties.items():
            if prop_id in [PlayerProp.PLPROP_X, PlayerProp.PLPROP_Y, PlayerProp.PLPROP_SPRITE]:
                # Single byte properties
                packet.extend([prop_id.value + 32, int(value) + 32])
            
            elif prop_id == PlayerProp.PLPROP_NICKNAME:
                # String property
                data = str(value).encode('ascii')
                packet.extend([prop_id.value + 32, len(data) + 32])
                packet.extend(data)
            
            elif prop_id == PlayerProp.PLPROP_COLORS:
                # Color array
                packet.append(prop_id.value + 32)
                for color in value[:5]:
                    packet.append(int(color) + 32)
            
            # Add other property types as needed...
        
        packet.append(0x0A)  # Newline terminator
        return bytes(packet)
```

---

## Chat System

### Send Chat Message (PLI_TOALL = 50)
```python
class ToAllPacket:
    def __init__(self, message: str):
        self.message = message
    
    def to_bytes(self) -> bytes:
        packet = bytearray([50 + 32])  # PLI_TOALL
        packet.extend(self.message.encode('ascii'))
        packet.append(0x0A)
        return bytes(packet)
```

### Receive Chat Message (PLO_TOALL = 19)
```
[PLO_TOALL + 32 (0x33)][Player ID (2 bytes)][Message Length + 32][Message][0x0A]
```

```python
def parse_toall_packet(data: bytes) -> tuple:
    reader = PacketReader(data)
    player_id = reader.read_short()  # Player ID (2 bytes)
    message = reader.read_string_with_length()
    return player_id, message
```

### Private Messages (PLI_PRIVATEMESSAGE = 51)
```python
class PrivateMessagePacket:
    def __init__(self, target_player_id: int, message: str):
        self.target_id = target_player_id
        self.message = message
    
    def to_bytes(self) -> bytes:
        packet = bytearray([51 + 32])  # PLI_PRIVATEMESSAGE
        
        # Target player ID (2 bytes, Graal-encoded)
        packet.append((self.target_id & 0xFF) + 32)
        packet.append(((self.target_id >> 8) & 0xFF) + 32)
        
        packet.extend(self.message.encode('ascii'))
        packet.append(0x0A)
        return bytes(packet)
```

---

## Movement and Actions

### Movement Packet
```python
def move_to(x: float, y: float, direction: int):
    packet = PlayerPropsPacket()
    packet.add_property(PlayerProp.PLPROP_X, int(x * 2))  # Half-tile precision
    packet.add_property(PlayerProp.PLPROP_Y, int(y * 2))
    packet.add_property(PlayerProp.PLPROP_SPRITE, direction)
    return packet.to_bytes()
```

### Bomb Placement (PLI_BOMBADD = 53)
```python
class BombAddPacket:
    def __init__(self, x: float, y: float, power: int = 1, timer: int = 55):
        self.x = x
        self.y = y
        self.power = power
        self.timer = timer
    
    def to_bytes(self) -> bytes:
        packet = bytearray([53 + 32])  # PLI_BOMBADD
        packet.append(int(self.x * 2) + 32)
        packet.append(int(self.y * 2) + 32)
        packet.append(self.power + 32)
        packet.append(self.timer + 32)
        packet.append(0x0A)
        return bytes(packet)
```

### Arrow Shooting (PLI_ARROWADD = 54)
```python
class ArrowAddPacket:
    def to_bytes(self) -> bytes:
        packet = bytearray([54 + 32])  # PLI_ARROWADD
        packet.append(0x0A)
        return bytes(packet)
```

---

## File Transfers

### Request File (PLI_WANTFILE = 56)
```python
class WantFilePacket:
    def __init__(self, filename: str):
        self.filename = filename
    
    def to_bytes(self) -> bytes:
        packet = bytearray([56 + 32])  # PLI_WANTFILE
        packet.extend(self.filename.encode('ascii'))
        packet.append(0x0A)
        return bytes(packet)
```

### Receive File (PLO_FILE = 39)
```
[PLO_FILE + 32][Filename Length + 32][Filename][File Data]
```

---

## Complete Packet Reference

### Client to Server (PLI_* packets)

| Packet ID | Name | Description | Format |
|-----------|------|-------------|---------|
| 2 | PLI_LOGIN | Login request | See [Login Process](#login-process) |
| 9 | PLI_PLAYERPROPS | Player properties | See [Player Properties](#player-properties) |
| 50 | PLI_TOALL | Chat message | `[50+32][message][0x0A]` |
| 51 | PLI_PRIVATEMESSAGE | Private message | `[51+32][target_id][message][0x0A]` |
| 53 | PLI_BOMBADD | Place bomb | `[53+32][x][y][power][timer][0x0A]` |
| 54 | PLI_ARROWADD | Shoot arrow | `[54+32][0x0A]` |
| 55 | PLI_FIRESPY | Fire effect | `[55+32][0x0A]` |
| 56 | PLI_WANTFILE | Request file | `[56+32][filename][0x0A]` |
| 58 | PLI_FLAGSET | Set server flag | `[58+32][flag_len+32][flag][value][0x0A]` |

### Server to Client (PLO_* packets)

| Packet ID | Name | Description | Format |
|-----------|------|-------------|---------|
| 8 | PLO_OTHERPLPROPS | Other player properties | `[8+32][player_id][properties...]` |
| 14 | PLO_PLAYERWARP | Warp player | `[14+32][x][y][level][0x0A]` |
| 19 | PLO_TOALL | Chat message | `[19+32][player_id][msg_len+32][message]` |
| 25 | PLO_SIGNATURE | Login response | `[25+32][signature_byte]` |
| 39 | PLO_FILE | File data | `[39+32][filename_len+32][filename][data]` |
| 42 | PLO_NEWWORLDTIME | Heartbeat | `[42+32][time_data]` |
| 44 | PLO_HASNPCSERVER | Server capabilities | `[44+32]` |
| 47 | PLO_STAFFGUILDS | Staff guild list | `[47+32][guild_data]` |

### Packet Reading Utility
```python
class PacketReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
    
    def read_byte(self) -> int:
        """Read Graal-encoded byte"""
        if self.pos >= len(self.data):
            return 0
        value = self.data[self.pos] - 32
        self.pos += 1
        return max(0, value)
    
    def read_short(self) -> int:
        """Read 2-byte value"""
        low = self.read_byte()
        high = self.read_byte()
        return low | (high << 8)
    
    def read_string_with_length(self) -> str:
        """Read string with Graal-encoded length prefix"""
        length = self.read_byte()
        if length < 0 or length > 223:
            return ""
        return self.read_string(length)
    
    def read_string(self, length: int) -> str:
        """Read fixed-length string"""
        if self.pos + length > len(self.data):
            length = len(self.data) - self.pos
        text = self.data[self.pos:self.pos + length].decode('ascii', errors='replace')
        self.pos += length
        return text
    
    def read_gstring(self) -> str:
        """Read newline-terminated string"""
        text = ""
        while self.pos < len(self.data):
            char = self.data[self.pos]
            self.pos += 1
            if char == ord('\n'):
                break
            text += chr(char)
        return text
```

---

## Implementation Best Practices

### 1. Threading Model
```python
# Use separate threads for send/receive to prevent blocking
import threading
from queue import Queue

class RebornClient:
    def __init__(self):
        self.send_queue = Queue()
        self.receive_thread = None
        self.send_thread = None
    
    def start_threads(self):
        self.receive_thread = threading.Thread(target=self._receive_loop)
        self.send_thread = threading.Thread(target=self._send_loop)
        self.receive_thread.start()
        self.send_thread.start()
```

### 2. Error Handling
```python
def recv_encrypted_packet_data(self, packet: bytes):
    try:
        # Decrypt and decompress
        compression_type = packet[0]
        encrypted_data = packet[1:]
        
        # Create per-packet codec
        packet_codec = GraalEncryption(self.encryption_key)
        packet_codec.iterator = self.in_codec.iterator
        packet_codec.limit_from_type(compression_type)
        
        decrypted = packet_codec.decrypt(encrypted_data)
        self.in_codec.iterator = packet_codec.iterator
        
        # Decompress
        if compression_type == 0x04:  # ZLIB
            return zlib.decompress(decrypted)
        elif compression_type == 0x06:  # BZ2
            return bz2.decompress(decrypted)
        else:  # UNCOMPRESSED
            return decrypted
            
    except Exception as e:
        # Log error but don't crash - return None for failed packets
        return None
```

### 3. Packet Batching
```python
def process_received_data(self, decrypted_data: bytes):
    """Handle multiple packets in one TCP receive"""
    pos = 0
    while pos < len(decrypted_data):
        # Find packet boundary (newline)
        next_newline = decrypted_data.find(b'\n', pos)
        if next_newline == -1:
            break
        
        # Extract packet
        packet = decrypted_data[pos:next_newline]
        pos = next_newline + 1
        
        if len(packet) >= 1:
            packet_id = packet[0] - 32
            packet_data = packet[1:]
            self.handle_packet(packet_id, packet_data)
```

---

## Security Considerations

1. **Key Management**: Encryption keys are sent in plaintext during login
2. **Packet Validation**: Always validate packet sizes and data ranges
3. **Rate Limiting**: Implement delays between sent packets (100ms recommended)
4. **Input Sanitization**: Validate all string inputs for proper ASCII encoding
5. **Connection Timeouts**: Use socket timeouts to prevent hanging connections

---

## Debugging Tips

### 1. Packet Logging
```python
def log_packet(direction: str, packet_id: int, data: bytes):
    try:
        name = ServerToPlayer(packet_id).name if direction == "IN" else PlayerToServer(packet_id).name
    except:
        name = f"UNKNOWN_{packet_id}"
    
    print(f"[{direction}] {name} (ID: {packet_id}, size: {len(data)})")
    if len(data) <= 50:
        print(f"    Hex: {data.hex()}")
        print(f"    ASCII: {repr(data.decode('ascii', errors='replace'))}")
```

### 2. Encryption State Debugging
```python
def debug_encryption_state(codec: GraalEncryption, label: str):
    print(f"{label}: iterator=0x{codec.iterator:08x}, limit={codec.limit}")
```

### 3. Common Issues
- **Desynchronized encryption**: Check that limits are set correctly per packet
- **Invalid packet IDs**: Ensure proper +32 encoding/decoding
- **Broken pipe errors**: Verify login sequence completion before sending actions
- **Garbled text**: Check string length calculations and encoding

---

This guide provides a complete reference for implementing the GServer protocol. The PyReborn library serves as a working reference implementation of all these concepts.