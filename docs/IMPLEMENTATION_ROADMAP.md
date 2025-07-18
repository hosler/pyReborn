# PyReborn Implementation Roadmap

## Phase 1: Core Gameplay Enhancement (1-2 months)

### 1.1 Item System Implementation
**Priority: HIGH** - Essential for gameplay

#### Tasks:
- [ ] Implement `PLI_ITEMADD` packet handler
- [ ] Implement `PLI_ITEMDEL` packet handler  
- [ ] Implement `PLI_ITEMTAKE` packet handler
- [ ] Add `PLO_ITEMADD` and `PLO_ITEMDEL` parsing
- [ ] Create `ItemManager` class for client-side tracking
- [ ] Add item pickup methods to client API

#### API Additions:
```python
# client.py additions
def pickup_item(self, x: float, y: float) -> bool:
    """Attempt to pick up item at position"""
    
def drop_item(self, item_type: int, x: float, y: float):
    """Drop an item at position"""
```

### 1.2 Chest Interaction
**Priority: HIGH** - Common gameplay element

#### Tasks:
- [ ] Implement `PLI_OPENCHEST` packet
- [ ] Parse chest responses in level data
- [ ] Track opened chests per level
- [ ] Add chest interaction to event system

#### API Additions:
```python
def open_chest(self, x: int, y: int) -> bool:
    """Open chest at tile position"""
    
# Event: 'chest_opened' with chest data
```

### 1.3 Throwing Mechanics
**Priority: MEDIUM** - Enhanced gameplay

#### Tasks:
- [ ] Implement `PLI_THROWCARRIED` packet
- [ ] Handle `PLO_THROWCARRIED` animations
- [ ] Add carry sprite tracking
- [ ] Implement throw physics

#### API Additions:
```python
def throw_carried(self, power: float = 1.0):
    """Throw currently carried object"""
    
def set_carry_sprite(self, sprite: str):
    """Set what player is carrying"""
```

## Phase 2: Combat System Enhancement (1-2 months)

### 2.1 Damage System
**Priority: HIGH** - Core combat feature

#### Tasks:
- [ ] Implement `PLI_HURTPLAYER` packet
- [ ] Handle `PLO_HURTPLAYER` notifications
- [ ] Add damage calculation
- [ ] Implement invulnerability frames
- [ ] Add health tracking for other players

#### API Additions:
```python
def hurt_player(self, player_id: int, damage: float):
    """Deal damage to another player"""
    
# Events: 'player_hurt', 'player_died'
```

### 2.2 Hit Detection
**Priority: HIGH** - Combat accuracy

#### Tasks:
- [ ] Implement `PLI_HITOBJECTS` packet
- [ ] Handle `PLO_HITOBJECTS` responses
- [ ] Add collision detection helpers
- [ ] Track hit confirmations

#### API Additions:
```python
def check_hit(self, x: float, y: float, width: float, height: float):
    """Check if attack hit objects/players in area"""
```

### 2.3 Baddy/Enemy Support
**Priority: MEDIUM** - PvE combat

#### Tasks:
- [ ] Implement `PLI_BADDYPROPS` packet handler
- [ ] Implement `PLI_BADDYHURT` packet
- [ ] Parse `PLO_BADDYPROPS` updates
- [ ] Create `BaddyManager` class
- [ ] Add baddy interaction methods

## Phase 3: NPC Interaction System (2-3 months)

### 3.1 Basic NPC Interaction
**Priority: HIGH** - Core feature

#### Tasks:
- [ ] Implement `PLI_NPCPROPS` packet
- [ ] Add NPC touch/activate detection
- [ ] Handle NPC message display
- [ ] Support basic NPC movement updates

#### API Additions:
```python
def touch_npc(self, npc_id: int):
    """Trigger NPC interaction"""
    
def update_npc_prop(self, npc_id: int, prop: NPCProp, value: Any):
    """Update NPC property"""
```

### 3.2 NPC Creation/Deletion
**Priority: MEDIUM** - Dynamic content

#### Tasks:
- [ ] Implement `PLI_PUTNPC` packet
- [ ] Implement `PLI_NPCDEL` packet
- [ ] Handle server responses
- [ ] Update NPC tracking

### 3.3 Triggeractions
**Priority: MEDIUM** - Server interaction

#### Tasks:
- [ ] Implement `PLI_TRIGGERACTION` packet
- [ ] Handle `PLO_TRIGGERACTION` responses
- [ ] Create trigger system
- [ ] Add common trigger helpers

