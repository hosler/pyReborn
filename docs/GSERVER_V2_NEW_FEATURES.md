# GServer-V2 New Features for pyReborn Implementation

## Summary of New Features in GServer-V2

Based on my analysis of the GServer-V2 codebase, here are the key new features and changes that could be implemented in pyReborn:

### 1. New Packet Types

#### Missing Client-to-Server Packets:
- `PLI_REQUESTUPDATEBOARD` (130) - Request board updates for specific level regions
- `PLI_REQUESTTEXT` (152) - Get server values
- `PLI_SENDTEXT` (154) - Set server values  
- `PLI_UPDATEGANI` (157) - GANI update requests
- `PLI_UPDATESCRIPT` (158) - Script update requests
- `PLI_UPDATEPACKAGEREQUESTFILE` (159) - Package file requests
- `PLI_UPDATECLASS` (161) - Class update requests

#### Missing Server-to-Client Packets:
- `PLO_MINIMAP` (172) - Minimap data
- `PLO_GHOSTTEXT` (173) - Ghost mode text display
- `PLO_GHOSTICON` (174) - Ghost mode icon
- `PLO_FULLSTOP` (176) - Freeze client input
- `PLO_SERVERWARP` (178) - Server-initiated warp
- `PLO_MOVE2` (189) - Enhanced movement packets
- `PLO_UNKNOWN190` (190) - Pre-weapon list packet
- `PLO_UNKNOWN195` (195) - GANI-related packet
- `PLO_UNKNOWN197` (197) - NPC registration packet

### 2. NC (NPC Control) Support

The server now has built-in NC support for server-side NPC control:

#### NC Packet Types:
- `PLI_NC_NPCGET` (103) - Get NPC data
- `PLI_NC_NPCDELETE` (104) - Delete NPC
- `PLI_NC_NPCRESET` (105) - Reset NPC
- `PLI_NC_NPCSCRIPTGET` (106) - Get NPC script
- `PLI_NC_NPCWARP` (107) - Warp NPC to location
- `PLI_NC_NPCFLAGSGET` (108) - Get NPC flags
- `PLI_NC_NPCSCRIPTSET` (109) - Set NPC script
- `PLI_NC_NPCFLAGSSET` (110) - Set NPC flags
- `PLI_NC_NPCADD` (111) - Add new NPC
- `PLI_NC_CLASSEDIT` (112) - Edit class
- `PLI_NC_CLASSADD` (113) - Add class
- `PLI_NC_LOCALNPCSGET` (114) - Get local NPCs
- `PLI_NC_WEAPONLISTGET` (115) - Get weapon list
- `PLI_NC_WEAPONGET` (116) - Get weapon data
- `PLI_NC_WEAPONADD` (117) - Add weapon
- `PLI_NC_WEAPONDELETE` (118) - Delete weapon
- `PLI_NC_CLASSDELETE` (119) - Delete class
- `PLI_NC_LEVELLISTGET` (150) - Get level list
- `PLI_NC_LEVELLISTSET` (151) - Set level list

### 3. Enhanced Player Properties

New player properties added:
- `PLPROP_OSTYPE` (75) - Operating system type
- `PLPROP_TEXTCODEPAGE` (76) - Text encoding
- `PLPROP_ONLINESECS2` (77) - Extended online time
- `PLPROP_X2` (78) - High precision X coordinate
- `PLPROP_Y2` (79) - High precision Y coordinate  
- `PLPROP_Z2` (80) - High precision Z coordinate
- `PLPROP_PLAYERLISTCATEGORY` (81) - Player list categorization
- `PLPROP_COMMUNITYNAME` (82) - Community/alias name

### 4. Special Level Features

#### Singleplayer Levels
- Levels that start with "singleplayer" in their script become singleplayer instances
- Each player gets their own copy of the level
- Other players are not visible in singleplayer levels
- Player is always the "leader" in singleplayer levels

#### Group Maps
- Maps can be designated as "group maps" in server settings
- Only players in the same group can see each other on group maps
- Groups are set via `gr.setgroup` or `gr.setlevelgroup` triggeractions

### 5. Triggeraction Extensions

Server-specific triggeraction commands:
- `gr.addweapon` - Add weapon to player
- `gr.deleteweapon` - Remove weapon from player
- `gr.setgroup` - Set player's group
- `gr.setlevelgroup` - Set level group for player
- `gr.appendfile` - Append to server file
- `gr.writefile` - Write server file
- `gr.npc.move` - Move NPC serverside
- `gr.npc.setpos` - Set NPC position
- `gr.fullhearts` - Set player's full hearts
- `gr.readfile` - Read server file

### 6. Enhanced Features

- **GANI Script Updates** - Dynamic GANI loading/updating (PLO_GANISCRIPT)
- **NPC Bytecode** - Compiled Torque-script support (PLO_NPCBYTECODE)
- **Board Layers** - Multiple level layers support (PLO_BOARDLAYER)
- **Ghost Mode** - Ghost mode with text/icon display
- **Minimap Support** - Server-controlled minimaps
- **Update Packages** - File update package system
- **High Precision Coordinates** - Support for X2/Y2/Z2 properties

## Implementation Plan for pyReborn

### Priority 1: Core Protocol Updates
1. Add missing packet type enums to `protocol/enums.py`
2. Implement packet builders for new client packets in `protocol/packets.py`
3. Add handlers for new server packets in `handlers/packet_handler.py`

### Priority 2: Enhanced Player Properties
1. Update `PlayerProp` enum with new properties
2. Modify player property parsing to handle high-precision coordinates
3. Add support for OSTYPE, TEXTCODEPAGE, and COMMUNITYNAME

### Priority 3: Special Level Support
1. Add singleplayer level detection and handling
2. Implement group/levelgroup tracking
3. Add group-based player visibility filtering

### Priority 4: NC Support (Optional)
1. Create NC packet builders and handlers
2. Add NPC control methods to client API
3. Implement class/weapon management

### Priority 5: Advanced Features
1. Ghost mode support
2. Minimap handling
3. GANI script updates
4. Board layer support

## Recommended Initial Implementation

Start with these high-value, low-complexity additions:

1. **High Precision Coordinates** - Add X2/Y2/Z2 support for smoother movement
2. **REQUESTUPDATEBOARD** - Enable partial level updates for better performance
3. **Ghost Mode Packets** - Simple to implement, useful for debugging
4. **Group Support** - Add group tracking and filtering
5. **Triggeraction Handler** - Parse and emit triggeraction events

These features would significantly enhance pyReborn's capabilities while maintaining backward compatibility.