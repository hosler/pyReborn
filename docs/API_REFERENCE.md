# PyReborn API Reference

Complete API documentation for the PyReborn library.

## Table of Contents

- [RebornClient](#rebornclient)
- [Player](#player)
- [Level](#level)
- [EventManager](#eventmanager)
- [SessionManager](#sessionmanager)
- [LevelManager](#levelmanager)
- [Constants](#constants)
- [Exceptions](#exceptions)

## RebornClient

The main client class for connecting to Reborn Server.

```python
from pyreborn import RebornClient

client = RebornClient(host="localhost", port=14900)
```

### Constructor

```python
RebornClient(host: str, port: int = 14900, receive_timeout: float = 0.1)
```

**Parameters:**
- `host` (str): Server hostname or IP address
- `port` (int): Server port (default: 14900)
- `receive_timeout` (float): Socket receive timeout in seconds (default: 0.1)

### Properties

- `connected` (bool): Whether the client is connected
- `authenticated` (bool): Whether the client is logged in
- `events` (EventManager): Event manager instance
- `session_manager` (SessionManager): Session manager instance
- `level_manager` (LevelManager): Level manager instance
- `player_x` (float): Current player X position
- `player_y` (float): Current player Y position
- `player_level` (str): Current level name

### Connection Methods

#### connect()
```python
def connect() -> bool
```
Connect to the server.

**Returns:** bool - True if connection successful, False otherwise

**Example:**
```python
if client.connect():
    print("Connected!")
else:
    print("Connection failed!")
```

#### disconnect()
```python
def disconnect() -> None
```
Disconnect from the server.

**Example:**
```python
client.disconnect()
```

#### login()
```python
def login(account: str, password: str) -> bool
```
Authenticate with the server.

**Parameters:**
- `account` (str): Account name
- `password` (str): Account password

**Returns:** bool - True if login successful, False otherwise

**Example:**
```python
if client.login("myaccount", "mypassword"):
    print("Logged in!")
```

#### run()
```python
def run() -> None
```
Run the client main loop. Blocks until disconnected.

**Example:**
```python
client.run()  # Blocks forever
```

### Movement Methods

#### move()
```python
def move(dx: float, dy: float) -> None
```
Move relative to current position.

**Parameters:**
- `dx` (float): Change in X position (in tiles)
- `dy` (float): Change in Y position (in tiles)

**Example:**
```python
client.move(1, 0)   # Move 1 tile right
client.move(0, -1)  # Move 1 tile up
```

#### move_to()
```python
def move_to(x: float, y: float) -> None
```
Move to an absolute position.

**Parameters:**
- `x` (float): Target X position (in tiles)
- `y` (float): Target Y position (in tiles)

**Example:**
```python
client.move_to(30.5, 25.0)  # Move to center area
```

### Communication Methods

#### set_chat()
```python
def set_chat(message: str) -> None
```
Set a chat bubble above your character.

**Parameters:**
- `message` (str): Chat message (max 223 characters)

**Example:**
```python
client.set_chat("Hello, world!")
```

#### say()
```python
def say(message: str) -> None
```
Send a chat message to the current level.

**Parameters:**
- `message` (str): Chat message

**Example:**
```python
client.say("Hi everyone!")
```

#### send_private_message()
```python
def send_private_message(player: str, message: str) -> None
```
Send a private message to another player.

**Parameters:**
- `player` (str): Target player name
- `message` (str): Message content

**Example:**
```python
client.send_private_message("JohnDoe", "Hey, how are you?")
```

#### send_toall()
```python
def send_toall(message: str) -> None
```
Send a server-wide message (if permitted).

**Parameters:**
- `message` (str): Message content

**Example:**
```python
client.send_toall("Server event starting!")
```

### Appearance Methods

#### set_nickname()
```python
def set_nickname(nickname: str) -> None
```
Set your display name.

**Parameters:**
- `nickname` (str): Display name

**Example:**
```python
client.set_nickname("CoolBot")
```

#### set_head_image()
```python
def set_head_image(image: str) -> None
```
Set your head image.

**Parameters:**
- `image` (str): Head image filename

**Example:**
```python
client.set_head_image("head1.png")
```

#### set_body_image()
```python
def set_body_image(image: str) -> None
```
Set your body image.

**Parameters:**
- `image` (str): Body image filename

**Example:**
```python
client.set_body_image("body1.png")
```

#### set_shield_image()
```python
def set_shield_image(image: str) -> None
```
Set your shield image.

**Parameters:**
- `image` (str): Shield image filename

**Example:**
```python
client.set_shield_image("shield1.png")
```

#### set_sword_image()
```python
def set_sword_image(image: str) -> None
```
Set your sword image.

**Parameters:**
- `image` (str): Sword image filename

**Example:**
```python
client.set_sword_image("sword1.png")
```

#### set_colors()
```python
def set_colors(colors: dict) -> None
```
Set your character colors.

**Parameters:**
- `colors` (dict): Color values for different parts

**Example:**
```python
client.set_colors({
    'skin': 'white',
    'coat': 'red',
    'sleeves': 'blue',
    'shoes': 'black',
    'belt': 'brown'
})
```

### Combat Methods

#### take_bomb()
```python
def take_bomb() -> None
```
Pick up a bomb.

**Example:**
```python
client.take_bomb()
```

#### throw_bomb() 
```python
def throw_bomb() -> None
```
Throw a bomb.

**Example:**
```python
client.throw_bomb()
```

#### take_bow()
```python
def take_bow() -> None
```
Pick up a bow.

**Example:**
```python
client.take_bow()
```

#### shoot_arrow()
```python
def shoot_arrow() -> None
```
Shoot an arrow.

**Example:**
```python
client.shoot_arrow()
```

#### take_sword()
```python
def take_sword() -> None
```
Pick up a sword.

**Example:**
```python
client.take_sword()
```

### World Interaction Methods

#### warp_to()
```python
def warp_to(x: float, y: float, level: str) -> None
```
Warp to another level.

**Parameters:**
- `x` (float): Target X position
- `y` (float): Target Y position  
- `level` (str): Target level name

**Example:**
```python
client.warp_to(30, 30, "level2.nw")
```

#### play_sound()
```python
def play_sound(filename: str) -> None
```
Play a sound effect.

**Parameters:**
- `filename` (str): Sound filename

**Example:**
```python
client.play_sound("beep.wav")
```

#### set_player_prop()
```python
def set_player_prop(prop_id: int, value: Any) -> None
```
Set a player property.

**Parameters:**
- `prop_id` (int): Property ID (see constants)
- `value` (Any): Property value

**Example:**
```python
from pyreborn.constants import PlayerProp
client.set_player_prop(PlayerProp.PLPROP_NICKNAME, "NewName")
```

## Player

Represents a player in the game.

### Properties

- `id` (int): Player ID
- `name` (str): Account name
- `nickname` (str): Display name
- `x` (float): X position
- `y` (float): Y position
- `level` (str): Current level
- `hearts` (float): Health (0-20)
- `fullhearts` (float): Maximum health
- `ap` (int): Alignment points
- `rupees` (int): Money
- `swordpower` (int): Sword strength (0-3)
- `shieldpower` (int): Shield strength (0-3)
- `glovepowe` (int): Glove power (0-2)
- `bombcount` (int): Number of bombs
- `head_image` (str): Head image filename
- `body_image` (str): Body image filename
- `shield_image` (str): Shield image filename
- `sword_image` (str): Sword image filename
- `colors` (dict): Character colors
- `sprite` (int): Animation sprite
- `status` (int): Player status flags
- `guild` (str): Guild name

### Methods

#### distance_to()
```python
def distance_to(x: float, y: float) -> float
```
Calculate distance to a position.

**Parameters:**
- `x` (float): Target X position
- `y` (float): Target Y position

**Returns:** float - Distance in tiles

**Example:**
```python
dist = player.distance_to(30, 30)
print(f"Distance: {dist} tiles")
```

## Level

Represents a game level.

### Properties

- `name` (str): Level filename
- `board_tiles_64x64` (List[int]): Raw tile data (4096 tiles)

### Methods

#### get_board_tiles_array()
```python
def get_board_tiles_array() -> List[int]
```
Get flat array of tile IDs.

**Returns:** List[int] - 4096 tile IDs

**Example:**
```python
tiles = level.get_board_tiles_array()
```

#### get_board_tiles_2d()
```python
def get_board_tiles_2d() -> List[List[int]]
```
Get 2D array of tile IDs.

**Returns:** List[List[int]] - 64x64 2D array [y][x]

**Example:**
```python
tiles_2d = level.get_board_tiles_2d()
tile_at_10_10 = tiles_2d[10][10]
```

#### get_tile_at()
```python
def get_tile_at(x: int, y: int) -> int
```
Get tile ID at position.

**Parameters:**
- `x` (int): X coordinate (0-63)
- `y` (int): Y coordinate (0-63)

**Returns:** int - Tile ID

**Example:**
```python
tile_id = level.get_tile_at(10, 10)
```

#### tile_to_tileset_coords()
```python
@staticmethod
def tile_to_tileset_coords(tile_id: int) -> Tuple[int, int, int, int]
```
Convert tile ID to tileset coordinates.

**Parameters:**
- `tile_id` (int): Tile ID

**Returns:** Tuple[int, int, int, int] - (tx, ty, px, py)
- `tx`, `ty`: Tile coordinates in tileset
- `px`, `py`: Pixel coordinates in tileset

**Example:**
```python
tx, ty, px, py = Level.tile_to_tileset_coords(tile_id)
```

## EventManager

Manages event subscriptions and emissions.

### Methods

#### subscribe()
```python
def subscribe(event_name: str, handler: Callable[[dict], None]) -> None
```
Subscribe to an event.

**Parameters:**
- `event_name` (str): Event name
- `handler` (Callable): Function to call when event fires

**Example:**
```python
def on_chat(event):
    print(f"Chat: {event['message']}")

client.events.subscribe('player_chat', on_chat)
```

#### unsubscribe()
```python
def unsubscribe(event_name: str, handler: Callable[[dict], None]) -> None
```
Unsubscribe from an event.

**Parameters:**
- `event_name` (str): Event name
- `handler` (Callable): Handler to remove

**Example:**
```python
client.events.unsubscribe('player_chat', on_chat)
```

#### emit()
```python
def emit(event_name: str, data: dict) -> None
```
Emit an event.

**Parameters:**
- `event_name` (str): Event name
- `data` (dict): Event data

**Example:**
```python
client.events.emit('custom_event', {'value': 42})
```

## SessionManager

Manages player sessions and state.

### Methods

#### get_player()
```python
def get_player(player_id: int) -> Optional[Player]
```
Get player by ID.

**Parameters:**
- `player_id` (int): Player ID

**Returns:** Optional[Player] - Player object or None

**Example:**
```python
player = client.session_manager.get_player(123)
```

#### get_player_by_name()
```python
def get_player_by_name(name: str) -> Optional[Player]
```
Get player by account name.

**Parameters:**
- `name` (str): Account name

**Returns:** Optional[Player] - Player object or None

**Example:**
```python
player = client.session_manager.get_player_by_name("JohnDoe")
```

#### get_all_players()
```python
def get_all_players() -> List[Player]
```
Get all online players.

**Returns:** List[Player] - List of all players

**Example:**
```python
players = client.session_manager.get_all_players()
print(f"{len(players)} players online")
```

#### get_players_on_level()
```python
def get_players_on_level(level_name: str) -> List[Player]
```
Get players on a specific level.

**Parameters:**
- `level_name` (str): Level name

**Returns:** List[Player] - Players on that level

**Example:**
```python
players = client.session_manager.get_players_on_level("level1.nw")
```

## LevelManager

Manages game levels.

### Methods

#### get_current_level()
```python
def get_current_level() -> Optional[Level]
```
Get the current level.

**Returns:** Optional[Level] - Current level or None

**Example:**
```python
level = client.level_manager.get_current_level()
if level:
    print(f"On level: {level.name}")
```

#### get_level()
```python
def get_level(name: str) -> Optional[Level]
```
Get a specific level by name.

**Parameters:**
- `name` (str): Level name

**Returns:** Optional[Level] - Level object or None

**Example:**
```python
level = client.level_manager.get_level("level2.nw")
```

## Constants

### PlayerProp

Player property IDs for use with `set_player_prop()`.

```python
from pyreborn.constants import PlayerProp

# Common properties
PlayerProp.PLPROP_NICKNAME    # 0 - Nickname
PlayerProp.PLPROP_HEADIMG     # 3 - Head image
PlayerProp.PLPROP_BODYIMG     # 4 - Body image
PlayerProp.PLPROP_SHIELDIMG   # 5 - Shield image
PlayerProp.PLPROP_SWORDIMG    # 6 - Sword image
PlayerProp.PLPROP_COLORS      # 7 - Colors
PlayerProp.PLPROP_SPRITE      # 8 - Animation sprite
```

### PacketType

Packet type constants.

```python
from pyreborn.constants import PacketType

PacketType.PLO_MOVE          # Player movement
PacketType.PLO_CHAT          # Chat message
PacketType.PLO_WARP          # Level warp
# ... many more
```

## Exceptions

### ConnectionError
Raised when connection fails.

```python
try:
    client.connect()
except ConnectionError as e:
    print(f"Connection failed: {e}")
```

### AuthenticationError
Raised when login fails.

```python
try:
    client.login("user", "pass")
except AuthenticationError as e:
    print(f"Login failed: {e}")
```

### ProtocolError
Raised when protocol errors occur.

```python
try:
    client.send_packet(data)
except ProtocolError as e:
    print(f"Protocol error: {e}")
```

## Thread Safety

PyReborn uses multiple threads internally:
- Main thread: Your code
- Receive thread: Handles incoming packets
- Send thread: Handles outgoing packets with rate limiting

### Thread-Safe Operations
- All public methods are thread-safe
- Event handlers are called from the receive thread
- Use queues for heavy processing in handlers

### Example: Thread-Safe Bot
```python
import queue
import threading

class ThreadSafeBot:
    def __init__(self, client):
        self.client = client
        self.work_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self.worker)
        self.worker_thread.daemon = True
        self.worker_thread.start()
        
        # Subscribe to events
        client.events.subscribe('player_chat', self.on_chat)
        
    def on_chat(self, event):
        # Don't process in event handler - queue it
        self.work_queue.put(('chat', event))
        
    def worker(self):
        while True:
            try:
                work_type, data = self.work_queue.get(timeout=1)
                if work_type == 'chat':
                    self.process_chat(data)
            except queue.Empty:
                continue
                
    def process_chat(self, event):
        # Safe to do heavy processing here
        player = event['player']
        message = event['message']
        
        # Example: database lookup, API call, etc.
        response = self.generate_response(message)
        self.client.set_chat(response)
```

## Best Practices

1. **Always check return values**
   ```python
   if client.connect() and client.login("user", "pass"):
       # Success
   else:
       # Handle failure
   ```

2. **Use context managers** (when available)
   ```python
   # Future feature
   with RebornClient("localhost", 14900) as client:
       client.login("user", "pass")
       # Auto-disconnect on exit
   ```

3. **Handle disconnections gracefully**
   ```python
   try:
       client.run()
   except KeyboardInterrupt:
       print("Shutting down...")
   finally:
       client.disconnect()
   ```

4. **Don't spam packets**
   ```python
   # Bad
   for i in range(100):
       client.move_to(i, i)  # Too fast!
   
   # Good
   for i in range(100):
       client.move_to(i, i)
       time.sleep(0.1)  # Rate limit
   ```

5. **Clean up event handlers**
   ```python
   handlers = []
   
   def subscribe(event, handler):
       client.events.subscribe(event, handler)
       handlers.append((event, handler))
       
   def cleanup():
       for event, handler in handlers:
           client.events.unsubscribe(event, handler)
   ```