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

import os
import time
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field

from .game.constants import PLAYER_STAND_X, PLAYER_STAND_Y

# Player feet/touch geometry, duplicated from pyreborn/game/collision.py
# (CollisionMixin.PLAYER_FEET_DX/DY, TOUCH_OFFSETS) — that is the source of
# truth; keep these in sync if it changes. Not imported directly: collision.py
# already does `from ..npc_handler import NPCHandler`, so importing collision.py
# from here would be circular.
#
# player_x/player_y (as passed to check_touch) are the sprite's TOP-LEFT, same
# as CollisionMixin's self.client.x/y. Character sprite is 3x3 tiles, but this
# geometry follows the standing point between the feet, not the shifted box
# centre or the wider visual sprite.
PLAYER_FEET_DX = PLAYER_STAND_X
PLAYER_FEET_DY = PLAYER_STAND_Y
TOUCH_OFFSETS = {
    0: [(1.0, 1.0), (2.0, 1.0)],    # up:    both box columns, row above the box
    1: [(0.0, 2.5), (0.0, 1.5)],    # left:  adjacent column, feet + torso
    2: [(1.0, 4.0), (2.0, 4.0)],    # down:  both box columns, row below the box
    3: [(3.0, 2.5), (3.0, 1.5)],    # right: adjacent column, feet + torso
}


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
        self.gs2 = None  # ClientGS2; consulted for bytecode NPCs' touch gate.
        self.npc_shapes: Dict[int, NPCShape] = {}  # npc_id -> shape
        self.npc_scripts: Dict[int, str] = {}  # npc_id -> script
        self.last_player_pos: Tuple[float, float] = (0, 0)
        self.touched_npcs: Set[int] = set()  # NPCs currently being touched

        # Touch event sink. Wired to the GS1 engine (gs1.trigger_npc_event) in
        # setup; this handler only does collision detection and hands the event
        # off — it does NOT interpret scripts itself.
        self.on_playertouchsme: Optional[callable] = None  # (npc_id, npc_data) -> None

    def forget_npc(self, npc_id: int):
        """Drop all per-NPC state for a despawned NPC (PLO_NPCDEL). Without
        this the stale collision shape keeps registering touches and its GS1
        prog keeps firing playertouchsme from the NPC's old tile."""
        self.npc_shapes.pop(npc_id, None)
        self.npc_scripts.pop(npc_id, None)
        self.touched_npcs.discard(npc_id)
        if self.gs1 is not None:
            self.gs1.forget_npc(npc_id)

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

        Test points are the feet point plus the per-direction touch points
        ahead of the player — the same geometry collision.py's CollisionMixin
        uses for movement-triggered interactions (chests/signs/doors), so NPC
        touch agrees with everything else that probes "what's in front of the
        player" instead of using its own hand-rolled player box.
        """
        touched = []

        test_points = [(player_x + PLAYER_FEET_DX, player_y + PLAYER_FEET_DY)]
        test_points += [(player_x + ox, player_y + oy)
                         for ox, oy in TOUCH_OFFSETS.get(player_dir, [])]

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
                if ('playertouchsme' in self.npc_scripts.get(npc_id, '')
                        or (self.gs2 is not None
                            and self.gs2.npc_has_event(npc_id,
                                                       "onPlayerTouchsMe"))):
                    if os.environ.get("PYREBORN_DEBUG"):
                        import sys
                        print(f"[touch] NPC {npc_id} at player ({new_x:.1f},{new_y:.1f}) dir={direction}",
                              file=sys.stderr)
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

    # Test touch detection. player_x/player_y are the sprite's TOP-LEFT (see
    # check_touch's docstring), so these no longer line up 1:1 with the NPC's
    # own (x, y) the way a "standing position" would.
    print("\n=== Testing touch detection ===")
    test_cases = [
        (25.0, 17.0, 0, "Player at (25,17) facing up - up-offset lands on NPC col 0-1"),
        (25.0, 17.0, 2, "Player at (25,17) facing down - offsets land off-shape, no touch"),
        (27.0, 17.0, 0, "Player at (27,17) facing up - col 2-3 not touchable"),
        (30.5, 17.0, 0, "Player at (30.5,17) facing up - col 6-7 touchable"),
        (25.0, 15.5, 2, "Player at (25,15.5) facing down - feet point alone touches"),
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
