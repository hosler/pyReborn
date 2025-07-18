# Bot Development Guide

This guide covers creating bots and automated scripts using the PyReborn library, from simple movement bots to complex AI systems.

## Getting Started

### Basic Bot Template

```python
from pyreborn import RebornClient
import time
import random

class BasicBot:
    def __init__(self, username: str, password: str, server: str = "localhost", port: int = 14900):
        self.client = RebornClient(server, port)
        self.username = username
        self.password = password
        self.running = False
        
    def connect(self) -> bool:
        """Connect to server and login"""
        if not self.client.connect():
            print("Failed to connect to server")
            return False
            
        if not self.client.login(self.username, self.password):
            print("Failed to login")
            return False
            
        print(f"Successfully logged in as {self.username}")
        return True
    
    def run(self):
        """Main bot loop"""
        if not self.connect():
            return
            
        self.running = True
        self.client.set_nickname("MyBot")
        self.client.set_chat("Hello! I'm a bot.")
        
        try:
            while self.running:
                self.update()
                time.sleep(0.1)  # 10 FPS update rate
        except KeyboardInterrupt:
            print("Bot stopped by user")
        finally:
            self.client.disconnect()
    
    def update(self):
        """Override this method with bot behavior"""
        pass

# Usage
if __name__ == "__main__":
    bot = BasicBot("mybot", "password")
    bot.run()
```

## Bot Patterns

### 1. Random Walker Bot

```python
class RandomWalkerBot(BasicBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_move_time = 0
        self.move_interval = 2.0  # Move every 2 seconds
    
    def update(self):
        current_time = time.time()
        if current_time - self.last_move_time > self.move_interval:
            # Move to random position
            x = random.randint(0, 63)
            y = random.randint(0, 63)
            self.client.move_to(x, y)
            self.last_move_time = current_time
            
            # Occasionally chat
            if random.random() < 0.1:  # 10% chance
                messages = [
                    "Walking around...",
                    "Nice weather today!",
                    "Just exploring!",
                    "Beep boop, I'm a bot!"
                ]
                self.client.set_chat(random.choice(messages))
```

### 2. Follower Bot

```python
class FollowerBot(BasicBot):
    def __init__(self, target_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_name = target_name
        self.target_player = None
        self.follow_distance = 2.0
        
        # Subscribe to events
        self.client.events.subscribe('player_added', self._on_player_added)
        self.client.events.subscribe('player_moved', self._on_player_moved)
        self.client.events.subscribe('player_removed', self._on_player_removed)
    
    def _on_player_added(self, event):
        player = event.get('player')
        if player and player.name == self.target_name:
            self.target_player = player
            self.client.set_chat(f"Following {self.target_name}!")
    
    def _on_player_moved(self, event):
        player = event.get('player')
        if player and player.name == self.target_name:
            self.target_player = player
            self._follow_target()
    
    def _on_player_removed(self, event):
        player = event.get('player')
        if player and player.name == self.target_name:
            self.target_player = None
            self.client.set_chat(f"{self.target_name} left :(")
    
    def _follow_target(self):
        if not self.target_player:
            return
            
        # Calculate distance to target
        my_pos = (self.client.player.x, self.client.player.y)
        target_pos = (self.target_player.x, self.target_player.y)
        
        distance = ((target_pos[0] - my_pos[0]) ** 2 + 
                   (target_pos[1] - my_pos[1]) ** 2) ** 0.5
        
        # Follow if too far away
        if distance > self.follow_distance:
            self.client.move_to(target_pos[0], target_pos[1])
    
    def update(self):
        # Periodically check if we need to follow
        if self.target_player:
            self._follow_target()
```

### 3. Event-Driven Reactive Bot

