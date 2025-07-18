# PyReborn Architecture Guide

This guide explains the design principles, architectural patterns, and internal structure of the PyReborn library.

## Overview

PyReborn implements a **layered, event-driven architecture** with clear separation between protocol handling, game state management, and user-facing APIs. The design prioritizes maintainability, extensibility, and thread safety while providing a clean abstraction over the complex Graal Reborn protocol.

## Architectural Principles

### 1. **Separation of Concerns**
Each component has a single, well-defined responsibility:
- **Client**: API coordination and user interface
- **Protocol**: Network communication and packet handling
- **Events**: Decoupled communication between components
- **Managers**: Specialized game state management
- **Models**: Data representation and validation

### 2. **Event-Driven Design**
All game updates flow through a central event system, enabling:
- Loose coupling between components
- Multiple listeners per event type
- Easy extension without modifying core code
- Clean separation of business logic from networking

### 3. **Layered Architecture**
```
┌─────────────────────────────────────┐
│           User API Layer            │  RebornClient, Actions
├─────────────────────────────────────┤
│          Manager Layer              │  LevelManager, ItemManager, etc.
├─────────────────────────────────────┤
│           Event Layer               │  EventManager, Event routing
├─────────────────────────────────────┤
│         Protocol Layer              │  Packet handling, encryption
├─────────────────────────────────────┤
│         Transport Layer             │  TCP sockets, threading
└─────────────────────────────────────┘
```

### 4. **Thread Safety**
- Queue-based communication between threads
- No shared mutable state without synchronization
- All public APIs are thread-safe
- Rate limiting prevents protocol desync

## Core Components

### RebornClient - Central Coordinator

The `RebornClient` class serves as the main entry point and coordinator:

```python
class RebornClient:
    def __init__(self, host: str, port: int, version: str = "2.1"):
        # Core components
        self.events = EventManager()
        self.session_manager = SessionManager(self.events)
        self.level_manager = LevelManager(self.events) 
        self.actions = PlayerActions(self)
        
        # Protocol handling
        self.packet_handler = PacketHandler(self.events)
        self.encryption = EncryptionManager()
        
        # Threading
        self.send_queue = queue.Queue()
        self.receive_thread = None
        self.send_thread = None
```

**Responsibilities**:
- Component initialization and lifecycle management
- High-level API methods delegation to action modules
- Connection establishment and authentication
- Thread management for send/receive operations

**Design Pattern**: **Facade** - Provides simplified interface to complex subsystem

### Event System - Decoupled Communication

The event system implements the **Observer Pattern** for loose coupling:

```python
class EventManager:
    def __init__(self):
        self._listeners: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()
    
    def subscribe(self, event_type: str, handler: Callable) -> None:
        with self._lock:
            self._listeners[event_type].append(handler)
    
    def emit(self, event_type: str, event_data: Dict) -> None:
        event_data['type'] = event_type
        event_data['timestamp'] = time.time()
        
        with self._lock:
            handlers = self._listeners[event_type].copy()
        
        for handler in handlers:
            try:
                handler(event_data)
            except Exception as e:
                self._handle_event_error(e, handler, event_data)
```

