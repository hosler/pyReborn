# PyReborn TODO - Next Development Session

## Recently Completed
- [x] Fixed sprite positioning (top-left, no offsets)
- [x] Fixed other player visibility (PLO_OTHERPLPROPS handling)
- [x] Fixed Y position jumping (added props 78/79/80 to parse_other_player)
- [x] Fixed props 75/76 parsing (OSTYPE/TEXTCODEPAGE, not X2/Y2)
- [x] Added position interpolation for smooth other player movement
- [x] Increased movement speed to match legacy client

## High Priority

### Other Player Rendering
- [ ] Verify other player gani animations display correctly
- [ ] Verify sword/shield rendering on other players
- [ ] Verify direction changes on other players
- [ ] Test multiple other players simultaneously

### Combat System
- [ ] Sword hit detection
- [ ] Damage numbers/effects
- [ ] Player hurt animations
- [ ] Death/respawn handling
- [ ] Bombs and explosions
- [ ] Arrows/projectiles

### NPC System
- [ ] NPC movement/pathfinding display
- [ ] NPC animation states
- [ ] Sign reading (NPC interaction)
- [ ] NPC dialogue boxes
- [ ] Trigger actions

## Medium Priority

### Audio
- [ ] Sound effect playback
- [ ] Music/ambient sounds
- [ ] Volume controls

### UI Improvements
- [ ] Chat message history display
- [ ] Player list/who's online
- [ ] Health/rupee/item counters
- [ ] Minimap for GMAP

### Items & Inventory
- [ ] Item pickup animations
- [ ] Chest opening
- [ ] Inventory management
- [ ] Weapon switching

### Level Features
- [ ] Level links (door warping)
- [ ] Level signs
- [ ] Animated tiles
- [ ] Water/lava effects

## Low Priority

### Polish
- [ ] Loading screen improvements
- [ ] Error handling/reconnection
- [ ] Configuration file for settings
- [ ] Key rebinding

### Protocol
- [ ] Full prop coverage audit in all parse functions
- [ ] Packet logging/replay for debugging
- [ ] Protocol version negotiation

### Testing
- [ ] Unit tests for packet parsing
- [ ] Integration tests with mock server
- [ ] Visual regression tests

## Known Issues
- Movement uses half-tile precision (0.5 tiles) - may look slightly choppy
- GMAP other players assume same sub-level if level prop not set

## Notes for Next Session

### Debugging Parser Issues
If positions jump randomly, check:
1. Are all props in parse_other_player consuming correct bytes?
2. Is the suspect value (e.g., 39.5) coming from string data being read as position?
3. Add debug: `print(f"prop={prop_id} pos={pos} remaining={len(data)-pos}")`

### GServer Reference
Check prop definitions in: `GServer-v2/server/include/TAccount.h`
Check prop encoding in: `GServer-v2/server/src/TPlayer/TPlayerProps.cpp`

### Quick Test Command
```bash
python -m pyreborn.example_pygame <username> <password> localhost 14900
```