```python
class ReactiveBot(BasicBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_event_handlers()
    
    def setup_event_handlers(self):
        events = self.client.events
        
        # React to chat messages
        events.subscribe('chat_message', self._on_chat_message)
        
        # React to new players
        events.subscribe('player_added', self._on_player_added)
        
        # React to items
        events.subscribe('item_added', self._on_item_added)
        
        # React to level changes
        events.subscribe('level_entered', self._on_level_entered)
    
    def _on_chat_message(self, event):
        message = event.get('message', '')
        player_name = event.get('player_name', 'Unknown')
        
        # Respond to greetings
        if any(word in message.lower() for word in ['hello', 'hi', 'hey']):
            self.client.set_chat(f"Hello {player_name}!")
        
        # Respond to questions about time
        elif 'time' in message.lower():
            current_time = time.strftime("%H:%M:%S")
            self.client.set_chat(f"The time is {current_time}")
        
        # Echo command
        elif message.startswith('!echo '):
            echo_text = message[6:]  # Remove '!echo '
            self.client.set_chat(f"Echo: {echo_text}")
    
    def _on_player_added(self, event):
        player = event.get('player')
        if player:
            self.client.set_chat(f"Welcome {player.name}!")
    
    def _on_item_added(self, event):
        item = event.get('item')
        if item:
            # Move towards item to collect it
            self.client.move_to(item.x, item.y)
            self.client.set_chat("Ooh, an item!")
    
    def _on_level_entered(self, event):
        level = event.get('level')
        if level:
            self.client.set_chat(f"Entered level: {level.nickname}")
```

## Advanced Bot Techniques

### 1. Pathfinding Bot

```python
from collections import deque
from typing import List, Tuple, Optional

class PathfindingBot(BasicBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_path = []
        self.path_index = 0
    
    def find_path(self, start: Tuple[int, int], goal: Tuple[int, int]) -> List[Tuple[int, int]]:
        """A* pathfinding implementation"""
        level = self.client.level_manager.get_current_level()
        if not level:
            return []
        
        tiles = level.get_board_tiles_2d()
        
        def is_walkable(x: int, y: int) -> bool:
            if x < 0 or x >= 64 or y < 0 or y >= 64:
                return False
            tile_id = tiles[y][x]
            return not self.is_tile_blocking(tile_id)
        
        def heuristic(a: Tuple[int, int], b: Tuple[int, int]) -> float:
            return abs(a[0] - b[0]) + abs(a[1] - b[1])
        
        # A* algorithm
        open_set = [(0, start)]
        came_from = {}
        g_score = {start: 0}
        f_score = {start: heuristic(start, goal)}
        
        while open_set:
            current = min(open_set, key=lambda x: f_score.get(x[1], float('inf')))[1]
            open_set = [(f, pos) for f, pos in open_set if pos != current]
            
            if current == goal:
                # Reconstruct path
                path = []
                while current in came_from:
                    path.append(current)
                    current = came_from[current]
                path.append(start)
                return path[::-1]
            
            for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                neighbor = (current[0] + dx, current[1] + dy)
                
                if not is_walkable(neighbor[0], neighbor[1]):
                    continue
                
                tentative_g = g_score[current] + 1
                
                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score[neighbor] = tentative_g + heuristic(neighbor, goal)
                    
                    if (f_score[neighbor], neighbor) not in open_set:
                        open_set.append((f_score[neighbor], neighbor))
        
        return []  # No path found
    
    def move_to_with_pathfinding(self, target_x: int, target_y: int):
        """Move to target using pathfinding"""
        start = (int(self.client.player.x), int(self.client.player.y))
        goal = (target_x, target_y)
        
        self.current_path = self.find_path(start, goal)
        self.path_index = 0
        
        if self.current_path:
            self.client.set_chat(f"Pathfinding to ({target_x}, {target_y})")
        else:
            self.client.set_chat("No path found!")
    
    def update(self):
        # Execute current path
        if self.current_path and self.path_index < len(self.current_path):
            target = self.current_path[self.path_index]
            current_pos = (int(self.client.player.x), int(self.client.player.y))
            
            # Check if we've reached the current waypoint
            if current_pos == target:
                self.path_index += 1
                if self.path_index < len(self.current_path):
                    next_target = self.current_path[self.path_index]
                    self.client.move_to(next_target[0], next_target[1])
                else:
                    self.client.set_chat("Destination reached!")
                    self.current_path = []
```

