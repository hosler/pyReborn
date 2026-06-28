#!/usr/bin/env python3
"""
NPC handler for client-side NPC collision detection and script execution.

In Reborn, many NPC events are client-side:
- playerenters: Client detects entering a level
- playertouchsme: Client detects touching an NPC shape
- timeout: Client manages script timeouts

This module provides:
1. NPC shape parsing from scripts (setshape, setshape2)
2. Collision detection between player and NPC shapes
3. Dispatching touch events to the GS1 engine

It does NOT interpret scripts itself. Touch detection fires `on_playertouchsme`,
which setup wires to ``gs1.trigger_npc_event`` — the one real GS1 engine
(``reborn_protocol.gs1``) evaluates the script and its conditions. There is no
regex-based fallback executor; that only ever diverged from the real engine.
"""

import time
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field


@dataclass
class NPCShape:
    """Represents an NPC's collision/touch shape."""
    x: float
    y: float
    width: int  # In tiles
    height: int  # In tiles
    solid_flags: List[int] = field(default_factory=list)  # Per-tile flags (22=solid)

    def get_touchable_tiles(self) -> List[Tuple[int, int]]:
        """Get list of touchable (solid) tile offsets."""
        tiles = []
        if not self.solid_flags:
            # If no flags, entire shape is touchable
            for ty in range(self.height):
                for tx in range(self.width):
                    tiles.append((tx, ty))
        else:
            # Use solid_flags to determine touchable tiles
            for i, flag in enumerate(self.solid_flags):
                if flag == 22:  # Solid/touchable
                    tx = i % self.width
                    ty = i // self.width
                    tiles.append((tx, ty))
        return tiles

    def is_point_inside(self, px: float, py: float) -> bool:
        """Check if point (in tiles) is inside this shape."""
        # Relative position
        rx = px - self.x
        ry = py - self.y

        if rx < 0 or ry < 0 or rx >= self.width or ry >= self.height:
            return False

        if not self.solid_flags:
            return True

        # Check specific tile
        tile_idx = int(ry) * self.width + int(rx)
        if tile_idx < len(self.solid_flags):
            return self.solid_flags[tile_idx] == 22

        return False


class NPCHandler:
    """Handles NPC collision detection and dispatches touch events.

    Collision shapes come from the GS1 engine: when an NPC script runs
    setshape/setshape2, the GS1 host records (width, height, flags) keyed by
    npc_id (see ClientGS1.shapes). `update_npcs` reads that geometry — nothing
    here parses scripts.
    """

    def __init__(self, client):
        self.client = client
        self.gs1 = None  # ClientGS1; set by the game client. Source of shapes.
        self.npc_shapes: Dict[int, NPCShape] = {}  # npc_id -> shape
        self.npc_scripts: Dict[int, str] = {}  # npc_id -> script
        self.last_player_pos: Tuple[float, float] = (0, 0)
        self.touched_npcs: Set[int] = set()  # NPCs currently being touched

        # Touch event sink. Wired to the GS1 engine (gs1.trigger_npc_event) in
        # setup; this handler only does collision detection and hands the event
        # off — it does NOT interpret scripts itself.
        self.on_playertouchsme: Optional[callable] = None  # (npc_id, npc_data) -> None

    def update_npcs(self):
        """Refresh per-NPC scripts and collision shapes.

        Shape geometry is whatever the GS1 engine recorded when the NPC's script
        ran setshape/setshape2 (positioned at the NPC's current x/y); call this
        after triggering playerenters so those shapes exist.
        """
        shapes = getattr(self.gs1, "shapes", {}) if self.gs1 is not None else {}
        for npc_id, npc_data in self.client.npcs.items():
            self.npc_scripts[npc_id] = npc_data.get('script', '')

            geom = shapes.get(npc_id)
            if geom:
                w, h, flags = geom
                self.npc_shapes[npc_id] = NPCShape(
                    x=npc_data.get('x', 0), y=npc_data.get('y', 0),
                    width=w, height=h, solid_flags=list(flags))

    def check_touch(self, player_x: float, player_y: float, player_dir: int) -> List[int]:
        """Check for NPC touches and return list of touched NPC IDs.

        Player direction affects which NPCs we check for touch - we test
        the area in front of the player where they would collide.
        """
        touched = []

        # Player occupies roughly a 1x2 tile area (1 wide, 2 tall)
        # Test multiple points around the player for collision
        test_points = [
            (player_x + 0.5, player_y),       # Center-top
            (player_x + 0.5, player_y + 1),   # Center-bottom
            (player_x, player_y + 0.5),       # Left-center
            (player_x + 1, player_y + 0.5),   # Right-center
        ]

        # Add direction-specific test point in front of player
        front_offsets = {
            0: (0.5, -0.3),   # Up: test just above
            1: (-0.3, 0.5),   # Left: test just left
            2: (0.5, 1.3),    # Down: test just below
            3: (1.3, 0.5),    # Right: test just right
        }
        if player_dir in front_offsets:
            offset = front_offsets[player_dir]
            test_points.append((player_x + offset[0], player_y + offset[1]))

        for npc_id, shape in self.npc_shapes.items():
            for tx, ty in test_points:
                if shape.is_point_inside(tx, ty):
                    touched.append(npc_id)
                    break  # Only add once

        return touched

    def process_movement(self, new_x: float, new_y: float, direction: int):
        """Process player movement and trigger touch events.

        Call this after the player moves to check for NPC collisions.
        """
        touched_now = set(self.check_touch(new_x, new_y, direction))

        # Find newly touched NPCs (ones we weren't touching before)
        new_touches = touched_now - self.touched_npcs

        # Hand each newly-touched NPC's event to the GS1 engine, which evaluates
        # the script's own conditions (playerdir, etc.) authoritatively. We don't
        # pre-filter on direction or re-parse the script here.
        if self.on_playertouchsme:
            for npc_id in new_touches:
                if 'playertouchsme' in self.npc_scripts.get(npc_id, ''):
                    self.on_playertouchsme(npc_id, self.client.npcs.get(npc_id, {}))

        self.touched_npcs = touched_now
        self.last_player_pos = (new_x, new_y)


