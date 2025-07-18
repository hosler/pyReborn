# Classic Reborn Client - Development Guide

This guide covers contributing to and extending the Classic Reborn Client, including adding new features, debugging, and following the established patterns.

## Development Environment Setup

### Prerequisites

```bash
# Install Python 3.8 or higher
python --version  # Should be 3.8+

# Install PyReborn in development mode
cd pyReborn
pip install -e ".[dev]"

# Verify Pygame installation
python -c "import pygame; print(pygame.version.ver)"

# Install additional development tools (optional)
pip install black flake8 mypy
```

### Asset Requirements

The client requires game assets that are not included in the repository:

```
assets/
├── pics1.png           # Main tileset (512x512 or larger)
├── sprites.png         # Player sprites
├── ganis/              # GANI animation files
│   ├── body.gani
│   ├── head0.gani
│   ├── sword1.gani
│   └── ... other animations
└── sounds/             # Sound effects (optional)
    ├── sword.wav
    ├── step.wav
    └── ... other sounds
```

Contact the project maintainers for access to the required assets.

## Architecture Overview

### Manager-Based Design

The client follows a modular architecture where each major system is implemented as a manager:

```python
# Core pattern for all managers
class SampleManager:
    def __init__(self, events, dependency1, dependency2):
        self.events = events
        self.dependency1 = dependency1
        self.dependency2 = dependency2
        
        # Subscribe to relevant events
        events.subscribe('relevant_event', self._on_relevant_event)
        
        # Initialize state
        self._initialize()
    
    def _initialize(self):
        """Setup initial state"""
        pass
    
    def update(self, dt: float):
        """Update manager state (called every frame)"""
        pass
    
    def _on_relevant_event(self, event):
        """Handle subscribed events"""
        pass
```

### Main Client Responsibilities

The `ClassicRebornClient` serves as the central coordinator:

1. **Initialization**: Creates and connects all managers
2. **Event Coordination**: Routes events between managers
3. **Game Loop**: Manages the main update/render cycle
4. **Resource Management**: Handles startup and shutdown

## Key Systems

### 1. Rendering System

**File**: `renderer.py`

The renderer handles all graphics output using Pygame:

```python
class Renderer:
    def __init__(self, screen, events, tile_defs, item_manager, bush_handler):
        self.screen = screen
        self.events = events
        
        # Graphics resources
        self.tileset = None
        self.sprites = None
        
        # Camera system
        self.camera_x = 0
        self.camera_y = 0
        
        # Load graphics
        self._load_graphics()
    
    def render(self):
        """Main render method called every frame"""
        self.screen.fill((0, 0, 0))  # Clear screen
        
        # Render in layers
        self._render_tiles()
        self._render_items()
        self._render_players()
        self._render_ui()
        
        pygame.display.flip()
```

**Adding New Visual Elements**:

```python
def _render_new_element(self):
    """Example of adding a new renderable element"""
    for element in self.new_elements:
        # Calculate screen position
        screen_x = element.x * TILE_SIZE - self.camera_x
        screen_y = element.y * TILE_SIZE - self.camera_y
        
        # Only render if visible
        if self._is_on_screen(screen_x, screen_y):
            self.screen.blit(element.sprite, (screen_x, screen_y))
```

### 2. Animation System

**File**: `animation_manager.py`

Manages player animations and GANI file playback:

```python
class AnimationManager:
    def __init__(self, events, gani_manager):
        self.events = events
        self.gani_manager = gani_manager
        
        # Per-player animation state
        self.player_animations = {}
        
        # Subscribe to animation triggers
        events.subscribe('player_moved', self._on_player_moved)
        events.subscribe('player_sword', self._on_player_sword)
    
    def set_player_animation(self, player_id: int, animation_name: str):
        """Set animation for a specific player"""
        if player_id not in self.player_animations:
            self.player_animations[player_id] = {
                'current': 'idle',
                'frame': 0,
                'start_time': time.time()
            }
        
        anim_state = self.player_animations[player_id]
        if anim_state['current'] != animation_name:
            anim_state['current'] = animation_name
            anim_state['frame'] = 0
            anim_state['start_time'] = time.time()
```

**Adding New Animations**:

1. Add GANI file to `assets/ganis/`
2. Create animation trigger in relevant system
3. Add animation mapping in animation manager

### 3. Physics System

**File**: `physics.py`

Handles collision detection and movement validation:

