# Reborn Modern - A Modern PyReborn Client

A modern pygame client that fully leverages PyReborn's new registry-driven architecture with 96.4% complexity reduction.

## Features

### 🎯 Modern Architecture
- **ModularRebornClient** - Clean dependency injection design
- **Event-driven systems** - Reactive rendering and updates
- **Registry-driven packets** - Automatic packet discovery and parsing
- **OutgoingPacketAPI** - Simplified packet sending

### 📊 Built-in Debug Tools
- **Packet Inspector** - Real-time packet monitoring with registry info
- **Coordinate Overlay** - Position tracking with GMAP support
- **Performance Metrics** - FPS and network statistics

### 🎨 Modern UI Components
- **Server Browser** - Search and filter servers
- **HUD** - Player stats, inventory, minimap
- **Chat System** - Commands, history, private messages
- **YAML Configuration** - Easy customization

### 🔧 Clean Systems Design
- **RenderingSystem** - Event-driven world rendering
- **InputSystem** - Modern input handling with packet API
- **AudioSystem** - Reactive sound effects
- **AnimationSystem** - Sprite animation management
- **PhysicsSystem** - Client-side prediction

## Usage

### Basic Launch
```bash
# Launch with server browser
python main.py

# Auto-login to localhost
python main.py your_username your_password

# Connect to specific server
python main.py your_username your_password --server hastur.hastur2.com

# Enable debug mode
python main.py --debug

# Custom configuration
python main.py --config custom.yaml
```

### Configuration

Edit `config.yaml` to customize:

```yaml
window:
  width: 1280
  height: 720
  fps: 60

client:
  host: localhost
  port: 14900
  version: 6.037

debug:
  show_fps: true
  packet_inspector: false
  coordinate_overlay: false

keybindings:
  move_up: w
  move_down: s
  move_left: a
  move_right: d
  attack: space
  chat: enter
```

### Controls

- **WASD** - Movement
- **Space** - Attack
- **Ctrl** - Grab/Lift
- **Enter** - Open chat
- **F3** - Toggle packet inspector
- **F4** - Toggle coordinate overlay
- **F11** - Toggle fullscreen

### Chat Commands

- `/help` - Show available commands
- `/pm <player> <message>` - Send private message
- `/guild <message>` - Guild chat
- `/clear` - Clear chat history

## Architecture

### Event-Driven Design

The client subscribes to PyReborn events for reactive updates:

```python
# Rendering system subscribes to level changes
events.subscribe(EventType.LEVEL_CHANGED, self._on_level_changed)
events.subscribe(EventType.PLAYER_MOVED, self._on_player_moved)

# Audio system reacts to game events
events.subscribe(EventType.WEAPON_FIRED, self._on_weapon_fired)
events.subscribe(EventType.PLAYER_HURT, self._on_player_hurt)
```

### Packet Introspection

Built-in packet inspector using PyReborn's PacketAPI:

```python
# Get packet information from registry
packet_info = self.packet_info_api.get_packet_info(packet_id)

# Display real-time packet statistics
stats = self.packet_info_api.get_statistics()
print(f"Registry: {stats['total_packets']} packets")
```

### Clean Separation of Concerns

- **Game** - Main game loop and state management
- **Systems** - Core functionality (rendering, input, etc.)
- **UI** - User interface components
- **Config** - Configuration management

## Extending the Client

### Adding New Systems

Create a new system in `systems/`:

```python
class CustomSystem:
    def __init__(self, client: ModularRebornClient):
        self.client = client
        # Subscribe to events
        client.events.subscribe(EventType.CUSTOM, self._on_custom)
    
    def update(self, dt: float):
        # Update logic
        pass
```

### Adding UI Components

Create new UI in `ui/`:

```python
class CustomUI:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
    
    def render(self):
        # Render UI
        pass
```

## Requirements

- Python 3.8+
- pygame
- PyYAML
- PyReborn (with new registry architecture)

## Future Enhancements

- [ ] Plugin system for community extensions
- [ ] Asset management system
- [ ] Tileset and sprite loading
- [ ] Advanced particle effects
- [ ] Network prediction improvements
- [ ] Recording and replay system