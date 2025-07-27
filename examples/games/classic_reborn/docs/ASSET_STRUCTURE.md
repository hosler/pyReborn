# Classic Reborn Client Asset Structure

## Essential Assets

The Classic Reborn Client requires the following assets to function:

### Core Graphics
- `pics1.png` - Main tileset (required)
- `sprites.png` - Character sprites
- `letters.png` - Font/text rendering
- `state.png` - UI states

### Player Graphics
- `levels/heads/` - Player head images
- `levels/bodies/` - Player body images  
- `levels/shields/` - Shield graphics
- `levels/swords/` - Sword graphics

### Animations
- `levels/ganis/` - GANI animation files
  - `idle.gani`, `walk.gani`, `sword.gani`, etc.

### Sound Effects
- `sounds/` - WAV files for game sounds
  - `sword.wav`, `item.wav`, `dead.wav`, etc.

### Optional Assets
- `levels/baddies/` - Enemy sprites
- `levels/images/` - Miscellaneous images
- `maps/` - Map files for navigation
- `levels/midis/` - Background music

## Note
The assets directory is git-ignored as these are proprietary game files.
Only essential assets for basic gameplay should be included.