```python
class Physics:
    def __init__(self, events, tile_defs):
        self.events = events
        self.tile_defs = tile_defs
    
    def can_move_to(self, x: float, y: float, level) -> bool:
        """Check if position is walkable"""
        # Get tile at position
        tile_x = int(x)
        tile_y = int(y)
        
        if not (0 <= tile_x < 64 and 0 <= tile_y < 64):
            return False
        
        tiles = level.get_board_tiles_2d()
        tile_id = tiles[tile_y][tile_x]
        
        return not self.tile_defs.is_blocking(tile_id)
    
    def check_collision_box(self, x: float, y: float, width: float, height: float, level) -> bool:
        """Check collision for a rectangular area"""
        # Check all corners of the collision box
        corners = [
            (x, y),
            (x + width, y),
            (x, y + height),
            (x + width, y + height)
        ]
        
        for corner_x, corner_y in corners:
            if not self.can_move_to(corner_x, corner_y, level):
                return True  # Collision detected
        
        return False  # No collision
```

### 4. Input System

**File**: `input_manager.py`

Processes keyboard and mouse input:

```python
class InputManager:
    def __init__(self, events):
        self.events = events
        
        # Key state tracking
        self.keys_pressed = set()
        self.keys_just_pressed = set()
        self.keys_just_released = set()
        
        # Input callbacks
        self.key_callbacks = {}
        self.mouse_callbacks = {}
    
    def update(self):
        """Process input events"""
        self.keys_just_pressed.clear()
        self.keys_just_released.clear()
        
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                self.keys_pressed.add(event.key)
                self.keys_just_pressed.add(event.key)
                self._trigger_key_callback('keydown', event.key)
                
            elif event.type == pygame.KEYUP:
                self.keys_pressed.discard(event.key)
                self.keys_just_released.add(event.key)
                self._trigger_key_callback('keyup', event.key)
```

**Adding New Controls**:

```python
# Register input callback
input_manager.register_key_callback('keydown', pygame.K_f, self._on_special_action)

def _on_special_action(self):
    """Handle special action key press"""
    self.events.emit('special_action_triggered', {})
```

## Adding New Features

### 1. Creating a New Manager

Follow this pattern when adding new systems:

```python
# Create: new_feature_manager.py
class NewFeatureManager:
    def __init__(self, events, dependency1, dependency2):
        self.events = events
        self.dependency1 = dependency1
        self.dependency2 = dependency2
        
        # Feature state
        self.feature_enabled = True
        self.feature_data = {}
        
        # Subscribe to events
        events.subscribe('relevant_event', self._on_relevant_event)
        events.subscribe('player_action', self._on_player_action)
    
    def enable_feature(self):
        """Enable the new feature"""
        self.feature_enabled = True
        self.events.emit('feature_enabled', {'feature': 'new_feature'})
    
    def disable_feature(self):
        """Disable the new feature"""
        self.feature_enabled = False
        self.events.emit('feature_disabled', {'feature': 'new_feature'})
    
    def update(self, dt: float):
        """Update feature state"""
        if not self.feature_enabled:
            return
            
        # Update feature logic here
        pass
    
    def _on_relevant_event(self, event):
        """Handle events relevant to this feature"""
        if not self.feature_enabled:
            return
            
        # Process event
        pass
```

### 2. Integrating with Main Client

Add the new manager to the main client:

```python
# In classic_reborn_client.py

def _initialize_managers(self):
    # ... existing managers ...
    
    # Add new manager
    self.new_feature_manager = NewFeatureManager(
        self.events,
        self.dependency1,
        self.dependency2
    )

def _update_managers(self, dt: float):
    # ... existing updates ...
    
    # Update new manager
    self.new_feature_manager.update(dt)
```

### 3. Adding Configuration

Add configuration options for new features:

```python
# In classic_constants.py
class NewFeatureConstants:
    FEATURE_ENABLED = True
    FEATURE_UPDATE_RATE = 0.1
    FEATURE_MAX_ITEMS = 100

# In main client initialization
self.new_feature_manager = NewFeatureManager(
    self.events,
    self.dependency1,
    self.dependency2,
    enabled=NewFeatureConstants.FEATURE_ENABLED,
    update_rate=NewFeatureConstants.FEATURE_UPDATE_RATE
)
```

## Working with Events

### Event-Driven Development

The client uses PyReborn's event system for loose coupling:

```python
# Emitting events
self.events.emit('custom_event', {
    'event_type': 'custom_event',
    'data': some_data,
    'timestamp': time.time()
})

# Subscribing to events
def _on_custom_event(self, event):
    data = event.get('data')
    # Handle the event
    
events.subscribe('custom_event', self._on_custom_event)
```