### 2. State Machine Bot

```python
from enum import Enum

class BotState(Enum):
    IDLE = "idle"
    EXPLORING = "exploring"  
    FOLLOWING = "following"
    COLLECTING = "collecting"
    CHATTING = "chatting"

class StateMachineBot(BasicBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = BotState.IDLE
        self.state_data = {}
        self.state_start_time = time.time()
        
        # State transition table
        self.transitions = {
            BotState.IDLE: self._idle_transitions,
            BotState.EXPLORING: self._exploring_transitions,
            BotState.FOLLOWING: self._following_transitions,
            BotState.COLLECTING: self._collecting_transitions,
            BotState.CHATTING: self._chatting_transitions,
        }
        
        # State handlers
        self.state_handlers = {
            BotState.IDLE: self._handle_idle,
            BotState.EXPLORING: self._handle_exploring,
            BotState.FOLLOWING: self._handle_following,
            BotState.COLLECTING: self._handle_collecting,
            BotState.CHATTING: self._handle_chatting,
        }
    
    def change_state(self, new_state: BotState, data: dict = None):
        """Change bot state"""
        old_state = self.state
        self.state = new_state
        self.state_data = data or {}
        self.state_start_time = time.time()
        
        print(f"State change: {old_state.value} -> {new_state.value}")
        self.client.set_chat(f"State: {new_state.value}")
    
    def time_in_state(self) -> float:
        """Get time spent in current state"""
        return time.time() - self.state_start_time
    
    def update(self):
        # Handle current state
        handler = self.state_handlers.get(self.state)
        if handler:
            handler()
        
        # Check for state transitions
        transition_checker = self.transitions.get(self.state)
        if transition_checker:
            transition_checker()
    
    # State handlers
    def _handle_idle(self):
        # Do nothing, wait for events
        pass
    
    def _handle_exploring(self):
        # Random exploration
        if self.time_in_state() > 3.0:  # Explore for 3 seconds
            x = random.randint(0, 63)
            y = random.randint(0, 63)
            self.client.move_to(x, y)
            self.state_start_time = time.time()  # Reset timer
    
    def _handle_following(self):
        target_name = self.state_data.get('target_name')
        # Implementation similar to FollowerBot
        pass
    
    def _handle_collecting(self):
        target_item = self.state_data.get('target_item')
        if target_item:
            self.client.move_to(target_item.x, target_item.y)
    
    def _handle_chatting(self):
        # Chat for a while then return to previous state
        if self.time_in_state() > 5.0:
            previous_state = self.state_data.get('previous_state', BotState.IDLE)
            self.change_state(previous_state)
    
    # State transitions
    def _idle_transitions(self):
        # Randomly start exploring
        if random.random() < 0.01:  # 1% chance per update
            self.change_state(BotState.EXPLORING)
    
    def _exploring_transitions(self):
        # Check for items to collect
        level = self.client.level_manager.get_current_level()
        if level and level.items:
            closest_item = min(level.items, key=lambda item: 
                ((item.x - self.client.player.x) ** 2 + 
                 (item.y - self.client.player.y) ** 2) ** 0.5)
            
            distance = ((closest_item.x - self.client.player.x) ** 2 + 
                       (closest_item.y - self.client.player.y) ** 2) ** 0.5
            
            if distance < 10:  # Item within 10 tiles
                self.change_state(BotState.COLLECTING, {'target_item': closest_item})
        
        # Return to idle after exploring for a while
        elif self.time_in_state() > 30.0:
            self.change_state(BotState.IDLE)
    
    def _following_transitions(self):
        # Stop following if target is gone
        target_name = self.state_data.get('target_name')
        # Check if player still exists
        pass
    
    def _collecting_transitions(self):
        # Return to exploring when item is collected or unreachable
        target_item = self.state_data.get('target_item')
        if not target_item or self.time_in_state() > 10.0:
            self.change_state(BotState.EXPLORING)
    
    def _chatting_transitions(self):
        # Handled in _handle_chatting
        pass
```

