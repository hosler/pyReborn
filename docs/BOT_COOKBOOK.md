# PyReborn Bot Cookbook

A collection of recipes and patterns for building bots with PyReborn.

## Table of Contents

1. [Basic Patterns](#basic-patterns)
2. [Movement Patterns](#movement-patterns)
3. [Communication Patterns](#communication-patterns)
4. [Combat Patterns](#combat-patterns)
5. [State Management](#state-management)
6. [Advanced Patterns](#advanced-patterns)
7. [Performance Tips](#performance-tips)
8. [Common Pitfalls](#common-pitfalls)

## Basic Patterns

### Simple Greeting Bot

```python
from pyreborn import RebornClient
import time

client = RebornClient("localhost", 14900)

# Track who we've greeted
greeted_players = set()

def on_player_joined(event):
    player = event['player']
    if player.name not in greeted_players:
        greeted_players.add(player.name)
        time.sleep(1)  # Small delay
        client.set_chat(f"Welcome {player.nickname}!")

client.events.subscribe('player_joined', on_player_joined)

if client.connect() and client.login("greetbot", "password"):
    client.set_nickname("GreeterBot")
    client.run()
```

### Command Bot

```python
from pyreborn import RebornClient

client = RebornClient("localhost", 14900)

def on_chat(event):
    player = event['player']
    message = event['message']
    
    # Check for commands
    if message.startswith("!"):
        command = message[1:].lower().split()
        
        if command[0] == "help":
            client.set_chat("Commands: !help, !time, !players")
        
        elif command[0] == "time":
            import datetime
            current_time = datetime.datetime.now().strftime("%H:%M:%S")
            client.set_chat(f"Current time: {current_time}")
        
        elif command[0] == "players":
            count = len(client.session_manager.get_all_players())
            client.set_chat(f"{count} players online")

client.events.subscribe('player_chat', on_chat)

if client.connect() and client.login("cmdbot", "password"):
    client.set_nickname("CommandBot")
    client.run()
```

## Movement Patterns

### Patrol Bot

```python
from pyreborn import RebornClient
import threading
import time

client = RebornClient("localhost", 14900)

class PatrolBot:
    def __init__(self, client, waypoints):
        self.client = client
        self.waypoints = waypoints
        self.current_index = 0
        self.running = True
        
    def start_patrol(self):
        patrol_thread = threading.Thread(target=self._patrol_loop)
        patrol_thread.daemon = True
        patrol_thread.start()
        
    def _patrol_loop(self):
        while self.running and self.client.connected:
            # Move to next waypoint
            target = self.waypoints[self.current_index]
            self.client.move_to(target[0], target[1])
            
            # Update index
            self.current_index = (self.current_index + 1) % len(self.waypoints)
            
            # Wait before moving to next point
            time.sleep(3)
    
    def stop(self):
        self.running = False

# Define patrol route
waypoints = [(30, 30), (40, 30), (40, 40), (30, 40)]
patrol = PatrolBot(client, waypoints)

if client.connect() and client.login("patrol", "password"):
    client.set_nickname("PatrolBot")
    patrol.start_patrol()
    
    try:
        client.run()
    finally:
        patrol.stop()
```

### Follow Bot

```python
from pyreborn import RebornClient
import math

client = RebornClient("localhost", 14900)
target_player = "PlayerToFollow"  # Change this

def on_player_moved(event):
    player = event['player']
    
    # Check if it's our target
    if player.name == target_player:
        # Calculate offset position (don't stand on top of them)
        offset_x = player.x + 2
        offset_y = player.y
        
        # Move to offset position
        client.move_to(offset_x, offset_y)

client.events.subscribe('player_moved', on_player_moved)

if client.connect() and client.login("follower", "password"):
    client.set_nickname("FollowerBot")
    client.set_chat(f"Following {target_player}")
    client.run()
```

### Circle Movement

```python
from pyreborn import RebornClient
import math
import threading
import time

client = RebornClient("localhost", 14900)

def move_in_circle(center_x, center_y, radius, speed=0.1):
    angle = 0
    while client.connected:
        # Calculate position on circle
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        
        # Move to position
        client.move_to(x, y)
        
        # Update angle
        angle += speed
        if angle > 2 * math.pi:
            angle -= 2 * math.pi
            
        time.sleep(0.1)

if client.connect() and client.login("circlebot", "password"):
    client.set_nickname("CircleBot")
    
    # Start circular movement
    thread = threading.Thread(
        target=move_in_circle,
        args=(32, 32, 10)  # center at (32,32), radius 10
    )
    thread.daemon = True
    thread.start()
    
    client.run()
```

## Communication Patterns

### Chat Logger

```python
from pyreborn import RebornClient
import datetime
import json

client = RebornClient("localhost", 14900)

class ChatLogger:
    def __init__(self, filename):
        self.filename = filename
        self.logs = []
        
    def log_chat(self, event):
        player = event['player']
        message = event['message']
        
        log_entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'player': player.name,
            'nickname': player.nickname,
            'message': message,
            'level': player.level,
            'position': {'x': player.x, 'y': player.y}
        }
        
        self.logs.append(log_entry)
        
        # Save to file
        with open(self.filename, 'w') as f:
            json.dump(self.logs, f, indent=2)

logger = ChatLogger('chat_log.json')
client.events.subscribe('player_chat', logger.log_chat)

if client.connect() and client.login("logger", "password"):
    client.set_nickname("ChatLogger")
    client.run()
```

### Translation Bot

```python
from pyreborn import RebornClient

client = RebornClient("localhost", 14900)

# Simple translation dictionary
translations = {
    'hello': {'es': 'hola', 'fr': 'bonjour', 'de': 'hallo'},
    'goodbye': {'es': 'adiós', 'fr': 'au revoir', 'de': 'auf wiedersehen'},
    'thanks': {'es': 'gracias', 'fr': 'merci', 'de': 'danke'},
}

def on_chat(event):
    message = event['message'].lower()
    
    # Check if message starts with translate command
    if message.startswith("!translate "):
        parts = message.split()
        if len(parts) >= 3:
            lang = parts[1]
            word = parts[2]
            
            if word in translations and lang in translations[word]:
                translation = translations[word][lang]
                client.set_chat(f"{word} in {lang}: {translation}")
            else:
                client.set_chat("Translation not found")

client.events.subscribe('player_chat', on_chat)

if client.connect() and client.login("translator", "password"):
    client.set_nickname("TranslatorBot")
    client.set_chat("Say: !translate <lang> <word>")
    client.run()
```

## Combat Patterns

### Guard Bot

```python
from pyreborn import RebornClient
import math

client = RebornClient("localhost", 14900)

class GuardBot:
    def __init__(self, client, guard_x, guard_y, guard_radius=5):
        self.client = client
        self.guard_x = guard_x
        self.guard_y = guard_y
        self.guard_radius = guard_radius
        
    def check_intruder(self, event):
        player = event['player']
        
        # Calculate distance from guard point
        dist = math.sqrt(
            (player.x - self.guard_x) ** 2 + 
            (player.y - self.guard_y) ** 2
        )
        
        # If player is too close
        if dist < self.guard_radius:
            self.client.set_chat(f"Stay back, {player.nickname}!")
            
            # Move towards intruder
            dx = player.x - self.client.player_x
            dy = player.y - self.client.player_y
            
            # Normalize and move
            if dx != 0 or dy != 0:
                length = math.sqrt(dx*dx + dy*dy)
                self.client.move(dx/length * 2, dy/length * 2)

guard = GuardBot(client, 32, 32, 8)
client.events.subscribe('player_moved', guard.check_intruder)

if client.connect() and client.login("guard", "password"):
    client.set_nickname("GuardBot")
    client.move_to(32, 32)  # Move to guard position
    client.set_chat("No trespassing!")
    client.run()
```

### Auto Dodge Bot

```python
from pyreborn import RebornClient
import random

client = RebornClient("localhost", 14900)

def on_bomb_thrown(event):
    bomb_x = event['x']
    bomb_y = event['y']
    
    # Calculate distance to bomb
    dist = math.sqrt(
        (bomb_x - client.player_x) ** 2 + 
        (bomb_y - client.player_y) ** 2
    )
    
    # If bomb is close, dodge!
    if dist < 5:
        # Move in random direction
        dodge_x = random.choice([-3, 3])
        dodge_y = random.choice([-3, 3])
        client.move(dodge_x, dodge_y)
        client.set_chat("Nice try!")

client.events.subscribe('bomb_thrown', on_bomb_thrown)

if client.connect() and client.login("dodger", "password"):
    client.set_nickname("DodgeBot")
    client.run()
```

## State Management

### Stateful Bot with Memory

```python
from pyreborn import RebornClient
import json
import os

client = RebornClient("localhost", 14900)

class StatefulBot:
    def __init__(self, state_file='bot_state.json'):
        self.state_file = state_file
        self.state = self.load_state()
        
    def load_state(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                return json.load(f)
        return {
            'players_met': {},
            'times_greeted': 0,
            'favorite_player': None
        }
    
    def save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def on_player_joined(self, event):
        player = event['player']
        
        # Track how many times we've seen this player
        if player.name not in self.state['players_met']:
            self.state['players_met'][player.name] = 0
            client.set_chat(f"Nice to meet you, {player.nickname}!")
        else:
            times = self.state['players_met'][player.name]
            client.set_chat(f"Welcome back! I've seen you {times} times before.")
        
        self.state['players_met'][player.name] += 1
        self.state['times_greeted'] += 1
        
        # Update favorite player (most seen)
        max_seen = max(self.state['players_met'].values())
        for name, count in self.state['players_met'].items():
            if count == max_seen:
                self.state['favorite_player'] = name
                break
        
        self.save_state()

bot = StatefulBot()
client.events.subscribe('player_joined', bot.on_player_joined)

if client.connect() and client.login("memory", "password"):
    client.set_nickname("MemoryBot")
    client.run()
```

### Quest Bot

```python
from pyreborn import RebornClient
import random

client = RebornClient("localhost", 14900)

class QuestBot:
    def __init__(self):
        self.quests = {
            'fetch': {
                'description': 'Bring me 10 apples',
                'reward': 100,
                'progress': {}
            },
            'explore': {
                'description': 'Visit all four corners of the map',
                'reward': 200,
                'progress': {}
            }
        }
        self.player_quests = {}  # player_name -> quest_name
        
    def on_chat(self, event):
        player = event['player']
        message = event['message'].lower()
        
        if message == "!quest":
            if player.name in self.player_quests:
                quest_name = self.player_quests[player.name]
                quest = self.quests[quest_name]
                client.set_chat(f"Your quest: {quest['description']}")
            else:
                # Assign random quest
                quest_name = random.choice(list(self.quests.keys()))
                self.player_quests[player.name] = quest_name
                quest = self.quests[quest_name]
                client.set_chat(f"New quest: {quest['description']}")
        
        elif message == "!complete":
            if player.name in self.player_quests:
                quest_name = self.player_quests[player.name]
                quest = self.quests[quest_name]
                
                # Check if quest is complete (simplified)
                client.set_chat(f"Quest complete! Reward: {quest['reward']} rupees")
                del self.player_quests[player.name]

quest_bot = QuestBot()
client.events.subscribe('player_chat', quest_bot.on_chat)

if client.connect() and client.login("questgiver", "password"):
    client.set_nickname("QuestGiver")
    client.set_chat("Say !quest to start")
    client.run()
```

## Advanced Patterns

### Multi-Bot Coordination

```python
from pyreborn import RebornClient
import threading
import queue

# Shared communication queue
bot_comm = queue.Queue()

def run_bot(name, role, comm_queue):
    client = RebornClient("localhost", 14900)
    
    def process_messages():
        while client.connected:
            try:
                msg = comm_queue.get(timeout=0.1)
                if msg['to'] == name:
                    # Handle message based on role
                    if role == 'scout':
                        # Scout reports player positions
                        players = client.session_manager.get_all_players()
                        for p in players:
                            comm_queue.put({
                                'from': name,
                                'to': 'guard',
                                'type': 'player_pos',
                                'data': {'name': p.name, 'x': p.x, 'y': p.y}
                            })
                    elif role == 'guard':
                        # Guard responds to threats
                        if msg['type'] == 'player_pos':
                            data = msg['data']
                            client.set_chat(f"Watching {data['name']}")
            except queue.Empty:
                pass
    
    if client.connect() and client.login(name, "password"):
        client.set_nickname(f"{name}Bot")
        
        # Start message processor
        msg_thread = threading.Thread(target=process_messages)
        msg_thread.daemon = True
        msg_thread.start()
        
        client.run()

# Start multiple bots
bots = [
    ('scout1', 'scout'),
    ('guard1', 'guard'),
]

threads = []
for bot_name, bot_role in bots:
    thread = threading.Thread(
        target=run_bot,
        args=(bot_name, bot_role, bot_comm)
    )
    thread.start()
    threads.append(thread)

# Wait for all bots
for thread in threads:
    thread.join()
```

### Plugin System

```python
from pyreborn import RebornClient
import importlib
import os

class PluginBot:
    def __init__(self, client):
        self.client = client
        self.plugins = {}
        self.load_plugins()
        
    def load_plugins(self):
        plugin_dir = 'plugins'
        if not os.path.exists(plugin_dir):
            os.makedirs(plugin_dir)
            
        for filename in os.listdir(plugin_dir):
            if filename.endswith('.py') and not filename.startswith('_'):
                module_name = filename[:-3]
                try:
                    module = importlib.import_module(f'plugins.{module_name}')
                    if hasattr(module, 'Plugin'):
                        plugin = module.Plugin(self.client)
                        self.plugins[module_name] = plugin
                        plugin.enable()
                        print(f"Loaded plugin: {module_name}")
                except Exception as e:
                    print(f"Failed to load plugin {module_name}: {e}")
    
    def reload_plugin(self, name):
        if name in self.plugins:
            self.plugins[name].disable()
            del self.plugins[name]
            
        # Reload the module
        module = importlib.reload(importlib.import_module(f'plugins.{name}'))
        if hasattr(module, 'Plugin'):
            plugin = module.Plugin(self.client)
            self.plugins[name] = plugin
            plugin.enable()

# Example plugin file: plugins/greeter.py
"""
class Plugin:
    def __init__(self, client):
        self.client = client
        
    def enable(self):
        self.client.events.subscribe('player_joined', self.on_join)
        
    def disable(self):
        self.client.events.unsubscribe('player_joined', self.on_join)
        
    def on_join(self, event):
        player = event['player']
        self.client.set_chat(f"Welcome {player.nickname}!")
"""

client = RebornClient("localhost", 14900)
bot = PluginBot(client)

if client.connect() and client.login("pluginbot", "password"):
    client.set_nickname("PluginBot")
    client.run()
```

## Performance Tips

### 1. Use Event Queues for Heavy Processing

```python
import queue
import threading

class PerformantBot:
    def __init__(self, client):
        self.client = client
        self.work_queue = queue.Queue()
        self.start_worker()
        
    def start_worker(self):
        def worker():
            while True:
                try:
                    work = self.work_queue.get(timeout=1)
                    self.process_work(work)
                except queue.Empty:
                    continue
                    
        thread = threading.Thread(target=worker)
        thread.daemon = True
        thread.start()
        
    def on_event(self, event):
        # Don't process in event handler
        self.work_queue.put(event)
        
    def process_work(self, event):
        # Do heavy processing here
        pass
```

### 2. Batch Operations

```python
class BatchBot:
    def __init__(self, client):
        self.client = client
        self.pending_messages = []
        self.last_batch_time = time.time()
        
    def queue_message(self, message):
        self.pending_messages.append(message)
        
        # Send batch every second or when buffer is full
        if (time.time() - self.last_batch_time > 1.0 or 
            len(self.pending_messages) > 10):
            self.send_batch()
            
    def send_batch(self):
        if self.pending_messages:
            # Send all at once
            combined = " | ".join(self.pending_messages[:5])  # Max 5
            self.client.set_chat(combined)
            self.pending_messages = self.pending_messages[5:]
            self.last_batch_time = time.time()
```

### 3. Cache Expensive Calculations

```python
class CachedBot:
    def __init__(self, client):
        self.client = client
        self.distance_cache = {}
        self.cache_time = {}
        self.cache_ttl = 1.0  # 1 second TTL
        
    def get_distance(self, x1, y1, x2, y2):
        key = (x1, y1, x2, y2)
        now = time.time()
        
        # Check cache
        if key in self.distance_cache:
            if now - self.cache_time[key] < self.cache_ttl:
                return self.distance_cache[key]
                
        # Calculate and cache
        dist = math.sqrt((x2-x1)**2 + (y2-y1)**2)
        self.distance_cache[key] = dist
        self.cache_time[key] = now
        return dist
```

## Common Pitfalls

### 1. Blocking in Event Handlers

```python
# BAD - Blocks event processing
def on_player_joined(event):
    time.sleep(5)  # Don't do this!
    client.set_chat("Welcome!")

# GOOD - Use threading
def on_player_joined(event):
    def greet_later():
        time.sleep(5)
        client.set_chat("Welcome!")
    
    threading.Thread(target=greet_later).start()
```

### 2. Not Handling Disconnections

```python
# BAD - Assumes always connected
while True:
    client.move_to(30, 30)
    time.sleep(1)

# GOOD - Check connection
while client.connected:
    client.move_to(30, 30)
    time.sleep(1)
```

### 3. Memory Leaks with Events

```python
# BAD - Creates new handler each time
def start_tracking():
    def handler(event):
        print(event)
    client.events.subscribe('player_moved', handler)
    # handler reference is lost!

# GOOD - Keep handler reference
class Tracker:
    def __init__(self, client):
        self.client = client
        self.handler = self.on_moved
        
    def start(self):
        self.client.events.subscribe('player_moved', self.handler)
        
    def stop(self):
        self.client.events.unsubscribe('player_moved', self.handler)
        
    def on_moved(self, event):
        print(event)
```

### 4. Rate Limiting Issues

```python
# BAD - Too many packets
for i in range(100):
    client.move(1, 0)  # Instant spam!

# GOOD - Respect rate limits
for i in range(100):
    client.move(1, 0)
    time.sleep(0.1)  # Rate limit
```

### 5. Not Validating Data

```python
# BAD - Assumes player exists
def on_chat(event):
    player = event['player']
    print(player.nickname)  # What if player is None?

# GOOD - Validate first
def on_chat(event):
    player = event.get('player')
    if player and hasattr(player, 'nickname'):
        print(player.nickname)
```

## Debugging Tips

### Enable Logging

```python
import logging

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Log all events
def debug_handler(event):
    logging.debug(f"Event received: {event}")

for event_type in ['player_joined', 'player_left', 'player_moved']:
    client.events.subscribe(event_type, debug_handler)
```

### Create Test Harness

```python
class BotTester:
    def __init__(self, bot_class):
        self.bot_class = bot_class
        self.client = RebornClient("localhost", 14900)
        
    def test_connection(self):
        assert self.client.connect(), "Connection failed"
        assert self.client.login("test", "test"), "Login failed"
        self.client.disconnect()
        
    def test_movement(self):
        if self.client.connect() and self.client.login("test", "test"):
            start_x = self.client.player_x
            self.client.move(5, 0)
            time.sleep(0.5)
            assert self.client.player_x > start_x, "Movement failed"
```

Happy bot building! 🤖