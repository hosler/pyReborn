# OpenGraal2 Documentation

Welcome to the comprehensive documentation for OpenGraal2, a modern Python implementation of the Graal Reborn client protocol and game client.

## Project Overview

OpenGraal2 consists of four main components:

1. **PyReborn Library** - Pure Python client library for Graal Reborn protocol
2. **Classic Reborn Client** - Full graphical game client built with Pygame  
3. **Reborn Server** - Docker-based game server for testing
4. **Server List Integration** - Server browser and discovery system

## Quick Start

### Installing PyReborn
```bash
cd pyReborn
pip install -e ".[dev]"
```

### Running the Game Client
```bash
cd pyReborn/examples/games/classic_reborn
./run.sh hosler 1234  # Auto-login to localhost
./run_hastur.sh       # Connect to GMAP test server
```

### Basic Bot Example
```python
from pyreborn import RebornClient

client = RebornClient("localhost", 14900)
if client.connect() and client.login("mybot", "password"):
    client.set_nickname("TestBot")
    client.set_chat("Hello from PyReborn!")
    client.move_to(30, 30)
    client.disconnect()
```

## Documentation Sections

### PyReborn Library
- [API Reference](pyreborn/api-reference.md) - Complete API documentation
- [Architecture Guide](pyreborn/architecture.md) - Library design and patterns
- [Protocol Implementation](pyreborn/protocol.md) - Graal protocol details
- [Event System](pyreborn/events.md) - Event-driven programming guide
- [Bot Development](pyreborn/bot-development.md) - Creating bots and scripts
- [Extension Guide](pyreborn/extending.md) - Customizing and extending PyReborn

### Classic Reborn Client
- [Client Overview](classic-client/overview.md) - Game client features and architecture
- [Development Guide](classic-client/development.md) - Contributing to the client
- [GMAP Support](classic-client/gmap.md) - Large world navigation
- [Graphics System](classic-client/graphics.md) - Rendering and animation
- [Audio System](classic-client/audio.md) - Sound effects and music

### Server Setup
- [Docker Server](server/docker-setup.md) - Running the test server
- [Server Configuration](server/configuration.md) - Customizing server settings
- [Level Creation](server/level-creation.md) - Creating game content

### Development
- [Contributing](development/contributing.md) - How to contribute to the project
- [Testing](development/testing.md) - Running tests and validation
- [Debugging](development/debugging.md) - Troubleshooting common issues

## Key Features

### PyReborn Library
- ✅ **Pure Python** - No external dependencies except for development
- ✅ **Full Protocol Support** - Complete GServer-v2 implementation  
- ✅ **Event-Driven Architecture** - Reactive programming with 50+ event types
- ✅ **Type Safety** - Full type hints and mypy support
- ✅ **Thread-Safe** - Multi-threaded design with proper synchronization
- ✅ **GMAP Support** - Large world navigation and coordinate management
- ✅ **Server List Integration** - Automatic server discovery
- ✅ **Encryption Support** - ENCRYPT_GEN_5 with compression

### Classic Reborn Client  
- ✅ **Authentic Graphics** - Uses original Graal tilesets and sprites
- ✅ **GANI Animation System** - Full Graal Animation support
- ✅ **Sound Effects** - Classic Graal audio experience
- ✅ **Smooth Movement** - Interpolated player movement
- ✅ **Server Browser** - Integrated server selection
- ✅ **Chat System** - Full chat integration with bubbles
- ✅ **Combat System** - Player vs player combat mechanics
- ✅ **Item System** - Interactive items, chests, and inventory

## Test Servers

### Local Server (Basic Testing)
- **Server**: localhost:14900
- **Account**: hosler / 1234
- **Features**: Basic levels, NPCs, items
- **Note**: No GMAP support

### Hastur Server (GMAP Testing)
- **Server**: hastur.eevul.net:14912  
- **Account**: hosler / 1234
- **Features**: Full GMAP support (Zelda: A Link to the Past)
- **Client Version**: Must use 6.034

## Community and Support

- **GitHub**: [OpenGraal2 Repository](https://github.com/user/opengraal2) 
- **Issues**: Report bugs and request features
- **Discord**: Join our development community
- **Wiki**: Community-maintained documentation

---

*This documentation is generated for OpenGraal2 - a modern implementation of the classic Graal Online experience.*