## Bot Utilities

### 1. Bot Manager for Multiple Bots

```python
import threading
from typing import List, Dict

class BotManager:
    def __init__(self):
        self.bots: Dict[str, BasicBot] = {}
        self.threads: Dict[str, threading.Thread] = {}
    
    def add_bot(self, name: str, bot: BasicBot):
        """Add a bot to the manager"""
        self.bots[name] = bot
    
    def start_bot(self, name: str):
        """Start a bot in a separate thread"""
        if name not in self.bots:
            print(f"Bot {name} not found")
            return
        
        bot = self.bots[name]
        thread = threading.Thread(target=bot.run, daemon=True)
        self.threads[name] = thread
        thread.start()
        print(f"Started bot: {name}")
    
    def stop_bot(self, name: str):
        """Stop a running bot"""
        if name in self.bots:
            self.bots[name].running = False
        if name in self.threads:
            self.threads[name].join(timeout=5.0)
            del self.threads[name]
        print(f"Stopped bot: {name}")
    
    def start_all(self):
        """Start all bots"""
        for name in self.bots.keys():
            self.start_bot(name)
    
    def stop_all(self):
        """Stop all bots"""
        for name in list(self.threads.keys()):
            self.stop_bot(name)

# Usage
manager = BotManager()
manager.add_bot("explorer", RandomWalkerBot("explorer1", "pass"))
manager.add_bot("follower", FollowerBot("target_player", "follower1", "pass"))
manager.add_bot("reactor", ReactiveBot("reactor1", "pass"))

# Start all bots
manager.start_all()

# Stop specific bot
manager.stop_bot("explorer")

# Stop all bots
manager.stop_all()
```

### 2. Bot Configuration System

```python
import json
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class BotConfig:
    username: str
    password: str
    server: str = "localhost"
    port: int = 14900
    version: str = "2.1"
    nickname: Optional[str] = None
    auto_reconnect: bool = True
    update_rate: float = 0.1  # seconds between updates
    
    def save_to_file(self, filename: str):
        with open(filename, 'w') as f:
            json.dump(asdict(self), f, indent=2)
    
    @classmethod
    def load_from_file(cls, filename: str) -> 'BotConfig':
        with open(filename, 'r') as f:
            data = json.load(f)
        return cls(**data)

class ConfigurableBot(BasicBot):
    def __init__(self, config: BotConfig):
        super().__init__(
            config.username, 
            config.password, 
            config.server, 
            config.port
        )
        self.config = config
        self.client.version = config.version
        
    def connect(self) -> bool:
        if super().connect():
            if self.config.nickname:
                self.client.set_nickname(self.config.nickname)
            return True
        return False
    
    def run(self):
        while True:
            try:
                if not self.connect():
                    if self.config.auto_reconnect:
                        print("Reconnecting in 10 seconds...")
                        time.sleep(10)
                        continue
                    else:
                        break
                
                super().run()
                
            except Exception as e:
                print(f"Bot error: {e}")
                if self.config.auto_reconnect:
                    print("Restarting bot...")
                    time.sleep(5)
                else:
                    break

# Usage
config = BotConfig(
    username="mybot",
    password="secret",
    server="hastur.eevul.net",
    port=14912,
    version="6.034",
    nickname="SuperBot",
    auto_reconnect=True
)

# Save config
config.save_to_file("bot_config.json")

# Load and run bot
config = BotConfig.load_from_file("bot_config.json")
bot = ConfigurableBot(config)
bot.run()
```

## Performance and Best Practices

### 1. Efficient Event Handling