def test_npc_handler():
    """Test the NPC handler with sample data."""
    # Mock client
    class MockClient:
        def __init__(self):
            self.npcs = {
                363: {
                    'id': 363,
                    'x': 25.0,
                    'y': 18.0,
                    'script': '''if(playerenters) {
setshape2 14,1,{22,22,0,0,0,0,22,22,0,0,0,0,22,22};
}
if(playertouchsme && playerdir == 0) {
triggeraction 0,0,gr.addweapon,-validation;
setplayerprop #c,:Added:;
play sen_select.wav;
}'''
                }
            }
            self.x = 25.0
            self.y = 19.0

    client = MockClient()
    handler = NPCHandler(client)

    # Shapes come from the GS1 engine: load the script, run playerenters (which
    # executes setshape2), then snapshot — same flow as the live client.
    from .gs1_client import ClientGS1
    gs1 = ClientGS1(client)
    for nid, npc in client.npcs.items():
        gs1.load_script(f"npc_{nid}", npc['script'], npc_id=nid)
    gs1.trigger_event('playerenters')
    handler.gs1 = gs1

    print("=== Updating NPCs ===")
    handler.update_npcs()
    print(f"Shapes from GS1 host: {len(handler.npc_shapes)}")
    for npc_id, shape in handler.npc_shapes.items():
        print(f"  NPC {npc_id}: ({shape.x}, {shape.y}) {shape.width}x{shape.height}")
        touchable = shape.get_touchable_tiles()
        print(f"    Touchable tiles: {touchable}")

    # Test touch detection
    print("\n=== Testing touch detection ===")
    test_cases = [
        (25.0, 19.0, 0, "Player at (25,19) facing up - should touch NPC"),
        (25.0, 18.0, 0, "Player at (25,18) facing up - inside NPC"),
        (27.0, 18.0, 0, "Player at (27,18) facing up - x+2 not touchable"),
        (31.0, 18.0, 0, "Player at (31,18) facing up - x+6 touchable"),
        (25.0, 19.0, 2, "Player at (25,19) facing down - wrong direction"),
    ]

    for px, py, pdir, desc in test_cases:
        touched = handler.check_touch(px, py, pdir)
        print(f"  {desc}")
        print(f"    -> Touched NPCs: {touched}")

    # Test movement -> touch event dispatch (the GS1 engine would run the
    # script; here we just confirm the handler fires the callback once on enter).
    print("\n=== Testing movement and touch dispatch ===")
    fired = []
    handler.on_playertouchsme = lambda npc_id, npc_data: fired.append(npc_id)
    handler.last_player_pos = (25, 20)
    handler.touched_npcs = set()

    for y in [19, 18, 17]:
        print(f"\nMoving to (25, {y}) facing up...")
        handler.process_movement(25, y, 0)
    print(f"  -> playertouchsme fired for NPCs: {fired}")


if __name__ == "__main__":
    test_npc_handler()