**Key Features**:
- Thread-safe subscription/emission
- Error isolation (one handler failure doesn't break others)
- Event data enrichment (timestamp, type)
- Synchronous delivery with error handling

### Protocol Layer - Network Communication

The protocol layer implements the complex Graal Reborn network protocol:

#### Packet Pipeline

```
Raw Bytes → Decryption → Decompression → Parsing → Event Emission
```

#### PacketHandler - Protocol Orchestration

```python
class PacketHandler:
    def __init__(self, events: EventManager):
        self.events = events
        self.handlers = {
            PlayerToServer.PLAYER_PROPS: self._handle_player_props,
            PlayerToServer.LEVEL_BOARD: self._handle_level_board,
            PlayerToServer.NPC_PROPS: self._handle_npc_props,
            # ... 50+ packet type handlers
        }
    
    def handle_packet(self, packet_id: int, packet_data: bytes) -> None:
        handler = self.handlers.get(packet_id)
        if handler:
            try:
                handler(packet_data)
            except Exception as e:
                self._handle_packet_error(packet_id, packet_data, e)
```

**Design Pattern**: **Command Pattern** - Each packet type has a dedicated handler

#### Encryption - ENCRYPT_GEN_5 Implementation

```python
class EncryptionManager:
    def __init__(self):
        self.gen_keys = [0] * 5  # Generation keys
        self.limit = 0x00004000  # Encryption limit
        self.offset = 0          # Current offset
    
    def encrypt(self, data: bytes) -> bytes:
        if self.offset + len(data) > self.limit:
            return data  # Send unencrypted when limit reached
        
        encrypted = bytearray()
        for byte in data:
            key_idx = self.offset % 5
            encrypted.append(byte ^ self.gen_keys[key_idx])
            self.offset += 1
        
        return bytes(encrypted)
```

**Protocol Features**:
- XOR-based stream cipher with 5 generation keys
- Encryption limit to prevent desync
- Compression support (zlib, bz2)
- Version-specific codec selection

### Manager Layer - Game State Management

Managers implement the **Strategy Pattern** for specialized game subsystems:

#### LevelManager - World Data Management

```python
class LevelManager:
    def __init__(self, events: EventManager):
        self.events = events
        self._levels: Dict[str, Level] = {}
        self._current_level: Optional[str] = None
        
        # Subscribe to level-related events
        events.subscribe('level_entered', self._on_level_entered)
        events.subscribe('level_board_received', self._on_board_received)
    
    def get_current_level(self) -> Optional[Level]:
        if self._current_level:
            return self._levels.get(self._current_level)
        return None
    
    def _parse_board_data(self, raw_data: bytes) -> List[int]:
        # Convert 8192 bytes to 4096 tile IDs (2 bytes each)
        tiles = []
        for i in range(0, len(raw_data), 2):
            tile_id = int.from_bytes(raw_data[i:i+2], byteorder='little')
            tiles.append(tile_id)
        return tiles
```

**Responsibilities**:
- Level data caching and retrieval
- Board data parsing (8192 bytes → 64×64 tile grid)
- Asset downloading (levels, images, sounds)
- GMAP coordinate management
- Tile coordinate conversion

#### SessionManager - Context Tracking

```python
class SessionManager:
    def __init__(self, events: EventManager):
        self.events = events
        self._conversations: Dict[int, Dict] = {}
        self._flags: Dict[str, Any] = {}
        
        events.subscribe('npc_conversation', self._on_npc_conversation)
    
    def get_conversation(self, npc_id: int) -> Optional[Dict]:
        return self._conversations.get(npc_id)
    
    def set_flag(self, flag_name: str, value: Any) -> None:
        self._flags[flag_name] = value
        self.events.emit('flag_changed', {
            'flag_name': flag_name,
            'value': value
        })
```

**Responsibilities**:
- NPC conversation state tracking
- Player flag/variable management
- Session persistence
- Context-aware event handling

### Action Layer - User Operations

The action layer implements the **Command Pattern** for user operations:

```python
class PlayerActions:
    def __init__(self, client: 'RebornClient'):
        self.client = client
        self.movement = MovementActions(client)
        self.communication = CommunicationActions(client)
        self.combat = CombatActions(client)
        self.appearance = AppearanceActions(client)
    
    def move_to(self, x: float, y: float) -> None:
        self.movement.move_to(x, y)
    
    def set_chat(self, message: str) -> None:
        self.communication.set_chat(message)
```

**Benefits**:
- Clean separation of action types
- Easy to extend with new actions
- Type-safe action parameters
- Consistent error handling

## Data Flow Architecture

### Event-Driven Data Flow

```
Network Packet → PacketHandler → Event Emission → Manager Updates → User Callbacks
```

**Example Flow - Player Movement**:

1. **Network**: Receive PLAYER_PROPS packet
2. **Protocol**: Parse player position data  
3. **Event**: Emit 'player_moved' event
4. **Managers**: Update player position in models
5. **User Code**: Handle movement event in bot logic

### Thread Communication

PyReborn uses a **multi-threaded architecture** with queue-based communication:

```
Main Thread                 Receive Thread              Send Thread
┌──────────┐               ┌──────────────┐            ┌─────────────┐
│   User   │               │   Socket     │            │   Queue     │
│   API    │               │   Receive    │            │ Processing  │
│          │               │              │            │             │
│ Events   │ ←──── emit ────│   Packet     │            │   Rate      │
│ Subscr.  │               │   Handler    │            │  Limiting   │
│          │               │              │            │             │
│ send() ──│─── queue ────→ │              │ ←── send ──│   Socket    │
└──────────┘               └──────────────┘            └─────────────┘
```

**Thread Safety Mechanisms**:
- `queue.Queue` for send operations (thread-safe)
- `threading.Lock` for event subscriptions
- Atomic operations for state updates
- No shared mutable state between threads

## Design Patterns Used

### 1. **Facade Pattern**
- `RebornClient` provides simplified interface to complex networking

### 2. **Observer Pattern**  
- `EventManager` for decoupled component communication

### 3. **Command Pattern**
- Packet handlers for protocol operations
- Action classes for user operations

### 4. **Strategy Pattern**
- Managers for different game subsystems
- Codec selection for different protocol versions

### 5. **Factory Pattern**
- Packet construction based on packet type
- Event creation with proper data structure

### 6. **Singleton Pattern**
- Encryption state management
- Client instance coordination

## Extension Points

### 1. **Custom Packet Handlers**

```python
def my_custom_handler(packet_data: bytes) -> None:
    # Custom packet processing
    pass

client.packet_handler.add_handler(255, my_custom_handler)
```

### 2. **Event Listeners**

```python
def on_custom_event(event: Dict) -> None:
    # React to game events
    pass

client.events.subscribe('custom_event', on_custom_event)
```

### 3. **Manager Extension**

```python
class CustomManager:
    def __init__(self, events: EventManager):
        self.events = events
        events.subscribe('relevant_event', self._handle_event)
    
    def _handle_event(self, event: Dict) -> None:
        # Custom game logic
        pass

# Add to client
client.custom_manager = CustomManager(client.events)
```

### 4. **Action Modules**

```python
class CustomActions:
    def __init__(self, client: RebornClient):
        self.client = client
    
    def custom_action(self, param: str) -> None:
        # Custom player action
        packet = build_custom_packet(param)
        self.client.send_packet(packet)

# Extend client actions
client.actions.custom = CustomActions(client)
```

## Performance Considerations

### 1. **Efficient Data Structures**
- `Dict` for O(1) lookups (players, levels, handlers)
- `List` for ordered collections (events, tiles)
- `Queue` for thread-safe communication

### 2. **Memory Management**
- Level data caching with eviction policies
- Event handler weak references (planned)
- Packet buffer reuse

### 3. **Network Optimization**
- Rate limiting prevents server disconnections
- Compression for large data transfers
- Connection pooling for multiple servers (planned)

### 4. **Thread Efficiency**
- Minimal thread context switching
- Queue batching for send operations
- Event batching for high-frequency updates

## Error Handling Strategy

### 1. **Layered Error Handling**

```python
# Network Layer
try:
    data = socket.recv(1024)
except socket.error as e:
    self._handle_network_error(e)

# Protocol Layer  
try:
    packet = parse_packet(data)
except ProtocolError as e:
    self._handle_protocol_error(e)

# Event Layer
try:
    handler(event)
except Exception as e:
    self._handle_event_error(e, handler, event)
```

### 2. **Graceful Degradation**
- Continue operation when non-critical components fail
- Fallback mechanisms for missing data
- Automatic reconnection for network failures

### 3. **Error Reporting**
- Structured error events for user code
- Detailed logging for debugging
- Error context preservation

## Testing Architecture

### 1. **Unit Testing**
- Each component tested in isolation
- Mock dependencies for clean tests
- Property-based testing for protocol parsing

### 2. **Integration Testing**
- Full client-server interaction tests
- Multi-threaded behavior validation
- Protocol compatibility testing

### 3. **Performance Testing**
- Throughput measurement
- Memory usage profiling
- Thread safety validation

---

This architecture provides a solid foundation for the PyReborn library while maintaining flexibility for future enhancements. The layered design with clear interfaces makes the codebase maintainable and extensible, while the event-driven approach enables complex bot behaviors without tight coupling to the core library.