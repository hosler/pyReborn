# GMAP Movement System Explanation

## Current Behavior (Traditional Graal GMAP)

In the traditional GMAP system:
1. Each segment is 64x64 tiles
2. Player coordinates are always local (0-64 within current segment)
3. When crossing boundaries:
   - x >= 64 → warp to x = 0 in east segment
   - x < 0 → warp to x = 63.5 in west segment
   - Same for y axis
4. Adjacent segments are rendered for visual continuity

## Why It Feels Restrictive

You're bounded by 64x64 because that's how GMAPs work - you're always in one segment at a time, with coordinates 0-64. The "seamless" world is an illusion created by:
- Rendering adjacent segments
- Instant warping between segments at boundaries

## Alternative: World Coordinates

If you want truly free movement across the entire GMAP without boundaries, we'd need to:
1. Use world coordinates (e.g., segment [2,1] at x=30 → world x = 2*64 + 30 = 158)
2. Translate to local coordinates for rendering and collision
3. Handle segment transitions internally

## Current Implementation

The current implementation follows traditional Graal behavior:
- Physics allows movement 0-64 per segment
- Boundary crossing triggers level change
- Camera follows player within segment
- Adjacent segments are rendered for continuity

This is working as designed. If you want different behavior (free movement across entire GMAP), that would be a fundamental change to how coordinates work.