# PyReborn

A Python library for connecting to GServer (Graal Reborn) servers with full protocol support including encryption, player tracking, and real-time communication.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- 🔐 **Full ENCRYPT_GEN_5 support** - Proper partial packet encryption
- 🎮 **Real-time player tracking** - See other players move around
- 💬 **Chat system** - Send and receive chat messages  
- 🤖 **Bot creation** - Build intelligent bots and automation
- 📦 **Packet streaming** - Handle multiple packets in single TCP reads
- 🔧 **Session management** - Track levels, players, and game state
- 📚 **Complete protocol** - All major packet types supported

## Quick Start

### Installation

```bash
git clone https://github.com/yourusername/pyReborn.git
cd pyReborn
pip install -e .
```

### Basic Connection

```python
from pyreborn import GraalClient

# Create client
client = GraalClient("localhost", 14900)

# Connect and login
if client.connect() and client.login("username", "password"):
    print("✅ Connected successfully!")
    
    # Send a chat message
    client.say("Hello from PyReborn!")
    
    # Move around
    client.move_to(30.5, 25.0)
    
    # Set nickname and appearance
    client.set_nickname("PyBot")
    client.set_body_image("body23.png")
    
    # Keep connection alive
    import time
    time.sleep(10)
    
    client.disconnect()
```

## Examples

### Player Tracking Bot

```python
from pyreborn import GraalClient, EventType

client = GraalClient("localhost", 14900)

# Track when players join/leave
def on_player_added(player):
    print(f"👋 {player.nickname} joined at ({player.x}, {player.y})")
    client.say(f"Welcome {player.nickname}!")

def on_player_removed(player):
    print(f"🚪 {player.nickname} left")

def on_chat(player_id, message):
    player = client.get_player_by_id(player_id)
    if player:
        print(f"💬 {player.nickname}: {message}")
        
        # Auto-respond to greetings
        if "hello" in message.lower():
            client.say(f"Hello {player.nickname}!")

# Subscribe to events
client.on(EventType.PLAYER_ADDED, on_player_added)
client.on(EventType.PLAYER_REMOVED, on_player_removed)
client.on(EventType.CHAT_MESSAGE, on_chat)

# Connect and run
if client.connect() and client.login("tracker_bot", "password"):
    print("🤖 Player tracker online!")
    
    try:
        while True:
            # Show periodic stats
            print(f"📊 Tracking {len(client.players)} players")
            time.sleep(30)
    except KeyboardInterrupt:
        print("Shutting down...")
    
    client.disconnect()
```

### Follower Bot

```python
import math
from pyreborn import GraalClient, EventType

class FollowerBot:
    def __init__(self, target_name):
        self.client = GraalClient("localhost", 14900)
        self.target_name = target_name
        self.target_player = None
        
        self.client.on(EventType.OTHER_PLAYER_UPDATE, self.on_player_update)
    
    def on_player_update(self, player):
        # Check if this is our target
        if player.nickname and self.target_name in player.nickname:
            self.target_player = player
            self.follow_target()
    
    def follow_target(self):
        if not self.target_player:
            return
            
        # Calculate distance
        my_pos = (self.client.local_player.x, self.client.local_player.y)
        target_pos = (self.target_player.x, self.target_player.y)
        
        distance = math.sqrt(
            (target_pos[0] - my_pos[0])**2 + 
            (target_pos[1] - my_pos[1])**2
        )
        
        # Follow if too far away
        if distance > 3.0:
            # Move closer
            dx = target_pos[0] - my_pos[0]
            dy = target_pos[1] - my_pos[1]
            
            if distance > 0:
                new_x = my_pos[0] + (dx / distance) * 1.0
                new_y = my_pos[1] + (dy / distance) * 1.0
                self.client.move_to(new_x, new_y)
    
    def run(self):
        if self.client.connect() and self.client.login("follower", "password"):
            print(f"🎯 Following {self.target_name}")
            self.client.set_nickname("Follower")
            self.client.say(f"Now following {self.target_name}!")
            
            try:
                while True:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                pass
            
            self.client.disconnect()

# Usage
bot = FollowerBot("SpaceManSpiff")
bot.run()
```

### Combat Bot

```python
from pyreborn import GraalClient, EventType
from pyreborn.protocol.enums import Direction

client = GraalClient("localhost", 14900)

def on_player_update(player):
    # Get nearby players
    my_pos = (client.local_player.x, client.local_player.y)
    nearby = client.get_nearby_players(my_pos[0], my_pos[1], radius=3.0)
    
    if nearby:
        # Found enemies nearby - attack!
        client.set_gani("sword")  # Sword animation
        client.say("En garde!")
        
        # Drop a bomb
        client.drop_bomb(power=2)
        
        # Shoot an arrow
        client.shoot_arrow()

client.on(EventType.OTHER_PLAYER_UPDATE, on_player_update)

if client.connect() and client.login("warrior", "password"):
    client.set_nickname("CombatBot")
    client.set_body_image("body19.png")  # Armor
    
    # Give ourselves equipment
    client.set_arrows(99)
    client.set_bombs(20)
    client.set_hearts(3, 3)
    
    client.say("Combat bot ready for battle! ⚔️")
    
    # Patrol around
    import random
    while True:
        x = random.randint(20, 40)
        y = random.randint(20, 40) 
        client.move_to(x, y)
        time.sleep(5)
```

### Advanced Session Management

