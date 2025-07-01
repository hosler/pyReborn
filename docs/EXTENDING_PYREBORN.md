# Extending PyReborn

This guide shows how to extend PyReborn with custom functionality while maintaining compatibility with the base library.

## Table of Contents
1. [Custom Client Classes](#custom-client-classes)
2. [Event System](#event-system)
3. [Custom Packet Handlers](#custom-packet-handlers)
4. [Adding New Actions](#adding-new-actions)
5. [Plugin System](#plugin-system)

## Custom Client Classes

The simplest way to extend PyReborn is by inheriting from `RebornClient`:

```python
from pyreborn import RebornClient

class MyCustomClient(RebornClient):
    def __init__(self, host: str, port: int = 14900):
        super().__init__(host, port)
        
        # Add custom attributes
        self.kill_count = 0
        self.custom_data = {}
        
    def custom_action(self):
        """Add new methods"""
        self.set_chat("Custom action!")
        
    def drop_bomb(self, x=None, y=None, power=1):
        """Override existing methods"""
        super().drop_bomb(x, y, power)
        self.events.emit('bomb_dropped', {'x': x, 'y': y, 'power': power})
```

## Event System

PyReborn uses an event-driven architecture that makes it easy to hook into any action:

### Subscribing to Events

```python
client = RebornClient("localhost", 14900)

# Subscribe to built-in events
client.events.subscribe('player_moved', on_player_moved)
client.events.subscribe('player_chat', on_player_chat)
client.events.subscribe('level_changed', on_level_changed)

# Handler functions
def on_player_moved(event):
    player = event['player']
    print(f"{player.name} moved to ({player.x}, {player.y})")
    
def on_player_chat(event):
    player = event['player']
    message = event['message']
    
    # React to specific messages
    if "help" in message.lower():
        client.set_chat("I can help!")
```

### Creating Custom Events

```python
class CombatClient(RebornClient):
    def attack_player(self, target_id: int):
        """Custom combat method"""
        # ... combat logic ...
        
        # Emit custom event
        self.events.emit('player_attacked', {
            'attacker': self.local_player.id,
            'target': target_id,
            'weapon': 'sword',
            'damage': 10
        })

# Use the custom event
client = CombatClient("localhost", 14900)
client.events.subscribe('player_attacked', lambda e: print(f"Attack: {e}"))
```

## Custom Packet Handlers

For advanced users who need to handle packets not yet supported by PyReborn:

### Method 1: Override handle_packet

```python
class AdvancedClient(RebornClient):
    def __init__(self, host: str, port: int = 14900):
        super().__init__(host, port)
        self.custom_packets_received = []
        
    def handle_packet(self, packet_id: int, data: bytes):
        """Override packet handling"""
        # Handle custom packet
        if packet_id == 99:  # Your custom packet ID
            self.handle_custom_packet(data)
            return
            
        # Let parent handle standard packets
        super().handle_packet(packet_id, data)
        
    def handle_custom_packet(self, data: bytes):
        """Handle your custom packet type"""
        # Parse the data
        parsed = self.parse_custom_format(data)
        self.custom_packets_received.append(parsed)
        
        # Emit event
        self.events.emit('custom_packet', {'data': parsed})
```

### Method 2: Extend PacketHandler

```python
from pyreborn.handlers.packet_handler import PacketHandler

class ExtendedPacketHandler(PacketHandler):
    def __init__(self):
        super().__init__()
        
        # Add new handler
        self.handlers[99] = self.handle_custom_packet
        
    def handle_custom_packet(self, data: bytes, client):
        """Handle custom packet type"""
        # Your logic here
        pass

# Use in client
class AdvancedClient(RebornClient):
    def __init__(self, host: str, port: int = 14900):
        super().__init__(host, port)
        # Replace packet handler
        self.packet_handler = ExtendedPacketHandler()
```

## Adding New Actions

Extend the client with new gameplay actions:

```python
from pyreborn.protocol.packets import PlayerPropsPacket
from pyreborn.protocol.enums import PlayerProp

class RPGClient(RebornClient):
    def __init__(self, host: str, port: int = 14900):
        super().__init__(host, port)
        self.level = 1
        self.experience = 0
        
    def cast_spell(self, spell_name: str, target=None):
        """Cast a spell"""
        # Visual effect
        self.set_gani(f"spell_{spell_name}")
        
        # Chat notification
        self.set_chat(f"*casts {spell_name}*")
        
        # Emit event for spell system
        self.events.emit('spell_cast', {
            'caster': self.local_player,
            'spell': spell_name,
            'target': target
        })
        
    def level_up(self):
        """Handle level up"""
        self.level += 1
        self.set_chat(f"Level {self.level}!")
        
        # Update appearance to show level
        self.set_nickname(f"{self.local_player.nickname} [Lv{self.level}]")
        
        # Emit event
        self.events.emit('level_up', {'new_level': self.level})
```

## Plugin System

Create a simple plugin system for your bot:

```python
class PluginClient(RebornClient):
    def __init__(self, host: str, port: int = 14900):
        super().__init__(host, port)
        self.plugins = []
        
    def load_plugin(self, plugin):
        """Load a plugin"""
        plugin.setup(self)
        self.plugins.append(plugin)
        
    def unload_plugin(self, plugin):
        """Unload a plugin"""
        if plugin in self.plugins:
            plugin.teardown(self)
            self.plugins.remove(plugin)

# Example plugin
class AutoGreetPlugin:
    def setup(self, client):
        """Initialize plugin"""
        self.client = client
        client.events.subscribe('player_joined', self.on_player_joined)
        
    def teardown(self, client):
        """Cleanup plugin"""
        client.events.unsubscribe('player_joined', self.on_player_joined)
        
    def on_player_joined(self, event):
        """Greet new players"""
        player = event['player']
        self.client.set_chat(f"Welcome {player.name}!")

# Usage
client = PluginClient("localhost", 14900)
client.load_plugin(AutoGreetPlugin())
```

## Best Practices

### 1. Use Events for Loose Coupling

Instead of directly modifying core classes, use events:

```python
# Good - uses events
class StatsTracker:
    def __init__(self, client):
        client.events.subscribe('player_moved', self.track_movement)
        client.events.subscribe('bomb_dropped', self.track_bombs)
        
# Bad - tightly coupled
class StatsClient(RebornClient):
    def move_to(self, x, y):
        super().move_to(x, y)
        self.movement_count += 1  # Modifies every movement
```

### 2. Preserve Original Functionality

When overriding methods, call the parent method:

```python
class SafeClient(RebornClient):
    def drop_bomb(self, x=None, y=None, power=1):
        # Add validation
        if self.local_player.bombs <= 0:
            self.set_chat("No bombs left!")
            return
            
        # Call original
        super().drop_bomb(x, y, power)
```

### 3. Document Your Extensions

```python
class DocumentedClient(RebornClient):
    """
    Extended client with additional features:
    - Auto-reconnect on disconnect
    - Command system for chat
    - Statistics tracking
    """
    
    def process_command(self, command: str):
        """
        Process chat commands starting with /
        
        Commands:
            /stats - Show statistics
            /follow <player> - Follow a player
            /stop - Stop current action
        """
        # Implementation...
```

## Example: Full Featured Bot

Here's a complete example combining multiple extension techniques:

```python
from pyreborn import RebornClient
import time
import json

class AdvancedBot(RebornClient):
    """Advanced bot with persistence, commands, and AI"""
    
    def __init__(self, host: str, port: int = 14900):
        super().__init__(host, port)
        
        # Load saved data
        self.data = self.load_data()
        
        # Command system
        self.commands = {
            'help': self.cmd_help,
            'stats': self.cmd_stats,
            'follow': self.cmd_follow,
            'patrol': self.cmd_patrol
        }
        
        # State
        self.following = None
        self.patrolling = False
        self.patrol_points = []
        
        # Setup event handlers
        self.setup_handlers()
        
    def setup_handlers(self):
        """Setup all event handlers"""
        self.events.subscribe('player_chat', self.on_chat)
        self.events.subscribe('player_moved', self.on_player_moved)
        self.events.subscribe('disconnected', self.save_data)
        
    def on_chat(self, event):
        """Process chat for commands"""
        message = event['message']
        if message.startswith('!'):
            self.process_command(message[1:])
            
    def process_command(self, command_str: str):
        """Process a command"""
        parts = command_str.split()
        if not parts:
            return
            
        cmd = parts[0].lower()
        args = parts[1:]
        
        if cmd in self.commands:
            self.commands[cmd](args)
        else:
            self.set_chat(f"Unknown command: {cmd}")
            
    def cmd_help(self, args):
        """Show help"""
        self.set_chat("Commands: !help !stats !follow !patrol")
        
    def cmd_stats(self, args):
        """Show statistics"""
        self.set_chat(f"Stats: {json.dumps(self.data['stats'])}")
        
    def cmd_follow(self, args):
        """Follow a player"""
        if args:
            self.following = args[0]
            self.set_chat(f"Following {self.following}")
        else:
            self.following = None
            self.set_chat("Stopped following")
            
    def cmd_patrol(self, args):
        """Start patrolling"""
        self.patrolling = True
        self.patrol_points = [(30, 30), (40, 30), (40, 40), (30, 40)]
        self.set_chat("Starting patrol")
        
    def on_player_moved(self, event):
        """Track player movements for following"""
        if self.following:
            player = event['player']
            if player.name == self.following:
                # Move towards them
                self.move_towards(player.x, player.y)
                
    def move_towards(self, target_x: float, target_y: float):
        """Move towards a target position"""
        dx = target_x - self.local_player.x
        dy = target_y - self.local_player.y
        distance = (dx**2 + dy**2) ** 0.5
        
        if distance > 2:  # Only move if far enough
            # Move 1 tile towards target
            move_x = self.local_player.x + (dx / distance)
            move_y = self.local_player.y + (dy / distance)
            self.move_to(move_x, move_y)
            
    def load_data(self) -> dict:
        """Load persistent data"""
        try:
            with open('bot_data.json', 'r') as f:
                return json.load(f)
        except:
            return {'stats': {}, 'settings': {}}
            
    def save_data(self, event=None):
        """Save persistent data"""
        with open('bot_data.json', 'w') as f:
            json.dump(self.data, f)
            
    def run(self):
        """Main bot loop with patrol logic"""
        patrol_index = 0
        last_patrol = 0
        
        while self.connected:
            try:
                # Patrol logic
                if self.patrolling and time.time() - last_patrol > 3:
                    point = self.patrol_points[patrol_index]
                    self.move_to(point[0], point[1])
                    patrol_index = (patrol_index + 1) % len(self.patrol_points)
                    last_patrol = time.time()
                    
                time.sleep(0.1)
                
            except KeyboardInterrupt:
                break
                
        self.disconnect()

# Usage
bot = AdvancedBot("localhost", 14900)
if bot.connect() and bot.login("advancedbot", "1234"):
    bot.set_nickname("AdvancedBot")
    bot.set_chat("Advanced bot online! Say !help")
    bot.run()
```

## Summary

PyReborn is designed to be extended. Key extension points:

1. **Inheritance** - Extend RebornClient with new functionality
2. **Events** - Hook into any action with the event system
3. **Packet Handlers** - Add support for new packet types
4. **Composition** - Build systems using PyReborn as a component
5. **Plugins** - Create reusable modules

The modular architecture ensures your extensions won't break when PyReborn is updated, as long as you follow the public API.