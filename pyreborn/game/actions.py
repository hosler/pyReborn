"""ActionsMixin — Player mechanics: move, sword, grab/pickup/throw, weapons, doors.

Split from pygame_game.py; methods operate on the GameClient instance."""

import time
import math
from typing import Optional, Tuple

from pygame.locals import (
    K_UP, K_DOWN, K_LEFT, K_RIGHT,
)

from reborn_protocol.coords import level_index, segment_at, world_to_local

from ..gani import direction_from_delta
from ..tiletypes import TileType
from .constants import (
    MOVE_STEP, PUSH_HOLD_TIME,
)


class ActionsMixin:
    """Mixin providing the above methods for GameClient."""

    def _facing_delta(self, direction: int) -> Tuple[int, int]:
        """(dx, dy) tile delta for a facing direction (0=up,1=left,2=down,3=right)."""
        return {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}.get(direction, (0, 0))

    def _pickup_ground_item(self, x: Optional[float] = None,
                            y: Optional[float] = None) -> bool:
        """Request a local pickup and play its sound when an item is present."""
        target_x = self.client.player.x if x is None else x
        target_y = self.client.player.y if y is None else y
        level_resolver = getattr(self.client, "get_current_level_from_position", None)
        level_name = level_resolver() if level_resolver is not None else ""
        items_reader = getattr(self.client, "items_in_level", None)
        items = (items_reader(level_name) if items_reader is not None
                 else getattr(self.client, "items", {}))
        local_x, local_y = world_to_local(target_x, target_y)
        nearby = min(
            ((math.hypot(ix - local_x, iy - local_y), item_type)
             for (ix, iy), item_type in items.items()),
            default=None,
        )
        sent = self.client.pickup_item(x, y)
        if sent and nearby is not None and nearby[0] <= 2.0:
            item_type = nearby[1].lower()
            sound = "item2.wav" if any(
                part in item_type for part in ('heart', 'key')) else "item.wav"
            self.sound_mgr.play(sound)
        return sent

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
            cx, cy = chest
            level_name = self._found_chest_level
            if not self.client.get_chest_opened(level_name, cx, cy):
                self.client.open_chest(cx, cy)
                self.client.set_chest_opened(level_name, cx, cy)
            return

        # Sitting is walk-on: having your feet on a chair tile IS sitting (see
        # _update_sitting_state) — movement is never intercepted or blocked
        # for chairs, you just ride across them in the sit ani.

        step = MOVE_STEP
        # Candidate moves: the full input first, then each single axis as a slide.
        candidates = [(dx, dy)]
        if dx != 0 and dy != 0:
            candidates += [(dx, 0), (0, dy)]

        mdx = mdy = 0
        # Escape hatch: if we're ALREADY overlapping a wall (bad server spawn,
        # warp onto a solid tile), blocking every move would trap us — allow
        # movement so the player can walk out. But only moves that stay on the
        # board and don't deepen the overlap: a blanket allow is noclip (walk
        # through walls, off the level edge, into negative coords).
        stuck_count = self._blocked_sample_count(self.client.x, self.client.y)
        for cdx, cdy in candidates:
            nx = self.client.x + cdx * step
            ny = self.client.y + cdy * step
            if stuck_count:
                if (not self._position_out_of_bounds(nx, ny)
                        and self._blocked_sample_count(nx, ny) <= stuck_count):
                    mdx, mdy = cdx, cdy
                    break
            elif not self._is_position_blocked(nx, ny, cdx, cdy):
                mdx, mdy = cdx, cdy
                break

        # Corner-assist: a blocked pure-cardinal press (no diagonal slide
        # applied above) that's only blocked by being slightly off a
        # doorway/corner opening gets nudged perpendicular instead of
        # stopping dead (see collision.py's _corner_assist_offset for the
        # geometry). Facing stays the PRESSED cardinal direction throughout
        # — the nudge is a positional aid, not a real turn, so the sprite
        # doesn't flip to face the nudge axis while sliding through.
        corner_assist_dir = None
        if mdx == 0 and mdy == 0 and not stuck_count:
            nudge = self._corner_assist_offset(dx, dy)
            if nudge:
                mdx, mdy = nudge
                corner_assist_dir = facing

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
            # Held-into-a-wall push feel — see _update_push_hold's docstring.
            self._update_push_hold(dx, dy)
            return

        # A move went through — no longer holding into a wall.
        self._clear_push_hold()

        # Move is allowed (full, slid onto a free axis, or a corner-assist
        # nudge). A corner-assist nudge keeps the originally-pressed facing
        # instead of the inferred nudge-axis direction (see face_direction).
        self.client.move(mdx, mdy, face_direction=corner_assist_dir)

        # Face the direction we actually moved (or the pressed direction,
        # for a corner-assist nudge).
        direction = corner_assist_dir if corner_assist_dir is not None \
            else direction_from_delta(mdx, mdy)

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
        # The touch dispatch above can hand the player to a script IN THIS
        # frame (bomber's piano: playertouchsme -> freezeplayer + setani
        # sen_piano_idle). A frozen player doesn't play walk — and writing it
        # here would also clobber player_anim.requested_name, killing the
        # on_file re-assert of a still-downloading scripted gani.
        if (self.current_anim_name != move_anim
                and time.time() >= getattr(self, '_frozen_until', 0.0)):
            self.player_anim.set_animation(move_anim, direction)
            self.current_anim_name = move_anim

        # Check for door/edge link at new position (auto-warp on walk-into).
        self._try_link_warp()

    def _scripted_movement_touch(self, keys):
        """NPC-touch probe for scripted movement (disabledefmovement).

        With default_movement off a weapon script moves the player from the
        VM, so _move() — the only caller of npc_handler.process_movement —
        never runs and playertouchsme/onPlayerTouchsMe can never fire.
        Bomber v6's queue counter (NPC 10376) is joined by pushing INTO it,
        so that killed both touch events and queue joins.

        Pushing a held arrow toward an NPC's shape is the same gesture as
        walking into it, so run the identical touch dispatch off the pressed
        direction at the player's current (script-driven) position, every
        frame a direction is held. process_movement's touched-set dedupes
        for as long as the overlap lasts, and also updates itself when the
        player leaves a shape — so a later re-push re-fires (the counter
        NPC's handlePlayer TOGGLES queue membership; re-fire must require
        walking away first, which the touched-set gives us for free)."""
        handler = getattr(self, 'npc_handler', None)
        if handler is None:
            return
        dx = dy = 0
        if keys[K_UP]:
            dy = -1
        elif keys[K_DOWN]:
            dy = 1
        if keys[K_LEFT]:
            dx = -1
        elif keys[K_RIGHT]:
            dx = 1
        if dx == 0 and dy == 0:
            return
        direction = direction_from_delta(dx, dy)
        # GS2-only NPCs (v6 bytecode, no GS1 script text) record their
        # setshape2 when pump_level_events runs their onPlayerEnters — a
        # frame or more AFTER _reload_level_scripts took the level-entry
        # update_npcs() snapshot, and nothing else re-snapshots for them.
        # Refresh here (cheap dict walk) so the probe sees those shapes and
        # any script-moved NPC positions.
        handler.update_npcs()
        handler.process_movement(self.client.x, self.client.y, direction)

    def _check_scripted_link_warp(self) -> bool:
        """Link-warp probe for scripted movement (disabledefmovement).

        With default_movement off a weapon script writes player x/y from the
        VM, so _move() — the only caller of _try_link_warp — never runs and
        walking onto a door link stopped warping. (Bomber v6's -Test/Movement
        weapon does NOT warp links itself: its bytecode only does wall checks
        (onwall2/hitwall) and ganis, matching the reference client, which
        warps whenever the player's position enters a link rect no matter
        what moved them.) So re-probe from the frame loop after the script
        engines have ticked, on any position change. _try_link_warp's
        rising-edge latch + arrival suppression already make a per-frame
        probe safe (no bounce across return/overlapping links), and a fired
        warp goes through the same _use_door_link path as an input-driven
        one (GS1/GS2 reload, playerenters, swimming recompute — never fork
        that logic).

        (Sibling gap: NPC touch under scripted movement is handled by
        _scripted_movement_touch above — that one is key-gesture-driven,
        while links are pure position overlap.)"""
        gs1 = getattr(self, 'gs1', None)
        if gs1 is None or gs1.default_movement:
            return False
        # Mid level-transition the position/link tables are in flux; let the
        # in-flight warp settle before probing again.
        if (getattr(self.client, '_local_level_transition', '')
                or getattr(self, '_level_transition_input_frozen', False)):
            return False
        pos = (self.client.x, self.client.y)
        if pos == getattr(self, '_scripted_link_pos', None):
            return False
        self._scripted_link_pos = pos
        self._check_scripted_gmap_segment()
        warped = self._try_link_warp()
        if warped:
            # Stamp the post-warp position so the next frame's probe only
            # fires again on genuine further movement.
            self._scripted_link_pos = (self.client.x, self.client.y)
        return warped

    def _check_scripted_gmap_segment(self) -> bool:
        """Announce a GMAP segment crossing made by scripted movement.

        move_to() tells the server when a step changes gmap cell; a script that
        writes `player.x` from the VM never calls move_to, so the server kept us
        in the spawn segment and never streamed the ones we walked into.
        Reuses move_to's wire sequence so "we crossed a seam" has one definition.

        Gate on in_gmap_segment, NOT is_gmap: is_gmap stays True inside a
        standalone interior (house/cave) of a gmap world, where player coords
        are LOCAL 0-63 — reading those as world coords maps every house to
        grid cell (0,0). Live LTTP 2026-07-26: walking around inside
        zlttp-linkshouse.nw announced segment (0,0) and the server obligingly
        warped us to zlttp-i0.nw (the gmap's top-left corner). Latent since
        07-23 (bomber wave 3) but masked until the level-change
        default_movement reset was removed, because this probe chain never
        ran past the first level announce."""
        client = self.client
        if not getattr(client, 'in_gmap_segment', False) or not client.gmap_grid:
            return False
        grid = segment_at(client.x, client.y)
        if grid == getattr(self, '_scripted_gmap_cell', None):
            return False
        level = client.gmap_grid.get(grid)
        # Unknown cell (hole in the grid, or off its edge): remember it so we
        # don't re-probe every frame, but say nothing to the server.
        self._scripted_gmap_cell = grid
        if not level or level == client._current_level_name:
            return False
        client.send_position()
        return client.enter_gmap_segment(level, *world_to_local(client.x, client.y))

    def _update_push_hold(self, dx: int, dy: int):
        """Track how long the currently-pressed direction has been held
        fully blocked; past PUSH_HOLD_TIME switches to the "push" gani
        (classic-engine feel: lean on a wall for a moment and the character
        visibly pushes against it). Called every frame _move() ends up
        fully blocked, including after a failed corner-assist — a real
        flat/solid wall, not a clearable corner.

        _clear_push_hold (called from _move whenever a move actually
        succeeds, and from input.py when no movement key is held at all)
        resets this; render.py's _update_animations falls back to idle if
        is_pushing goes False while the gani is still showing "push"."""
        # Carrying/sitting already own the gani (carry, sit) — walking a
        # carried object or a chair into a wall shouldn't switch to "push".
        if self.client.player.is_carrying() or self.client.player.is_sitting:
            self._clear_push_hold()
            return

        now = time.time()
        if self._push_hold_dir != (dx, dy):
            self._push_hold_dir = (dx, dy)
            self._push_hold_start = now
            self.is_pushing = False
            return
        if not self.is_pushing and now - self._push_hold_start >= PUSH_HOLD_TIME:
            self.is_pushing = True
        if self.is_pushing:
            direction = direction_from_delta(dx, dy)
            self.player_anim.set_direction(direction)
            if self.current_anim_name != "push":
                self.player_anim.set_animation("push", direction, force=True)
                self.current_anim_name = "push"
                # Broadcast the push gani the same way the sit/sword states
                # do (client.set_animation -> PLI_PLAYERPROPS with PLPROP_GANI
                # + PLPROP_SPRITE direction — never the legacy prop 14).
                self.client.set_animation("push")

    def _clear_push_hold(self):
        """Stop tracking a held-blocked direction (a move succeeded, the key
        was released, or something else — grab, sword, sitting — took
        over)."""
        self._push_hold_dir = None
        self.is_pushing = False

    def _update_grab_pull_state(self, dx: int, dy: int):
        """Continuous per-frame update while the grab key (A) is held —
        called every frame from input.py's A-held branches, in addition to
        (not instead of) _try_grab's one-shot fresh-press dispatch.

        Holding A while facing a plain blocking wall tile (nothing
        liftable/interactable there — a bush/pot/rock, a chest, a door link,
        or a sign all keep taking priority and are handled, one-shot, by
        _try_grab) shows the "grab" gani. Once grabbing, additionally
        holding the movement key OPPOSITE the grabbed facing switches to
        "pull". Facing is pinned to whatever it was when the grab started —
        pulling doesn't spin the player to face the direction they're
        pulling toward. Releasing A (see _clear_grab_state, called from
        input.py) exits back to idle/walk.

        This never actually moves a block — there's no server support for
        pushable/pullable tiles; it's purely the character's held-against-
        a-wall animation."""
        player = self.client.player
        # Lifting/carrying/sitting/swimming already own current_anim_name —
        # never fight them with a grab gani of our own.
        if player.is_carrying() or player.is_sitting or self.is_swimming:
            self._clear_grab_state()
            return

        # Facing is pinned once a grab starts (see docstring); otherwise use
        # whatever we're currently facing to decide whether one CAN start.
        direction = self._grab_direction if self.grab_state is not None else player.direction

        # A liftable/chest/door/sign in front is already handled, with
        # priority, by _try_grab's one-shot dispatch — don't show a grab
        # gani over top of it.
        points = self._touch_points(direction)
        interactable = (
            any(self._is_tile_liftable(self._get_tile_at(tx, ty)) for tx, ty in points)
            or self._find_chest_in_front() is not None
            or self._get_non_edge_door() is not None
            or self._check_sign_nearby() is not None
        )
        if interactable:
            self._clear_grab_state()
            return

        if not any(self._is_blocked_at(tx, ty) for tx, ty in points):
            self._clear_grab_state()
            return

        opposite = {0: 2, 1: 3, 2: 0, 3: 1}[direction]
        pulling = self.grab_state is not None and (dx, dy) == self._facing_delta(opposite)
        new_state = "pull" if pulling else "grab"

        if self.grab_state != new_state:
            if self.grab_state is None:
                self._grab_direction = direction
            self.grab_state = new_state
            self.player_anim.set_animation(new_state, self._grab_direction, force=True)
            self.current_anim_name = new_state
            # Same broadcast mechanism as push/sit/sword (see _update_push_hold).
            self.client.set_animation(new_state)
        self.is_moving = False

    def _clear_grab_state(self):
        """Stop the grab/pull hold state (A released, or a lift/chest/door/
        sign/carry/sit took over)."""
        self.grab_state = None
        self._grab_direction = None

    def _swing_sword(self):
        """Swing sword attack."""
        player = self.client.player
        self.client.sword_attack(player.direction)
        # sword_attack already carries the sword gani in its wire update.
        self._play_action_animation("sword", broadcast=False)

    def _play_action_animation(self, name: str, broadcast: bool = True):
        """Start a one-shot local gani and expose it to nearby players."""
        direction = self.client.player.direction
        self.player_anim.set_animation(name, direction, force=True)
        self.current_anim_name = name
        if broadcast:
            self.client.set_animation(name)
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
            cx, cy = chest
            level_name = self._found_chest_level
            if not self.client.get_chest_opened(level_name, cx, cy):
                self.client.open_chest(cx, cy)
                self.client.set_chest_opened(level_name, cx, cy)
            return

        # Lift an object in front — plain A lifts, classic style (no
        # arrow needed).
        if self._lift_in_front(player.direction):
            return

        # Check for sign NPC nearby
        sign_text = self._check_sign_nearby()
        if sign_text:
            # Display sign text in dialogue box
            self._show_dialogue(sign_text, classic_font=True)
            return

        # Check for door link
        door_link = self._get_non_edge_door()
        if door_link:
            self._use_door_link(door_link)
            return

        # Try to pickup item at current position
        self._pickup_ground_item()
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

        # Touch points are world coords (matter in a GMAP); sign keys are
        # level-local, so fold via a signed offset from the current
        # segment's grid origin — same helper/pattern as render_objects.py's
        # _check_and_render_signs. A raw %64 wrap snaps a touch point just
        # past a segment's edge back to a low local value, missing near-edge
        # signs and falsely matching signs on the level's opposite edge.
        origin_x, origin_y = self._current_segment_origin()

        player = self.client.player
        for tx, ty in self._touch_points(player.direction):
            lx, ly = tx - origin_x, ty - origin_y
            for (sx, sy), text in signs.items():
                if abs(lx - sx) < 1.5 and abs(ly - sy) < 1.5:
                    return text

        return None
    def _show_dialogue(self, text: str, classic_font: bool = False):
        """Show dialogue text in the dialogue box.

        classic_font marks sign-style text (level signs, PLO_SAY2): those
        carry the classic sign-code escapes (#K(nn) raw chars, #k(n) key
        names, #u/#d/... button symbols, #i() inline images), which the real
        client renders as glyphs — translate them instead of leaking the raw
        tokens into the box (see dialogue.format_sign_text)."""
        if classic_font:
            from .dialogue import format_sign_text
            text = format_sign_text(text)
        self.dialogue_text = text
        self.dialogue_classic_font = classic_font
        font = self.fonts.classic() if classic_font else self.font_small
        box_width = min(self.screen_w - 40, 400) - 20
        self.dialogue_pager.replace(text, lambda value: font.size(value)[0],
                                    box_width)

    def _dismiss_dialogue(self):
        """Dismiss the current dialogue."""
        self.dialogue_text = None
        self.dialogue_classic_font = False

    def _advance_dialogue(self):
        """Advance the dialogue, closing it after its final page."""
        if not self.dialogue_pager.advance():
            self._dismiss_dialogue()
    def _try_pickup(self, dx: int, dy: int):
        """A + arrow: lift a 2x2 object in that direction, or
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
            self._pickup_ground_item(px, py)

    def _lift_in_front(self, direction: int) -> bool:
        """Lift the 2x2 liftable at the touch points for the
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
        # floor, not int(): the same truncation-vs-floor split collision.py's
        # _world_to_level_local documents. Equivalent for every reachable
        # probe (a negative world coord only arrives here from an off-board
        # touch point, whose tile is -1 and so never liftable), but the two
        # spellings must not disagree on the frame this returns origins in.
        tx, ty = math.floor(x), math.floor(y)
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
            lx, ly = world_to_local(wx, wy)
            tiles[level_index(lx, ly)] = self.grass_tile_id
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
        throw_gani = self.gani_parser.parse("throw")
        if throw_gani is not None:
            prefetch = getattr(self, '_prefetch_gani_assets', None)
            if prefetch is not None:
                prefetch(throw_gani)
        anim = "throw" if throw_gani else "idle"
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
            'range': 10.5,               # tiles of flight before landing
        })
    def _find_chest_in_front(self) -> Optional[Tuple[int, int]]:
        """Return the local key of the chest being faced."""
        for tx, ty in self._touch_points(self.client.player.direction):
            # Touch points are world coords (matter in a GMAP); chest keys
            # are level-local (0-63), so fold to the current segment's local
            # frame the same way collision.py's _chest_blocks does — else
            # chests off the origin segment are never found here.
            ftx, fty = self._world_to_level_local(tx, ty)
            level_name, _ = self._level_tiles_at(tx, ty)
            if not level_name:
                continue
            chests = self.client.chests_in_level(level_name)
            for (cx, cy) in chests:
                if cx <= ftx <= cx + 1 and cy <= fty <= cy + 1:
                    self._found_chest_level = level_name
                    return cx, cy
        return None
    def _update_sitting_state(self):
        """Walk-on sitting: you're seated for as long as your feet are on a
        chair tile — riding across a run of chairs keeps the sit ani at
        normal movement speed, same as walking. Movement is completely
        normal — walking onto, across, and off a chair is just walking;
        only the ani differs. Only leaving chair tiles stands you up.

        The chair may be an NPC's rather than the board's: classic Bomber's
        player-base furniture publishes its chair cells through `setshape2`,
        so ask _effective_tile_type instead of the board alone.

        Sampled at _player_ground (x+1.5, y+2.0), the single point
        `TPlayer::testSittingSleeping` uses (Preagonal/FourPlay/quattroplay/
        src/TPlayer.cpp:5925-5927) - NOT _player_feet (y+2.5). Half a tile
        matters here: Bomber's furniture chairs are two tiles tall, and
        sampling low shifted the seatable band up the screen, which is why
        only the upper part of a chair ever sat you down."""
        player = self.client.player
        on_chair = (not player.is_carrying() and not self.is_swimming
                    and self._effective_tile_type(*self._player_ground())
                    == TileType.CHAIR)
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
                self._play_action_animation("shoot")
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
                self._play_action_animation("jlaybomb")
                # Spawn visual bomb at player position
                self.active_bombs.append({
                    'x': self.client.player.x,
                    'y': self.client.player.y,
                    'time': time.time(),
                    'fuse_time': self.bomb_fuse_time,
                    'power': self.client.player.bomb_power,
                    'exploded': False,
                    'source': 'local',
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
        # Standalone cross-level warps hold the old visual position until the
        # destination board is active. Same-level and gmap warps still snap now.
        if not getattr(self.client, '_local_level_transition', ''):
            self.visual_x = self.client.x
            self.visual_y = self.client.y
        # Force world surface redraw
        self.world_surface = None
        # Recompute swimming immediately (don't wait for the next frame's
        # blanket update in run()) so a door out of water into a dry level -
        # or vice versa - never reports the old level's state, even for one
        # frame or for callers that drive warps outside the run() loop.
        self._update_swimming_state()
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
        # Sample the collision box's centre point (x+1.5, y+2.5), not the
        # sprite's top-left — otherwise swimming is judged off from where
        # the player visibly stands.
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