### Common Event Patterns

```python
# Player action events
events.emit('player_action', {
    'player_id': player.id,
    'action': 'sword',
    'position': (player.x, player.y)
})

# UI events
events.emit('ui_notification', {
    'message': 'Feature activated!',
    'duration': 3.0,
    'type': 'info'
})

# State change events
events.emit('game_state_changed', {
    'old_state': old_state,
    'new_state': new_state,
    'reason': 'player_action'
})
```

## Testing and Debugging

### Debug Mode

Enable debug features during development:

```python
# In classic_reborn_client.py
DEBUG_MODE = True
SHOW_COLLISION_DEBUG = True
SHOW_FPS = True

if DEBUG_MODE:
    # Enable debug rendering
    self.renderer.debug_mode = True
    
    # Enable performance monitoring
    self.enable_performance_monitoring()
    
    # Enable verbose logging
    logging.basicConfig(level=logging.DEBUG)
```

### Unit Testing

Create tests for individual managers:

```python
# Create: testing/test_new_feature.py
import unittest
from unittest.mock import Mock, MagicMock

from new_feature_manager import NewFeatureManager

class TestNewFeatureManager(unittest.TestCase):
    def setUp(self):
        self.events = Mock()
        self.dependency1 = Mock()
        self.dependency2 = Mock()
        
        self.manager = NewFeatureManager(
            self.events,
            self.dependency1,
            self.dependency2
        )
    
    def test_feature_initialization(self):
        """Test that feature initializes correctly"""
        self.assertTrue(self.manager.feature_enabled)
        self.assertEqual(self.manager.feature_data, {})
    
    def test_enable_disable_feature(self):
        """Test enabling and disabling feature"""
        self.manager.disable_feature()
        self.assertFalse(self.manager.feature_enabled)
        
        self.manager.enable_feature()
        self.assertTrue(self.manager.feature_enabled)
    
    def test_event_handling(self):
        """Test that events are handled correctly"""
        test_event = {'type': 'relevant_event', 'data': 'test'}
        self.manager._on_relevant_event(test_event)
        
        # Add assertions based on expected behavior

if __name__ == '__main__':
    unittest.main()
```

### Integration Testing

Test complete features with a test client:

```python
# Create: testing/integration_test.py
from classic_reborn_client import ClassicRebornClient

class TestClient(ClassicRebornClient):
    def __init__(self):
        super().__init__()
        self.test_mode = True
        
    def run_test_scenario(self, scenario_name: str):
        """Run a specific test scenario"""
        if scenario_name == "movement_test":
            self._test_movement()
        elif scenario_name == "feature_test":
            self._test_new_feature()
    
    def _test_movement(self):
        """Test player movement"""
        # Simulate player movement
        initial_pos = (self.player.x, self.player.y)
        self.movement_controller.move_to(30, 30)
        
        # Wait for movement to complete
        while self.movement_controller.is_moving:
            self.update(1/60)  # 60 FPS simulation
        
        # Verify movement
        final_pos = (self.player.x, self.player.y)
        assert final_pos != initial_pos, "Player should have moved"
        
    def _test_new_feature(self):
        """Test new feature functionality"""
        # Test feature activation
        self.new_feature_manager.enable_feature()
        assert self.new_feature_manager.feature_enabled
        
        # Test feature behavior
        # ... add specific tests
```

### Performance Testing

Monitor performance during development:

```python
import cProfile
import time
from collections import deque

class PerformanceMonitor:
    def __init__(self):
        self.frame_times = deque(maxlen=1000)
        self.update_times = {}
        
    def start_frame(self):
        self.frame_start = time.time()
        
    def end_frame(self):
        frame_time = time.time() - self.frame_start
        self.frame_times.append(frame_time)
        
    def start_update(self, component: str):
        self.update_times[component] = time.time()
        
    def end_update(self, component: str):
        if component in self.update_times:
            duration = time.time() - self.update_times[component]
            print(f"{component}: {duration*1000:.2f}ms")
            
    def get_stats(self):
        if not self.frame_times:
            return {}
            
        avg_frame_time = sum(self.frame_times) / len(self.frame_times)
        fps = 1.0 / avg_frame_time if avg_frame_time > 0 else 0
        
        return {
            'fps': fps,
            'avg_frame_time_ms': avg_frame_time * 1000,
            'frame_count': len(self.frame_times)
        }
```

