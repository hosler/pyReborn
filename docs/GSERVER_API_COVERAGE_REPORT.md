# PyReborn API Coverage Report vs GServer-v2

## Executive Summary

After a deep analysis of the GServer-v2 codebase and PyReborn's implementation, PyReborn covers approximately **60-70%** of the core gameplay protocol. The implementation focuses on essential features (movement, chat, basic combat) while missing more advanced features like NPC scripting, item management, and server administration tools.

## Protocol Coverage Analysis

### ✅ Well-Covered Areas (80-100%)

1. **Player Movement & Properties**
   - Basic position updates (X, Y, Z)
   - Player appearance (head, body, colors, sprite)
   - Basic stats (hearts, rupees, arrows, bombs)
   - Player animations (GANI)
   - Nickname and chat

2. **Core Communication**
   - Chat messages (toall)
   - Private messages
   - Server text messages
   - Basic file requests

3. **Level Management**
   - Level board data
   - Level names
   - Board modifications (receive only)
   - Signs and links

4. **Basic Combat**
   - Sword power
   - Shield power
   - Arrow shooting
   - Bomb placement
   - Basic explosions

### ⚠️ Partially Covered Areas (30-60%)

1. **NPC System**
   - Can receive NPC properties
   - Cannot create or modify NPCs
   - No scripting support
   - Limited NPC interactions

2. **Advanced Player Properties**
   - Missing many GATTRIB properties (only 1-5 implemented, 1-30 exist)
   - No horse management
   - No carried NPC support
   - Limited status flags

3. **Item System**
   - Can display items
   - Cannot pick up or manage items
   - No chest interaction
   - No throwing mechanics

4. **File System**
   - Basic file requests work
   - No update package support
   - No class/script requests
   - No GANI script updates

### ❌ Missing Features (0-30%)

1. **Server Administration**
   - No RC (Remote Control) packet support
   - No NC (NPC Control) packet support
   - No server flag management
   - No player administration

2. **Advanced Combat**
   - No hurt/damage system
   - No hit detection packets
   - No baddy/enemy support
   - No PvP claiming

3. **Scripting & Classes**
   - No GS1/GS2 script execution
   - No class system
   - No weapon scripts
   - No triggeractions

4. **Modern Features**
   - Limited ghost mode support
   - No RPG windows
   - No status lists
   - No process monitoring

## Detailed Missing Packet Analysis

### Critical Missing Client→Server Packets

| Packet | Description | Impact |
|--------|-------------|--------|
| PLI_BOARDMODIFY | Modify level tiles | Cannot edit levels |
| PLI_NPCPROPS | Update NPC properties | Cannot interact with NPCs |
| PLI_THROWCARRIED | Throw carried items | No throwing mechanics |
| PLI_ITEMADD/DEL | Item management | Cannot pick up items |
| PLI_OPENCHEST | Open chests | No chest interaction |
| PLI_PUTNPC | Place NPCs | Cannot create NPCs |
| PLI_HURTPLAYER | Damage players | No PvP combat |
| PLI_HITOBJECTS | Hit detection | Limited combat |
| PLI_TRIGGERACTION | Server triggers | No script triggers |

### Critical Missing Server→Client Packets

| Packet | Description | Impact |
|--------|-------------|--------|
| PLO_PLAYERWARP2 | Enhanced warping | Limited warp support |
| PLO_ITEMDEL | Remove items | Items persist |
| PLO_HURTPLAYER | Damage notification | No damage feedback |
| PLO_PUSHAWAY | Push effects | No collision effects |
| PLO_SAY2 | Enhanced chat/signs | Limited text display |
| PLO_FREEZEPLAYER2 | Freeze player | No freeze effects |
| PLO_RPGWINDOW | RPG dialogs | No dialog support |
| PLO_STATUSLIST | Status windows | No status display |
| PLO_NPCBYTECODE | Compiled scripts | No script execution |

## GServer-v2 Specific Features Not Implemented

### 1. High-Precision Movement (v2.30+)
- Properties X2, Y2, Z2 (IDs 78-80) for sub-pixel positioning
- PyReborn only implements basic X, Y, Z

### 2. Extended Attributes
- GATTRIB6-30 (IDs 46-74) for custom player/NPC data
- PyReborn only implements GATTRIB1-5

### 3. Community Features
- COMMUNITYNAME (ID 82) for Graal v5 accounts
- PLAYERLISTCATEGORY (ID 81) for organizing players
- OSTYPE and TEXTCODEPAGE for client info

### 4. Modern Packets
- Ghost mode overlay (PLO_GHOSTTEXT, PLO_GHOSTICON)
- Minimap system (PLO_MINIMAP)
- Server warping (PLO_SERVERWARP)
- Full stop controls (PLO_FULLSTOP/2)

### 5. Update System
- Package-based updates
- Class/script hot-reloading
- File verification system

## Impact on Bot/Client Development

### What Works Well ✅
- Basic movement and navigation
- Chat-based interactions
- Following players
- Basic combat (sword, arrows, bombs)
- Level exploration
- Server hopping

### What's Limited ⚠️
- Cannot interact with world objects
- Limited NPC interactions
- No scripted content
- Basic combat only
- No item collection

### What's Impossible ❌
- Level editing
- NPC creation/scripting
- Advanced combat systems
- Server administration
- Custom weapon creation
- Dialog systems

## Recommendations for PyReborn Enhancement

### High Priority (Core Gameplay)
1. **Item System**
   - Implement PLI_ITEMADD/DEL
   - Add chest interaction
   - Support throwing mechanics

2. **NPC Interaction**
   - Basic NPC property updates
   - Simple NPC interactions
   - Touch/activate support

3. **Combat Enhancement**
   - Hurt/damage system
   - Hit detection
   - Baddy support

### Medium Priority (Extended Features)
1. **High-Precision Movement**
   - Implement X2, Y2, Z2 properties
   - Sub-pixel positioning

2. **Extended Attributes**
   - Support GATTRIB6-30
   - Custom data storage

3. **Modern UI**
   - RPG windows
   - Status lists
   - Enhanced chat

### Low Priority (Advanced)
1. **Scripting Support**
   - Basic triggeractions
   - Simple script execution
   - Class system

2. **Administration**
   - RC packet support
   - Server management
   - Player moderation

## Conclusion

PyReborn provides a solid foundation for basic Graal gameplay and bot development. However, it lacks many advanced features that modern GServer-v2 supports. The missing features primarily impact:

1. **Content Creation** - No level editing or NPC scripting
2. **Advanced Gameplay** - Limited combat and no item systems  
3. **Server Features** - No administration or modern UI elements

For most bot development and basic gameplay, PyReborn is sufficient. For full client implementation or advanced features, significant protocol extensions would be needed.

### Estimated Development Effort

- **Basic Missing Features**: 2-3 months
- **Advanced Features**: 4-6 months
- **Full Protocol Parity**: 8-12 months

The modular design of PyReborn makes it relatively straightforward to add new packet handlers, but some features (like scripting) would require substantial architectural additions.