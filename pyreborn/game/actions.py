"""ActionsMixin — Player mechanics: move, sword, grab/pickup/throw, weapons, doors.

Split from pygame_game.py; methods operate on the GameClient instance."""

import time
import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame
from pygame.locals import (
    QUIT, KEYDOWN, MOUSEBUTTONDOWN,
    K_ESCAPE, K_RETURN, K_q, K_a, K_s, K_d, K_SPACE, K_m, K_h,
    K_UP, K_DOWN, K_LEFT, K_RIGHT,
    K_F1, K_F2, K_1, K_2, K_3, K_4, K_5, K_6, K_7
)

from .. import Client
from ..gani import GaniParser, AnimationState, direction_from_delta
from ..sprites import SpriteManager, TilesetManager, create_placeholder_sprite, create_shadow_sprite
from ..sounds import SoundManager, preload_common_sounds
from ..inventory_ui import InventoryUI, HeartDisplay
from ..npc_handler import NPCHandler
from ..player import Player
from ..tiletypes import TileType, get_tile_type
from .constants import (
    TILE_CORRECTIONS_FILE, TILE_SIZE, SCREEN_WIDTH, SCREEN_HEIGHT,
    TILESET_COLS, TILESET_ROWS, MOVE_STEP, parse_npc_visual_effects,
)


