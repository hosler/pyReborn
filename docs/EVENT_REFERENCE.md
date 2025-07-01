# PyReborn Event Reference

This document describes all events emitted by PyReborn and their data structures.

## Event System Overview

PyReborn uses an event-driven architecture where game actions trigger events that your code can listen to.

### Subscribing to Events

```python
def my_handler(event):
    # event is a dictionary containing event data
    print(f"Event triggered: {event}")

# Subscribe to an event
client.events.subscribe('event_name', my_handler)

# Unsubscribe from an event
client.events.unsubscribe('event_name', my_handler)
```

### Event Data Structure

All events are dictionaries with event-specific keys. Most events include:
- Related player objects
- Timestamps
- Previous values (for change events)

## Connection Events

### `connected`
Fired when successfully connected to the server.

```python
def on_connected(event):
    print("Connected to server!")
    
event = {}  # No additional data
```

### `disconnected`
Fired when disconnected from the server.

```python
def on_disconnected(event):
    reason = event.get('reason', 'Unknown')
    print(f"Disconnected: {reason}")
    
event = {
    'reason': str  # Reason for disconnection (optional)
}
```

### `login_success`
Fired after successful authentication.

```python
def on_login_success(event):
    print("Login successful!")
    
event = {}  # No additional data
```

### `login_failed`
Fired when login fails.

```python
def on_login_failed(event):
    reason = event.get('reason', 'Invalid credentials')
    print(f"Login failed: {reason}")
    
event = {
    'reason': str  # Reason for failure
}
```

## Player Events

### `player_joined`
Fired when a player enters your current level.

```python
def on_player_joined(event):
    player = event['player']
    print(f"{player.nickname} joined the level")
    
event = {
    'player': Player  # The player who joined
}
```

### `player_left`
Fired when a player leaves your current level.

```python
def on_player_left(event):
    player = event['player']
    print(f"{player.nickname} left the level")
    
event = {
    'player': Player  # The player who left
}
```

### `player_moved`
Fired when a player moves.

```python
def on_player_moved(event):
    player = event['player']
    old_x, old_y = event['old_x'], event['old_y']
    print(f"{player.nickname} moved from ({old_x}, {old_y}) to ({player.x}, {player.y})")
    
event = {
    'player': Player,  # The player who moved
    'old_x': float,    # Previous X position
    'old_y': float     # Previous Y position
}
```

### `player_chat`
Fired when a player sends a chat message.

```python
def on_player_chat(event):
    player = event['player']
    message = event['message']
    print(f"{player.nickname}: {message}")
    
event = {
    'player': Player,  # The player who sent the message
    'message': str     # The chat message
}
```

### `player_nickname_changed`
Fired when a player changes their nickname.

```python
def on_nickname_changed(event):
    player = event['player']
    old_nick = event['old_nickname']
    print(f"{player.name} changed nickname from {old_nick} to {player.nickname}")
    
event = {
    'player': Player,      # The player who changed nickname
    'old_nickname': str    # Previous nickname
}
```

### `player_prop_changed`
Fired when any player property changes.

```python
def on_prop_changed(event):
    player = event['player']
    prop = event['property']
    old_val = event['old_value']
    new_val = event['new_value']
    print(f"{player.nickname}'s {prop} changed from {old_val} to {new_val}")
    
event = {
    'player': Player,     # The player whose property changed
    'property': str,      # Property name (e.g., 'hearts', 'shield')
    'old_value': Any,     # Previous value
    'new_value': Any      # New value
}
```

## Combat Events

### `player_hurt`
Fired when a player takes damage.

```python
def on_player_hurt(event):
    player = event['player']
    damage = event['damage']
    print(f"{player.nickname} took {damage} damage! Hearts: {player.hearts}")
    
event = {
    'player': Player,  # The player who was hurt
    'damage': float,   # Amount of damage taken
    'attacker': Player # Player who caused damage (optional)
}
```

### `player_died`
Fired when a player dies (hearts reach 0).

```python
def on_player_died(event):
    player = event['player']
    print(f"{player.nickname} died!")
    
event = {
    'player': Player,   # The player who died
    'killer': Player    # Player who killed them (optional)
}
```

### `bomb_thrown`
Fired when a player throws a bomb.

```python
def on_bomb_thrown(event):
    player = event['player']
    x, y = event['x'], event['y']
    print(f"{player.nickname} threw a bomb at ({x}, {y})")
    
event = {
    'player': Player,  # The player who threw the bomb
    'x': float,        # Bomb X position
    'y': float         # Bomb Y position
}
```

### `arrow_shot`
Fired when a player shoots an arrow.

```python
def on_arrow_shot(event):
    player = event['player']
    direction = event['direction']
    print(f"{player.nickname} shot an arrow {direction}")
    
event = {
    'player': Player,    # The player who shot the arrow
    'direction': str,    # Direction: 'up', 'down', 'left', 'right'
    'x': float,          # Arrow start X position
    'y': float           # Arrow start Y position
}
```

## Level Events

### `level_changed`
Fired when you enter a new level.

```python
def on_level_changed(event):
    old_level = event['old_level']
    new_level = event['new_level']
    print(f"Entered {new_level} from {old_level}")
    
event = {
    'old_level': str,  # Previous level name (None if first level)
    'new_level': str   # New level name
}
```

### `level_loaded`
Fired when level data is fully loaded.

```python
def on_level_loaded(event):
    level = event['level']
    print(f"Level {level.name} loaded with {len(level.get_board_tiles_array())} tiles")
    
event = {
    'level': Level  # The loaded Level object
}
```

