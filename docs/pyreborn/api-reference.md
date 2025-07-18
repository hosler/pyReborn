# PyReborn API Reference

Complete API documentation for the PyReborn library.

## Core Classes

### RebornClient

The main client class that provides the primary interface to Graal Reborn servers.

```python
from pyreborn import RebornClient

client = RebornClient(host: str, port: int, version: str = "2.1")
```

#### Constructor Parameters
- `host` (str): Server hostname or IP address
- `port` (int): Server port number  
- `version` (str): Client version string (default: "2.1")

#### Connection Methods

##### `connect() -> bool`
Establishes connection to the server.

**Returns**: `True` if connection successful, `False` otherwise

**Example**:
```python
if client.connect():
    print("Connected successfully!")
```

##### `disconnect() -> None`
Cleanly disconnects from the server.

**Example**:
```python
client.disconnect()
```

##### `login(username: str, password: str) -> bool`
Authenticates with the server.

**Parameters**:
- `username` (str): Account username
- `password` (str): Account password

**Returns**: `True` if login successful, `False` otherwise

**Example**:
```python
if client.login("myuser", "mypass"):
    print("Logged in successfully!")
```

#### Player Actions

##### `move_to(x: float, y: float) -> None`
Moves the player to the specified coordinates.

**Parameters**:
- `x` (float): Target X coordinate
- `y` (float): Target Y coordinate

**Example**:
```python
client.move_to(30.5, 25.0)
```

##### `set_chat(message: str) -> None`
Sets the player's chat bubble text.

**Parameters**:
- `message` (str): Chat message to display

**Example**:
```python
client.set_chat("Hello, world!")
```

##### `set_nickname(nickname: str) -> None`
Changes the player's display name.

**Parameters**:
- `nickname` (str): New nickname (max 223 characters)

**Example**:
```python
client.set_nickname("CoolPlayer")
```

##### `say(message: str) -> None`
Sends a chat message to all players on the current level.

**Parameters**:
- `message` (str): Message to send

**Example**:
```python
client.say("Hi everyone!")
```

##### `private_message(player_id: int, message: str) -> None`
Sends a private message to a specific player.

**Parameters**:
- `player_id` (int): Target player's ID
- `message` (str): Private message text

**Example**:
```python
client.private_message(1234, "Secret message")
```

#### Combat Actions

##### `set_sword_power(power: int) -> None`
Sets the player's sword power level.

**Parameters**:
- `power` (int): Sword power (0-4)

**Example**:
```python
client.set_sword_power(3)
```

##### `set_shield_power(power: int) -> None`
Sets the player's shield power level.

**Parameters**:
- `power` (int): Shield power (0-3)

**Example**:
```python
client.set_shield_power(2)
```

#### Appearance Actions

##### `set_colors(colors: List[int]) -> None`
Sets the player's color palette.

**Parameters**:
- `colors` (List[int]): List of 5 color values (0-31)

**Example**:
```python
client.set_colors([10, 15, 5, 20, 8])
```

##### `set_sprite(sprite_name: str) -> None`
Changes the player's sprite.

**Parameters**:
- `sprite_name` (str): Name of the sprite

**Example**:
```python
client.set_sprite("knight")
```

#### Properties

##### `player` (Player)
The current player object containing position, stats, and appearance data.

**Example**:
```python
print(f"Player at ({client.player.x}, {client.player.y})")
```

##### `level_manager` (LevelManager)
Manager for level data and navigation.

**Example**:
```python
current_level = client.level_manager.get_current_level()
tiles = current_level.get_board_tiles_array()
```

##### `events` (EventManager)
Event system for subscribing to game events.

**Example**:
```python
def on_player_moved(event):
    player = event.get('player')
    print(f"{player.name} moved")

client.events.subscribe('player_moved', on_player_moved)
```

---

## Event System

### EventManager

Manages event subscriptions and notifications using a publisher-subscriber pattern.

#### `subscribe(event_type: str, handler: Callable) -> None`
Subscribe to an event type.

**Parameters**:
- `event_type` (str): Event type name (see EventType enum)
- `handler` (Callable): Function to call when event occurs

**Example**:
```python
def handle_chat(event):
    message = event.get('message')
    player_name = event.get('player_name', 'Unknown')
    print(f"{player_name}: {message}")

client.events.subscribe('chat_message', handle_chat)
```

#### `unsubscribe(event_type: str, handler: Callable) -> None`
Remove an event subscription.

