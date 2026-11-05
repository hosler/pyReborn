"""Client CombatMixin methods."""

from __future__ import annotations

import time
from typing import Optional

from reborn_protocol import BDMODE, BDPROP
from reborn_protocol.coords import level_index, segment_at, segment_origin, world_to_local

from .bushcut import (
    BUSH_PROBE, BUSH_REPLACE, EXPLOSION_PROBE, bush_probe, find_bush_block,
)
from .explosions import (
    board_blocks_at, bomb_crosses, cross_cells, explosion_damage, hits_player,
    knockback,
)
from .game.constants import (
    PLAYER_BODY_CENTER_X, PLAYER_BODY_CENTER_Y,
    PLAYER_COLLISION_BOTTOM, PLAYER_COLLISION_LEFT,
    PLAYER_COLLISION_RIGHT, PLAYER_COLLISION_TOP,
)
from .packets import PacketID, build_baddy_props, build_sword_attack
from .sword import SwordState, npc_probe, owns_spin
from .arrowflight import overlaps_player, shield_blocks, arrow_damage



class CombatMixin:
    def can_receive_local_hit(self, attacker_id=None, *, pvp=False):
        """getNoHurt/getNoHit, TPlayer.cpp:2987-3043, for local reports.

        PvP adds saint alignment, level no-PK, community and ally gates;
        ordinary NPC/environment damage only asks getNoHurt. Inbound server
        HP and forced hurt packets never use this predicate.
        """
        if self.player.no_hurt() or self.ghost_mode:
            return False
        gs2 = getattr(self, 'gs2_host', None)
        flags = getattr(gs2, 'player_object', None)
        if flags is not None and (flags.get('isinvincible') or flags.get('isinvincible2')):
            return False
        if not pvp:
            return True
        if not self.get_current_level_from_position():
            return False
        disable_saint = flags.get('disableapsaint') if flags is not None else False
        if self.player.ap > 99 and not disable_saint:
            return False
        level = getattr(gs2, 'level_object', None)
        if getattr(self, 'level_nopk', False) or (level is not None and level.get('isnopkzone')):
            return False
        attacker = self.players.get(attacker_id, {})
        community = getattr(self.player, 'community', '')
        other = attacker.get('community', '')
        if other and (other == community or other in getattr(self.player, 'allies', ())):
            return False
        return True

    def sword_attack(self, direction: Optional[int] = None) -> bool:
        """
        Swing sword in the given direction.

        Args:
            direction: 0=up, 1=left, 2=down, 3=right (default: current direction)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        # TPlayer.cpp:2014: ghosts cannot use the sword button.
        if self.ghost_mode or self.player.hurt.input_locked(time.time()) or self.player.status & 1:
            return False
        if (self.player.action_mode in (10, 13)
                or self.player.animation in ('dead', 'spin')):
            return False

        if direction is None:
            direction = self.player.direction

        # Always send local coords (0-63)
        local_x, local_y = world_to_local(self.player.x, self.player.y)
        old = getattr(self, '_sword_state', None)
        spin = bool(old and self.player.action_mode == 6
                    and time.time() < old.started + old.duration and owns_spin(self))
        data = build_sword_attack(local_x, local_y, direction)
        sent = self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

        # Classic sword damage is attacker-client-authoritative: the swing
        # itself is just a gani prop; the attacker detects the hit and sends
        # PLI_HURTPLAYER per victim (the server only relays/applies). Without
        # this, sword swings are cosmetic and players can't melee each other.
        # Level NPCs and baddies get the same treatment: NPCs react to a
        # `washit` event (bushes/pots/enemies with scripts) and baddies take
        # real damage via PLI_BADDYHURT.
        if sent:
            self._sword_state = SwordState(time.time(), direction, spin)
            # Per-victim report window survives swing restarts: mashing S
            # (or a swing turning into a spin) must not re-report a victim
            # inside its forty-tick hurt immunity.
            now = time.time()
            self._sword_hit_until = {pid: until for pid, until
                                     in getattr(self, '_sword_hit_until', {}).items()
                                     if until > now}
            self.player.action_mode = 13 if spin else 6
            self.player.animation = 'spin' if spin else 'sword'
            if spin:
                self.set_animation('spin')
            self._tick_sword_attack()
            self._sword_hit_npcs(direction)
            self._sword_hit_baddies(direction)
            # Also report the swing to the server so IT can run hit detection
            # against server-side scripted NPCs (fires their `washit`). Real
            # clients send PLI_HITOBJECTS on every swing; the probe point is
            # the center of the swing arc in local level coords.
            from .packets import build_hit_objects
            dir_vec = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}.get(direction, (0, 1))
            probe_lx, probe_ly = world_to_local(self.player.x, self.player.y)
            probe_x = probe_lx + 1 + dir_vec[0] * 1.5
            probe_y = probe_ly + 1.5 + dir_vec[1] * 1.5
            power = max(1.0, float(getattr(self.player, "sword_power", 1) or 1))
            self._protocol.send_packet(
                PacketID.PLI_HITOBJECTS, build_hit_objects(power, probe_x, probe_y))
            self._sword_cut_bushes(direction)
        return sent

    def _tick_sword_attack(self, now=None):
        """20 Hz hit window, TPlayer::animatePlayer and :5438-5494."""
        state = getattr(self, '_sword_state', None)
        if state is None:
            return
        now = time.time() if now is None else now
        if self.player.action_mode not in (6, 13) or self.player.status & 0x09:
            self._sword_state = None
            return
        for tick, direction in state.due(now):
            self._sword_hit_players(direction)
            if state.spin:
                self._sword_cut_bushes(direction, spinning=True)
                # TGaniObject.cpp:2912-2915: spin old sprite ==9 every 5 steps.
                if tick and tick % 5 == 0:
                    self._sword_hit_npcs(direction)
        if now + 1e-9 >= state.started + state.duration:
            self._sword_state = None
            self.player.action_mode = 0

    def _bush_board(self):
        """Resolve the player's board, never an adjacent preload's board."""
        level = self.get_current_level_from_position()
        if not level:
            return None
        board = self.levels.get(level)
        if board is None and self._tiles_level_name == level:
            board = self.tiles
        if board is None or len(board) < 4096:
            return None
        ox, oy = (segment_origin(*segment_at(self.player.x, self.player.y))
                  if self.in_gmap_segment else (0, 0))
        return level, board, ox, oy

    def _sword_cut_bushes(self, direction: int, *, spinning=False):
        # TPlayer.cpp:7668-7725: canLayItem requires an action level and an
        # unrounded laytest point clear of walls (NPCs/bombs/chests included,
        # other players excluded) and water; action modes 10 (swimming) and 13
        # (spin) return early, as does sword power 0. Mode 6 may become 13
        # during this swing, but that transition DOES NOT skip slayBushes.
        # slayBushes (:2314) additionally requires serverLevel == actionlevel.
        # Our action level is the segment containing the player's position.
        if direction not in range(4) or self.player.sword_power <= 0:
            return None
        action = getattr(self.player, 'action_mode', 0)
        if action == 10 or self.player.animation == 'dead' or (
                not spinning and (action == 13 or self.player.animation == 'spin')):
            return None
        current = self._bush_board()
        if current is None:
            return None
        _level, _board, ox, oy = current
        lx, ly = self.player.x - ox, self.player.y - oy
        # Deliberate deviation: slaySword (TPlayer.cpp:7681) gates on canLayItem
        # (:7668), and walltile (TServerLevel.cpp:~700-745) counts bush tiles
        # (type 20) as walls, so a flush bush could never be cut; skip the gate.
        return self._cut_bush_at(*bush_probe(lx, ly, int(direction)))

    def _can_lay_item(self, direction: int):
        """TPlayer.cpp:7668 canLayItem; not applied to bush cutting."""
        current = self._bush_board()
        if current is None:
            return False
        level, board, ox, oy = current
        lx, ly = self.player.x - ox, self.player.y - oy
        dx, dy = BUSH_PROBE[int(self.player.direction)]
        lay_x, lay_y = lx + dx, ly + dy
        if not (0 <= lay_x < 64 and 0 <= lay_y < 64):
            return False
        from .tiletypes import get_tile_type
        tile_type = get_tile_type(board[int(lay_x) + int(lay_y) * 64])
        # TServerLevel::walltile (:741) and isOnWater (:925): water is
        # types 11/12 here, rather than the scripting helper's shallow type 8.
        if tile_type > 19 or tile_type == 4:
            return False
        wx, wy = ox + lay_x, oy + lay_y
        runtime = getattr(getattr(self, 'gs1_host', None), 'rt', None)
        if runtime is not None:
            if runtime.npc_blocks_at(wx, wy):
                return False
            npc_type = runtime.npc_tile_type(wx, wy)
            if npc_type > 1:
                tile_type = npc_type
        if tile_type in (11, 12):
            return False
        for cx, cy in self.chests.get(level, {}):
            if cx <= lay_x < cx + 2 and cy <= lay_y < cy + 2:
                return False
        # TServerLevel::isOnBomb (:2666-2718); constants at TInitStatics.cpp:1248-1249.
        for bomb in self.bombs.get(level, {}).values():
            if (bomb['x'] + 0.25 <= lay_x < bomb['x'] + 3.0
                    and bomb['y'] <= lay_y < bomb['y'] + 2):
                return False
        return True

    def _cut_bush_at(self, tile_x: int, tile_y: int):
        current = self._bush_board()
        if current is None:
            return None
        _level, board, ox, oy = current
        match = find_bush_block(lambda x, y: board[x + y * 64], tile_x, tile_y)
        if match is None:
            return None
        start_x, start_y, index = match
        tl, bl, tr, br = BUSH_REPLACE[index]
        # Tables are column-major; modify_board's public API is row-major.
        # It also patches both local board caches optimistically.
        self.modify_board(start_x, start_y, 2, 2, [tl, tr, bl, br])
        if self.on_bush_cut:
            self.on_bush_cut(ox + start_x, oy + start_y, index)
        if self.on_leaps:
            self.on_leaps(index, ox + start_x, oy + start_y)  # TPlayer.cpp:2356-2357
        return ox + start_x, oy + start_y

    def _blast_board_at(self, x: float, y: float):
        """TServerLevel.cpp:1502-1590: board effects on the active level only."""
        from .tiletypes import active_tilestype
        current = self._bush_board()
        if current is None:
            return set()
        _level, board, ox, oy = current
        origins = set()
        for block in board_blocks_at(lambda tx, ty: board[level_index(tx, ty)],
                                     active_tilestype(), x - ox, y - oy):
            tl, bl, tr, br = block.replacement_column_major
            # TServerLevel.cpp:1534,1558,1582: publish the column-major patch.
            tiles = [tl, tr, bl, br]
            if self.modify_board(block.start_x, block.start_y, 2, 2, tiles):
                # TServerLevel.cpp:1582-1583: stones change the board without
                # debris; notify its painter even when no leap callback fires.
                if self.on_board_modify:
                    info = {'x': block.start_x, 'y': block.start_y,
                            'width': 2, 'height': 2, 'tiles': tiles}
                    if self.in_gmap_segment:
                        info['map_x'], info['map_y'] = segment_at(self.player.x, self.player.y)
                    self.on_board_modify(info)
            wx, wy = ox + block.start_x, oy + block.start_y
            origins.add((wx, wy))
            if block.bush_index is not None and self.on_bush_cut:
                self.on_bush_cut(wx, wy, block.bush_index)
            if block.leap_type is not None and self.on_leaps:
                self.on_leaps(block.leap_type, wx, wy)
        return origins

    def _cut_bushes_at_explosion(self, x: float, y: float):
        return self._blast_board_at(x, y)

    # ------------------------------------------------------------------
    # Bomb fuses, chain detonation and our own explosion damage.
    #
    # The reference client owns all three. putBomb creates a TICKING bomb for
    # the owner and for every other client alike (TServerLevel.cpp:1087-1130;
    # sendToServer only gates the PLI_BOMBADD send). animateBombs counts it
    # down every frame and explodes it below zero (:1310-1337). explodeBomb
    # removes it and makes the explosion (:1691-1725); every explosion cell
    # then probes for further bombs and explodes those inline (putExplosion,
    # :1494-1500). TExplosion::animate hurts the LOCAL player (TExplosion.cpp:
    # 48-96) and no hurt packet exists: hearts reach the server as CURPOWER.
    # So the Client simulates all of it from client.bombs, like the arrow sim.

    @staticmethod
    def _bomb_ticks(timer_ms: int) -> int:
        """PLI/PLO_BOMBADD tick counter for a fuse in ms (+50ms, see
        parse_bomb_add)."""
        return max(0, (int(timer_ms) - 50) // 50)

    def _level_world_origin(self, level: str):
        """World origin of a level's board: its gmap segment, else (0, 0)."""
        if not self.in_gmap_segment:
            return 0, 0
        for cell, name in self.gmap_grid.items():
            if name == level:
                return segment_origin(*cell)
        return 0, 0

    def _register_bomb(self, level: str, local_x: float, local_y: float, *,
                       wx: float, wy: float, owner_id: int, from_player: bool,
                       power: int, fuse_s: float, placed_at: float,
                       extra: Optional[dict] = None) -> dict:
        record = dict(extra or {})
        record.update(
            x=local_x, y=local_y, wx=wx, wy=wy, level=level, owner_id=owner_id,
            from_player=from_player, power=power, placed_at=placed_at,
            fuse_s=fuse_s, timer_ms=int(round(fuse_s * 1000)))
        self.bombs.setdefault(level, {})[(local_x, local_y)] = record
        return record

    def _bomb_records(self):
        """Every simulated bomb record, tolerating the legacy flat shape."""
        for level, bucket in list(self.bombs.items()):
            if not isinstance(bucket, dict):
                continue
            for record in list(bucket.values()):
                if isinstance(record, dict) and 'fuse_s' in record:
                    yield record

    def _drop_bomb_record(self, record: dict) -> bool:
        bucket = self.bombs.get(record.get('level'))
        key = (record['x'], record['y'])
        if bucket is None or bucket.get(key) is not record:
            return False
        del bucket[key]
        return True

    def _tick_bomb_sims(self, now: Optional[float] = None):
        """animateBombs (TServerLevel.cpp:1310-1337): explode every registry
        bomb whose fuse has run out. Call regularly (update() does)."""
        if not self.bombs:
            return
        if now is None:
            now = time.time()
        live_levels = {self._current_level_name, self._pending_level_name}
        if self.in_gmap_segment:
            live_levels.update(self.gmap_grid.values())
        for record in list(self._bomb_records()):
            if record['level'] not in live_levels:
                # The reference frees a level's bombs when the player leaves.
                self._drop_bomb_record(record)
                continue
            if now - record['placed_at'] >= record['fuse_s'] - 1e-9:
                self._explode_bomb(record, now)

    def _is_on_bomb(self, x: float, y: float, level: str):
        """TServerLevel::isOnBomb (:2666-2718) for a point probe."""
        for record in self._bomb_records():
            if not self.in_gmap_segment and record['level'] != level:
                continue
            if (record['wx'] + 0.25 <= x < record['wx'] + 3.0
                    and record['wy'] <= y < record['wy'] + 2):
                return record
        return None

    def _explode_bomb(self, record: dict, now: Optional[float] = None):
        """TServerLevel::explodeBomb (:1691-1725): remove the bomb, then make
        its explosion (one cross, or five for a superbomb)."""
        if not self._drop_bomb_record(record):
            return False  # already gone: re-entry from a chain
        now = time.time() if now is None else now
        power = record.get('power', 1)
        crosses = bomb_crosses(record['wx'], record['wy'], power)
        groups = [cross_cells(x, y, radius) for x, y, radius in crosses]
        if self.on_bomb_exploded:
            self.on_bomb_exploded(record, [cell for group in groups for cell in group])
        owner = record.get('owner_id', 0) if record.get('from_player') else 0
        hit = None
        for cells in groups:
            hit = self._explosion_cells(cells, record['level'], now) or hit
        if hit is not None:
            self._hurt_by_explosion(hit, power, owner)
        return True

    def _explosion_cells(self, cells, level: str, now: float):
        """putExplosion per cell (:1494-1500, 1614-1641): probe for bombs and
        chain them inline, then the board effects. Returns the first cell
        that overlaps the local player, which TExplosion::animate would use."""
        on_active_board = (self.in_gmap_segment
                           or level == self.get_current_level_from_position())
        hit = None
        for cell in cells:
            for dx, dy in EXPLOSION_PROBE:
                bomb = self._is_on_bomb(cell.x + dx, cell.y + dy, level)
                if bomb is not None:
                    self._explode_bomb(bomb, now)
            if on_active_board:
                self._blast_board_at(cell.x, cell.y)
            # TExplosion.cpp:54-61: only a player on the explosion's own level.
            if (hit is None and on_active_board
                    and hits_player(cell.x, cell.y, self.player.x, self.player.y)):
                hit = cell
        return hit

    def _hurt_by_explosion(self, cell, bomb_type: int, attacker_id: int):
        """TExplosion.cpp:62-91: hurt the local player once for this
        explosion. hurtPlayer's 40-tick immunity (can_receive_local_hit)
        collapses the remaining cells."""
        pvp = bool(attacker_id) and attacker_id != self.player.id and attacker_id in self.players
        if not self.can_receive_local_hit(attacker_id, pvp=pvp):
            return False
        damage = explosion_damage(bomb_type)
        push = knockback(cell.sprite_row)
        if not self.respond_to_hurt(damage, self.hurt_animation, knockback=push):
            return False
        if self.on_hurt:
            # damage_type 1 = BOMB, matching pygserver's DamageType.BOMB.
            self.on_hurt(attacker_id, damage, 1, push[0], push[1])
        return True

    def _apply_explosion(self, x: float, y: float, radius: int, bomb_type: int,
                         owner_id: int, from_player: bool,
                         now: Optional[float] = None):
        """scriptfun_client_addexplosion -> makeExplosion (TClient.cpp:3593-
        3620): the same chain, board and self-damage path a bomb uses.
        x/y are world coordinates. Returns the cells."""
        now = time.time() if now is None else now
        cells = cross_cells(x, y, radius)
        level = self.get_current_level_from_position()
        hit = self._explosion_cells(cells, level, now)
        if hit is not None:
            self._hurt_by_explosion(hit, bomb_type, owner_id if from_player else 0)
        return cells

    _SWORD_REACH = 4.0  # FourPlay TInitStatics.cpp:1251
    _SWORD_HALF_WIDTH = 2.0  # FourPlay TInitStatics.cpp:1277

    def _target_in_sword_arc(self, target_x: float, target_y: float,
                             fx: int, fy: int) -> bool:
        """Compare both player centres as in FourPlay TPlayer.cpp:5450-5457."""
        my_cx, my_cy = self.player.x + 1.5, self.player.y + 2.0
        target_cx, target_cy = target_x + 1.5, target_y + 2.0
        dx, dy = target_cx - my_cx, target_cy - my_cy
        forward = dx * fx + dy * fy
        lateral = dx * fy - dy * fx
        # FourPlay TPlayer.cpp:5465
        return (0 <= forward <= self._SWORD_REACH
                and abs(lateral) <= self._SWORD_HALF_WIDTH)

    # Baddies retain their existing collision-box test.
    def _npc_in_sword_arc(self, target_x: float, target_y: float,
                          fx: int, fy: int) -> bool:
        """Return True if a target collision box overlaps the facing sword arc."""
        my_cx = self.player.x + PLAYER_BODY_CENTER_X
        my_cy = self.player.y + PLAYER_BODY_CENTER_Y
        corners = (
            (target_x + PLAYER_COLLISION_LEFT, target_y + PLAYER_COLLISION_TOP),
            (target_x + PLAYER_COLLISION_LEFT, target_y + PLAYER_COLLISION_BOTTOM),
            (target_x + PLAYER_COLLISION_RIGHT, target_y + PLAYER_COLLISION_TOP),
            (target_x + PLAYER_COLLISION_RIGHT, target_y + PLAYER_COLLISION_BOTTOM),
        )
        forwards = [(x - my_cx) * fx + (y - my_cy) * fy for x, y in corners]
        laterals = [(x - my_cx) * fy - (y - my_cy) * fx for x, y in corners]
        return (max(forwards) > 0 and min(forwards) <= 1.5
                and max(laterals) >= -0.5
                and min(laterals) <= 0.5)

    def _sword_hit_players(self, direction: int):
        """Send PLI_HURTPLAYER for every other player inside the sword arc."""
        dir_vec = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}.get(direction)
        if not dir_vec:
            return
        fx, fy = dir_vec
        # self.players['x'/'y'] are now always LEVEL-LOCAL (0-63) - the
        # PLO_OTHERPLPROPS handler normalizes both classic X/Y and
        # high-precision X2/Y2 into that one frame at merge time - while
        # self.player.x/y are WORLD coords on a GMAP, so folding in an
        # offset is still required to compare them. 'world_x'/'world_y' are
        # set on that same merge whenever the wire told us the true world
        # position (a value >= 64, only possible via X2/Y2); prefer those
        # when known instead of assuming the attacker's own segment. When
        # they're not known (pygserver never sends per-player GMAPLEVELX/Y
        # (43/44) for OTHERPLPROPS, so a player on a DIFFERENT segment from
        # ours has no way to report its true segment), fall back to folding
        # in the ATTACKER's own segment offset - correct for same-segment
        # targets, but a target one segment over (e.g. attacker on
        # chicken1 at world (64, 95.5), target on chicken2 at local
        # (63.5, 94), a 1.6-tile world gap) still won't connect. Documented
        # limitation, not fixable client-side without server support.
        seg_ox, seg_oy = segment_origin(
            *segment_at(self.player.x, self.player.y))
        # Half a heart per sword power level, matching the classic client.
        damage = 0.5 * max(1, int(getattr(self.player, 'sword_power', 1) or 1))
        for pid, p in list(self.players.items()):
            wx, wy = p.get('world_x'), p.get('world_y')
            if wx is not None and wy is not None:
                px, py = wx, wy
            else:
                px, py = p.get('x'), p.get('y')
                if px is None or py is None:
                    continue
                px, py = px + seg_ox, py + seg_oy
            if self._target_in_sword_arc(px, py, fx, fy):
                # getNoHit, TPlayer.cpp:2987-3043. Remote action mode is
                # available only when supplied; jumping/hiding are NOT gates.
                if (p.get('ap', p.get('alignment', 50)) > 99
                        or p.get('status', 0) & 0x09
                        or p.get('action_mode', 0) in (3, 10)):
                    continue
                # The receiver's hurt window lasts forty ticks. Avoid
                # duplicate forced hurt relays while still testing each tick.
                now = time.time()
                until = getattr(self, '_sword_hit_until', {})
                if until.get(pid, 0.0) > now:
                    continue
                self.attack_player(pid, damage=damage,
                                   knockback_x=(px - self.player.x) * 0.5,
                                   knockback_y=(py - self.player.y) * 0.5)
                until[pid] = now + 2.0
                self._sword_hit_until = until

    def _sword_hit_npcs(self, direction: int):
        """Fire on_sword_hit_npc at the TPlayer.cpp:6484-6520 point probe.
        Hidden NPCs (`hide`/
        `destroy` -> visible=False) and non-blocking ones (`dontblock`) are
        skipped: per npcserver-gs1.md, `visible` tracks whether an NPC has
        been made invisible, and a dontblock NPC has no collision to hit.
        NPC positions use world_x/world_y (set on PLO_NPCPROPS) since
        self.player.x/y are world coords on a GMAP."""
        if not self.on_sword_hit_npc:
            return
        dir_vec = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}.get(direction)
        if not dir_vec:
            return
        probe_x, probe_y = npc_probe(self.player.x, self.player.y, direction)
        runtime = getattr(getattr(self, 'gs1_host', None), 'rt', None)
        for npc_id, npc in list(self.npcs.items()):
            if npc.get('visible', True) is False or npc.get('dontblock'):
                continue
            nx = npc.get('world_x', npc.get('x'))
            ny = npc.get('world_y', npc.get('y'))
            if nx is None or ny is None:
                continue
            hit = (runtime.npc_footprint_hit(npc, probe_x, probe_y)
                   if runtime is not None else
                   nx <= probe_x < nx + npc.get('width', 2.0)
                   and ny <= probe_y < ny + npc.get('height', 2.0))
            if hit:
                self.on_sword_hit_npc(npc_id)

    def _sword_hit_baddies(self, direction: int):
        """Send PLI_BADDYHURT for every baddy inside the sword arc (same math
        as _sword_hit_players). Baddy x/y are level-local, not world coords
        (unlike NPCs, PLO_BADDYPROPS has no world_x/world_y), so fold in the
        current GMAP segment's offset first, like render_entities.py does for
        drawing them."""
        dir_vec = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}.get(direction)
        if not dir_vec:
            return
        fx, fy = dir_vec
        seg_off_x = seg_off_y = 0
        if self.gmap_grid:
            seg = next((g for g, n in self.gmap_grid.items()
                        if n == self._current_level_name), None)
            if seg:
                seg_off_x, seg_off_y = segment_origin(*seg)
        # Half a heart per sword power level, matching the classic client.
        damage = 0.5 * max(1, int(getattr(self.player, 'sword_power', 1) or 1))
        baddies = self.baddies_in_level(self._current_level_name)
        for bid, b in list(baddies.items()):
            bx, by = b.get('x'), b.get('y')
            if bx is None or by is None:
                continue
            wx, wy = bx + seg_off_x, by + seg_off_y
            if self._npc_in_sword_arc(wx, wy, fx, fy):
                if self.is_leader:
                    # As this level's leader we're the one who resolves baddy
                    # damage (see _leader_apply_baddy_damage) - apply it and
                    # broadcast the result directly instead of sending
                    # PLI_BADDYHURT, which the server would just relay back
                    # to us (we ARE the leader) and double-apply through the
                    # PLO_BADDYHURT handler (handlers/combat.py).
                    self._leader_apply_baddy_damage(bid, int(damage * 2))
                else:
                    self.hurt_baddy(bid, damage=damage, hurt_dx=fx, hurt_dy=fy)

    # ---- Leader-authoritative baddy damage (client-authoritative combat
    # parity, task 2) -----------------------------------------------------
    #
    # GServer-v2 makes the level's LEADER (the first player to enter it,
    # PLO_ISLEADER) the sole resolver of baddy damage: any other player's
    # PLI_BADDYHURT is relayed to the leader ONLY (msgPLI_BADDYHURT,
    # PlayerClientPackets.cpp:523-539 - `leader->sendPacket(...)`), and the
    # leader is expected to apply the damage locally and report the result
    # back via PLI_BADDYPROPS, which the server both stores server-side and
    # relays to every OTHER player in the level (msgPLI_BADDYPROPS,
    # PlayerClientPackets.cpp:494-521 - the leader itself is excluded from
    # that relay). Without this, non-leader clients' PLI_BADDYHURT packets
    # reach the leader and stop there - the leader's own baddies dict never
    # updates and nobody else ever learns the baddy took damage or died.

    def _leader_apply_baddy_damage(self, baddy_id: int, damage_half_hearts: float) -> bool:
        """Apply damage to a baddy we (the leader) own and broadcast the
        result. `damage_half_hearts` is in the same raw wire units as
        PLO_BADDYHURT's power field (half-hearts) - baddy['power'] itself is
        plain hit points (GServer-v2's BaddyProp::POWERIMAGE), not hearts.
        This client already treats one half-heart of sword damage as one
        point of baddy power (see the PLO_BADDYHURT handler, unchanged by
        this task), so the units are kept consistent with that existing
        convention rather than introduced fresh here.
        """
        found = self.find_baddy(baddy_id)
        if found is None:
            return False
        _, baddy = found
        new_power = max(0, baddy.get('power', 0) - damage_half_hearts)
        baddy['power'] = new_power
        baddy['mode'] = int(BDMODE.DEAD) if new_power <= 0 else int(BDMODE.HURT)
        return self._leader_broadcast_baddy_props(baddy_id, baddy)

    def _leader_broadcast_baddy_props(self, baddy_id: int, baddy: dict) -> bool:
        """Send PLI_BADDYPROPS reporting this baddy's current POWERIMAGE +
        MODE. Leader-only - see the docstring above this section."""
        if not self.connected or not self._authenticated:
            return False
        data = build_baddy_props(baddy_id, {
            BDPROP.POWERIMAGE: (int(baddy.get('power', 0)), baddy.get('image', '') or ''),
            BDPROP.MODE: int(baddy.get('mode', BDMODE.WALK)),
        })
        return self._protocol.send_packet(PacketID.PLI_BADDYPROPS, data)
    # =========================================================================
    # Victim-side arrow flight simulation (client-authoritative combat
    # parity, task 1)
    #
    # GServer-v2 without a running NPCServer never runs its own arrow
    # collision detection at all (msgPLI_ARROWADD, PlayerClientPackets.cpp:
    # 287-311, only reaches level->addArrow() when m_server->hasNPCServer()
    # is true) - it just relays PLO_ARROWADD to everyone else in the level
    # and washes its hands of the projectile. That means on a real server,
    # the VICTIM is the only one who can ever notice they got shot: each
    # client must simulate every other player's arrow itself and apply
    # damage to itself the instant its own collision box connects.
    #
    # Flight constants below are copied from pygserver's own server-side
    # arrow simulation (pygserver/combat.py Arrow/CombatManager) as the best
    # available reference for "how an arrow behaves", not because pygserver
    # needs this client-side copy to work (pygserver already does its own
    # authoritative simulation - see the double-damage guard below).
    # =========================================================================

    _ARROW_SPEED = 20.0  # FourPlay TClient.cpp:3653: DOUBLE_004023d8 = 1 tile/50ms tick
    _ARROW_MAX_DISTANCE = 128.0  # GServer Level.cpp:2629
    _ARROW_DAMAGE = 1.0    # TServerFlying.cpp:222, default power 1.
    _ARROW_HIT_RADIUS = 1.0  # tiles, AABB half-extent (pygserver _update_arrow)
    _ARROW_STEP = 0.05     # seconds/substep - matches pygserver's 50ms tick;
                            # sub-stepping avoids tunneling through the
                            # player's hitbox when update() is called at a
                            # lower rate than the arrow crosses it.
    # Grace period between "our own sim detected a hit" and actually
    # applying it (see _tick_arrow_sims). pygserver runs its OWN
    # independent server-side arrow simulation using the exact same speed/
    # lifetime constants (that's where they're copied from), so it detects
    # the same hit at very nearly the same simulated time - and unlike our
    # side, applying it there is unconditional: pygserver's apply_damage()
    # has no idea our client is also tracking this arrow, so it always
    # subtracts once, on its own schedule, no matter what we do locally
    # (confirmed live: self-applying immediately let a fresh server-side
    # hit land moments later, silently overwriting our hearts via a second,
    # independent CURPOWER push and taking a full 1.0 hearts off a single
    # 0.5-heart arrow). Waiting this long before WE apply gives a
    # server-authoritative hit - if one is coming at all - time to arrive
    # and be recorded in _arrow_hurt_suppress first, so our own attempt
    # backs off instead of adding a second reduction. On real GServer-v2 no
    # such packet is ever sent (arrows are a pure client relay there), so
    # this is a pure server-only concern; a quarter-second is small enough
    # not to be felt as its own gameplay guard.
    _ARROW_HIT_GRACE = 0.25
    # Suppression window for the double-damage guard - matches pygserver's
    # own post-hit invincibility duration (CombatManager.apply_damage sets
    # `self._invincible[player.id] = time.time() + 1.0`), so it can't be
    # tighter than the window during which a genuine second hit from
    # anywhere wouldn't register server-side there anyway.
    _ARROW_HURT_SUPPRESS_WINDOW = 1.0
    _OWN_ARROW_ECHO_WINDOW = 0.5  # seconds to match a self-fired arrow's echo

    _ARROW_DIR_VECTORS = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}

    def _start_arrow_sim(self, info: dict, now: Optional[float] = None):
        """Start victim-side flight simulation for another player's arrow
        (PLO_ARROWADD). Skips arrows we fired ourselves (matched
        heuristically against _own_recent_arrows - see its docstring) and
        arrows with no usable direction vector."""
        dir_vec = self._ARROW_DIR_VECTORS.get(info.get('direction'))
        if dir_vec is None:
            return
        if now is None:
            now = time.time()

        self._own_recent_arrows = [
            e for e in self._own_recent_arrows if now - e[0] < self._OWN_ARROW_ECHO_WINDOW]
        for i, (fire_time, fdir, fx, fy) in enumerate(self._own_recent_arrows):
            if (fdir == info.get('direction')
                    and abs(fx - info['x']) < 1.0 and abs(fy - info['y']) < 1.0):
                del self._own_recent_arrows[i]
                return

        self._arrow_sims.append({
            'owner_id': info.get('owner_id', 0),
            'power': info.get('power', 1), 'direction': info['direction'],
            'x': info['x'], 'y': info['y'],
            'dx': dir_vec[0], 'dy': dir_vec[1],
            'spawn_time': now, 'last_tick': now,
            'distance': 0.0,
        })

    def _advance_arrow_sim(self, sim: dict, now: float, my_x: float, my_y: float) -> bool:
        """Step one arrow simulation forward from its last-checked time to
        `now`, sub-stepping at _ARROW_STEP so a low update() call rate cannot
        let the arrow tunnel through the player's hitbox between checks.
        Returns True (and leaves `sim` at the point of impact) on hit."""
        dt_total = min(now - sim['last_tick'],
                       (self._ARROW_MAX_DISTANCE - sim['distance']) / self._ARROW_SPEED)
        if dt_total <= 0:
            return False
        steps = max(1, int(dt_total / self._ARROW_STEP) + 1)
        step_dt = dt_total / steps
        hit = False
        for _ in range(steps):
            sim['x'] += sim['dx'] * self._ARROW_SPEED * step_dt
            sim['y'] += sim['dy'] * self._ARROW_SPEED * step_dt
            sim['distance'] += self._ARROW_SPEED * step_dt
            if sim.get('deflected'):
                continue
            overlaps = overlaps_player(sim['x'], sim['y'], sim['direction'], my_x, my_y)
            if overlaps:
                if self.player.no_hurt():
                    continue
                if shield_blocks(self.player, sim['direction'], sim['power']):
                    old_direction = sim['direction']
                    sim['dx'], sim['dy'] = -sim['dx'], -sim['dy']
                    sim['direction'] = (old_direction + 2) % 4
                    if self.player.shield_power == 1:
                        sim['deflected'] = True
                        sim['distance'] = self._ARROW_MAX_DISTANCE
                        break
                    from .packets import build_arrow_add
                    self._protocol.send_packet(PacketID.PLI_ARROWADD, build_arrow_add(
                        sim['x'], sim['y'], old_direction,
                        107 + sim['direction'], sim['power'], reflect=True, from_player=True))
                    # TServerFlying.cpp:194-232: the mirror branch leaves
                    # the collision counter negative and falls through to hurt.
                    hit = True
                    break
                hit = True
                break
        sim['last_tick'] = now
        return hit

    def _resolve_pending_arrow_hit(self, pending: dict):
        """Apply arrow damage to ourselves via the same self-authoritative
        hearts-update path (respond_to_hurt) the PLO_HURTPLAYER handler
        uses, unless a server hurt packet for this same owner already
        landed during the grace period (see _tick_arrow_sims / the
        double-damage guard docs above _ARROW_HIT_GRACE) - in which case
        this is a duplicate and is dropped."""
        owner_id = pending['owner_id']
        now = time.time()
        if owner_id in self._arrow_hurt_suppress and now < self._arrow_hurt_suppress[owner_id]:
            return
        if not self.can_receive_local_hit(owner_id, pvp=pending.get('pvp', True)):
            return
        self._arrow_hurt_suppress[owner_id] = now + self._ARROW_HURT_SUPPRESS_WINDOW
        damage = pending.get('damage', arrow_damage(pending.get('power', 1)))
        if not self.respond_to_hurt(damage, self.hurt_animation,
                                    knockback=(pending['dx'], pending['dy'])):
            return
        self._local_arrow_reports[owner_id] = now + self._ARROW_HURT_SUPPRESS_WINDOW
        if self.on_hurt:
            # damage_type 2 = ARROW, matching pygserver's DamageType.ARROW.
            self.on_hurt(owner_id, damage, pending.get('damage_type', 2), pending['dx'], pending['dy'])

    def _tick_arrow_sims(self, now: Optional[float] = None):
        """Advance every tracked victim-side arrow simulation, queue
        self-damage for any that connect with our own collision box this
        tick (see _ARROW_HIT_GRACE for why it is queued rather than applied
        immediately), and resolve anything whose grace period has elapsed.
        Call regularly (update() does this automatically)."""
        if now is None:
            now = time.time()

        if self._arrow_hurt_suppress:
            self._arrow_hurt_suppress = {
                oid: exp for oid, exp in self._arrow_hurt_suppress.items() if exp > now}
        self._local_arrow_reports = {
            oid: exp for oid, exp in self._local_arrow_reports.items() if exp > now}

        if self._arrow_sims:
            my_x, my_y = world_to_local(self.player.x, self.player.y)
            alive = []
            for sim in self._arrow_sims:
                if self._advance_arrow_sim(sim, now, my_x, my_y):
                    self._pending_arrow_hits.append({
                        'owner_id': sim['owner_id'], 'dx': sim['dx'], 'dy': sim['dy'],
                        'power': sim['power'],
                        'resolve_at': now + self._ARROW_HIT_GRACE,
                    })
                    continue  # consumed on hit - handed off to the pending queue
                if sim['distance'] < self._ARROW_MAX_DISTANCE - 1e-9:
                    alive.append(sim)
            self._arrow_sims = alive

        if self._pending_arrow_hits:
            still_pending = []
            for pending in self._pending_arrow_hits:
                if now >= pending['resolve_at']:
                    self._resolve_pending_arrow_hit(pending)
                else:
                    still_pending.append(pending)
            self._pending_arrow_hits = still_pending
