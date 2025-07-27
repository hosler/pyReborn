# Classic Reborn Client Reorganization Plan

## Current Issues

1. **Flat File Structure** - All modules in root directory with no clear organization
2. **Large Main File** - classic_reborn_client.py is 2,668 lines
3. **Mixed Concerns** - Documentation, scripts, and code all in same directory
4. **No Clear Separation** - Core systems mixed with utilities and helpers
5. **Testing Scripts** - Mixed with production code

## Proposed New Structure

```
classic_reborn/
├── main.py                    # Simple entry point (50-100 lines max)
├── run.sh                     # Launch script (unchanged)
├── README.md                  # User documentation
│
├── game/                      # Main game package
│   ├── __init__.py
│   ├── client.py             # Main game client class (simplified)
│   ├── constants.py          # Game constants (from classic_constants.py)
│   └── state.py              # Game state management
│
├── core/                      # Core game systems
│   ├── __init__.py
│   ├── connection.py         # Network connection manager
│   ├── physics.py            # Physics and collision
│   ├── renderer.py           # Rendering engine
│   └── input.py              # Input handling
│
├── managers/                  # Game managers
│   ├── __init__.py
│   ├── animation.py          # Animation manager
│   ├── audio.py              # Audio manager
│   ├── gmap.py               # GMAP handler
│   ├── item.py               # Item manager
│   └── ui.py                 # UI manager
│
├── systems/                   # Game systems
│   ├── __init__.py
│   ├── bush.py               # Bush interaction
│   ├── combat.py             # Combat system (new)
│   ├── chat.py               # Chat system (extract from UI)
│   └── movement.py           # Movement system (extract from physics)
│
├── parsers/                   # File parsers
│   ├── __init__.py
│   ├── gani.py               # GANI parser
│   ├── tiledefs.py           # Tile definitions parser
│   └── gmap_preloader.py     # GMAP preloader
│
├── ui/                        # UI components  
│   ├── __init__.py
│   ├── server_browser.py     # Server browser
│   ├── player_props.py       # Player properties window
│   ├── hud.py                # HUD elements (extract from UI manager)
│   └── widgets.py            # Common UI widgets
│
├── utils/                     # Utilities
│   ├── __init__.py
│   └── logging.py            # Logging configuration
│
├── data/                      # Game data files
│   ├── tiledefs.txt
│   └── tiledefs.dat
│
├── scripts/                   # Launch scripts
│   ├── run_hastur.sh
│   ├── run_local.sh
│   └── run_v2.sh
│
├── docs/                      # Documentation
│   ├── CLAUDE.md
│   ├── *.md                  # All other docs
│   └── architecture/         # New architecture docs
│
├── testing/                   # Test scripts
│   └── *.py                  # All test scripts
│
└── assets/                    # (git-ignored) Game assets
```

## Implementation Steps

### Phase 1: Create Package Structure (Day 1)
1. Create all new directories and __init__.py files
2. Move data files to data/
3. Move scripts to scripts/
4. Move documentation to docs/
5. Move test scripts to testing/

### Phase 2: Extract Core Systems (Day 2)
1. Extract connection management from main client
2. Extract physics system
3. Extract renderer
4. Extract input handling
5. Create simplified main.py entry point

### Phase 3: Reorganize Managers (Day 3)
1. Move animation_manager.py → managers/animation.py
2. Move audio_manager.py → managers/audio.py
3. Move gmap_handler.py → managers/gmap.py
4. Move item_manager.py → managers/item.py
5. Move ui_manager.py → managers/ui.py

### Phase 4: Extract Game Systems (Day 4)
1. Extract movement logic from physics → systems/movement.py
2. Extract chat from UI manager → systems/chat.py
3. Move bush_handler.py → systems/bush.py
4. Create new combat system in systems/combat.py

### Phase 5: Reorganize Parsers and UI (Day 5)
1. Move gani_parser.py → parsers/gani.py
2. Move tile_defs.py → parsers/tiledefs.py
3. Move gmap_preloader_simple.py → parsers/gmap_preloader.py
4. Reorganize UI components into ui/ package

### Phase 6: Refactor Main Client (Day 6)
1. Break down classic_reborn_client.py into smaller modules
2. Create clean game/client.py with clear initialization
3. Extract game loop into separate method
4. Simplify event handling

## Benefits

1. **Clear Organization** - Easy to find and modify code
2. **Smaller Files** - No more 2,668 line files
3. **Modular Design** - Easy to add/remove features
4. **Better Testing** - Clear separation of test code
5. **Maintainable** - New developers can understand structure
6. **Extensible** - Easy to add new systems/managers

## Migration Guidelines

- All imports will need updating
- Preserve all functionality
- Keep backward compatibility where possible
- Document any breaking changes
- Test thoroughly after each phase