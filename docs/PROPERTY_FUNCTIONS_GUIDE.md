# Graal Player Property Functions Guide

This guide documents all the player property functions available in `graal_debug_client.py`.

## Available Functions

### 1. set_nickname(nickname: str)
Changes the player's display name.

```python
client.set_nickname("NewName")
```

- Maximum length: 223 characters
- Can include guild tags in parentheses: "Name (Guild)"

### 2. set_chat(message: str)
Sets a chat message that appears above the player's head.

```python
client.set_chat("Hello world!")
```

- Maximum length: 223 characters
- Appears as a speech bubble above player

### 3. set_hearts(current: float, max_hearts: float = None)
Sets the player's current and optionally maximum hearts.

```python
client.set_hearts(2.5)         # Set current hearts only
client.set_hearts(2.5, 5)      # Set current and max hearts
```

- Hearts use 0.5 increments (2.5 = 2½ hearts)
- Internally stored as integers (multiplied by 2)

### 4. set_gattrib(index: int, value: str)
Sets a custom player attribute (gattrib1 through gattrib30).

```python
client.set_gattrib(1, "Custom value")
client.set_gattrib(2, "Player status: AFK")
```

- Index must be between 1 and 30
- Maximum value length: 223 characters
- These are persistent custom fields for any data

### 5. set_colors(coat: int, skin: int, belt: int, shoes: int, sleeves: int)
Changes the player's appearance colors.

```python
client.set_colors(
    coat=100,     # Red coat
    skin=200,     # Light skin  
    belt=50,      # Dark belt
    shoes=150,    # Green shoes
    sleeves=75    # Blue sleeves
)
```

- Each color value: 0-255
- Colors map to different parts of the player sprite

## Property IDs Reference

The following properties can be set using PLI_PLAYERPROPS:

| ID | Property | Type | Description |
|----|----------|------|-------------|
| 0  | NICKNAME | String | Player display name |
| 1  | MAXPOWER | Byte | Maximum hearts (×2) |
| 2  | CURPOWER | Byte | Current hearts (×2) |
| 3  | RUPEESCOUNT | Int | Money/rupees |
| 4  | ARROWSCOUNT | Byte | Arrow count |
| 5  | BOMBSCOUNT | Byte | Bomb count |
| 6  | GLOVEPOWER | Byte | Glove strength |
| 7  | BOMBPOWER | Byte | Bomb power |
| 8  | SWORDPOWER | Byte | Sword image index |
| 9  | SHIELDPOWER | Byte | Shield image index |
| 10 | GANI | String | Current animation |
| 11 | HEADGIF | String | Head image filename |
| 12 | CURCHAT | String | Chat message |
| 13 | COLORS | 5 Bytes | Player colors |
| 14 | ID | Short | Player ID (read-only) |
| 15 | X | Byte | X position |
| 16 | Y | Byte | Y position |
| 17 | SPRITE | Byte | Direction sprite |
| 18 | STATUS | Byte | Player status flags |
| 19 | CARRYSPRITE | Byte | Carrying sprite |
| 20 | CURLEVEL | String | Current level name |
| 37-66 | GATTRIB1-30 | String | Custom attributes |

## Packet Format

All property changes use the PLI_PLAYERPROPS packet:

```
[PLI_PLAYERPROPS + 32][Property1][Property2]...[Newline]
```

Each property:
```
[PropertyID + 32][Length + 32][Data]
```

## Example: Setting Multiple Properties

```python
# Connect to server
client = GraalDebugClient("localhost", 14900)
client.connect()
client.login("username", "password")

# Wait for login
time.sleep(2)

# Change multiple properties
client.set_nickname("TestBot")
client.set_chat("Hello from Python!")
client.set_hearts(3, 5)
client.set_gattrib(1, "Bot Version 1.0")
client.set_colors(255, 200, 100, 50, 0)
```

## Implementation Notes

1. **Graal Encoding**: All numeric values (packet IDs, property IDs, lengths) must have 32 added
2. **String Encoding**: Strings are sent as ASCII without the +32 offset
3. **Packet Termination**: All packets must end with a newline (`\n`)
4. **Length Limits**: Most string properties have a 223-character limit
5. **Persistence**: Some properties persist between sessions, others reset on disconnect

## Future Properties to Implement

- Sword/Shield power (equipment)
- Position (X/Y coordinates)
- Animation (GANI files)
- Head image
- Carrying sprite
- Money/items (rupees, arrows, bombs)
- Player status flags

These functions provide the foundation for creating a fully-featured Graal client that can interact with the game world and other players.