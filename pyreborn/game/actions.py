"""ActionsMixin — Player mechanics: move, sword, grab/pickup/throw, weapons, doors.

Split from pygame_game.py; methods operate on the GameClient instance."""

import math
from typing import Optional, Tuple

from pygame.locals import (
    K_UP, K_DOWN, K_LEFT, K_RIGHT,
)

from reborn_protocol.coords import level_index, segment_at, world_to_local

from .. import ground_items
from ..gmap_coords import origin_at
from ..gani import direction_from_delta
from ..ground_effects import (
    BED_TILE_TYPE, LAVA_ANI, LAVA_DAMAGE, LAVA_SWIM_TILE_TYPE, SLEEP_ANI,
    SLEEP_HEAL, SWIM_ACTION_MODE, SWIM_LEAP_OFFSET, SWIM_LEAP_TYPE,
    TickCounter, bed_samples, bed_snap_y, is_lava_type,
)
from ..hiding import (
    HIDDEN_ACTION_MODE, HIDDEN_MOVE_ANI, HIDDEN_STILL_ANI, can_hide, is_hidden,
    unhide_leap,
)
from ..liftobjects import LIFT_PROBE, match_lift_object
from ..tiletypes import TileType
from .constants import (
    MOVE_STEP, PUSH_HOLD_TIME,
)
from .clocked import ClockedMixin
import logging
from ..logutil import log_swallowed
logger = logging.getLogger(__name__)


