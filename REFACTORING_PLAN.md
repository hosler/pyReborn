# PyReborn Refactoring Plan

## Goals
1. **Maintain working protocol** - Don't break what works
2. **Improve maintainability** - Clear separation of concerns
3. **Make it extendable** - Easy to add new features/handlers
4. **Easy to hack** - Clear API for bot/client developers

## Current Architecture Analysis

### What Works Well
- Encryption/decryption logic is solid
- Packet sending/receiving with proper threading
- Event system for decoupling
- Level manager for game state

### Pain Points
- Everything in one large client.py file (790+ lines)
- Mixing of concerns (networking, game logic, state management)
- Hard to extend with new packet types
- No clear plugin/extension system

## Proposed Architecture

### Layer 1: Core Networking
```
pyreborn/core/
├── connection.py      # TCP socket management
├── encryption.py      # Already exists, keep as-is
└── protocol.py        # Packet encoding/decoding
```

### Layer 2: Protocol Implementation
```
pyreborn/protocol/
├── enums.py          # Already exists, keep as-is  
├── packets.py        # Already exists, keep as-is
├── handlers/         # Packet handlers
│   ├── base.py       # Base handler interface
│   ├── login.py      # Login/auth handlers
│   ├── player.py     # Player property handlers
│   ├── level.py      # Level/warp handlers
│   ├── chat.py       # Chat message handlers
│   └── registry.py   # Handler registration
└── codec.py          # Packet codec (moved from client)
```

### Layer 3: Game Layer
```
pyreborn/game/
├── client.py         # High-level game client
├── actions.py        # Player actions (move, chat, etc)
├── state.py          # Game state management
└── queries.py        # State queries (get player, etc)
```

### Layer 4: Extensions
```
pyreborn/extensions/
├── __init__.py       # Extension loader
├── session.py        # Session tracking
└── level_manager.py  # Level management (already exists)
```

## Implementation Strategy

### Phase 1: Extract Core Networking
1. Create `core/connection.py` with socket management
2. Create `core/protocol.py` with packet framing
3. Keep encryption.py as-is (it works!)

### Phase 2: Organize Protocol Layer  
1. Create handler base class with clear interface
2. Split packet handling into focused handlers
3. Create handler registry for easy extension

### Phase 3: Create Game Layer
1. Extract game actions to `game/actions.py`
2. Extract state management to `game/state.py`
3. Create clean `game/client.py` that uses layers below

### Phase 4: Main Client API
1. Keep `RebornClient` in `client.py` as main API
2. Make it a thin wrapper that delegates to layers
3. Maintain backward compatibility

## Key Design Principles

### 1. Event-Driven Architecture
- Keep the event system as central communication
- All layers emit events, don't call each other directly
- Makes it easy to hook into any part of the system

### 2. Handler Pattern
```python
class PacketHandler:
    def can_handle(self, packet_id: int) -> bool:
        """Check if this handler handles this packet type"""
        
    def handle(self, packet_data: bytes, client_state: ClientState):
        """Handle the packet and emit events"""
```

### 3. Clear Separation
- Core: Only knows about bytes and sockets
- Protocol: Only knows about Graal packet format
- Game: Only knows about game concepts
- Client: Orchestrates everything

### 4. Easy Extension
```python
# Users can easily add custom handlers
@client.register_handler
class CustomHandler(PacketHandler):
    def can_handle(self, packet_id):
        return packet_id == MY_CUSTOM_PACKET
        
    def handle(self, data, state):
        # Custom logic
```

## Backward Compatibility

The main `RebornClient` API will remain the same:
- `connect()`, `login()`, `disconnect()`
- `move_to()`, `set_chat()`, `set_nickname()`, etc.
- `events.subscribe()` for event handling
- `level_manager`, `session` attributes

## Benefits

1. **Maintainable**: Each file has a single responsibility
2. **Testable**: Can test each layer in isolation  
3. **Extendable**: Easy to add new packet types/handlers
4. **Hackable**: Clear structure for bot developers
5. **Debuggable**: Can log/inspect at each layer

## Migration Path

1. Create new structure alongside existing
2. Move code piece by piece, testing each step
3. Once working, update imports in main client
4. Remove old code
5. Update examples to show extensibility