#### API Additions:
```python
def trigger_action(self, action: str, params: str = ""):
    """Send triggeraction to server"""
    
# Event: 'trigger_response' with data
```

## Phase 4: Modern Features (1-2 months)

### 4.1 High-Precision Movement
**Priority: HIGH** - Smooth gameplay

#### Tasks:
- [ ] Implement X2, Y2, Z2 properties (78-80)
- [ ] Update movement system for sub-pixel positioning
- [ ] Modify packet encoding/decoding
- [ ] Update position interpolation

### 4.2 Extended Attributes
**Priority: MEDIUM** - Custom data

#### Tasks:
- [ ] Support GATTRIB6-30 properties
- [ ] Update property encoding
- [ ] Add attribute management methods

### 4.3 Enhanced UI Support
**Priority: LOW** - Visual features

#### Tasks:
- [ ] Parse `PLO_RPGWINDOW` packets
- [ ] Handle `PLO_STATUSLIST` data
- [ ] Support `PLO_SAY2` enhanced text
- [ ] Add freeze/unfreeze mechanics

## Phase 5: Server Features (Optional, 3-4 months)

### 5.1 Update System
**Priority: LOW** - Advanced feature

#### Tasks:
- [ ] Implement update package protocol
- [ ] Add class request system
- [ ] Support hot-reloading
- [ ] File verification

### 5.2 Basic Scripting
**Priority: LOW** - Advanced feature

#### Tasks:
- [ ] Parse script responses
- [ ] Basic GS1 command support
- [ ] Simple script execution
- [ ] Script event handling

## Implementation Guidelines

### Code Organization
```
pyreborn/
├── managers/           # New manager classes
│   ├── item_manager.py
│   ├── baddy_manager.py
│   └── trigger_manager.py
├── protocol/
│   ├── packets/       # New packet implementations
│   │   ├── combat.py
│   │   ├── items.py
│   │   └── npcs.py
│   └── handlers/      # New packet handlers
└── events/           # New event types
```

### Testing Strategy
1. Unit tests for each packet type
2. Integration tests for feature sets
3. Example scripts demonstrating features
4. Compatibility tests with GServer-v2

### Backwards Compatibility
- All new features should be optional
- Existing API must remain unchanged
- New events should not break old code
- Version detection for feature availability

## Priority Matrix

| Feature | Impact | Effort | Priority | Target Phase |
|---------|--------|--------|----------|--------------|
| Item System | HIGH | LOW | CRITICAL | Phase 1 |
| Damage System | HIGH | MEDIUM | CRITICAL | Phase 2 |
| NPC Interaction | HIGH | HIGH | HIGH | Phase 3 |
| High-Precision Movement | MEDIUM | LOW | HIGH | Phase 4 |
| Throwing | MEDIUM | LOW | MEDIUM | Phase 1 |
| Baddies | MEDIUM | MEDIUM | MEDIUM | Phase 2 |
| Triggeractions | MEDIUM | MEDIUM | MEDIUM | Phase 3 |
| Extended Attributes | LOW | LOW | LOW | Phase 4 |
| Scripting | LOW | HIGH | LOW | Phase 5 |

## Success Metrics

### Phase 1 Complete When:
- Players can pick up all item types
- Chests can be opened and give items
- Objects can be carried and thrown

### Phase 2 Complete When:
- Players can damage each other
- Hit detection works accurately
- Baddies can be fought

### Phase 3 Complete When:
- NPCs can be interacted with
- Triggeractions work with server
- Basic NPC management works

### Phase 4 Complete When:
- Movement is pixel-perfect
- All 30 GATTRIB slots work
- Modern UI packets parse correctly

### Phase 5 Complete When:
- Update packages download
- Basic scripts execute
- Classes can be requested

## Estimated Timeline

- **Phase 1**: 4-6 weeks
- **Phase 2**: 4-6 weeks  
- **Phase 3**: 8-12 weeks
- **Phase 4**: 4-6 weeks
- **Phase 5**: 12-16 weeks (optional)

**Total for Core Features (Phases 1-4)**: 5-7 months
**Total for All Features**: 8-11 months

## Next Steps

1. Create GitHub issues for each phase
2. Set up feature branches
3. Begin with Phase 1.1 (Item System)
4. Regular testing against GServer-v2
5. Update documentation as features complete