```python
class OptimizedBot(BasicBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.event_queue = []
        self.last_process_time = 0
        
        # Subscribe to events and queue them
        events = self.client.events
        events.subscribe('player_moved', self._queue_event)
        events.subscribe('chat_message', self._queue_event)
        events.subscribe('item_added', self._queue_event)
    
    def _queue_event(self, event):
        """Queue events for batch processing"""
        self.event_queue.append(event)
    
    def update(self):
        current_time = time.time()
        
        # Process events in batches
        if current_time - self.last_process_time > 0.1:  # 10 FPS
            self._process_event_batch()
            self.last_process_time = current_time
    
    def _process_event_batch(self):
        """Process all queued events"""
        for event in self.event_queue:
            self._handle_event(event)
        self.event_queue.clear()
    
    def _handle_event(self, event):
        event_type = event.get('type')
        if event_type == 'player_moved':
            self._handle_player_moved(event)
        elif event_type == 'chat_message':
            self._handle_chat_message(event)
        # ... handle other events
```

### 2. Resource Management

```python
class ResourceAwareBot(BasicBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.memory_limit = 100 * 1024 * 1024  # 100 MB
        self.last_cleanup = time.time()
    
    def update(self):
        super().update()
        
        # Periodic resource cleanup
        if time.time() - self.last_cleanup > 60:  # Every minute
            self._cleanup_resources()
            self.last_cleanup = time.time()
    
    def _cleanup_resources(self):
        """Clean up memory and resources"""
        import gc
        
        # Force garbage collection
        gc.collect()
        
        # Check memory usage
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        
        if memory_mb > self.memory_limit / 1024 / 1024:
            print(f"Warning: High memory usage: {memory_mb:.1f} MB")
            
        print(f"Memory usage: {memory_mb:.1f} MB")
```

### 3. Error Recovery

```python
class RobustBot(BasicBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_count = 0
        self.max_errors = 10
        self.last_error_time = 0
    
    def safe_execute(self, func, *args, **kwargs):
        """Execute function with error handling"""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            self._handle_error(e, func.__name__)
            return None
    
    def _handle_error(self, error: Exception, context: str):
        """Handle errors gracefully"""
        current_time = time.time()
        self.error_count += 1
        
        print(f"Error in {context}: {error}")
        
        # Rate limit error messages
        if current_time - self.last_error_time > 10:  # Max 1 error log per 10 seconds
            print(f"Error #{self.error_count}: {error}")
            self.last_error_time = current_time
        
        # Stop bot if too many errors
        if self.error_count > self.max_errors:
            print("Too many errors, stopping bot")
            self.running = False
    
    def update(self):
        # Wrap all operations in safe_execute
        self.safe_execute(super().update)
```

## Debugging Bots

### 1. Debug Logger

```python
import logging

class DebugBot(BasicBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_logging()
    
    def setup_logging(self):
        """Setup debug logging"""
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(f'bot_{self.username}.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(f'bot_{self.username}')
    
    def update(self):
        self.logger.debug(f"Bot update - Position: ({self.client.player.x}, {self.client.player.y})")
        super().update()
```

### 2. Performance Monitor

```python
import time
from collections import deque

class ProfiledBot(BasicBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.frame_times = deque(maxlen=100)
        self.last_frame_time = time.time()
    
    def update(self):
        start_time = time.time()
        super().update()
        
        # Track performance
        frame_time = time.time() - start_time
        self.frame_times.append(frame_time)
        
        # Log performance occasionally
        if len(self.frame_times) == 100:
            avg_frame_time = sum(self.frame_times) / len(self.frame_times)
            fps = 1.0 / avg_frame_time if avg_frame_time > 0 else 0
            print(f"Bot performance: {fps:.1f} FPS, {avg_frame_time*1000:.1f}ms avg frame time")
```

---

This guide provides a comprehensive foundation for creating bots with PyReborn. Start with the basic templates and gradually incorporate more advanced features as needed. Remember to respect server rules and be considerate of other players when running bots!