class ActionsMixin:
    """Mixin providing the above methods for GameClient."""

    def _facing_delta(self, direction: int) -> Tuple[int, int]:
        """(dx, dy) tile delta for a facing direction (0=up,1=left,2=down,3=right)."""
        return {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}.get(direction, (0, 0))
    def _move(self, dx: int, dy: int):
        """Move the player, checking for blocking tiles."""
        # Calculate destination position. Check the actual step distance the
        # client will move (matches Client.move's default step) so the player
        # stops right at a wall instead of a full tile short of it.
        step = MOVE_STEP
        dest_x = self.client.x + dx * step
        dest_y = self.client.y + dy * step

        # Check if destination is blocked (pass direction for directional checks)
        if self._is_position_blocked(dest_x, dest_y, dx, dy):
            # Can't move there - still update direction for visual feedback
            direction = direction_from_delta(dx, dy)
            self.player_anim.set_direction(direction)
            return

        # Move is allowed
        self.client.move(dx, dy)

        # Update direction
        direction = direction_from_delta(dx, dy)

        # Check NPC touch after movement
        self.npc_handler.process_movement(self.client.x, self.client.y, direction)

        # Update swimming state after move
        self._update_swimming_state()
        self.player_anim.set_direction(direction)

        # Pick the movement animation. Carrying uses the looping "carry" gani
        # (walk-with-object); setting it only when it changes lets it actually
        # animate instead of resetting to frame 0 every step.
        if self.is_swimming:
            move_anim = "swim"
        elif self.client.player.is_carrying():
            move_anim = "carry"
        else:
            move_anim = "walk"
        if self.current_anim_name != move_anim:
            self.player_anim.set_animation(move_anim, direction)
            self.current_anim_name = move_anim

        # Check for door link at new position (auto-warp on walk-into)
        door_link = self._get_non_edge_door()
        if door_link:
            self._use_door_link(door_link)
    def _swing_sword(self):
        """Swing sword attack."""
        self.client.sword_attack(self.client.player.direction)
        self.player_anim.set_animation("sword", self.client.player.direction, force=True)
        self.current_anim_name = "sword"
    def _try_grab(self):
        """Try to grab/interact with something.

        Priority:
        1. If carrying an object, throw it
        2. If sitting, stand up
        3. If near a chair, sit down
        4. Check for door links
        5. Try to pickup items at current position
        """
        player = self.client.player

        # If carrying something, throw it
        if player.is_carrying():
            self._throw_object()
            return

        # If sitting, stand up
        if player.is_sitting:
            player.stand_up()
            self.player_anim.set_animation("idle", player.direction, force=True)
            self.current_anim_name = "idle"
            return

        # Open a chest in front of the player
        chest = self._find_chest_in_front()
        if chest is not None:
            if not self.client.chests.get(chest, False):
                cx, cy = chest
                self.client.open_chest(cx, cy)
                self.client.chests[chest] = True   # optimistic; server confirms
            return

        # Check for chair in front of player
        chair_tile = self._find_adjacent_chair()
        if chair_tile is not None:
            tx, ty, tile_id = chair_tile
            # Sit down facing direction of chair
            if player.sit_down(player.direction):
                self.player_anim.set_animation("sit", player.direction, force=True)
                self.current_anim_name = "sit"
                return

        # Check for sign NPC nearby
        sign_text = self._check_sign_nearby()
        if sign_text:
            # Display sign text in dialogue box
            self._show_dialogue(sign_text)
            return

        # Check for door link
        door_link = self._get_non_edge_door()
        if door_link:
            self._use_door_link(door_link)
            return

        # Try to pickup item at current position
        self.client.pickup_item()
    def _check_sign_nearby(self) -> Optional[str]:
        """Check for sign NPC nearby and return its text if found."""
        import re
        player = self.client.player

        # Probe the per-direction touch points in front of the player.
        points = self._touch_points(player.direction)

        for npc_id, npc in self.client.npcs.items():
            npc_x = npc.get('x', 0)
            npc_y = npc.get('y', 0)

            # Check if NPC is close to any probed touch point
            if any(abs(npc_x - cx) < 1.5 and abs(npc_y - cy) < 1.5
                   for cx, cy in points):
                # Check if this NPC is a sign (has signlink or setplayerprop #c)
                script = npc.get('script', '')
                image = npc.get('image', '')

                # Look for sign-like images
                if 'sign' in image.lower():
                    # Extract message from script
                    match = re.search(r'setplayerprop\s+#c\s*,?\s*([^;]+)', script, re.IGNORECASE)
                    if match:
                        return match.group(1).strip()
                    # Try to find any text in the script
                    match = re.search(r'message\s+([^;]+)', script, re.IGNORECASE)
                    if match:
                        return match.group(1).strip()
                    # Default to NPC image name if it's a sign
                    return f"(Sign: {image})"

        return None
    def _show_dialogue(self, text: str):
        """Show dialogue text in the dialogue box."""
        self.dialogue_text = text
        self.dialogue_time = time.time()
    def _dismiss_dialogue(self):
        """Dismiss the current dialogue."""
        self.dialogue_text = None
    def _try_pickup(self, dx: int, dy: int):
        """Try to pickup a liftable 2x2 object (bush/rock/pot) in the given direction.

        Requires appropriate glove power:
        - Bush: glove power 1+
        - Pot: glove power 2+
        - Rock: glove power 3
        """
        player = self.client.player

        # Update direction first
        direction = direction_from_delta(dx, dy)
        self.player_anim.set_direction(direction)
        player.direction = direction

        # If already carrying, throw instead
        if player.is_carrying():
            self._throw_object()
            return

        # If sitting, stand up first
        if player.is_sitting:
            player.stand_up()

        # Probe the per-direction touch points and take the first liftable tile.
        points = self._touch_points(direction)
        target = next(((tx, ty) for tx, ty in points
                       if self._is_tile_liftable(self._get_tile_at(tx, ty))), None)

        if target is not None:
            target_x, target_y = target
            tile_id = self._get_tile_at(target_x, target_y)
            required_power = self._get_tile_lift_power(tile_id)
            glove_power = player.glove_power

            if glove_power >= required_power:
                # Find the 2x2 object origin (top-left corner)
                obj_origin = self._find_2x2_object_origin(target_x, target_y)
                if obj_origin:
                    ox, oy = obj_origin
                    # Get all 4 tile IDs
                    tile_ids = self._get_2x2_tiles(ox, oy)
                    object_name = self._get_liftable_name(tile_id)

                    # Store original tiles and replace with grass
                    self._remove_2x2_tiles(ox, oy, tile_ids)

                    # Pick up the object
                    player.pickup_object(object_name, tile_ids, (ox, oy))

                    # Play lift animation then switch to carry
                    self.player_anim.set_animation("lift", direction, force=True)
                    self.current_anim_name = "lift"

                    # Invalidate world surface to show removed tiles
                    self.world_surface = None

                    print(f"Picked up {object_name}!")
            else:
                # Not enough glove power
                object_name = self._get_liftable_name(tile_id)
                print(f"Need glove power {required_power} to lift {object_name} (have {glove_power})")
        else:
            # No liftable object in front - try a regular item pickup at the
            # primary touch point.
            px, py = points[0]
            self.client.pickup_item(px, py)

            # Play lift animation anyway for visual feedback
            self.player_anim.set_animation("lift", direction, force=True)
            self.current_anim_name = "lift"
    def _find_2x2_object_origin(self, x: float, y: float) -> Optional[Tuple[int, int]]:
        """Find the top-left corner of a 2x2 liftable object.

        Checks if the clicked tile is part of a 2x2 group of the same type.
        Returns (origin_x, origin_y) or None if not found.
        """
        tx, ty = int(x), int(y)
        tile_id = self._get_tile_at(tx, ty)
        if not self._is_tile_liftable(tile_id):
            return None

        tile_type = self._get_corrected_tile_type(tile_id)

        # Check all 4 possible positions this tile could be in a 2x2 grid
        # and find which arrangement has all matching tiles
        possible_origins = [
            (tx, ty),      # This is top-left
            (tx - 1, ty),  # This is top-right
            (tx, ty - 1),  # This is bottom-left
            (tx - 1, ty - 1),  # This is bottom-right
        ]

        for ox, oy in possible_origins:
            # Check if all 4 tiles in this 2x2 are the same type
            all_match = True
            for dy in range(2):
                for dx in range(2):
                    check_tile = self._get_tile_at(ox + dx, oy + dy)
                    check_type = self._get_corrected_tile_type(check_tile)
                    if check_type != tile_type:
                        all_match = False
                        break
                if not all_match:
                    break

            if all_match:
                return (ox, oy)

        # Fallback: just use this tile as origin (for single-tile objects)
        return (tx, ty)
    def _get_2x2_tiles(self, ox: int, oy: int) -> Tuple[int, int, int, int]:
        """Get the 4 tile IDs of a 2x2 object starting at origin."""
        tl = self._get_tile_at(ox, oy)
        tr = self._get_tile_at(ox + 1, oy)
        bl = self._get_tile_at(ox, oy + 1)
        br = self._get_tile_at(ox + 1, oy + 1)
        return (tl, tr, bl, br)
    def _remove_2x2_tiles(self, ox: int, oy: int, tile_ids: Tuple[int, int, int, int]):
        """Remove 2x2 tiles from the level and replace with grass."""
        level_name = self.client._current_level_name
        if not level_name or level_name not in self.client.levels:
            return

        tiles = self.client.levels[level_name]
        local_ox = ox % 64
        local_oy = oy % 64

        # Store original tiles and replace with grass
        positions = [(0, 0), (1, 0), (0, 1), (1, 1)]
        for i, (dx, dy) in enumerate(positions):
            lx, ly = local_ox + dx, local_oy + dy
            if 0 <= lx < 64 and 0 <= ly < 64:
                idx = ly * 64 + lx
                self.removed_tiles[(level_name, lx, ly)] = tile_ids[i]
                tiles[idx] = self.grass_tile_id
    def _restore_2x2_tiles(self, ox: int, oy: int, tile_ids: Tuple[int, int, int, int]):
        """Restore 2x2 tiles to the level (when throwing object back)."""
        level_name = self.client._current_level_name
        if not level_name or level_name not in self.client.levels:
            return

        tiles = self.client.levels[level_name]
        local_ox = ox % 64
        local_oy = oy % 64

        # Restore original tiles
        positions = [(0, 0), (1, 0), (0, 1), (1, 1)]
        for i, (dx, dy) in enumerate(positions):
            lx, ly = local_ox + dx, local_oy + dy
            if 0 <= lx < 64 and 0 <= ly < 64:
                idx = ly * 64 + lx
                tiles[idx] = tile_ids[i]
                # Remove from tracking
                key = (level_name, lx, ly)
                if key in self.removed_tiles:
                    del self.removed_tiles[key]
    def _throw_object(self):
        """Throw the currently carried object."""
        player = self.client.player
        if not player.is_carrying():
            return

        thrown_type, thrown_tiles, thrown_pos = player.throw_object()
        direction = player.direction

        # Play throw animation; fall back to idle if the gani isn't available
        # (otherwise we'd stay stuck in the looping carry pose after throwing).
        anim = "throw" if self.gani_parser.parse("throw") else "idle"
        self.player_anim.set_animation(anim, direction, force=True)
        self.current_anim_name = anim

        if not thrown_tiles:
            print(f"Threw {thrown_type} in direction {direction}!")
            return

        # Land the object ~2 tiles ahead of the player's feet, centered.
        fx, fy = self._player_feet()
        ddx, ddy = self._facing_delta(direction)
        ox = int(round(fx - 0.5 + ddx * 2))
        oy = int(round(fy - 0.5 + ddy * 2))

        # Validate the landing 2x2 is on-level and not blocked; else drop where
        # it was picked up so it never vanishes into a wall.
        clear = True
        for ddx2 in range(2):
            for ddy2 in range(2):
                tx, ty = ox + ddx2, oy + ddy2
                if not self.client.is_gmap and not (0 <= tx < 64 and 0 <= ty < 64):
                    clear = False
                elif self._is_tile_blocking(self._get_tile_at(tx, ty)):
                    clear = False
        if not clear and thrown_pos:
            ox, oy = thrown_pos

        self._restore_2x2_tiles(ox, oy, thrown_tiles)
        self.world_surface = None  # Force redraw

        print(f"Threw {thrown_type} in direction {direction} -> ({ox},{oy})!")
    def _find_chest_in_front(self) -> Optional[Tuple[int, int]]:
        """Return the (cx, cy) key of a chest whose 2x2 footprint the player is
        facing, or None. Chests block, so the player stands adjacent and the
        per-direction touch points land on the chest's tiles."""
        chests = getattr(self.client, "chests", None)
        if not chests:
            return None
        for tx, ty in self._touch_points(self.client.player.direction):
            ftx, fty = math.floor(tx), math.floor(ty)
            for (cx, cy) in chests:
                if cx <= ftx <= cx + 1 and cy <= fty <= cy + 1:
                    return (cx, cy)
        return None
    def _find_adjacent_chair(self) -> Optional[Tuple[int, int, int]]:
        """Find a chair tile adjacent to the player in the direction they're facing.

        Returns (tile_x, tile_y, tile_id) if chair found, None otherwise.
        """
        player = self.client.player

        # Check the per-direction touch points in front of the player, plus the
        # feet tile itself, so sitting works whether you walk onto or face a chair.
        candidates = self._touch_points(player.direction) + [self._player_feet()]
        for cx, cy in candidates:
            tile_id = self._get_tile_at(cx, cy)
            if self._is_tile_chair(tile_id):
                return (int(cx), int(cy), tile_id)

        return None
    def _use_weapon(self):
        """Use the currently equipped weapon."""
        # Get selected weapon from inventory
        weapon = self.inventory_ui.get_selected_weapon(self.weapons)
        if weapon:
            # Use weapon-specific action
            if "bow" in weapon.lower():
                self.client.shoot(self.client.player.direction)
                # Spawn visual projectile
                import math
                direction = self.client.player.direction
                speed = 8.0  # Tiles per second
                # Direction to velocity
                dx_map = {0: 0, 1: -speed, 2: 0, 3: speed}
                dy_map = {0: -speed, 1: 0, 2: speed, 3: 0}
                self.active_projectiles.append({
                    'x': self.client.player.x,
                    'y': self.client.player.y,
                    'dx': dx_map.get(direction, 0),
                    'dy': dy_map.get(direction, 0),
                    'time': time.time(),
                    'direction': direction,
                    'gani': 'arrow',
                    'max_distance': 10.0,  # Max distance in tiles
                    'start_x': self.client.player.x,
                    'start_y': self.client.player.y,
                })
            elif "bomb" in weapon.lower():
                self.client.drop_bomb(self.client.player.bomb_power)
                # Spawn visual bomb at player position
                self.active_bombs.append({
                    'x': self.client.player.x,
                    'y': self.client.player.y,
                    'time': time.time(),
                    'power': self.client.player.bomb_power,
                    'exploded': False,
                })
            else:
                # Default to sword attack
                self.client.sword_attack(self.client.player.direction)
    def _cycle_weapon(self):
        """Cycle through available weapons."""
        self.inventory_ui.cycle_weapon(self.weapons)
    def _use_door_link(self, door_link: dict):
        """Use a door link to warp to another level."""
        self.client.use_link(door_link)
        # Update visual position to match new position
        self.visual_x = self.client.x
        self.visual_y = self.client.y
        # Force world surface redraw
        self.world_surface = None
        # Load and trigger NPC scripts for new level
        self._load_npc_scripts()
        self._trigger_playerenters()
        self.npc_handler.trigger_playerenters()
    def _get_non_edge_door(self) -> Optional[dict]:
        """Get door link at current position, ignoring edge links in GMAP mode."""
        link = self.client.check_link_collision()
        if not link:
            return None

        # In GMAP mode, ignore edge links
        if self.client.is_gmap:
            if self._is_edge_link(link):
                return None

        return link
    def _is_edge_link(self, link: dict) -> bool:
        """Check if a link is an edge warp."""
        x = link.get('x', 0)
        y = link.get('y', 0)
        w = link.get('width', 1)
        h = link.get('height', 1)

        # Edge links are at level boundaries
        return x <= 1 or x + w >= 63 or y <= 1 or y + h >= 63
    def _update_swimming_state(self):
        """Update swimming state based on current position."""
        was_swimming = self.is_swimming
        self.is_swimming = self._check_water_at_position(self.client.x, self.client.y)

        # If swimming state changed, update animation
        if self.is_swimming != was_swimming:
            if self.is_swimming:
                # Just entered water - could play splash sound
                pass
            else:
                # Just left water
                pass
