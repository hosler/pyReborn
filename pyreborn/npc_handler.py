#!/usr/bin/env python3
"""
NPC handler for client-side NPC collision detection and script execution.

In Graal, many NPC events are client-side:
- playerenters: Client detects entering a level
- playertouchsme: Client detects touching an NPC shape
- timeout: Client manages script timeouts

This module provides:
1. NPC shape parsing from scripts (setshape, setshape2)
2. Collision detection between player and NPC shapes
3. Event triggering (playertouchsme, playerenters)
4. Integration with GS1 interpreter
"""

import re
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


def parse_npc_shape(script: str) -> Optional[NPCShape]:
    """Parse setshape or setshape2 from NPC script.

    setshape type,width,height;
    setshape2 width,height,{flags...};
    """
    # Try setshape2 first (more detailed)
    match = re.search(r'setshape2\s+(\d+)\s*,\s*(\d+)\s*,\s*\{([^}]*)\}', script)
    if match:
        width = int(match.group(1))
        height = int(match.group(2))
        flags_str = match.group(3)
        flags = [int(f.strip()) for f in flags_str.split(',') if f.strip()]
        return NPCShape(x=0, y=0, width=width, height=height, solid_flags=flags)

    # Try setshape
    match = re.search(r'setshape\s+(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', script)
    if match:
        # type, width, height - type 1 is solid
        shape_type = int(match.group(1))
        width = int(match.group(2))
        height = int(match.group(3))
        if shape_type == 1:  # Solid shape
            # All tiles are solid
            flags = [22] * (width * height)
        else:
            flags = []
        return NPCShape(x=0, y=0, width=width, height=height, solid_flags=flags)

    return None


class NPCHandler:
    """Handles NPC collision detection and event triggering."""

    def __init__(self, client):
        self.client = client
        self.npc_shapes: Dict[int, NPCShape] = {}  # npc_id -> shape
        self.npc_scripts: Dict[int, str] = {}  # npc_id -> script
        self.last_player_pos: Tuple[float, float] = (0, 0)
        self.touched_npcs: Set[int] = set()  # NPCs currently being touched

        # Callbacks
        self.on_playertouchsme: Optional[callable] = None  # (npc_id, npc_data) -> None
        self.on_triggeraction: Optional[callable] = None  # (action, x, y) -> None

    def update_npcs(self):
        """Update NPC shapes from client's NPC data."""
        for npc_id, npc_data in self.client.npcs.items():
            script = npc_data.get('script', '')
            x = npc_data.get('x', 0)
            y = npc_data.get('y', 0)

            # Store script
            self.npc_scripts[npc_id] = script

            # Parse shape if present
            shape = parse_npc_shape(script)
            if shape:
                shape.x = x
                shape.y = y
                self.npc_shapes[npc_id] = shape

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

        # Trigger playertouchsme for new touches
        for npc_id in new_touches:
            npc_data = self.client.npcs.get(npc_id, {})
            script = self.npc_scripts.get(npc_id, '')

            # Check if script has playertouchsme with direction check
            if 'playertouchsme' in script:
                # Check for direction requirement (e.g., "playerdir == 0")
                dir_check = re.search(r'playerdir\s*==\s*(\d)', script)
                if dir_check:
                    required_dir = int(dir_check.group(1))
                    if direction != required_dir:
                        continue  # Skip - wrong direction

                # Trigger the event
                if self.on_playertouchsme:
                    self.on_playertouchsme(npc_id, npc_data)

                # Execute playertouchsme script block
                self._execute_playertouchsme(npc_id, script, direction)

        self.touched_npcs = touched_now
        self.last_player_pos = (new_x, new_y)

    def _execute_playertouchsme(self, npc_id: int, script: str, player_dir: int):
        """Execute the playertouchsme block of an NPC script."""
        # Find playertouchsme block
        pattern = r'if\s*\(playertouchsme[^)]*\)\s*\{'
        match = re.search(pattern, script, re.IGNORECASE)
        if not match:
            return

        # Extract block body
        start = match.end()
        brace_count = 1
        pos = start
        while pos < len(script) and brace_count > 0:
            if script[pos] == '{':
                brace_count += 1
            elif script[pos] == '}':
                brace_count -= 1
            pos += 1

        body = script[start:pos-1].replace('§', '\n')

        # Execute relevant commands
        self._execute_script_body(npc_id, body, player_dir)

    def _execute_script_body(self, npc_id: int, body: str, player_dir: int):
        """Execute script body, looking for triggeraction commands."""
        # Split by semicolon and newline
        lines = re.split(r'[;\n]', body)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Look for triggeraction
            match = re.match(r'triggeraction\s+([^;]+)', line, re.IGNORECASE)
            if match:
                args_str = match.group(1)
                # Parse: x,y,action,params...
                # e.g., "0,0,gr.addweapon,-validation"
                parts = [p.strip() for p in args_str.split(',')]
                if len(parts) >= 3:
                    x = float(parts[0]) if parts[0].replace('.', '').replace('-', '').isdigit() else self.client.x
                    y = float(parts[1]) if parts[1].replace('.', '').replace('-', '').isdigit() else self.client.y
                    action = ','.join(parts[2:])
                    print(f"  [TRIGGER] {action} at ({x}, {y})")
                    if self.on_triggeraction:
                        self.on_triggeraction(action, x, y)
                    else:
                        # Send to server
                        self.client.triggeraction(action, x, y, npc_id)

            # Look for setplayerprop #c (chat message)
            match = re.match(r'setplayerprop\s+#c\s*,\s*([^;]+)', line, re.IGNORECASE)
            if match:
                message = match.group(1).strip()
                print(f"  [CHAT] {message}")

            # Look for play (sound)
            match = re.match(r'play\s+([^;]+)', line, re.IGNORECASE)
            if match:
                sound = match.group(1).strip()
                print(f"  [PLAY] {sound}")

    def trigger_playerenters(self):
        """Trigger playerenters for all NPCs in current level."""
        self.update_npcs()
        for npc_id, script in self.npc_scripts.items():
            if 'playerenters' in script.lower():
                self._execute_playerenters(npc_id, script)

    def _execute_playerenters(self, npc_id: int, script: str):
        """Execute playerenters block of an NPC script."""
        pattern = r'if\s*\([^)]*playerenters[^)]*\)\s*\{'
        match = re.search(pattern, script, re.IGNORECASE)
        if not match:
            return

        start = match.end()
        brace_count = 1
        pos = start
        while pos < len(script) and brace_count > 0:
            if script[pos] == '{':
                brace_count += 1
            elif script[pos] == '}':
                brace_count -= 1
            pos += 1

        body = script[start:pos-1].replace('§', '\n')
        self._execute_script_body(npc_id, body, 2)  # Default direction


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

        def triggeraction(self, action, x, y, npc_id):
            print(f"  [SERVER] triggeraction: {action} at ({x}, {y}) npc={npc_id}")

    client = MockClient()
    handler = NPCHandler(client)

    print("=== Updating NPCs ===")
    handler.update_npcs()
    print(f"Shapes parsed: {len(handler.npc_shapes)}")
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

    # Test movement and event triggering
    print("\n=== Testing movement and events ===")
    print("Starting at (25, 20), moving up...")
    handler.last_player_pos = (25, 20)
    handler.touched_npcs = set()

    for y in [19, 18, 17]:
        print(f"\nMoving to (25, {y}) facing up...")
        handler.process_movement(25, y, 0)


if __name__ == "__main__":
    test_npc_handler()