## Communication Events

### `private_message`
Fired when you receive a private message.

```python
def on_private_message(event):
    from_player = event['from_player']
    message = event['message']
    print(f"PM from {from_player}: {message}")
    
event = {
    'from_player': str,  # Name of player who sent the PM
    'message': str       # The message content
}
```

### `server_message`
Fired when the server sends a system message.

```python
def on_server_message(event):
    message = event['message']
    msg_type = event.get('type', 'info')
    print(f"[SERVER-{msg_type}] {message}")
    
event = {
    'message': str,  # The server message
    'type': str      # Message type: 'info', 'warning', 'error' (optional)
}
```

### `toall_message`
Fired when a server-wide message is received.

```python
def on_toall_message(event):
    from_player = event['from_player']
    message = event['message']
    print(f"[TOALL] {from_player}: {message}")
    
event = {
    'from_player': str,  # Who sent the toall
    'message': str       # The message content
}
```

## Item Events

### `item_picked_up`
Fired when you pick up an item.

```python
def on_item_picked_up(event):
    item = event['item']
    print(f"Picked up {item}")
    
event = {
    'item': str,      # Item type: 'bomb', 'bow', 'sword', etc.
    'quantity': int   # Amount picked up (optional)
}
```

### `item_used`
Fired when you use an item.

```python
def on_item_used(event):
    item = event['item']
    print(f"Used {item}")
    
event = {
    'item': str  # Item type that was used
}
```

## Custom Events

You can also emit your own custom events:

```python
# Emit a custom event
client.events.emit('my_custom_event', {
    'data': 'some value',
    'timestamp': time.time()
})

# Listen for custom events
def on_custom_event(event):
    data = event['data']
    print(f"Custom event: {data}")

client.events.subscribe('my_custom_event', on_custom_event)
```

## Event Handler Best Practices

### 1. Handle Errors Gracefully

```python
def safe_handler(event):
    try:
        player = event['player']
        # Your logic here
    except KeyError:
        print("Event missing required data")
    except Exception as e:
        print(f"Error in handler: {e}")
```

### 2. Use Specific Handlers

```python
# Good - Specific handler for each event
def on_player_chat(event):
    # Handle chat
    pass

def on_player_moved(event):
    # Handle movement
    pass

# Bad - One handler for everything
def handle_all(event):
    if event.get('type') == 'chat':
        # Handle chat
    elif event.get('type') == 'move':
        # Handle movement
```

### 3. Don't Block the Event Thread

```python
# Good - Quick handler
def on_player_joined(event):
    player = event['player']
    welcome_queue.put(player)  # Process later

# Bad - Blocking handler
def on_player_joined(event):
    player = event['player']
    time.sleep(5)  # Don't do this!
    client.set_chat(f"Welcome {player.nickname}!")
```

### 4. Clean Up Subscriptions

```python
class MyBot:
    def __init__(self, client):
        self.client = client
        self.handlers = []
        
    def start(self):
        # Track handlers for cleanup
        handler = self.on_player_chat
        self.client.events.subscribe('player_chat', handler)
        self.handlers.append(('player_chat', handler))
        
    def stop(self):
        # Clean up all handlers
        for event_name, handler in self.handlers:
            self.client.events.unsubscribe(event_name, handler)
        self.handlers.clear()
```

## Debugging Events

Enable logging to see all events:

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Or create a universal event logger
def log_all_events(event):
    print(f"Event: {event}")

# Subscribe to all events (not recommended for production)
for event_name in ['player_joined', 'player_left', 'player_moved', ...]:
    client.events.subscribe(event_name, log_all_events)
```

## Performance Considerations

- Event handlers are called synchronously
- Keep handlers fast to avoid blocking
- Use queues for heavy processing
- Avoid modifying event data (it may be shared)
- Unsubscribe when no longer needed

## Common Patterns

### State Tracking

```python
class PlayerTracker:
    def __init__(self, client):
        self.client = client
        self.player_positions = {}
        
        client.events.subscribe('player_joined', self.on_joined)
        client.events.subscribe('player_moved', self.on_moved)
        client.events.subscribe('player_left', self.on_left)
        
    def on_joined(self, event):
        player = event['player']
        self.player_positions[player.name] = (player.x, player.y)
        
    def on_moved(self, event):
        player = event['player']
        self.player_positions[player.name] = (player.x, player.y)
        
    def on_left(self, event):
        player = event['player']
        self.player_positions.pop(player.name, None)
```

### Command System

```python
class CommandBot:
    def __init__(self, client):
        self.client = client
        self.commands = {}
        
        client.events.subscribe('player_chat', self.on_chat)
        
    def register_command(self, name, handler):
        self.commands[name] = handler
        
    def on_chat(self, event):
        message = event['message']
        if message.startswith('!'):
            parts = message[1:].split()
            cmd = parts[0].lower()
            args = parts[1:]
            
            if cmd in self.commands:
                self.commands[cmd](event['player'], args)
```

### Delayed Responses

```python
import threading
import time

class DelayedGreeter:
    def __init__(self, client):
        self.client = client
        client.events.subscribe('player_joined', self.on_joined)
        
    def on_joined(self, event):
        player = event['player']
        # Don't block the event handler
        threading.Thread(
            target=self.greet_delayed,
            args=(player.nickname,)
        ).start()
        
    def greet_delayed(self, nickname):
        time.sleep(2)  # Wait 2 seconds
        self.client.set_chat(f"Welcome {nickname}!")
```