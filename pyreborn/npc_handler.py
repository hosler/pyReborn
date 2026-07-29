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

import math
import os
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field

from .game.constants import PLAYER_STAND_X, PLAYER_STAND_Y

# player_x/player_y (as passed to check_touch) are the sprite's TOP-LEFT, same
# as CollisionMixin's self.client.x/y. The feet point follows the standing
# point between the feet (shared PLAYER_STAND constants), not the shifted box
# centre or the wider visual sprite.
PLAYER_FEET_DX = PLAYER_STAND_X
PLAYER_FEET_DY = PLAYER_STAND_Y
# NPC-touch probe points: the reference client's `touchtestd` table verbatim
# (TPlayer::touchNPCs probes touchtestd[dir] and touchtestd[dir+4] each
# frame — Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:1792-1831, table at
# TInitStatics.cpp:1492-1501). Both points sit HALF A TILE beyond the 2x2
# collision box (x+0.5..2.5, y+1..3) along the facing, which is what lets a
# touch land from the resting gap a check-then-move movement script leaves
# (up to speed - 1/16 = 0.24 tiles short on Bomber v6) while staying strictly
# in front of the player — an adjacent NPC you are not facing is never
# probed. This table deliberately differs from collision.py's TOUCH_OFFSETS
# (grab/read reach); it is NPC touch only.
TOUCH_OFFSETS = {
    0: [(1.05, 0.5), (1.95, 0.5)],    # up
    1: [(0.0, 2.45), (0.0, 1.55)],    # left
    2: [(1.95, 3.5), (1.05, 3.5)],    # down
    3: [(3.0, 1.55), (3.0, 2.45)],    # right
}

# A character NPC (`showcharacter`) that never ran setshape/setshape2 still has
# a box: "a 2x2 square centered on the character's feet" at +(8, 16) pixels
# from its position (NPC.h:540-552 getCollisionBoundingBox), i.e. +(0.5, 1.0)
# tiles and 2x2 tiles in size. Same square gs1_client.py's _char_rect() hands
# to testnpc().
CHARACTER_TOUCH_DX = 0.5
CHARACTER_TOUCH_DY = 1.0
CHARACTER_TOUCH_TILES = 2
# NPC image of a character NPC: `showcharacter` sets it (NPC.h:484-487
# isCharacter, and GS1Commands.cpp:3049 which writes the prop). Servers that
# run the level script themselves stream that image to us; when OUR engine
# runs the command instead it records the same fact on the NPC dict as
# 'is_character' (gs1_client.py:1068).
CHARACTER_IMAGE = '#c#'


def _is_character_npc(npc_data: dict) -> bool:
    return (npc_data.get('image') == CHARACTER_IMAGE
            or bool(npc_data.get('is_character')))