**Example**:
```python
client.events.unsubscribe('chat_message', handle_chat)
```

### Event Types

#### Connection Events
- `CONNECTED` - Successfully connected to server
- `DISCONNECTED` - Disconnected from server  
- `LOGIN_SUCCESS` - Successfully authenticated
- `LOGIN_FAILED` - Authentication failed

#### Player Events
- `PLAYER_UPDATE` - Player properties changed
- `PLAYER_MOVED` - Player position changed
- `PLAYER_WARP` - Player warped to new level
- `STATS_UPDATE` - Player stats (health, magic, etc.) changed
- `PLAYER_HURT` - Player took damage
- `PLAYER_ADDED` - New player entered level
- `PLAYER_REMOVED` - Player left level

#### Level Events  
- `LEVEL_ENTERED` - Entered a new level
- `LEVEL_BOARD_LOADED` - Level board data loaded
- `TILES_UPDATED` - Level tiles changed
- `LEVEL_NPCS_LOADED` - NPCs loaded for level
- `LEVEL_ITEMS_LOADED` - Items loaded for level

#### Chat Events
- `CHAT_MESSAGE` - Public chat message received
- `PRIVATE_MESSAGE` - Private message received
- `SERVER_MESSAGE` - Server announcement

#### Combat Events
- `EXPLOSION_CREATED` - Explosion effect created
- `PROJECTILE_CREATED` - Projectile (arrow, etc.) fired

#### Item Events
- `ITEM_ADDED` - Item appeared on level
- `ITEM_REMOVED` - Item removed from level
- `CHEST_OPENED` - Chest was opened

**Event Data Structure**:
```python
{
    'type': 'event_type_name',
    'timestamp': float,
    # Event-specific data fields
    'player': Player,      # For player events
    'message': str,        # For chat events  
    'level': Level,        # For level events
    # ... other fields depending on event type
}
```

---

## Data Models

### Player

Represents a player in the game world.

#### Properties
- `id` (int): Unique player identifier
- `name` (str): Player's nickname
- `x` (float): X coordinate position
- `y` (float): Y coordinate position  
- `direction` (int): Facing direction (0-3)
- `status` (int): Player status flags
- `level_name` (str): Current level name
- `health` (float): Health points
- `magic` (float): Magic points  
- `ap` (int): Alignment points
- `colors` (List[int]): Color palette
- `sprite` (str): Current sprite name
- `sword_power` (int): Sword power level
- `shield_power` (int): Shield power level

**Example**:
```python
player = client.player
print(f"{player.name} at ({player.x}, {player.y}) on {player.level_name}")
print(f"Health: {player.health}, Magic: {player.magic}")
```

### Level  

Represents a game level/map.

#### Properties
- `name` (str): Level filename
- `nickname` (str): Level display name
- `width` (int): Level width (usually 64)
- `height` (int): Level height (usually 64)
- `board_data` (bytes): Raw board data (8192 bytes)
- `npcs` (List[NPC]): NPCs on this level
- `items` (List[Item]): Items on this level
- `chests` (List[Chest]): Chests on this level
- `signs` (List[Sign]): Signs on this level
- `links` (List[Link]): Level links/warps

#### Methods

##### `get_board_tiles_array() -> List[int]`
Returns the level tiles as a flat 4096-element array.

**Returns**: List of tile IDs (0-65535)

**Example**:
```python
level = client.level_manager.get_current_level()
tiles = level.get_board_tiles_array()
tile_at_center = tiles[32 * 64 + 32]  # Tile at (32, 32)
```

##### `get_board_tiles_2d() -> List[List[int]]`
Returns the level tiles as a 64x64 2D array.

**Returns**: 2D list of tile IDs

**Example**:
```python
tiles_2d = level.get_board_tiles_2d()
tile_at_center = tiles_2d[32][32]  # Tile at (32, 32)
```

##### `tile_to_tileset_coords(tile_id: int) -> Tuple[int, int, int, int]`
Converts a tile ID to tileset coordinates.

**Parameters**:
- `tile_id` (int): Tile ID from board data

**Returns**: Tuple of (tileset_x, tileset_y, pixel_x, pixel_y)

**Example**:
```python
tx, ty, px, py = level.tile_to_tileset_coords(1234)
print(f"Tile 1234 is at tileset ({tx}, {ty}), pixel ({px}, {py})")
```

---

## Managers

