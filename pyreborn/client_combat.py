"""Client CombatMixin methods."""

from __future__ import annotations

import time
from typing import Optional

from reborn_protocol import BDMODE, BDPROP
from reborn_protocol.coords import segment_at, segment_origin, world_to_local

from .game.constants import (
    PLAYER_BODY_CENTER_X, PLAYER_BODY_CENTER_Y,
    PLAYER_COLLISION_BOTTOM, PLAYER_COLLISION_LEFT,
    PLAYER_COLLISION_RIGHT, PLAYER_COLLISION_TOP,
)
from .packets import PacketID, build_baddy_props, build_sword_attack



class CombatMixin:
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

        if direction is None:
            direction = self.player.direction

        # Always send local coords (0-63)
        local_x, local_y = world_to_local(self.player.x, self.player.y)
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
            self._sword_hit_players(direction)
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
        return sent

    # The blade rectangle starts at the attacker's body center. A target is
    # hittable when its canonical 2x2 collision box overlaps that rectangle.
    # These dimensions retain the former center-test envelope: adding the
    # target box's one-tile half-size gives 2.5 forward and 1.5 lateral tiles.
    _SWORD_REACH = 1.5
    _SWORD_HALF_WIDTH = 0.5

    def _target_in_sword_arc(self, target_x: float, target_y: float,
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
        return (max(forwards) > 0 and min(forwards) <= self._SWORD_REACH
                and max(laterals) >= -self._SWORD_HALF_WIDTH
                and min(laterals) <= self._SWORD_HALF_WIDTH)

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
                self.attack_player(pid, damage=damage,
                                   knockback_x=fx * 2, knockback_y=fy * 2)

    def _sword_hit_npcs(self, direction: int):
        """Fire on_sword_hit_npc for every visible, blocking level NPC inside
        the sword arc (same math as _sword_hit_players). Hidden NPCs (`hide`/
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
        fx, fy = dir_vec
        for npc_id, npc in list(self.npcs.items()):
            if npc.get('visible', True) is False or npc.get('dontblock'):
                continue
            nx = npc.get('world_x', npc.get('x'))
            ny = npc.get('world_y', npc.get('y'))
            if nx is None or ny is None:
                continue
            if self._target_in_sword_arc(nx, ny, fx, fy):
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
        for bid, b in list(self.baddies.items()):
            bx, by = b.get('x'), b.get('y')
            if bx is None or by is None:
                continue
            wx, wy = bx + seg_off_x, by + seg_off_y
            if self._target_in_sword_arc(wx, wy, fx, fy):
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
        baddy = self.baddies.get(baddy_id)
        if baddy is None:
            return False
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

    _ARROW_SPEED = 8.0    # tiles/sec (pygserver combat.py Arrow.speed)
    _ARROW_LIFETIME = 2.0  # seconds (pygserver combat.py Arrow.expired)
    _ARROW_DAMAGE = 0.5    # hearts = 1 half-heart (pygserver CombatManager.arrow_damage)
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
            'x': info['x'], 'y': info['y'],
            'dx': dir_vec[0], 'dy': dir_vec[1],
            'spawn_time': now, 'last_tick': now,
        })

    def _advance_arrow_sim(self, sim: dict, now: float, my_x: float, my_y: float) -> bool:
        """Step one arrow simulation forward from its last-checked time to
        `now`, sub-stepping at _ARROW_STEP so a low update() call rate cannot
        let the arrow tunnel through the player's hitbox between checks.
        Returns True (and leaves `sim` at the point of impact) on hit."""
        dt_total = now - sim['last_tick']
        if dt_total <= 0:
            return False
        steps = max(1, int(dt_total / self._ARROW_STEP) + 1)
        step_dt = dt_total / steps
        hit = False
        for _ in range(steps):
            sim['x'] += sim['dx'] * self._ARROW_SPEED * step_dt
            sim['y'] += sim['dy'] * self._ARROW_SPEED * step_dt
            if (abs(sim['x'] - my_x) < self._ARROW_HIT_RADIUS
                    and abs(sim['y'] - my_y) < self._ARROW_HIT_RADIUS):
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
        self._arrow_hurt_suppress[owner_id] = now + self._ARROW_HURT_SUPPRESS_WINDOW
        self.respond_to_hurt(self._ARROW_DAMAGE, self.hurt_animation)
        if self.on_hurt:
            # damage_type 2 = ARROW, matching pygserver's DamageType.ARROW.
            self.on_hurt(owner_id, self._ARROW_DAMAGE, 2, pending['dx'], pending['dy'])

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

        if self._arrow_sims:
            my_x, my_y = world_to_local(self.player.x, self.player.y)
            alive = []
            for sim in self._arrow_sims:
                if now - sim['spawn_time'] >= self._ARROW_LIFETIME:
                    continue  # expired - either a miss/dodge, or simply too old
                if self._advance_arrow_sim(sim, now, my_x, my_y):
                    self._pending_arrow_hits.append({
                        'owner_id': sim['owner_id'], 'dx': sim['dx'], 'dy': sim['dy'],
                        'resolve_at': now + self._ARROW_HIT_GRACE,
                    })
                    continue  # consumed on hit - handed off to the pending queue
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