@dataclass
class NPCShape:
    """Represents an NPC's collision/touch shape."""
    x: float
    y: float
    width: int  # In tiles
    height: int  # In tiles
    solid_flags: List[int] = field(default_factory=list)  # Per-tile flags (22=solid)
    # Optional exact point test overriding the rect/flags walk — used for
    # image-footprint shapes, where gs1.npc_footprint_hit refines the rect
    # per-pixel by image transparency (the reference touch test resolves to
    # !isPixelTransparent inside the image rect, TServerNPC::isOnNPC).
    hit_test: Optional[callable] = None

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
        if self.hit_test is not None:
            return bool(self.hit_test(px, py))
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
        if self.gs2 is not None:
            self.gs2.forget_npc(npc_id)

    def update_npcs(self):
        """Refresh per-NPC scripts and collision shapes.

        Shape geometry is whatever the GS1 engine recorded when the NPC's script
        ran setshape/setshape2 (positioned at the NPC's current x/y); call this
        after triggering playerenters so those shapes exist.

        A CHARACTER NPC with no script shape still gets a touch box, because
        upstream gives it one implicitly: `isCharacter() && shape is empty` ->
        a 2x2 square on its feet (NPC.h:540-552). Without that, classic
        Bomber's tailor NPC Jonah -- who only calls showcharacter, never
        setshape -- had no entry here at all, so check_touch could never
        return him and his `playertouchsme` handler never ran.

        A shapeless IMAGE NPC is touchable on its image footprint (setimgpart
        rect, else the image's full size), the same geometry that blocks
        movement: the reference touch dispatch and the wall test share
        TServerNPC::isOnNPC (Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:
        1807-1808 -> TServerNPC.cpp:2093-2196). GTA's touch-say signs and its
        `if (playertouchsme) {hidelocal; dontblocklocal;}` doors never talked
        or opened while only script shapes and characters got touch boxes.

        Touch does NOT check the blocking flag (a dontblock'ed NPC still
        fires playertouchsme when walked over) but an INVISIBLE NPC is
        untouchable — TServerNPC::isOnNPC bails on !m_visible before any
        geometry, and the wall path's blocking-flag skip is the wall path's
        alone. Hence the visibility gate here, and hence rebuilding from
        scratch on every call so hide/show cycles (GTA's doors re-show on
        timeout) track: a stale entry for a hidden NPC kept firing its touch.
        """
        shapes = getattr(self.gs1, "shapes", {}) if self.gs1 is not None else {}
        self.npc_shapes.clear()
        for npc_id, npc_data in self.client.npcs.items():
            self.npc_scripts[npc_id] = npc_data.get('script', '')

            if npc_data.get('visible', True) is False:
                continue
            geom = shapes.get(npc_id)
            w, h, flags = geom if geom else (0, 0, ())
            if w > 0 and h > 0:
                self.npc_shapes[npc_id] = NPCShape(
                    x=npc_data.get('x', 0), y=npc_data.get('y', 0),
                    width=int(w), height=int(h), solid_flags=list(flags))
            elif _is_character_npc(npc_data):
                self.npc_shapes[npc_id] = NPCShape(
                    x=float(npc_data.get('x', 0) or 0) + CHARACTER_TOUCH_DX,
                    y=float(npc_data.get('y', 0) or 0) + CHARACTER_TOUCH_DY,
                    width=CHARACTER_TOUCH_TILES, height=CHARACTER_TOUCH_TILES)
            elif npc_data.get('image'):
                # getattr guard: unit stubs stand in for gs1 with a bare
                # `.shapes` holder.
                image_rect = getattr(self.gs1, 'npc_image_rect', None)
                rect = image_rect(npc_data) if image_rect is not None else None
                if rect is not None:
                    rx, ry, rw, rh = rect
                    hit = self.gs1.npc_footprint_hit
                    self.npc_shapes[npc_id] = NPCShape(
                        x=rx, y=ry,
                        width=int(math.ceil(rw)), height=int(math.ceil(rh)),
                        hit_test=(lambda px, py, _n=npc_data, _h=hit:
                                  _h(_n, px, py)))

    def check_touch(self, player_x: float, player_y: float, player_dir: int) -> List[int]:
        """Check for NPC touches and return list of touched NPC IDs.

        Test points are the feet point plus the reference client's two
        per-direction `touchtestd` probe points (see TOUCH_OFFSETS above).
        collision.py's CollisionMixin keeps its own, different offsets for
        grab/read interactions (chests/signs/doors) — NPC touch follows the
        NPC-touch oracle, not that table.
        """
        touched = []

        # The reference probes reach half a tile beyond the collision box
        # along the facing (see TOUCH_OFFSETS above), so both flush contact
        # against a bottom-exclusive setshape2 rect AND the <= 0.24-tile
        # resting gap a check-then-move movement script leaves are inside a
        # faced NPC's footprint with margin — no epsilon extension needed
        # (this replaces the old 1/16-tile flush-contact hack).
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
        Refreshes the shape snapshot first (when a real GS1 engine is
        attached): touch geometry tracks live NPC state (script-moved
        positions, hide/show cycles like GTA's doors, late-arriving GS2
        setshape2), and callers on the default-movement path historically
        only snapshotted at level load. The walk is a cheap per-NPC dict
        pass. Harnesses that hand-build npc_shapes with no gs1 keep them.
        """
        if self.gs1 is not None:
            self.update_npcs()
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
    handler.touched_npcs = set()

    for y in [19, 18, 17]:
        print(f"\nMoving to (25, {y}) facing up...")
        handler.process_movement(25, y, 0)
    print(f"  -> playertouchsme fired for NPCs: {fired}")


if __name__ == "__main__":
    test_npc_handler()
