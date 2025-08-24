# PyReborn Examples

This directory contains examples demonstrating different aspects of the PyReborn library.

## 🎯 API Examples (`api/`)

Demonstrates different API patterns available in PyReborn:

- **`context_manager_example.py`** - Using context managers for automatic cleanup
- **`builder_example.py`** - Fluent builder pattern for complex configurations
- **`async_example.py`** - Async/await support for modern Python applications
- **`event_handling_example.py`** - Event-driven programming with decorators
- **`complete_api_showcase.py`** - Comprehensive demonstration of all API patterns

## 🤖 Bot Examples (`bots/`)

Example bots showing practical PyReborn usage:

- **`simple_bot.py`** - Basic connection, movement, and chat
- **`comprehensive_test_bot.py`** - Full feature testing and validation
- **`coordinate_example_bot.py`** - Coordinate system and movement validation
- **`movement_example_bot.py`** - Movement patterns and navigation
- **`exploration_bot.py`** - Automated exploration and level traversal

## 🎮 Game Client (`games/reborn_modern/`)

Complete game client implementation demonstrating:

- Full graphical interface
- Real-time rendering
- User input handling
- Game state management
- Advanced PyReborn integration

See `games/reborn_modern/README.md` for detailed information.

## Running Examples

### API Examples
```bash
cd examples/api
python context_manager_example.py
python builder_example.py
python complete_api_showcase.py
```

### Bot Examples
```bash
cd examples/bots
python simple_bot.py your_username your_password
python comprehensive_test_bot.py your_username your_password
```

### Game Client
```bash
cd examples/games/reborn_modern
python main.py
```

## Requirements

All examples use the core PyReborn library with zero external dependencies. The game client may require additional packages like pygame - see its specific README for details.

## Contributing

When adding new examples:

1. Use generic credentials (your_username, your_password)
2. Include clear docstrings explaining the purpose
3. Add command-line argument parsing for flexibility
4. Use context managers for resource management
5. Include proper error handling