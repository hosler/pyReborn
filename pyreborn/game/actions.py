"""ActionsMixin — Player mechanics: move, sword, grab/pickup/throw, weapons, doors.

Split from pygame_game.py; methods operate on the GameClient instance."""

import time
import json
import math
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
        """Move the player, checking for blocking tiles.

        If a diagonal move is blocked, slide along whichever axis is still free
        so the player glides along walls instead of sticking to them.
        """
        player = self.client.player

        # Press a direction INTO an adjacent object to interact, the classic
        # Reborn way (no separate action key): a chest in front opens, a chair in
        # front seats you. Face the pressed direction first so the in-front
        # probes look the right way.
        facing = direction_from_delta(dx, dy)
        player.direction = facing
        self.player_anim.set_direction(facing)

        chest = self._find_chest_in_front()
        if chest is not None:
            if not self.client.chests.get(chest, False):
                cx, cy = chest
                self.client.open_chest(cx, cy)
                self.client.chests[chest] = True   # optimistic; server confirms
            return

        # Sitting is walk-on: standing on a chair tile IS sitting (see
        # _update_sitting_state) — movement is never intercepted or blocked
        # for chairs, it's just a different idle ani.

        step = MOVE_STEP
        # Candidate moves: the full input first, then each single axis as a slide.
        candidates = [(dx, dy)]
        if dx != 0 and dy != 0:
            candidates += [(dx, 0), (0, dy)]

        mdx = mdy = 0
        # Escape hatch: if we're ALREADY overlapping a wall (bad server spawn,
        # warp onto a solid tile), blocking every move would trap us — allow
        # movement so the player can walk out.
        stuck = self._is_position_blocked(self.client.x, self.client.y)
        for cdx, cdy in candidates:
            if stuck or not self._is_position_blocked(self.client.x + cdx * step,
                                                      self.client.y + cdy * step,
                                                      cdx, cdy):
                mdx, mdy = cdx, cdy
                break

        if mdx == 0 and mdy == 0:
            # Fully blocked - still face where we tried to go.
            blocked_dir = direction_from_delta(dx, dy)
            self.player_anim.set_direction(blocked_dir)
            # You touch an NPC by walking INTO it; if a wall behind it stops the
            # move, fire touch detection anyway at the direction we pressed so the
            # NPC's playertouchsme still runs (room-join NPC, signs, ...).
            self.npc_handler.process_movement(self.client.x, self.client.y, blocked_dir)
            # Cave/door entrances sit on solid tiles you can't step onto, so
            # walking into them blocks. Treat pushing into a warp link as
            # entering it (the body-sample detection sees the overlapped door).
            self._try_link_warp()
            return

        # Move is allowed (full or slid onto a free axis).
        self.client.move(mdx, mdy)

        # Face the direction we actually moved.
        direction = direction_from_delta(mdx, mdy)

        # Check NPC touch after movement
        self.npc_handler.process_movement(self.client.x, self.client.y, direction)

        # Update swimming state after move
        self._update_swimming_state()
        self.player_anim.set_direction(direction)

        # Pick the movement animation. Carrying uses the looping "carry" gani
        # (walk-with-object); setting it only when it changes lets it actually
        # animate instead of resetting to frame 0 every step. (Sword/lift
        # can't be active here — those root the player in _handle_input.)
        if self.is_swimming:
            move_anim = "swim"
        elif self.client.player.is_carrying():
            move_anim = "carry"
        else:
            move_anim = "walk"
        if self.current_anim_name != move_anim:
            self.player_anim.set_animation(move_anim, direction)
            self.current_anim_name = move_anim

        # Check for door/edge link at new position (auto-warp on walk-into).
        self._try_link_warp()
    def _swing_sword(self):
        """Swing sword attack."""
        player = self.client.player
        self.client.sword_attack(player.direction)
        self.player_anim.set_animation("sword", player.direction, force=True)
        self.current_anim_name = "sword"
    def _try_grab(self):
        """Try to grab/interact with something.

        Priority:
        1. If carrying an object, throw it
        2. Open a chest / lift an object / read a sign / use a door
        3. Try to pickup items at current position

        (Sitting is walk-on state, not a grab action — see
        _update_sitting_state.)
        """
        player = self.client.player

        # If carrying something, throw it
        if player.is_carrying():
            self._throw_object()
            return

        # Open a chest in front of the player
        chest = self._find_chest_in_front()
        if chest is not None:
            if not self.client.chests.get(chest, False):
                cx, cy = chest
                self.client.open_chest(cx, cy)
                self.client.chests[chest] = True   # optimistic; server confirms
            return

        # Lift a bush/pot/rock in front — plain A lifts, classic style (no
        # arrow needed).
        if self._lift_in_front(player.direction):
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
        """Check for a sign at the player's touch points and return its text.

        Reads client.signs (the real parsed sign data: {level_name: {(x, y):
        text}}, tile coords LOCAL to the level) — the same source
        render_objects.py's _check_and_render_signs auto-popup reads, so the
        A-press path and the proximity popup agree. This replaces the old
        regex-scraping of NPC scripts/images, which only ever matched signs
        implemented as NPCs and could return garbage for anything else."""
        signs = self.client.signs.get(self.client._current_level_name)
        if not signs:
            return None

        player = self.client.player
        for tx, ty in self._touch_points(player.direction):
            # Touch points are world coords (matter in a GMAP); sign keys are
            # level-local, so wrap the same way render_objects.py does.
            lx, ly = tx % 64, ty % 64
            for (sx, sy), text in signs.items():
                if abs(lx - sx) < 1.5 and abs(ly - sy) < 1.5:
                    return text

        return None
    def _show_dialogue(self, text: str):
        """Show dialogue text in the dialogue box."""
        self.dialogue_text = text
        self.dialogue_time = time.time()
    def _dismiss_dialogue(self):
        """Dismiss the current dialogue."""
        self.dialogue_text = None
    def _try_pickup(self, dx: int, dy: int):
        """A + arrow: lift a 2x2 object (bush/rock/pot) in that direction, or
        throw the carried one."""
        player = self.client.player

        # Update direction first
        direction = direction_from_delta(dx, dy)
        self.player_anim.set_direction(direction)
        player.direction = direction

        # If already carrying, throw instead
        if player.is_carrying():
            self._throw_object()
            return

        if not self._lift_in_front(direction):
            # No liftable object in front - try a regular item pickup at the
            # primary touch point. No lift animation: flailing the lift gani
            # at empty ground on every failed grab read as pure jank.
            px, py = self._touch_points(direction)[0]
            self.client.pickup_item(px, py)

    def _lift_in_front(self, direction: int) -> bool:
        """Lift the 2x2 liftable (bush/pot/rock) at the touch points for the
        given facing, if any and glove power allows. Returns True if lifted."""
        player = self.client.player

        # Probe the per-direction touch points and take the first liftable tile.
        points = self._touch_points(direction)
        target = next(((tx, ty) for tx, ty in points
                       if self._is_tile_liftable(self._get_tile_at(tx, ty))), None)
        if target is None:
            return False

        target_x, target_y = target
        tile_id = self._get_tile_at(target_x, target_y)
        tile_type = self._get_corrected_tile_type(tile_id)
        required_power = self._get_tile_lift_power(tile_id)
        object_name = self._get_liftable_name(tile_id)

        if player.glove_power < required_power:
            print(f"Need glove power {required_power} to lift {object_name} "
                  f"(have {player.glove_power})")
            return False

        # Find the 2x2 object origin (top-left corner)
        obj_origin = self._find_2x2_object_origin(target_x, target_y)
        if not obj_origin:
            return False

        ox, oy = obj_origin
        # tile_type/tile_id let _get_2x2_tiles and _remove_2x2_tiles tell a real
        # quadrant of the object from a neighbor that only happens to sit in the
        # 2x2 box (the corrections overlay may only cover some of an object's 4
        # tiles, so the single-tile fallback origin above can pull in plain
        # grass/other decor on the other 3).
        tile_ids = self._get_2x2_tiles(ox, oy, tile_type, tile_id)

        # Remove the object's tiles (replaced with grass) and hoist it overhead.
        self._remove_2x2_tiles(ox, oy, tile_type)
        player.pickup_object(object_name, tile_ids, (ox, oy))

        # Play lift animation then switch to carry
        self.player_anim.set_animation("lift", direction, force=True)
        self.current_anim_name = "lift"
        self.sound_mgr.play("lift.wav")

        # Invalidate world surface to show removed tiles
        self.world_surface = None
        return True
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
    def _get_2x2_tiles(self, ox: int, oy: int, tile_type: int, anchor_tile_id: int) -> Tuple[int, int, int, int]:
        """Get the 4 tile IDs of a 2x2 object starting at origin.

        Only quadrants whose corrected type matches the lifted object's type
        are real pieces of it (the corrections overlay may only cover some of
        an object's 4 tiles). A mismatched quadrant reports anchor_tile_id
        (the tile that was actually lifted) instead of its own unrelated tile
        — the carried-object renderer (render_entities.py _render_carried_object)
        indexes tile_ids directly into a tileset lookup with no None/0 handling,
        so a real tile id is required; anchor_tile_id renders fine there and
        _remove_2x2_tiles below leaves that quadrant's actual tile in place.
        """
        tiles = []
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            t = self._get_tile_at(ox + dx, oy + dy)
            tiles.append(t if self._get_corrected_tile_type(t) == tile_type else anchor_tile_id)
        return tuple(tiles)
    def _remove_2x2_tiles(self, ox: int, oy: int, tile_type: int):
        """Remove the 2x2 object's tiles from the level, replacing with grass.

        Skips any quadrant whose corrected type doesn't match tile_type — that
        position isn't part of the object (see _get_2x2_tiles), so its tile
        stays on the ground untouched."""
        # Per-tile segment lookup so an object straddling a GMAP boundary (or
        # lifted from the adjacent segment) edits the right level's tiles.
        positions = [(0, 0), (1, 0), (0, 1), (1, 1)]
        for dx, dy in positions:
            wx, wy = ox + dx, oy + dy
            check_tile = self._get_tile_at(wx, wy)
            if self._get_corrected_tile_type(check_tile) != tile_type:
                continue
            level_name, tiles = self._level_tiles_at(wx, wy)
            if not level_name or not tiles:
                continue
            lx, ly = wx % 64, wy % 64
            tiles[ly * 64 + lx] = self.grass_tile_id
    def _throw_object(self):
        """Throw the carried object: it flies ahead in an arc and breaks on
        landing (or on the first wall it hits), classic style. It does NOT
        re-plant itself in the level — a thrown bush is a destroyed bush."""
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
        self.sound_mgr.play("put.wav")

        if not thrown_tiles:
            return

        ddx, ddy = self._facing_delta(direction)
        # Launch from where the carried object is drawn: 2x2 top-left over the
        # head, i.e. z0 tiles above a ground anchor just below the torso — so
        # the sprite doesn't jump on release.
        z0 = 2.75
        self.thrown_objects.append({
            'tiles': thrown_tiles,
            'type': thrown_type,
            'x': self.client.x,          # ground-projected 2x2 top-left
            'y': self.client.y + 1.0,
            'z': z0, 'z0': z0,           # height above ground, eases to 0
            'dx': ddx, 'dy': ddy,
            'speed': 20.0,               # tiles/second
            'dist': 0.0,
            'range': 16.0,               # tiles of flight before landing
        })
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
    def _update_sitting_state(self):
        """Walk-on sitting: you're seated exactly while standing still on a
        chair tile. Movement is completely normal — walking onto, across, and
        off a chair is just walking; only the stationary ani differs."""
        player = self.client.player
        on_chair = (not self.is_moving and not player.is_carrying()
                    and not self.is_swimming
                    and self._is_tile_chair(self._get_tile_at(*self._player_feet())))
        if on_chair and not player.is_sitting:
            if player.sit_down(player.direction):
                self.client.set_animation("sit")
        elif not on_chair and player.is_sitting:
            player.stand_up()
            # Tell the server/other players we're no longer in the sit gani.
            self.client.set_animation("walk" if self.is_moving else "idle")
    def _use_weapon(self):
        """Use the currently equipped weapon."""
        # Get selected weapon from inventory
        weapon = self.inventory_ui.get_selected_weapon(self.weapons)
        if weapon:
            # A GS1-scripted weapon (a Reborn weapon is an inventory NPC) handles
            # its own fire: pressing D fires the weapon-fire event and the script
            # does the work (drops a bomb, shoots, ...). This is how Bomber Arena
            # weapons play. Fall through to the built-in actions only if the
            # weapon has no script loaded.
            prog_key = f"weapon_{weapon}"
            gs1 = getattr(self, 'gs1', None)
            if gs1 is not None and prog_key in getattr(gs1, '_progs', {}):
                for ev in ('playerfires', 'weaponfired'):
                    try:
                        gs1.trigger_event(ev, name=prog_key)
                    except Exception:
                        pass
                return
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
    def _try_link_warp(self) -> bool:
        """Warp through a link under the player, but only on the rising edge of
        touching it.

        After a warp you arrive standing ON a link — often the return link, or,
        in crusty hand-built levels, smack in the middle of an overlapping one.
        Firing every frame you're on a link would bounce you straight back, so a
        link only triggers when you first step onto it (was-off -> now-on); while
        you stay on links (walking out across an overlap) nothing re-fires."""
        # Expire the post-warp suppression once we've physically moved away from
        # where the last warp dropped us (distance, NOT link-load state — the new
        # level's links can arrive a few frames late, and clearing on "no link
        # right now" would re-arm a return warp and loop).
        if self._link_arrival is not None:
            ax, ay = self._link_arrival
            if abs(self.client.x - ax) >= 1.5 or abs(self.client.y - ay) >= 1.5:
                self._link_arrival = None

        link = self._get_non_edge_door()
        on_link = link is not None
        if not on_link:
            self._was_on_link = False
            return False
        # Still sitting near a recent warp arrival: don't re-fire (covers the
        # return link, an overlapping link we landed in, and late-loading links).
        if self._link_arrival is not None:
            self._was_on_link = True
            return False
        if not self._was_on_link:
            # Rising edge: stepped onto a link. Mark on-link + record the arrival
            # point BEFORE warping isn't possible (use_link moves us), so set the
            # latch first, then stamp arrival from the post-warp position.
            self._was_on_link = True
            self._use_door_link(link)
            self._link_arrival = (self.client.x, self.client.y)
            return True
        return False
    def _use_door_link(self, door_link: dict):
        """Use a door link to warp to another level."""
        self.client.use_link(door_link)
        # Update visual position to match new position
        self.visual_x = self.client.x
        self.visual_y = self.client.y
        # Force world surface redraw
        self.world_surface = None
        # Load + run NPC scripts through the GS1 engine, THEN snapshot collision
        # shapes — setshape runs during playerenters, so shapes only exist after.
        self._load_npc_scripts()
        self._trigger_playerenters()
        self.npc_handler.update_npcs()
        # Mark this level as the one the GS1 engine is loaded for so the loop's
        # level-change detector doesn't redundantly reload it.
        self._gs1_level = self.client._current_level_name
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
        # Sample the feet, not the sprite's top-left (1 tile left, 2.5 tiles
        # above where the player actually stands) — otherwise swimming is
        # judged a tile off from where the player visibly is.
        self.is_swimming = self._check_water_at_position(*self._player_feet())

        # If swimming state changed, update animation
        if self.is_swimming != was_swimming:
            player = self.client.player
            if self.is_swimming:
                # Just entered water: splash feedback, and snap the gani to
                # swim immediately if we're not mid-move/mid-action (a step
                # that ends in water is already picked up by _move()'s
                # move_anim choice; this covers standing still / warping into
                # water, which used to leave the walk/idle gani showing until
                # the next explicit anim change).
                self.sound_mgr.play("splash.wav")
                if not player.is_carrying() and not player.is_sitting and \
                        self.current_anim_name in ("idle", "walk"):
                    self.player_anim.set_animation("swim", player.direction)
                    self.current_anim_name = "swim"
            else:
                # Just left water: splash out, and restore idle/walk from
                # swim/swim-idle so the player doesn't stay in the swim pose
                # standing on dry land.
                self.sound_mgr.play("splash.wav")
                if self.current_anim_name == "swim" and not self.is_moving:
                    self.player_anim.set_animation("idle", player.direction)
                    self.current_anim_name = "idle"
