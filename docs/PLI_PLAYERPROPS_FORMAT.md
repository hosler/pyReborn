# PLI_PLAYERPROPS Packet Format Analysis

## Issue Summary
The server was receiving truncated PLI_PLAYERPROPS packets showing only "02 00" in the logs, missing the actual property data.

## Root Cause
The encryption implementation in the Python client had a bug where it would stop encrypting data entirely when the encryption limit reached 0, instead of just stopping the iterator updates.

### Incorrect Implementation
```python
if self.limit == 0:
    break  # This stops encrypting entirely!
```

### Correct Implementation (from server C++ code)
```cpp
if (m_limit == 0) return;  // In C++, this is inside the encryption loop
```

The correct behavior is:
1. When limit reaches 0, stop updating the iterator
2. Continue applying XOR encryption to all remaining bytes using the last iterator value

## PLI_PLAYERPROPS Packet Format

### Basic Structure
```
[PLI_PLAYERPROPS (1 byte)][Properties...][Newline terminator]
```

### Property Format
Each property in the packet follows this structure:
```
[Property ID + 32 (1 byte)][Property-specific data...]
```
- Property IDs use +32 encoding (readGUChar/writeGChar)

### Common Property Formats

#### PLPROP_NICKNAME (ID: 0)
```
[0x00 + 32][Length + 32 (1 byte)][Nickname string (ASCII)]
```
- Property ID uses +32 encoding (0 + 32 = 32 = 0x20)
- Length uses +32 encoding
- Maximum nickname length: 223 characters

#### PLPROP_HEADGIF (ID: 11)
```
[0x0B + 32][Length + 100 (1 byte)][Head image filename]
```
- Property ID uses +32 encoding (11 + 32 = 43 = 0x2B)
- Length is encoded as actual_length + 100

#### PLPROP_SWORDPOWER (ID: 8)
```
[0x08 + 32][Power + 30 (1 byte)][Length + 32 (1 byte)][Sword image filename]
```
- Property ID uses +32 encoding (8 + 32 = 40 = 0x28)
- Power is encoded as actual_power + 30
- Length uses +32 encoding

#### PLPROP_COLORS (ID: 13)
```
[0x0D + 32][Color0 + 32][Color1 + 32][Color2 + 32][Color3 + 32][Color4 + 32]
```
- Property ID uses +32 encoding (13 + 32 = 45 = 0x2D)
- 5 color bytes for skin, coat, sleeves, shoes, belt (each with +32 encoding)

### Multiple Properties
You can send multiple properties in a single PLI_PLAYERPROPS packet:
```
[PLI_PLAYERPROPS][Prop1 ID][Prop1 Data][Prop2 ID][Prop2 Data]...[Newline]
```

### Example: Nickname Change Packet
For nickname "TestNick123":
```
22 20 2B 54 65 73 74 4E 69 63 6B 31 32 33 0A
|  |  |  |----------------------------------------|  |
|  |  |  |          "TestNick123"                 |  |
|  |  |  Length (11 + 32 = 43 = 0x2B)             |  |
|  |  PLPROP_NICKNAME (0 + 32 = 32 = 0x20)        |  |
|  PLI_PLAYERPROPS (2 + 32 = 34 = 0x22)           Newline
```

## Encryption Details

### GEN_5 Encryption Process
1. Set encryption limit based on compression type:
   - UNCOMPRESSED: limit = 12
   - ZLIB/BZ2: limit = 4

2. For each byte in the data:
   - Every 4th byte: Update iterator (if limit > 0)
   - XOR byte with iterator bytes[i % 4]

3. Important: Continue XORing all bytes even after limit reaches 0

### Packet Construction Flow
1. Build packet data with properties
2. Add newline terminator
3. Apply compression (if needed)
4. Apply encryption
5. Prepend compression type byte (unencrypted)
6. Send with 2-byte length header (big-endian)

## Server Processing
The server's `msgPLI_PLAYERPROPS` function:
1. Receives the packet after decryption
2. Calls `setProps(pPacket, PLSETPROPS_SETBYPLAYER | PLSETPROPS_FORWARD)`
3. The `setProps` function parses properties in a loop
4. Each property is validated and applied
5. Changes are forwarded to other players as needed

## Common Issues
1. **Missing newline terminator**: PLI packets must end with '\n'
2. **Incorrect length encoding**: Property lengths are usually raw values (not +32)
3. **Encryption limit bug**: Must continue encrypting all bytes
4. **Property order**: Some properties may need to be sent in specific order
5. **Validation**: Server validates nicknames, filters bad words, checks lengths

## Testing
To test nickname changes:
1. Connect and login
2. Wait for initial packets to complete
3. Send PLI_PLAYERPROPS with PLPROP_NICKNAME
4. Server should accept and forward the change
5. Other players receive PLO_OTHERPLPROPS with the update