class ActionsMixin(ClockedMixin):
    """Mixin providing the above methods for GameClient."""

    def _move_hurt_step(self, dx, dy):
        """hurtFly's twelve wall probes, through the normal world collision path."""
        from ..hurt import HURT_FLY_PROBES
        player = self.client.player
        nx, ny = player.x + dx, player.y + dy
        if any(self._is_blocked_at(nx + edge[i], ny + edge[i + 1], check_players=False)
               for edge in HURT_FLY_PROBES for i in (0, 2, 4)):
            return False
        return self.client.move(dx, dy, step=1.0, face_direction=player.direction)

    def _advance_hurt(self, dt):
        player = self.client.player
        state = getattr(player, 'hurt', None)
        if state is None or player.hearts <= 0 or player.status & 1:
            return
        state.advance(dt, self._move_hurt_step)
        if state.ticks >= 40 and player.action_mode == 3:
            player.action_mode = 0

    def _try_start_ledge_jump(self, direction):
        from ..jumping import JumpState
        player = self.client.player
        if (getattr(self, '_ledge_jump', None) is not None or player.hearts <= 0
                or self.client.frozen or player.hurt.input_locked(self.clock.sim_now())
                or getattr(self.client, 'ghost_mode', 0) or player.is_sitting
                or not self._can_ledge_jump(direction)):
            return False
        player.direction = direction
        player.action_mode = 2
        self._ledge_jump = JumpState(player.x, player.y, direction)
        self.is_moving = False
        self._clear_push_hold()
        # animateJumping (:6453-6482) moves independently of any gani and
        # never waits for one. Preserve the current pose if jump is absent.
        if self.gani_parser.parse('jump') is not None:
            self._play_action_animation('jump')
        self.sound_mgr.play('jump.wav')
        return True

    def _advance_ledge_jump(self, dt):
        jump = getattr(self, '_ledge_jump', None)
        if jump is None:
            return
        player = self.client.player
        if player.action_mode != 2 or player.hearts <= 0:
            self._ledge_jump = None
            return
        if self.client.frozen:
            return
        def move_to(x, y):
            # Scripted arc: no collision along the path, but normal segment
            # entry and local-coordinate wire updates still run in move().
            self.client.move(x - player.x, y - player.y, step=1.0,
                             face_direction=jump.direction)
        if jump.advance(dt, move_to):
            self._ledge_jump = None
            player.action_mode = 0
            self._play_action_animation('carry' if player.is_carrying() else 'idle')
            self._update_swimming_state()

    def _facing_delta(self, direction: int) -> Tuple[int, int]:
        """(dx, dy) tile delta for a facing direction (0=up,1=left,2=down,3=right)."""
        return {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}.get(direction, (0, 0))

    def _pickup_ground_item(self, x: Optional[float] = None,
                            y: Optional[float] = None) -> bool:
        """Request a local pickup and play its sound when an item is present."""
        if getattr(self.client, 'ghost_mode', 0):
            return False
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

    def _auto_pickup_items(self) -> int:
        """Walk-over pickup (TServerLevel::animateExtras).

        Sends PLI_ITEMTAKE addressed at the item's own spot after checking
        its age and distance; the item leaves the local model as the take is
        sent (`Client.pickup_item`), so nothing waits on a server echo.
        Kinds the reference does not report are removed locally only."""
        if getattr(self.client, 'ghost_mode', 0):
            return 0
        client = self.client
        if not (client.connected and client.authenticated):
            return 0
        level_resolver = getattr(client, "get_current_level_from_position", None)
        level_name = level_resolver() if level_resolver is not None else ""
        items = client.items_in_level(level_name)
        now = self.clock.sim_now()
        ages = ground_items.item_ages(self, level_name, items, now)
        if not items:
            return 0
        sent = self.__dict__['_item_take_sent']
        local_x, local_y = world_to_local(client.player.x, client.player.y)
        count = 0
        for key in ground_items.walkover_takes(local_x, local_y, items, ages):
            if (level_name, key) in sent:
                continue
            # Read the kind first: a take drops the item from the local model.
            item_type = str(items[key]).lower()
            if client.pickup_item(key[0], key[1]):
                sent.add((level_name, key))
                count += 1
                self.sound_mgr.play("item2.wav" if any(
                    part in item_type for part in ('heart', 'key')) else "item.wav")
        # The reference deletes the other touched kinds too, but only the
        # giveaway kinds are reported (TServerLevel.cpp:1453-1457).
        for key in ground_items.walkover_absorbs(local_x, local_y, items, ages):
            item_type = str(items[key]).lower()
            client.remove_item_local(level_name, key[0], key[1])
            self.sound_mgr.play("item2.wav" if any(
                part in item_type for part in ('heart', 'key')) else "item.wav")
        return count

    def _giveaway_stats(self):
        player = self.client.player
        return {'rupees': player.rupees, 'bombs': player.bombs,
                'arrows': player.arrows, 'hearts': player.hearts}

    def _giveaway_select(self):
        """S-held A press: enter / advance selection (TPlayer.cpp:6612-6687)."""
        if getattr(self.client, 'ghost_mode', 0):
            return None
        stats = self._giveaway_stats()

        def available(index):
            return ground_items.giveaway_available(
                index, stats['rupees'], stats['bombs'], stats['arrows'],
                stats['hearts'])

        self._giveaway_item = ground_items.next_give_item(
            available, getattr(self, '_giveaway_item', None))
        if self._giveaway_item < 0:
            self._giveaway_item = None
            if self.client.player.action_mode == 9:
                self.client.player.action_mode = 0
            return
        # Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:6620-6621.
        self.client.player.action_mode = 9
        self._play_action_animation('idle')
        self.sound_mgr.play("item2.wav")

    def _giveaway_drop(self) -> bool:
        """Bare A press: loseItem + putExtra + PLI_ITEMADD (TPlayer.cpp:2232-2247)."""
        if getattr(self.client, 'ghost_mode', 0):
            return False
        index = getattr(self, '_giveaway_item', None)
        if index is None or index not in ground_items.GIVEAWAY_COST:
            return False
        stats = self._giveaway_stats()
        if not ground_items.giveaway_available(
                index, stats['rupees'], stats['bombs'], stats['arrows'],
                stats['hearts']):
            return False
        from reborn_protocol import PLPROP
        client, player = self.client, self.client.player
        stat, amount = ground_items.GIVEAWAY_COST[index]
        if stat == 'hearts':
            object.__setattr__(player, 'hearts', player.hearts - amount)
            client.send_appearance_prop(PLPROP.CURPOWER, int(player.hearts * 2))
        else:
            value = getattr(player, stat) - amount
            setattr(player, stat, value)
            prop = {'rupees': PLPROP.RUPEESCOUNT, 'bombs': PLPROP.BOMBSCOUNT,
                    'arrows': PLPROP.ARROWSCOUNT}[stat]
            client.send_appearance_prop(prop, value)
        local_x, local_y = world_to_local(player.x, player.y)
        x, y = ground_items.drop_position(local_x, local_y, player.direction)
        level_name = client.get_current_level_from_position()
        client.items.setdefault(level_name, {})[(x, y)] = ground_items.ITEM_NAMES[index]
        client.send_item_add(x, y, index)
        self._giveaway_item = None
        player.action_mode = 0
        self.sound_mgr.play("item.wav")
        return True

    def _open_chest_sign(self, level_name: str, cx: int, cy: int) -> bool:
        """A chest's sign index opens that level sign as a modal sign and stops
        walking (TPlayer.cpp:2825-2837). An index past the level's sign list
        shows nothing."""
        index = self.client.chest_signs.get(level_name, {}).get((cx, cy), -1)
        if index < 0:
            return False
        texts = list(self.client.signs.get(level_name, {}).values())
        if index >= len(texts):
            return False
        self._show_dialogue(texts[index], classic_font=True)
        self.is_moving = False
        self._move_accum = 0.0
        return True

    def _move(self, dx: int, dy: int):
        """Walk held axes in up, left, down, right order."""
        # TPlayer.cpp:3496 dispatches every held direction in index order.
        for ax, ay in ((0, -1), (-1, 0), (0, 1), (1, 0)):
            # A warp (a door link, a script warp) ends this tick's walking.
            if getattr(self.client, 'tick_movement_ended', False):
                return
            if (ax and ax == dx) or (ay and ay == dy):
                self._move_axis(ax, ay)

    # A gap of more than this many 20 Hz ticks between moved steps means the
    # walk restarted (the "first movement tick").
    _FOOTSTEP_RESTART_TICKS = 3

    def _gani_plays_sound(self, name: str) -> bool:
        """True when the current animation's own PLAYSOUND lines include name."""
        directions = getattr(getattr(self.player_anim, 'gani', None),
                             'directions', None)
        if not isinstance(directions, (list, tuple)):
            return False
        return any(sound[0].lower() == name
                   for frames in directions for frame in frames
                   for sound in frame.sounds)

    def _play_footsteps(self, tick: Optional[int] = None):
        """Footstep sounds for one moved step: steps.wav (water.wav on water)
        when the walk starts, then steps2.wav every 5th tick and water.wav
        every 15th while on water, modes 0/10 only (TPlayer.cpp:7494-7502,
        :7599-7612). Ghost mode suppresses them. The oracle plays the first
        one on every movementAction call, not only the first, but its engine
        keeps one voice per file; replayed here that would stack 20 voices/s.
        The unknown205 no-sound flag is not tracked by this client. The stock
        walk gani already PLAYSOUNDs steps2.wav, so that one is left to it."""
        if tick is None:
            tick = self.clock.tick
        last = getattr(self, '_footstep_tick', None)
        if tick == last:
            return  # two MOVE_STEPs fit in one tick; sound once per tick
        self._footstep_tick = tick
        # serverMoved flips the swamp sprite parity every step (TServerPlayer.cpp:1468).
        self._step_parity = 1 - getattr(self, '_step_parity', 0)
        if getattr(self.client, 'ghost_mode', 0):
            return
        on_water = self._effective_tile_type(
            *self._player_ground()) == TileType.WATER
        if last is None or tick - last > self._FOOTSTEP_RESTART_TICKS:
            self.sound_mgr.play('water.wav' if on_water else 'steps.wav')
        if tick % 5 or getattr(self.client.player, 'action_mode', 0) not in (0, 10):
            return
        if on_water:
            if tick % 15 == 0:
                self.sound_mgr.play('water.wav')
        elif not self._gani_plays_sound('steps2.wav'):
            self.sound_mgr.play('steps2.wav')

    def _move_axis(self, dx: int, dy: int):
        """Apply one cardinal sub-step, retaining its facing even if blocked."""
        player = self.client.player

        if getattr(self, '_ledge_jump', None) is not None:
            return
        if getattr(player, 'hurt', None) is not None and player.hurt.input_locked(self.clock.sim_now()):
            return

        # Press a direction INTO an adjacent object to interact, the classic
        # Reborn way (no separate action key): a chest in front opens, a chair in
        # front seats you. Face the pressed direction first so the in-front
        # probes look the right way.
        facing = direction_from_delta(dx, dy)
        player.direction = facing
        self.player_anim.set_direction(facing)

        if self._walk_sign_contact():
            return

        chest = self._find_chest_in_front()
        if chest is not None:
            cx, cy = chest
            level_name = self._found_chest_level
            if not self.client.get_chest_opened(level_name, cx, cy):
                self.client.open_chest(cx, cy)
                self.client.set_chest_opened(level_name, cx, cy)
                self._open_chest_sign(level_name, cx, cy)
            return

        # Sitting is walk-on: having your feet on a chair tile IS sitting (see
        # _update_sitting_state) — movement is never intercepted or blocked
        # for chairs, you just ride across them in the sit ani.

        if self._ledge_ahead(facing):
            from ..jumping import JUMP_PUSH_TICKS
            from ..hurt import TICK_SECONDS
            self._update_push_hold(dx, dy)
            started = self.push.hold_start
            if started is not None and self.clock.passed(started, JUMP_PUSH_TICKS * TICK_SECONDS):
                self._try_start_ledge_jump(facing)
            return

        if self.current_anim_name == SLEEP_ANI:
            self.current_anim_name = "idle"  # movementAction restarts walk (:7587)
        step = MOVE_STEP
        mdx = mdy = 0
        # Escape hatch: if we're ALREADY overlapping a wall (bad server spawn,
        # warp onto a solid tile), blocking every move would trap us — allow
        # movement so the player can walk out. But only moves that stay on the
        # board and don't deepen the overlap: a blanket allow is noclip (walk
        # through walls, off the level edge, into negative coords).
        stuck_count = self._blocked_sample_count(self.client.x, self.client.y)
        nx = self.client.x + dx * step
        ny = self.client.y + dy * step
        if stuck_count:
            allowed = (not self._position_out_of_bounds(nx, ny)
                       and self._blocked_sample_count(nx, ny) <= stuck_count)
        else:
            allowed = not self._is_position_blocked(nx, ny, dx, dy)
        if allowed:
            mdx, mdy = dx, dy

        # Corner-assist: a cardinal press blocked by being slightly off a
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

        # Each axis keeps its pressed facing, including a corner nudge.
        self.client.move(mdx, mdy, face_direction=corner_assist_dir)
        self._play_footsteps()

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
            move_anim = LAVA_ANI if getattr(self, '_swim_in_lava', False) else "swim"
        elif self._is_hidden():
            move_anim = HIDDEN_MOVE_ANI
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
                and self.clock.passed(getattr(self, '_frozen_until', 0.0))):
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
        if (getattr(self.client, 'local_level_transition', '')
                or getattr(self, '_level_transition_input_frozen', False)):
            return False
        pos = (self.client.x, self.client.y)
        if pos == self.arrival.scripted_link_pos:
            return False
        self.arrival.scripted_link_pos = pos
        self._check_scripted_gmap_segment()
        warped = self._try_link_warp()
        if warped:
            # Stamp the post-warp position so the next frame's probe only
            # fires again on genuine further movement.
            self.arrival.scripted_link_pos = (self.client.x, self.client.y)
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
        if grid == self.arrival.scripted_gmap_cell:
            return False
        level = client.gmap_grid.get(grid)
        # Unknown cell (hole in the grid, or off its edge): remember it so we
        # don't re-probe every frame, but say nothing to the server.
        self.arrival.scripted_gmap_cell = grid
        if not level or level == client.current_level_name:
            return False
        client.send_position()
        return client.enter_gmap_segment(level, *world_to_local(client.x, client.y))

    def _stone_npcs_at(self, x, y):
        """NPC footprints at a point, including nonblocking NPCs."""
        runtime = getattr(self, 'gs1', None)
        shapes = getattr(runtime, 'shapes', {})
        for npc_id, npc in self.client.npcs.items():
            if not npc.get('visible', True):
                continue
            shape = shapes.get(npc_id)
            if shape and shape[0] > 0 and shape[1] > 0:
                nx = npc.get('world_x', npc.get('x', 0))
                ny = npc.get('world_y', npc.get('y', 0))
                if nx <= x < nx + shape[0] and ny <= y < ny + shape[1]:
                    yield npc_id
            elif runtime is not None and runtime.npc_footprint_hit(npc, x, y):
                yield npc_id

    def _pull_wall_before(self, direction):
        # TInitStatics.cpp:1536: the four pulltest points.
        ox, oy = ((1.5, .9), (0, 2), (1.5, 3.1), (3, 2))[direction]
        x, y = self.client.x + ox, self.client.y + oy
        # TPlayer.cpp:5805: players veto grabbing, even over a wall/NPC.
        if self._player_blocks(x, y):
            return False
        if next(self._stone_npcs_at(x, y), None) is not None:
            return True
        from ..tiletypes import type_is_blocking
        return type_is_blocking(self._effective_tile_type(x, y))

    def _stone_action(self, action, direction):
        # TPlayer.cpp:5817: push targets 1.5 tiles beyond the body centre.
        reach = 2.0 if action == 'pull' else 1.5
        dx, dy = self._facing_delta(direction)
        lx, ly = world_to_local(self.client.x, self.client.y)
        x, y = lx + 1.5 + reach * dx, ly + 2.0 + reach * dy
        if not (0 <= x < 64 and 0 <= y < 64):
            return
        # TPlayer.cpp:5858: pull supplies the opposite direction.
        param = (direction + 2) & 3 if action == 'pull' else direction
        runtime = getattr(self, 'gs1', None)
        if runtime is not None:
            wx, wy = self.client.x + 1.5 + reach * dx, self.client.y + 2 + reach * dy
            for npc_id in list(self._stone_npcs_at(wx, wy)):
                runtime.call_npc(npc_id, 'action' + action, (param,))
        # TPlayer.cpp:5880: also send the action to the server.
        self.client.triggeraction(f'{action},{param}', x, y)

    def _update_push_hold(self, dx: int, dy: int):
        """Keep the initial countdown, then repeat every 20 ticks.

        TPlayer.cpp:7531-7544 fires moveStones and its sound; the counter
        wraps from 38 to 18 at TPlayer.cpp:7558-7561.
        """
        player = self.client.player
        now = self.clock.sim_now()
        if self.push.hold_dir != (dx, dy) or self.push.hold_start is None:
            self.push.hold_dir = (dx, dy)
            self.push.hold_start = now
            self.push.fire_cycle = -1
            self.push.pushing = False
        ticks = max(0, self.clock.ticks_since(self.push.hold_start))
        self.push.counter = max(18, 38 - ticks)
        if self.push.counter > 18:
            return
        # The countdown itself is shared with the ledge jump and runs for
        # everyone; only the push pose and its NPC event need a free-handed,
        # standing, non-ghost player.
        if getattr(self.client, 'ghost_mode', 0) or player.is_carrying() or player.is_sitting:
            self.push.pushing = False
            return
        self.push.pushing = True
        direction = direction_from_delta(dx, dy)
        self.player_anim.set_direction(direction)
        if self.current_anim_name != 'push':
            self._play_action_animation('push')
        # TPlayer.cpp:7558-7561: each subsequent cycle takes 20 ticks (1 s).
        cycle = (ticks - 20) // 20
        if cycle > self.push.fire_cycle:
            self.push.fire_cycle = cycle
            self._stone_action('push', direction)
            # TPlayer.cpp:7535-7542: default movement owns this sound. As with
            # footsteps, leave an animation's own PLAYSOUND to that animation.
            if (getattr(getattr(self, 'gs1', None), 'default_movement', True)
                    and not self._gani_plays_sound('stonemove.wav')):
                self.sound_mgr.play('stonemove.wav')

    def _clear_push_hold(self):
        self.push.clear_push()

    def _update_grab_pull_state(self, dx: int, dy: int):
        """Grab at counter 1; an opposite-direction hold advances 2 to 19."""
        player = self.client.player
        if (getattr(self.client, 'ghost_mode', 0) or player.is_carrying() or player.is_sitting
                or self.is_swimming):
            self._clear_grab_state()
            return
        direction = self.push.grab_direction if self.push.grab is not None else player.direction
        if not self._pull_wall_before(direction):
            self._clear_grab_state()
            return
        if self.push.grab is None:
            # TPlayer.cpp:2058: A enters action mode 5 with counter 1.
            self.push.grab_direction = direction
            self.push.pull_started = None
            self.push.pull_fired = False
            self.push.pull_counter = 1
            player.action_mode = 5
        pulling = (dx, dy) == self._facing_delta((direction + 2) & 3)
        state = 'pull' if pulling else 'grab'
        if pulling:
            now = self.clock.sim_now()
            if self.push.pull_started is None:
                self.push.pull_started = now
            self.push.pull_counter = min(19, 2 + int((max(0, now - self.push.pull_started) + 1e-9) / .05))
            # TPlayer.cpp:7475: dispatch when the pull counter reaches 19.
            if self.push.pull_counter == 19 and not self.push.pull_fired:
                self.push.pull_fired = True
                self._stone_action('pull', direction)
        else:
            self.push.pull_started = None
            self.push.pull_fired = False
            self.push.pull_counter = 1
        if self.push.grab != state:
            self.push.grab = state
            self.player_anim.set_animation(state, direction, force=True)
            self.current_anim_name = state
            self.client.set_animation(state)
        self.is_moving = False

    def _clear_grab_state(self):
        if self.client.player.action_mode == 5:
            self.client.player.action_mode = 0
        self.push.clear_grab()

    def _swing_sword(self):
        """Swing sword attack."""
        if getattr(self.client, 'ghost_mode', 0):
            return None
        player = self.client.player
        # slaySword (TPlayer.cpp:7681-7689): refused in action mode 10
        # (swimming), and when canLayItem's laytest point is water (:7678).
        if self.is_swimming:
            return
        ox, oy = LIFT_PROBE[int(player.direction) & 3]
        if self._effective_tile_type(self.client.x + ox, self.client.y + oy) in (
                TileType.WATER, TileType.LAVA):
            return
        self.client.sword_attack(player.direction)
        # sword_attack already carries the sword gani in its wire update.
        from ..sword import play_sword_pose
        play_sword_pose(self)

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
        if getattr(self.client, 'ghost_mode', 0):
            return None
        player = self.client.player

        # If carrying something, throw it (hidden: A only un-hides)
        if player.is_carrying():
            if self._is_hidden():
                self._unhide()
            else:
                self._throw_object()
            return

        # TPlayer.cpp:2039-2047: A cannot start another action in these modes.
        if player.action_mode in (4, 5, 10):
            return

        # Open a chest in front of the player
        chest = self._find_chest_in_front()
        if chest is not None:
            cx, cy = chest
            level_name = self._found_chest_level
            if not self.client.get_chest_opened(level_name, cx, cy):
                self.client.open_chest(cx, cy)
                self.client.set_chest_opened(level_name, cx, cy)
                self._open_chest_sign(level_name, cx, cy)
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
    def _sign_contact(self):
        """Return the sign under the upward wall probe, including its key."""
        if self.client.player.direction != 0:
            return None
        signs = self.client.signs.get(self.client.current_level_name, {})
        if not signs:
            return None
        # TPlayer.cpp:2849 uses (x+1.5,y+0.5), on a wall; the sign box is
        # inclusive and 2x1 tiles (TServerLevel.cpp:297).
        x, y = self.client.x + 1.5, self.client.y + 0.5
        origin_x, origin_y = self._current_segment_origin()
        lx, ly = x - origin_x, y - origin_y
        for (sx, sy), text in signs.items():
            if sx <= lx <= sx + 2.0 and sy <= ly <= sy + 1.0:
                if self._is_blocked_at(x, y, check_players=False):
                    return (self.client.current_level_name, sx, sy), text
        return None

    def _walk_sign_contact(self):
        contact = self._sign_contact()
        if contact is None:
            self._sign_contact_key = None
            return False
        key, text = contact
        if key != getattr(self, '_sign_contact_key', None):
            self._sign_contact_key = key
            self._show_dialogue(text, classic_font=True)
        return True

    def _check_sign_nearby(self) -> Optional[str]:
        """Use the same sign box and wall probe for the A interaction."""
        contact = self._sign_contact()
        if contact is None:
            return None
        self._sign_contact_key = contact[0]
        return contact[1]

    def _show_dialogue(self, text: str, classic_font: bool = False):
        """Show dialogue text in the dialogue box.

        classic_font marks sign-style text (level signs, PLO_SAY2): those
        carry the classic sign-code escapes (#K(nn) raw chars, #k(n) key
        names, #u/#d/... button symbols, #i() inline images), which the real
        client renders as glyphs — translate them instead of leaking the raw
        tokens into the box (see dialogue.format_sign_text)."""
        if classic_font:
            from .dialogue import SignText, format_sign_text
            if not isinstance(text, SignText):
                text = format_sign_text(text)
        self.dialogue_text = text
        self.dialogue_classic_font = classic_font
        font = self.fonts.classic() if classic_font else self.font_small
        box_width = min(self.screen_w - 40, 400) - 20
        measure = lambda value: font.size(value)[0]
        if classic_font:
            sprite_mgr = getattr(self, 'sprite_mgr', None)
            for image in text.images.values():
                if image.load(sprite_mgr) is None and hasattr(self, '_request_asset'):
                    self._request_asset(image.name)
            measure = lambda value: text.measure(
                value, lambda segment: font.size(segment)[0], sprite_mgr)
        self.dialogue_pager.replace(text, measure, box_width)

    def _rewrap_sign_dialogue(self, filename: str):
        """Re-wrap an open sign once one of its inline images arrives: it
        was measured 0 px wide while missing. Keeps the reader's page."""
        text = self.dialogue_text
        images = getattr(text, 'images', None) if self.dialogue_classic_font else None
        if not images or not any(i.name == filename for i in images.values()):
            return
        offset = self.dialogue_pager.offset
        self._show_dialogue(text, classic_font=True)
        self.dialogue_pager.offset = min(offset, max(0, len(self.dialogue_pager.lines) - 1))

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
        if getattr(self.client, 'ghost_mode', 0):
            return None
        player = self.client.player
        if not player.is_carrying() and player.action_mode in (4, 5, 10):
            return

        # Update direction first
        direction = direction_from_delta(dx, dy)
        self.player_anim.set_direction(direction)
        player.direction = direction

        # If already carrying, throw instead (hidden: A only un-hides)
        if player.is_carrying():
            if self._is_hidden():
                self._unhide()
            else:
                self._throw_object()
            return

        if not self._lift_in_front(direction):
            # No liftable object in front - try a regular item pickup at the
            # primary touch point. No lift animation: flailing the lift gani
            # at empty ground on every failed grab read as pure jank.
            px, py = self._touch_points(direction)[0]
            self._pickup_ground_item(px, py)

    def _lift_probe_tile(self, direction: int) -> Tuple[int, int]:
        """The single tile `TPlayer::liftObjects` probes (liftobjects.LIFT_PROBE).

        It is NOT one of the _touch_points: the reference's "up" probe is the
        row the box's top edge touches (player y + 0), so a solid object such
        as a vase, which the player cannot walk into, is still reached when
        standing flush against it. The generic touch row for "up" is one tile
        further down, inside the player's own box."""
        ox, oy = LIFT_PROBE[direction]
        return (math.floor(self.client.x + ox + 0.0001),
                math.floor(self.client.y + oy + 0.0001))

    def _lift_in_front(self, direction: int) -> bool:
        """Lift the 2x2 object at the touch points for the given facing.

        The object is one of the reference client's five tile-id patterns
        (pyreborn/liftobjects.py). Glove power selects how far down that table
        the search may go - it is not a per-object requirement - so there is
        no "you need a glove for this" message to print: a row out of reach
        simply never matches, exactly as `TPlayer::liftObjects` behaves.
        """
        if getattr(self.client, 'ghost_mode', 0):
            return False
        player = self.client.player
        if (player.is_carrying() or player.action_mode in (4, 5, 10)
                or getattr(self, 'is_swimming', False)):
            return False

        match = match_lift_object(self._get_tile_at,
                                  *self._lift_probe_tile(direction),
                                  player.glove_power)
        if match is None:
            if not self._lift_bomb(direction):
                return False
        else:
            self._replace_lifted_tiles(match)
            tl, bl, tr, br = match.tiles
            player.pickup_object(match.name, (tl, tr, bl, br),
                                 (match.origin_x, match.origin_y))
            from ..throwing import carry_code
            from ..carrying import publish_carry
            publish_carry(self.client, carry_code(match.carry_sprite))

        # Play lift animation then switch to carry
        self.player_anim.set_animation("lift", direction, force=True)
        self.current_anim_name = "lift"
        player.action_mode = 4
        set_animation = getattr(self.client, 'set_animation', None)
        if set_animation is not None:
            set_animation('lift')
        # lift.gani:129: PLAYSOUND is consumed by local animation playback.

        # Invalidate world surface to show removed tiles
        self.world_surface = None
        return True

    def _lift_bomb(self, direction):
        # TPlayer.cpp:1983-2003: bombs are the second loop, using the same tile probe.
        if getattr(self.client, 'ghost_mode', 0):
            return False
        from ..carrying import bomb_sprite, publish_carry
        from ..throwing import carry_code
        tx, ty = self._lift_probe_tile(direction)
        bombs = getattr(self, 'active_bombs', [])
        if not bombs and not getattr(self.client, 'bombs', {}):
            return False
        level_name, _ = self._level_tiles_at(tx, ty)
        registry = getattr(self.client, 'bombs', {}).get(level_name, {})
        ox, oy = origin_at(tx, ty) if self.client.in_gmap_segment else (0, 0)
        for info in list(registry.values()):
            bx, by = info['x'] + ox, info['y'] + oy
            if not any((b.get('bomb_id') == info['bomb_id'] if 'bomb_id' in info
                        else b['x'] == bx and b['y'] == by) for b in bombs):
                self._add_remote_bomb(dict(info, x=bx, y=by))
        for bomb in bombs:
            if bomb.get('exploded') or bomb.get('carried_by') is not None or bomb.get('in_flight'):
                continue
            bx, by = bomb['x'], bomb['y']
            if not (bx <= tx < bx + 2 and by <= ty < by + 2):
                continue
            if self.clock.passed(bomb['time'], bomb.get('fuse_time', 3.0)):
                continue
            sprite = bomb_sprite(bomb, self.clock.sim_now())
            self.client.player.pickup_object('bomb', (), (bx, by))
            self.client.player.carried_bomb = bomb
            # TServerLevel.cpp:1310-1340: removed/non-lying bombs do not count down.
            bomb['fuse_remaining'] = bomb['time'] + bomb.get('fuse_time', 3.0) - self.clock.sim_now()
            bomb['carried_by'] = self.client.player.id
            publish_carry(self.client, carry_code(sprite))
            self.client.remove_bomb(bx, by)
            position = self.client.bomb_half_tile(bx, by)
            self.active_bombs[:] = [b for b in self.active_bombs
                                    if b is bomb or b.get('exploded')
                                    or self.client.bomb_half_tile(b['x'], b['y']) != position]
            return True
        return False

    def _replace_lifted_tiles(self, match) -> None:
        """Put the object's replacement tiles on the board, and on the wire.

        Each row has its OWN ground (liftobjreplace), so this is not a blanket
        "fill with grass": the stump left by a bush is not the tile under a
        pot. The reference lifts through modifyBoard with its send flag set
        (TPlayer.cpp:1974), so other players see the object go. A gmap object
        that straddles a seam cannot be sent - PLI_BOARDMODIFY only ever
        addresses the sender's own segment - so those tiles are patched
        locally and the rest of the object still goes out.
        """
        standing = self.client.get_current_level_from_position()
        for wx, wy, _current, replacement in match.quadrants():
            level_name, tiles = self._level_tiles_at(wx, wy)
            if not level_name:
                continue
            lx, ly = world_to_local(wx, wy)
            if level_name == standing:
                self.client.modify_board(lx, ly, 1, 1, [replacement])
            elif tiles:
                tiles[level_index(lx, ly)] = replacement

    def _is_hidden(self) -> bool:
        return is_hidden(self.client.player)

    def _hide_or_unhide(self):
        """D while carrying (TPlayer.cpp:2121-2135): un-hide when hidden,
        else a carried bush/stone/blackstone starts mode 14."""
        if getattr(self.client, 'ghost_mode', 0):
            return None
        player = self.client.player
        if self._is_hidden():
            self._unhide()
        elif (can_hide(player.carried_object_type) and not self.is_swimming
                and player.action_mode == 0):
            player.action_mode = HIDDEN_ACTION_MODE
            self._play_action_animation(HIDDEN_STILL_ANI)

    def _unhide(self):
        """TPlayer::unHide (:6412): mode 14 ends, the object stays carried."""
        self.client.player.action_mode = 0
        leap = unhide_leap(self.client.player.carried_object_type,
                           self.client.x, self.client.y)
        if leap is not None:
            self._spawn_leaps(*leap)
        from ..carrying import standing_carry
        self._play_action_animation(standing_carry(self))

    def _throw_object(self):
        """Release the carried tiles through the shared throw simulation."""
        if getattr(self.client, 'ghost_mode', 0):
            return None
        player = self.client.player
        if not player.is_carrying():
            return

        bomb = getattr(player, 'carried_bomb', None)
        thrown_type, thrown_tiles, thrown_pos = player.throw_object()
        from ..throwing import make_throw, report_throw
        report_throw(self.client)
        direction = player.direction
        if getattr(player, 'action_mode', 0) == HIDDEN_ACTION_MODE:  # TPlayer.cpp:2032
            player.action_mode = 0

        # TPlayer.cpp:7845: release immediately starts idle, without a sound.
        from ..carrying import publish_carry
        publish_carry(self.client, -1)
        if getattr(player, 'action_mode', 0) == 4:
            player.action_mode = 0
        self.player_anim.set_animation('idle', direction, force=True)
        self.current_anim_name = 'idle'
        set_animation = getattr(self.client, 'set_animation', None)
        if set_animation is not None:
            set_animation('idle')

        if not thrown_tiles and bomb is None:
            return

        obj = make_throw(self.client.x, self.client.y, direction, thrown_type, thrown_tiles)
        if bomb is not None:
            obj['bomb'] = bomb
            bomb['carried_by'] = None
            bomb['in_flight'] = True
        self.thrown_objects.append(obj)
    def _find_chest_in_front(self) -> Optional[Tuple[int, int]]:
        """Return the local key of the chest being faced."""
        direction = self.client.player.direction
        points = self._touch_points(direction)
        if direction in (0, 2):
            # Vertical TOUCH_OFFSETS probe a full tile off the box edge:
            # facing up y+1.0 is exactly the box top (y+1), so a player flush
            # against a chest's south face floors into the tile BELOW it and
            # misses; facing down y+4.0 reaches a whole tile past the box
            # bottom (y+3), opening chests from a gap. Probe half a tile
            # beyond the box edge, as the left/right probes do.
            oy = 0.5 if direction == 0 else 3.5
            points = [(self.client.x + ox, self.client.y + oy)
                      for ox in (1.0, 2.0)]
        for tx, ty in points:
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
        if getattr(self.client, 'ghost_mode', 0):
            return None
        # keyAction D (TPlayer.cpp:2100-2103): no weapon while the ground
        # point is water. Weapon cycling (S+D) is not gated.
        if self.is_swimming:
            return
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
            if gs1 is not None and gs1.has_program(prog_key):
                for ev in ('playerfires', 'weaponfired'):
                    try:
                        gs1.trigger_event(ev, name=prog_key)
                    except Exception:
                        log_swallowed(logger)
                return
            # Use weapon-specific action
            if "bow" in weapon.lower():
                self.client.shoot(self.client.player.direction)
                self._play_action_animation("shoot")
                # Spawn visual projectile
                import math
                direction = self.client.player.direction
                speed = self.client.ARROW_SPEED  # FourPlay TClient.cpp:3646
                # Direction to velocity
                dx_map = {0: 0, 1: -speed, 2: 0, 3: speed}
                dy_map = {0: -speed, 1: 0, 2: speed, 3: 0}
                self.active_projectiles.append({
                    'x': self.client.player.x,
                    'y': self.client.player.y,
                    'dx': dx_map.get(direction, 0),
                    'dy': dy_map.get(direction, 0),
                    'time': self.clock.sim_now(),
                    'direction': direction,
                    'gani': 'arrow',
                    'max_distance': self.client.ARROW_MAX_DISTANCE,  # GServer Level.cpp:2629
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
                    'time': self.clock.sim_now(),
                    'fuse_time': self.bomb_fuse_time,
                    'power': self.client.player.bomb_power,
                    'exploded': False,
                    'source': 'local',
                })
                self._client_bomb_record(self.active_bombs[-1])
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
        if self.arrival.link_arrival is not None:
            ax, ay = self.arrival.link_arrival
            if abs(self.client.x - ax) >= 1.5 or abs(self.client.y - ay) >= 1.5:
                self.arrival.link_arrival = None

        link = self._get_non_edge_door()
        on_link = link is not None
        if not on_link:
            self.arrival.on_link = False
            return False
        # Still sitting near a recent warp arrival: don't re-fire (covers the
        # return link, an overlapping link we landed in, and late-loading links).
        if self.arrival.link_arrival is not None:
            self.arrival.on_link = True
            return False
        if not self.arrival.on_link:
            # Rising edge: stepped onto a link. Mark on-link + record the arrival
            # point BEFORE warping isn't possible (use_link moves us), so set the
            # latch first, then stamp arrival from the post-warp position.
            self.arrival.on_link = True
            self._use_door_link(link)
            self.arrival.link_arrival = (self.client.x, self.client.y)
            return True
        return False
    def _use_door_link(self, door_link: dict):
        """Use a door link to warp to another level."""
        self.client.use_link(door_link)
        # Standalone cross-level warps hold the old visual position until the
        # destination board is active. Same-level and gmap warps still snap now.
        if not getattr(self.client, 'local_level_transition', ''):
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
        self.arrival.gs1_level = self.client.current_level_name
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
    def _advance_ground_effects(self, dt):
        """Lava damage and the sleeping heal, both on the 20 Hz tick
        (TPlayer.cpp:5887-5912 testForLava, :7350-7362 sleep heal)."""
        player = self.client.player
        if getattr(self, '_ground_ticks', None) is None:
            self._ground_ticks = (TickCounter(), TickCounter())
        lava_ticks, sleep_ticks = self._ground_ticks
        alive = player.hearts > 0
        on_lava = (alive and not getattr(self.client, 'frozen', False)
                   and is_lava_type(self._effective_tile_type(*self._player_ground())))
        if lava_ticks.advance(dt, on_lava):
            # changePower2(-0.5, forceDamage=true) skips the swimming/pause
            # gates, so write past Player's immunity guard. The client owns
            # its HP; pygserver takes the CURPOWER report as-is.
            object.__setattr__(player, 'hearts', max(0.0, player.hearts - LAVA_DAMAGE))
            self.client.send_hearts()
        sleeping = alive and self.current_anim_name == SLEEP_ANI
        if sleep_ticks.advance(dt, sleeping) and player.hearts < player.max_hearts:
            self.client.send_hearts(player.hearts + SLEEP_HEAL)

    def _update_sleeping_state(self):
        """testSittingSleeping's bed half. The oracle runs it when a direction
        key is released (:3429) and on level entry (:1041), not every frame."""
        was_moving = getattr(self, '_sleep_was_moving', False)
        entered = getattr(self, '_sleep_level', None) != self.client.current_level_name
        self._sleep_was_moving = self.is_moving
        self._sleep_level = self.client.current_level_name
        if not self.is_moving and (was_moving or entered):
            self._test_sleeping()

    def _test_sleeping(self):
        player = self.client.player
        if (player.hearts <= 0 or player.is_carrying() or player.is_sitting
                or player.action_mode not in (0, 1)):
            return
        if self._effective_tile_type(*self._player_ground()) == TileType.CHAIR:
            return
        left, right = bed_samples(self.client.x, self.client.y)
        left_hits = [self._effective_tile_type(*p) == BED_TILE_TYPE for p in left]
        right_hits = [self._effective_tile_type(*p) == BED_TILE_TYPE for p in right]
        if not any(left_hits) or not any(right_hits):
            return
        self._play_action_animation(SLEEP_ANI)
        target = bed_snap_y(self.client.y, left_hits[0] or right_hits[0])
        if target != self.client.y:
            self.client.move(0, target - self.client.y, step=1.0,
                             face_direction=player.direction)

    def _update_swimming_state(self):
        """Update swimming state based on current position."""
        player = self.client.player
        # TPlayer.cpp:5990: jumping (2) and the rooted action (6) skip water.
        if (getattr(self, '_ledge_jump', None) is not None
                or player.action_mode in (2, 6)):
            return
        # TPlayer.cpp:5994-5997: frozen, scripted movement and ghosts skip it.
        if (getattr(self.client, 'frozen', False)
                or not self.clock.passed(getattr(self, '_frozen_until', 0.0))
                or not getattr(getattr(self, 'gs1', None), 'default_movement', True)
                or getattr(self.client, 'ghost_mode', 0)):
            return
        was_swimming = self.is_swimming
        # testForWater samples (x+1.5, y+2.0), the shared ground point
        # (TPlayer.cpp:6003-6004), not the y+2.5 feet point.
        self.is_swimming = self._check_water_at_position(*self._player_ground())
        self._swim_in_lava = (self.is_swimming and self._effective_tile_type(
            *self._player_ground()) == LAVA_SWIM_TILE_TYPE)

        swim_anim = LAVA_ANI if self._swim_in_lava else "swim"
        # Swimming drops a carried object: testForWater's setActionMode(10)
        # runs with a non-carry gani, which throws it (TPlayer.cpp:5774-5779).
        if self.is_swimming and player.is_carrying():
            self._throw_object()
            self.player_anim.set_animation(swim_anim, player.direction, force=True)
            self.current_anim_name = swim_anim

        if self.is_swimming != was_swimming:
            if self.is_swimming:
                # TPlayer.cpp:6018-6022,6029-6033: enter mode 10 and swim/lava.
                player.action_mode = SWIM_ACTION_MODE
                self.player_anim.set_animation(swim_anim, player.direction)
                self.current_anim_name = swim_anim
            else:
                # TPlayer.cpp:6007-6012: leaving water only clears mode 10.
                if player.action_mode == SWIM_ACTION_MODE:
                    player.action_mode = 0
                if self.current_anim_name in ("swim", LAVA_ANI) and not self.is_moving:
                    self.player_anim.set_animation("idle", player.direction)
                    self.current_anim_name = "idle"
            # TPlayer.cpp:6010-6011,6039-6040: both transitions burst;
            # putLeaps supplies water.wav (TServerLevel.cpp:2864-2865).
            dx, dy = SWIM_LEAP_OFFSET
            self._spawn_leaps(SWIM_LEAP_TYPE, self.client.x + dx, self.client.y + dy)
        elif (self.is_swimming and self.current_anim_name in ("swim", LAVA_ANI)
                and self.current_anim_name != swim_anim):
            # TPlayer.cpp:6016-6022: water <-> lava keeps the swim mode.
            self.player_anim.set_animation(swim_anim, player.direction)
            self.current_anim_name = swim_anim