```python
from pyreborn import GraalClient, EventType

client = GraalClient("localhost", 14900)

# Get comprehensive session info
def show_session_stats():
    stats = client.get_session_summary()
    
    print(f"📊 Session Statistics:")
    print(f"   Current level: {stats['current_level']}")
    print(f"   Players seen: {stats['players_seen']}")
    print(f"   Chat messages: {stats['chat_messages']}")
    print(f"   Levels visited: {len(stats['levels_visited'])}")
    print(f"   Session duration: {stats['session_duration']:.1f}s")

# Get conversation history
def show_chat_with_player(player_name):
    # Find player by name
    players = client.find_players_by_name(player_name)
    if players:
        player = players[0]
        conversation = client.get_conversation_with(player.id)
        
        print(f"💬 Chat history with {player.nickname}:")
        for msg in conversation[-10:]:  # Last 10 messages
            print(f"   {msg['timestamp']}: {msg['message']}")

# Track level changes
def on_level_entered(level):
    print(f"🚪 Entered level: {level.name}")
    
    # Get level info
    level_info = client.get_level_session_info(level.name)
    if level_info:
        print(f"   Time in level: {level_info['time_spent']:.1f}s")
        print(f"   Players here: {len(level_info['players'])}")

client.on(EventType.LEVEL_ENTERED, on_level_entered)

if client.connect() and client.login("session_bot", "password"):
    client.say("Session tracking bot online!")
    
    # Show stats every 30 seconds
    import time
    while True:
        time.sleep(30)
        show_session_stats()
```

## Protocol Documentation

For detailed protocol implementation, see [GRAAL_PROTOCOL_GUIDE.md](docs/GRAAL_PROTOCOL_GUIDE.md).

### Key Protocol Features

- **ENCRYPT_GEN_5**: Partial packet encryption (first X bytes only)
- **Compression**: UNCOMPRESSED, ZLIB, BZ2 support
- **Packet Streaming**: Multiple packets per TCP read
- **Player Properties**: 80+ different property types
- **Real-time Updates**: Position, chat, actions, level changes

## API Reference

### GraalClient

Main client class for connecting to GServer.

```python
class GraalClient:
    def __init__(self, host: str, port: int = 14900)
    def connect() -> bool
    def login(account: str, password: str, timeout: float = 5.0) -> bool
    def disconnect()
    
    # Movement
    def move_to(x: float, y: float, direction: Optional[Direction] = None)
    
    # Chat
    def say(message: str)
    def send_pm(player_id: int, message: str)
    
    # Appearance
    def set_nickname(nickname: str)
    def set_body_image(image: str)
    def set_head_image(image: str)
    def set_chat(message: str)  # Chat bubble
    
    # Combat
    def drop_bomb(x: float = None, y: float = None, power: int = 1)
    def shoot_arrow()
    def fire_effect()
    
    # Items
    def set_arrows(count: int)
    def set_bombs(count: int)
    def set_rupees(count: int)
    def set_hearts(current: float, maximum: float = None)
    
    # Players
    def get_all_players() -> Dict[int, Player]
    def get_player_by_id(player_id: int) -> Optional[Player]
    def get_nearby_players(x: float, y: float, radius: float = 5.0) -> List[Player]
    def find_players_by_name(name: str) -> List[Player]
    
    # Events
    def on(event_type: EventType, handler: Callable)
    def off(event_type: EventType, handler: Callable)
```

### Event Types

```python
class EventType(Enum):
    # Connection
    CONNECTED = auto()
    DISCONNECTED = auto()
    LOGIN_SUCCESS = auto()
    
    # Players
    PLAYER_ADDED = auto()
    PLAYER_REMOVED = auto()
    OTHER_PLAYER_UPDATE = auto()
    PLAYER_WARP = auto()
    
    # Chat
    CHAT_MESSAGE = auto()
    PRIVATE_MESSAGE = auto()
    SERVER_MESSAGE = auto()
    
    # Levels
    LEVEL_ENTERED = auto()
    LEVEL_LEFT = auto()
    
    # Raw packets (advanced)
    RAW_PACKET_RECEIVED = auto()
```

### Player Model

```python
class Player:
    id: int
    nickname: str
    account: str
    x: float
    y: float
    level: str
    
    # Appearance
    body_image: str
    head_image: str
    colors: List[int]
    
    # Stats
    hearts: float
    max_hearts: float
    arrows: int
    bombs: int
    rupees: int
    
    # State
    chat: str      # Current chat bubble
    gani: str      # Current animation
    direction: Direction
```

## Requirements

- Python 3.8+
- No external dependencies (uses only standard library)

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Testing

```bash
# Run basic connection test
python examples/test_connection.py

# Run player tracking test
python examples/test_player_tracking.py

# Run follower bot
python examples/spacemanspiff_follower.py
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- GServer development team for the original protocol
- OpenGraal community for protocol documentation
- Contributors to protocol reverse engineering efforts

## Troubleshooting

### Common Issues

**Connection fails:**
- Check server address and port
- Ensure server is running and accessible
- Verify firewall settings

**Login timeout:**
- Check username/password
- Verify account exists on server
- Check for server-side login restrictions

**Broken pipe errors:**
- Ensure login completes before sending actions
- Check encryption setup
- Verify packet format

**Can't see other players:**
- Check if players are in same level
- Verify packet decryption is working
- Check player property parsing

For more help, see the [troubleshooting guide](docs/TROUBLESHOOTING.md) or open an issue.

---

**PyReborn** - Bringing Python to the Graal universe! 🐍⚔️