### LevelManager

Manages level data, caching, and navigation.

#### `get_current_level() -> Optional[Level]`
Returns the currently loaded level.

**Example**:
```python
level = client.level_manager.get_current_level()
if level:
    print(f"Current level: {level.nickname}")
```

#### `get_level(level_name: str) -> Optional[Level]`
Returns a specific level by name.

**Parameters**:
- `level_name` (str): Level filename

**Example**:
```python
level = client.level_manager.get_level("overworld.graal")
```

#### `download_level(level_name: str) -> bool`
Downloads level data from the server.

**Parameters**:
- `level_name` (str): Level filename to download

**Returns**: `True` if download successful

**Example**:
```python
success = client.level_manager.download_level("newlevel.graal")
```

### SessionManager

Manages conversation context and session state.

#### `get_conversation(npc_id: int) -> Optional[Dict]`
Gets conversation state with an NPC.

**Parameters**:
- `npc_id` (int): NPC identifier

**Returns**: Dictionary with conversation data or None

### ItemManager

Manages item drops, pickup, and inventory.

#### `get_items_on_level() -> List[Item]`
Returns all items currently on the level.

**Example**:
```python
items = client.item_manager.get_items_on_level()
for item in items:
    print(f"Item {item.name} at ({item.x}, {item.y})")
```

---

## Utilities

### TileMapping

Utility functions for tile coordinate conversion and collision detection.

#### `tile_to_tileset_coords(tile_id: int) -> Tuple[int, int, int, int]`
Static method for converting tile IDs to tileset coordinates.

**Parameters**:
- `tile_id` (int): Tile ID (0-65535)

**Returns**: Tuple of (tileset_x, tileset_y, pixel_x, pixel_y)

**Example**:
```python
from pyreborn import TileMapping

tx, ty, px, py = TileMapping.tile_to_tileset_coords(1234)
```

#### `is_tile_blocking(tile_id: int) -> bool`
Checks if a tile blocks player movement.

**Parameters**:
- `tile_id` (int): Tile ID to check

**Returns**: `True` if tile blocks movement

**Example**:
```python
if TileMapping.is_tile_blocking(tile_id):
    print("Can't walk through this tile")
```

---

## Server List

### ServerListClient

Client for discovering available servers.

```python
from pyreborn import ServerListClient

sl_client = ServerListClient(host="listserver.graal.in", port=14922)
```

#### `connect() -> bool`
Connects to the server list.

#### `request_server_list(username: str, password: str) -> None`
Requests the list of available servers.

#### `servers` (List[ServerInfo])
List of discovered servers.

**Example**:
```python
sl_client = ServerListClient()
if sl_client.connect():
    sl_client.request_server_list("username", "password")
    for server in sl_client.servers:
        print(f"{server.name} - {server.ip}:{server.port}")
```

---

## Exception Handling

### PyReborn Exceptions

#### `ConnectionError`
Raised when connection to server fails.

#### `AuthenticationError`  
Raised when login credentials are invalid.

#### `ProtocolError`
Raised when protocol communication fails.

**Example**:
```python
from pyreborn import RebornClient, AuthenticationError

try:
    client = RebornClient("localhost", 14900)
    client.connect()
    client.login("user", "wrongpass")
except AuthenticationError:
    print("Invalid credentials!")
```

---

## Advanced Usage

### Custom Packet Handlers

```python
def custom_packet_handler(packet_data):
    print(f"Received custom packet: {packet_data}")

client.packet_handler.add_handler(255, custom_packet_handler)
```

### Event Filtering

```python
def player_filter(event):
    player = event.get('player')
    return player and player.name.startswith('Bot')

def handle_filtered_event(event):
    print(f"Bot player event: {event}")

client.events.subscribe('player_moved', handle_filtered_event, filter_func=player_filter)
```

### Threading Considerations

PyReborn is thread-safe and uses multiple threads internally:
- Main thread: User API, event processing
- Receive thread: Network packet reception  
- Send thread: Packet transmission with rate limiting

When using PyReborn in multi-threaded applications, all public API methods are safe to call from any thread.

**Example**:
```python
import threading

def bot_thread():
    client = RebornClient("localhost", 14900)
    client.connect()
    client.login("bot", "pass")
    
    while True:
        client.move_to(random.randint(0, 63), random.randint(0, 63))
        time.sleep(5)

thread = threading.Thread(target=bot_thread)
thread.start()
```