## Common Development Tasks

### 1. Adding New Tile Types

```python
# In tiledefs.txt, add new tile definition
# Format: tile_id type water_level
1234 22 0  # Blocking tile
1235 0 1   # Water tile

# In tile_defs.py, add support for new behavior
def is_special_tile(self, tile_id: int) -> bool:
    """Check if tile has special behavior"""
    return tile_id in self.special_tiles

# In physics.py, handle new tile behavior
def can_move_to(self, x: float, y: float, level) -> bool:
    tile_id = self._get_tile_at(x, y, level)
    
    if self.tile_defs.is_blocking(tile_id):
        return False
    elif self.tile_defs.is_special_tile(tile_id):
        return self._handle_special_tile(tile_id, x, y)
    
    return True
```

### 2. Adding New Player Actions

```python
# In input_manager.py, add key binding
KEY_BINDINGS = {
    # ... existing bindings ...
    'special_action': pygame.K_x,
}

def _setup_key_callbacks(self):
    # ... existing callbacks ...
    self.register_key_callback('keydown', self.KEY_BINDINGS['special_action'], 
                              self._on_special_action)

def _on_special_action(self):
    self.events.emit('player_special_action', {
        'player_id': self.client.player.id
    })

# In main client, handle the action
def _on_player_special_action(self, event):
    player_id = event.get('player_id')
    
    # Send to server
    self.connection_manager.send_special_action()
    
    # Update local state
    self.animation_manager.set_player_animation(player_id, 'special')
```

### 3. Adding UI Elements

```python
# In ui_manager.py
class UIManager:
    def __init__(self, screen, events, font):
        # ... existing initialization ...
        self.new_ui_element = NewUIElement()
    
    def render(self):
        # ... existing rendering ...
        self.new_ui_element.render(self.screen)
    
    def update(self, dt: float):
        # ... existing updates ...
        self.new_ui_element.update(dt)

class NewUIElement:
    def __init__(self):
        self.visible = True
        self.position = (10, 10)
        self.text = "New UI Element"
    
    def render(self, screen):
        if self.visible:
            # Render UI element
            pass
    
    def update(self, dt: float):
        # Update UI element state
        pass
```

## Code Style Guidelines

### Python Style

Follow PEP 8 with these project-specific additions:

```python
# Class names: PascalCase
class FeatureManager:
    pass

# Method names: snake_case
def update_feature_state(self):
    pass

# Constants: UPPER_SNAKE_CASE
FEATURE_ENABLED = True
MAX_FEATURE_COUNT = 100

# Private methods: leading underscore
def _internal_helper(self):
    pass

# Event handlers: _on_event_name pattern
def _on_player_moved(self, event):
    pass
```

### Documentation

Document all public methods:

```python
def move_player(self, x: float, y: float) -> bool:
    """Move player to specified coordinates.
    
    Args:
        x: Target X coordinate (0-63.99)
        y: Target Y coordinate (0-63.99)
        
    Returns:
        True if movement started successfully, False if blocked
        
    Raises:
        ValueError: If coordinates are out of bounds
    """
    if not (0 <= x < 64 and 0 <= y < 64):
        raise ValueError(f"Coordinates out of bounds: ({x}, {y})")
        
    return self._start_movement(x, y)
```

### Error Handling

Use consistent error handling patterns:

```python
try:
    result = risky_operation()
except SpecificError as e:
    self.logger.error(f"Specific error in {context}: {e}")
    # Handle specific error
except Exception as e:
    self.logger.error(f"Unexpected error in {context}: {e}")
    # Handle unexpected error
finally:
    # Cleanup code
    pass
```

## Contributing Guidelines

### Pull Request Process

1. **Create Feature Branch**: `git checkout -b feature/new-feature`
2. **Implement Feature**: Follow the patterns described above
3. **Add Tests**: Create unit and integration tests
4. **Update Documentation**: Add to relevant docs
5. **Test Thoroughly**: Run all existing tests
6. **Submit PR**: Include clear description of changes

### Code Review Checklist

- [ ] Follows established architectural patterns
- [ ] Includes appropriate error handling
- [ ] Has unit tests for new functionality
- [ ] Documentation is updated
- [ ] Performance impact is considered
- [ ] No unnecessary dependencies added
- [ ] Event-driven design is followed
- [ ] Code style follows guidelines

---

This development guide provides the foundation for contributing to the Classic Reborn Client. The modular architecture makes it easy to add new features while maintaining code quality and performance.