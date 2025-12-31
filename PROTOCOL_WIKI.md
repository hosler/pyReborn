# Reborn Protocol Wiki

Complete protocol reference for pyReborn - the Python client library for Reborn game servers.

## Table of Contents

1. [Overview](#overview)
2. [Data Types](#data-types)
3. [Encryption & Compression](#encryption--compression)
4. [Connection Handshake](#connection-handshake)
5. [Packet Structure](#packet-structure)
6. [Server-to-Client Packets](#server-to-client-packets)
7. [Client-to-Server Packets](#client-to-server-packets)
8. [Player Properties](#player-properties)
9. [NPC Properties](#npc-properties)
10. [Baddy Properties](#baddy-properties)
11. [Remote Control Packets](#remote-control-packets)
12. [Quick Reference](#quick-reference)

---

## Overview

The Reborn protocol uses TCP connections with custom encryption and compression. All data is framed with 2-byte length prefixes (big-endian).

**Supported Protocol Versions:**
| Version | Protocol String | Client Type |
|---------|-----------------|-------------|
| 2.22 | `GNW03014` | TYPE_CLIENT3 |
| 6.037 | `G3D0311C` | TYPE_CLIENT3 |
| 6.037 Linux | `G3D0511C` | TYPE_CLIENT3 |

**Client Types:**
| ID | Name | Description |
|----|------|-------------|
| 0 | TYPE_CLIENT | Legacy client |
| 1 | TYPE_RC | Remote Control |
| 3 | TYPE_NC | NPC Control |
| 4 | TYPE_CLIENT2 | Client v2 |
| 5 | TYPE_CLIENT3 | Modern client |
| 6 | TYPE_RC2 | Remote Control v2 |

---

## Data Types

The Reborn protocol uses custom encoding for all values. Understanding these types is critical for packet parsing.

### GCHAR (1 byte)
Single byte with +32 offset. Value range: 0-223.

```python
# Encode
encoded = value + 32

# Decode
value = byte - 32
```

### GSHORT (2 bytes)
Two bytes using 7-bit encoding with +32 offset. Value range: 0-16383.

```python
# Encode
b1 = ((value >> 7) & 0x7F) + 32
b2 = (value & 0x7F) + 32

# Decode
value = ((b1 - 32) << 7) | (b2 - 32)
```

### GINT3 (3 bytes)
Three bytes using 7-bit encoding. Value range: 0-2097151.

```python
# Encode
b1 = ((value >> 14) & 0x7F) + 32
b2 = ((value >> 7) & 0x7F) + 32
b3 = (value & 0x7F) + 32

# Decode
value = ((b1 - 32) << 14) | ((b2 - 32) << 7) | (b3 - 32)
```

### GINT4 (4 bytes)
Four bytes using 7-bit encoding. Value range: 0-268435455.

```python
# Decode
value = ((b1 - 32) << 21) | ((b2 - 32) << 14) | ((b3 - 32) << 7) | (b4 - 32)
```

### GINT5 (5 bytes)
Five bytes for large values (e.g., file modification times).

### GSTRING
Length-prefixed string: GCHAR(length) + raw bytes.

```python
# Encode
data = bytes([len(string) + 32]) + string.encode('latin-1')

# Decode
length = data[0] - 32
string = data[1:1+length].decode('latin-1')
```

### Position Encoding

**Half-Tile Precision (GCHAR):**
Position in half-tiles. 1 tile = 16 pixels.

```python
# Encode (tiles to bytes)
byte_value = int(tiles * 2) + 32

# Decode (bytes to tiles)
tiles = (byte_value - 32) / 2.0
```

**Pixel Precision (GSHORT) - Props 78/79:**
High-precision position with sign bit.

```python
# Decode PLPROP_X2/Y2
raw = ((b1 - 32) << 7) | (b2 - 32)
pixels = raw >> 1
if raw & 0x0001:  # Sign bit
    pixels = -pixels
tiles = pixels / 16.0

# Encode
pixel_value = int(tiles * 16)
if pixel_value < 0:
    raw = ((-pixel_value) << 1) | 1
else:
    raw = pixel_value << 1
b1 = ((raw >> 7) & 0x7F) + 32
b2 = (raw & 0x7F) + 32
```

---

## Encryption & Compression

### Gen5 Encryption (ENCRYPT_GEN_5)

Used for protocol versions 2.22+. Partial encryption with XOR cipher.

**Constants:**
```python
ITERATOR_START = 0x4A80B38
MULTIPLIER = 0x8088405
```

**Encryption Limits by Compression Type:**
| Compression | Limit (32-bit words) |
|-------------|---------------------|
| UNCOMPRESSED (0x02) | 12 |
| ZLIB (0x04) | 4 |
| BZ2 (0x06) | 4 |

**Algorithm:**
```python
def encrypt(data, key, iterator, limit):
    result = bytearray(data)
    bytes_to_encrypt = min(len(data), limit * 4) if limit > 0 else len(data)

    for i in range(bytes_to_encrypt):
        if i % 4 == 0:
            iterator = (iterator * MULTIPLIER + key) & 0xFFFFFFFF
        iterator_bytes = struct.pack('<I', iterator)
        result[i] ^= iterator_bytes[i % 4]

    return bytes(result)
```

### Compression

**Compression Types:**
| ID | Name | Usage |
|----|------|-------|
| 0x02 | UNCOMPRESSED | Packets <= 55 bytes |
| 0x04 | ZLIB | Packets 56-8192 bytes |
| 0x06 | BZ2 | Packets > 8192 bytes |

**Packet Format:**
```
[2 bytes: length] [1 byte: compression_type] [encrypted_data]
```

---

## Connection Handshake

### Login Packet (Special - ZLIB only, no encryption)

The login packet is sent first and uses only ZLIB compression (no encryption).

**Format:**
```
[2 bytes: length] [zlib_compressed_data]

Compressed data contains:
- client_type + 32 (1 byte)
- encryption_key + 32 (1 byte)
- protocol_string (8 bytes ASCII)
- username_length + 32 (1 byte)
- username (ASCII)
- password_length + 32 (1 byte)
- password (ASCII)
- [optional: build_length + 32, build_string]
- client_info (ASCII, e.g., "linux,,,,,pyreborn")
```

**Example:**
```python
packet = bytearray()
packet.append(client_type + 32)       # e.g., 5 + 32 = 37 for TYPE_CLIENT3
packet.append(encryption_key + 32)    # Random 0-127
packet.extend(b'G3D0311C')            # Protocol string
packet.append(len(username) + 32)
packet.extend(username.encode('ascii'))
packet.append(len(password) + 32)
packet.extend(password.encode('ascii'))
packet.extend(b'linux,,,,,pyreborn')

compressed = zlib.compress(bytes(packet))
send([len(compressed) as 2 bytes BE] + compressed)
```

### Server Response

The first server response is ZLIB compressed but NOT encrypted.
All subsequent packets use encryption.

---

## Packet Structure

### Sending Packets

```
[2 bytes: total_length (BE)] [1 byte: compression_type] [encrypted_payload]

Payload (before encryption):
[packet_id + 32] [data...] [0x0A newline]
```

### Receiving Packets

```
[2 bytes: length (BE)] [compressed/encrypted data]
```

After decryption/decompression, data contains newline-delimited packets:
```
[packet_id + 32] [data...] \n
[packet_id + 32] [data...] \n
...
```

### Raw Data Mode (PLO_RAWDATA)

When PLO_RAWDATA (100) is received, the next N bytes are NOT newline-delimited.

```python
# PLO_RAWDATA format: GINT3(size)
size = ((b1 - 32) << 14) | ((b2 - 32) << 7) | (b3 - 32)
# Next 'size' bytes are a raw packet (includes packet_id + 32 prefix)
```

---

## Server-to-Client Packets

### PLO_LEVELBOARD (0)
Level metadata (compressed format).

### PLO_LEVELLINK (1)
Level warp/door definition.

**Format:** `destLevel x y width height newX newY` (space-separated ASCII)

```python
# Example: "cave.nw 10 20 2 2 30 30"
{
    'dest_level': 'cave.nw',
    'x': 10, 'y': 20,
    'width': 2, 'height': 2,
    'dest_x': '30', 'dest_y': '30'
}
```

### PLO_BADDYPROPS (2)
Baddy/enemy properties.

**Format:** `GCHAR(baddy_id) [prop_id data]...`

### PLO_NPCPROPS (3)
NPC properties update.

**Format:** `GINT3(npc_id) [prop_id data]...`

### PLO_PLAYERLEFT (4)
Player left the level.

**Format:** `GSHORT(player_id)`

### PLO_LEVELSIGN (5)
Level sign text content.

### PLO_LEVELNAME (6)
Current level name.

**Format:** ASCII string (e.g., `level.nw` or `world.gmap`)

### PLO_OTHERPLPROPS (8)
Other player's properties (movement, appearance).

**Format:** `GSHORT(player_id) [prop_id data]...`

### PLO_PLAYERPROPS (9)
Your player's properties.

**Format:** `[prop_id data]...`

### PLO_TOALL (13)
Chat message OR movement update (check first prop to distinguish).

**Chat Format:** `GSHORT(player_id) GCHAR(msg_len-1) message[1:]`

### PLO_PLAYERWARP (14)
Player warp confirmation (non-GMAP).

**Format:** `GCHAR(x*2) GCHAR(y*2) level_name`

### PLO_ITEMADD (22)
Item spawned on ground.

**Format:** `GCHAR(x*2) GCHAR(y*2) GSTRING(item_type)`

### PLO_ITEMDEL (23)
Item removed from ground.

**Format:** `GCHAR(x*2) GCHAR(y*2)`

### PLO_NPCDEL (29)
NPC deleted.

**Format:** `GINT3(npc_id)`

### PLO_SHOWIMG (32)
Show image / level chat display.

### PLO_NPCWEAPONADD (33)
Weapon added to player.

**Format:** `+weaponname imagename!<script`

### PLO_RC_ADMINMESSAGE (35)
Admin broadcast message.

**Format:** `Admin accountname:` + 0xA7 + `message`

### PLO_EXPLOSION (36)
Explosion effect at location.

### PLO_PRIVATEMESSAGE (37)
Private message received.

**Format:** `SHORT(sender_id BE) "","type:",message`

### PLO_HURTPLAYER (40)
Player took damage notification.

**Format:** `GSHORT(attacker_id) GCHAR(damage*2) GCHAR(type) GCHAR(src_x) GCHAR(src_y)`

| Damage Type | Description |
|-------------|-------------|
| 0 | Sword |
| 1 | Bomb |
| 2 | Arrow |
| 3 | Fire |

### PLO_NEWWORLDTIME (42)
Server heartbeat / time sync.

**Format:** 4 raw bytes (little-endian time value)

### PLO_HITOBJECTS (46)
Objects hit notification.

### PLO_PLAYERWARP2 (49)
Player warp with GMAP grid position.

**Format:** `GCHAR(x*2) GCHAR(y*2) GCHAR(z) GCHAR(gmap_x) GCHAR(gmap_y) level_name`

### PLO_RAWDATA (100)
Announces upcoming raw data bytes.

**Format:** `GINT3(byte_count)`

### PLO_BOARDPACKET (101)
Level tile data (raw 8192 bytes = 64x64 tiles @ 2 bytes each).

**Tile Format:** Little-endian 16-bit, masked to 12-bit (& 0xFFF).

```python
tiles = []
for i in range(0, 8192, 2):
    tile_id = data[i] + (data[i+1] << 8)
    tiles.append(tile_id & 0xFFF)
```

### PLO_FILE (102)
File transfer data.

**Format:** `GCHAR5(mod_time) GCHAR(filename_len) filename file_data`

### PLO_FILESENDFAILED (104)
File request failed.

**Format:** `filename` (ASCII)

---

## Client-to-Server Packets

### PLI_LEVELWARP (0)
Request warp to level.

**Format:** `GCHAR(x*2) GCHAR(y*2) level_name`

### PLI_PLAYERPROPS (2)
Send player properties update.

**Format:** `[prop_id + 32] [value]...`

Common props to send:
- 17: Direction/sprite
- 15/16: X/Y position (half-tiles)
- 78/79: X/Y position (pixels)
- 10: Animation name
- 2: Current hearts
- 12: Chat text (level chat)
- 20: Current level name

### PLI_NPCPROPS (3)
Update NPC properties (gani attrs).

**Format:** `GINT4(npc_id) GCHAR(prop_id) GCHAR(len) value`

### PLI_TOALL (6)
Send chat message.

**Format:** `message` (raw ASCII)

### PLI_HORSEADD (7)
Mount/add horse.

**Format:** `GCHAR(x*2) GCHAR(y*2) GCHAR(dir|bush) image_name`

### PLI_ARROWADD (9)
Add arrow to level.

### PLI_BADDYHURT (16)
Damage a baddy.

**Format:** `GCHAR(baddy_id) GCHAR(damage*2)`

### PLI_FLAGSET (18)
Set player flag.

**Format:** `flagname` or `flagname=value` (ASCII)

### PLI_FLAGDEL (19)
Delete player flag.

**Format:** `flagname` (ASCII)

### PLI_OPENCHEST (20)
Open chest at position.

**Format:** `GCHAR(x*2) GCHAR(y*2)`

### PLI_WANTFILE (23)
Request file download.

**Format:** `filename` (ASCII)

### PLI_SHOWIMG (24)
Show image / local chat.

### PLI_HURTPLAYER (26)
Attack another player.

**Format:** `GSHORT(victim_id) GCHAR(dx) GCHAR(dy) GCHAR(damage*2) GINT4(npc_id)`

### PLI_EXPLOSION (27)
Create bomb explosion.

**Format:** `GCHAR(x*2) GCHAR(y*2) GCHAR(power)`

### PLI_PRIVATEMESSAGE (28)
Send private message.

**Format:** `GSHORT(count) [GSHORT(player_id)]... message`

### PLI_ITEMTAKE (32)
Pick up item.

**Format:** `GCHAR(x*2) GCHAR(y*2)`

### PLI_ADJACENTLEVEL (35)
Request adjacent GMAP level data.

**Format:** `GINT5(modtime) level_name`

### PLI_HITOBJECTS (36)
Report hit objects.

### PLI_TRIGGERACTION (38)
Trigger server-side action.

**Format:** `GINT4(npc_id) GCHAR(x*2) GCHAR(y*2) action_string`

### PLI_SHOOT (40)
Shoot projectile (old format).

### PLI_LANGUAGE (44)
Set client language.

### PLI_SHOOT2 (48)
Shoot projectile (v5.07+ format).

**Format:**
```
GSHORT(pixel_x) GSHORT(pixel_y) GSHORT(pixel_z)
GCHAR(offset_x) GCHAR(offset_y)
GCHAR(angle) GCHAR(z_angle)
GCHAR(speed) GCHAR(gravity)
GSHORT(gani_len) gani_name
GCHAR(params_len) params
```

---

## Player Properties

Property IDs used in PLO_PLAYERPROPS, PLO_OTHERPLPROPS, and PLI_PLAYERPROPS.

### Basic Properties

| ID | Name | Size | Description |
|----|------|------|-------------|
| 0 | NICKNAME | string | Player display name |
| 1 | MAXPOWER | 1 byte | Max hearts * 2 |
| 2 | CURPOWER | 1 byte | Current hearts * 2 |
| 3 | RUPEESCOUNT | 3 bytes | Rupee count (GINT3) |
| 4 | ARROWSCOUNT | 1 byte | Arrow count |
| 5 | BOMBSCOUNT | 1 byte | Bomb count |
| 6 | GLOVEPOWER | 1 byte | Glove power level |
| 7 | BOMBPOWER | 1 byte | Bomb power level |
| 8 | SWORDPOWER | 1+ bytes | Sword power (see below) |
| 9 | SHIELDPOWER | 1+ bytes | Shield power (see below) |
| 10 | GANI | string | Current animation |
| 11 | HEADGIF | string | Head image (special encoding) |
| 12 | CURCHAT | string | Chat bubble text |
| 13 | COLORS | 5 bytes | Player colors (skin, coat, etc.) |
| 14 | ID | 2 bytes | Direction (legacy) |
| 15 | X | 1 byte | X position (half-tiles) |
| 16 | Y | 1 byte | Y position (half-tiles) |
| 17 | SPRITE | 1 byte | Direction in lower 2 bits |
| 18 | STATUS | 1 byte | Player status flags |
| 19 | CARRYSPRITE | 1 byte | Carried item sprite |
| 20 | CURLEVEL | string | Current level name |
| 21 | HORSEGIF | string | Horse image |
| 22 | HORSEBUSHES | 1 byte | Horse bush hiding |
| 23 | EFFECTCOLORS | 4 bytes | RGBA effect color |
| 24 | CARRYNPC | 4 bytes | Carried NPC ID (GINT4) |
| 34 | ACCOUNTNAME | string | Account name |
| 35 | BODYIMG | string | Body image |

### Sword/Shield Power Encoding

**Sword (prop 8):**
- Value 0-4: Built-in sword (power = value)
- Value > 4: Custom sword (power = value - 30, followed by image string)

**Shield (prop 9):**
- Value 0-3: Built-in shield (power = value)
- Value > 3: Custom shield (power = value - 10, followed by image string)

### Head Image Encoding (prop 11)

```python
# Decode
len_val = byte - 32
if len_val >= 100:
    actual_len = len_val - 100
    head_image = read_string(actual_len)
```

### High-Precision Position

| ID | Name | Size | Description |
|----|------|------|-------------|
| 75 | OSTYPE | string | Operating system type |
| 76 | TEXTCODEPAGE | 3 bytes | Text codepage (GINT3) |
| 78 | X2 | 2 bytes | X in pixels / 16 (signed) |
| 79 | Y2 | 2 bytes | Y in pixels / 16 (signed) |
| 80 | Z2 | 2 bytes | Z in pixels / 16 |

### GATTRIB Properties (36-74)

GATTRIBs are custom string attributes for scripting:

| ID | Name |
|----|------|
| 36 | GATTRIB1 |
| 37 | GATTRIB2 |
| ... | ... |
| 74 | GATTRIB30 |

---

## NPC Properties

Used in PLO_NPCPROPS packets. Format: `GINT3(npc_id) [props...]`

| ID | Name | Size | Description |
|----|------|------|-------------|
| 0 | IMAGE | string | NPC image file |
| 1 | SCRIPT | GSHORT(len) + string | NPC script |
| 2 | X | 1 byte | X position (half-tiles) |
| 3 | Y | 1 byte | Y position (half-tiles) |
| 5 | DIR | 1 byte | Direction |
| 75 | OSTYPE | string | OS type |
| 76 | CODEPAGE | 3 bytes | Text codepage |

### NPC GATTRIB Mapping (for PLI_NPCPROPS)

| Script Name | Prop ID |
|-------------|---------|
| P1 | 36 |
| P2 | 37 |
| P3 | 38 |
| P4 | 39 |
| P5 | 40 |
| P6 | 44 |
| P7 | 45 |
| P8 | 46 |
| P9 | 47 |
| P10-P30 | 53-73 |

---

## Baddy Properties

Used in PLO_BADDYPROPS packets. Format: `GCHAR(baddy_id) [props...]`

| ID | Name | Size | Description |
|----|------|------|-------------|
| 1 | X | 1 byte | X position (half-tiles) |
| 2 | Y | 1 byte | Y position (half-tiles) |
| 3 | TYPE | 1 byte | Baddy type ID |
| 4 | POWER | 1 byte | Remaining health |
| 5 | DIR | 1 byte | Direction |
| 6 | IMAGE | string | Custom image |
| 7 | ANI | string | Animation name |

---

## Remote Control Packets

RC (Remote Control) packets for server administration.

### Server to RC Client

| ID | Name | Description |
|----|------|-------------|
| 61 | PLO_RC_SERVERFLAGSGET | Server flags list |
| 62 | PLO_RC_PLAYERRIGHTSGET | Player rights |
| 63 | PLO_RC_PLAYERCOMMENTSGET | Player comments |
| 64 | PLO_RC_PLAYERBANGET | Ban status |
| 65 | PLO_RC_FILEBROWSER_DIRLIST | Directory listing |
| 66 | PLO_RC_FILEBROWSER_DIR | Directory contents |
| 67 | PLO_RC_FILEBROWSER_MESSAGE | File operation result |
| 70 | PLO_RC_ACCOUNTLISTGET | Account list |
| 72 | PLO_RC_PLAYERPROPSGET | Player properties |
| 73 | PLO_RC_ACCOUNTGET | Account details |
| 74 | PLO_RC_CHAT | RC chat message |
| 76 | PLO_RC_SERVEROPTIONSGET | Server options |
| 77 | PLO_RC_FOLDERCONFIGGET | Folder config |
| 103 | PLO_RC_MAXUPLOADFILESIZE | Max upload size |

### RC Client to Server

| ID | Name | Description |
|----|------|-------------|
| 51 | PLI_RC_SERVEROPTIONSGET | Get server config |
| 52 | PLI_RC_SERVEROPTIONSSET | Set server config |
| 53 | PLI_RC_FOLDERCONFIGGET | Get folder config |
| 59 | PLI_RC_PLAYERPROPSGET | Get player props |
| 61 | PLI_RC_DISCONNECTPLAYER | Kick player |
| 62 | PLI_RC_UPDATELEVELS | Reload levels |
| 63 | PLI_RC_ADMINMESSAGE | Broadcast message |
| 64 | PLI_RC_PRIVADMINMESSAGE | Private admin message |
| 68 | PLI_RC_SERVERFLAGSGET | Get server flags |
| 70 | PLI_RC_ACCOUNTADD | Create account |
| 71 | PLI_RC_ACCOUNTDEL | Delete account |
| 72 | PLI_RC_ACCOUNTLISTGET | Get account list |
| 77 | PLI_RC_ACCOUNTGET | Get account details |
| 79 | PLI_RC_CHAT | Send RC chat |
| 82 | PLI_RC_WARPPLAYER | Warp player |
| 83 | PLI_RC_PLAYERRIGHTSGET | Get player rights |
| 85 | PLI_RC_PLAYERCOMMENTSGET | Get player comments |
| 87 | PLI_RC_PLAYERBANGET | Get ban status |
| 88 | PLI_RC_PLAYERBANSET | Set ban |
| 89 | PLI_RC_FILEBROWSER_START | Start file browser |
| 90 | PLI_RC_FILEBROWSER_CD | Change directory |
| 91 | PLI_RC_FILEBROWSER_END | End file browser |
| 92 | PLI_RC_FILEBROWSER_DOWN | Download file |
| 97 | PLI_RC_FILEBROWSER_DELETE | Delete file |
| 98 | PLI_RC_FILEBROWSER_RENAME | Rename file |

---

## Quick Reference

### Packet ID Quick Reference

#### Server to Client (PLO_*)

| ID | Name | Brief |
|----|------|-------|
| 0 | LEVELBOARD | Level metadata |
| 1 | LEVELLINK | Warp definitions |
| 2 | BADDYPROPS | Enemy data |
| 3 | NPCPROPS | NPC data |
| 4 | PLAYERLEFT | Player departed |
| 5 | LEVELSIGN | Sign text |
| 6 | LEVELNAME | Level filename |
| 8 | OTHERPLPROPS | Other player data |
| 9 | PLAYERPROPS | Your player data |
| 13 | TOALL | Chat/movement |
| 14 | PLAYERWARP | Warp (non-GMAP) |
| 22 | ITEMADD | Item spawned |
| 23 | ITEMDEL | Item removed |
| 29 | NPCDEL | NPC removed |
| 32 | SHOWIMG | Image/chat display |
| 33 | NPCWEAPONADD | Weapon received |
| 37 | PRIVATEMESSAGE | PM received |
| 40 | HURTPLAYER | Damage notification |
| 42 | NEWWORLDTIME | Heartbeat |
| 49 | PLAYERWARP2 | GMAP warp |
| 100 | RAWDATA | Raw data size |
| 101 | BOARDPACKET | Tile data |
| 102 | FILE | File data |
| 104 | FILESENDFAILED | File error |

#### Client to Server (PLI_*)

| ID | Name | Brief |
|----|------|-------|
| 0 | LEVELWARP | Request warp |
| 2 | PLAYERPROPS | Send props |
| 3 | NPCPROPS | Update NPC |
| 6 | TOALL | Send chat |
| 7 | HORSEADD | Mount horse |
| 16 | BADDYHURT | Attack enemy |
| 18 | FLAGSET | Set flag |
| 19 | FLAGDEL | Delete flag |
| 20 | OPENCHEST | Open chest |
| 23 | WANTFILE | Request file |
| 26 | HURTPLAYER | Attack player |
| 27 | EXPLOSION | Create bomb |
| 28 | PRIVATEMESSAGE | Send PM |
| 32 | ITEMTAKE | Pickup item |
| 35 | ADJACENTLEVEL | Request level |
| 38 | TRIGGERACTION | Trigger action |
| 48 | SHOOT2 | Shoot projectile |

### Common Patterns

**Move Player:**
```python
# Props: sprite(17) + X2(78) + Y2(79)
packet = bytes([
    17 + 32, direction + 32,  # Direction
    78 + 32, x_hi, x_lo,      # X position
    79 + 32, y_hi, y_lo       # Y position
])
send_packet(2, packet)  # PLI_PLAYERPROPS
```

**Send Chat:**
```python
send_packet(6, message.encode('latin-1'))  # PLI_TOALL
```

**Attack Player:**
```python
# PLI_HURTPLAYER: victim_id(gshort) + dx + dy + damage + npc_id(gint4)
packet = bytes([
    (victim_id >> 7) + 32, (victim_id & 0x7F) + 32,
    dx + 32, dy + 32,
    int(damage * 2) + 32,
    32, 32, 32, 32  # npc_id = 0
])
send_packet(26, packet)
```

**Request File:**
```python
send_packet(23, filename.encode('latin-1'))  # PLI_WANTFILE
```

### Direction Values

| Value | Direction |
|-------|-----------|
| 0 | Up |
| 1 | Left |
| 2 | Down |
| 3 | Right |

### GMAP Coordinate System

```
World coordinates = Local coordinates + (Grid position * 64)

Local: 0-63 within a level segment
World: Continuous across entire GMAP

Grid X = floor(world_x / 64)
Grid Y = floor(world_y / 64)
Local X = world_x % 64
Local Y = world_y % 64
```

---

## Python Examples

### Connect and Login

```python
from pyreborn import Client

client = Client("localhost", 14900, version="6.037")
client.connect()
client.login("username", "password")
```

### Movement Loop

```python
while client.connected:
    client.update()  # Process incoming packets

    # Move right
    client.move(1, 0)
    time.sleep(0.016)
```

### Custom Packet Handler

```python
def on_custom_packet(data):
    print(f"Received: {data.hex()}")

client.on_packet[42] = on_custom_packet  # PLO_NEWWORLDTIME
```

### Send Raw Packet

```python
from pyreborn.packets import PacketID

# Build custom packet
data = bytes([...])
client._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)
```

---

*This documentation covers pyReborn protocol implementation. For server-specific behaviors, refer to your server's documentation.*
