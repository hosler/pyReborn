"""Script-fired flying objects (shootfireblast / shootnuke): the per-tick
hit rules of TServerFlying::animate (Preagonal/FourPlay/quattroplay/src/
TServerFlying.cpp:361-416), applied to the projectile dicts that
gs1_callbacks.on_flying queues.

The official client never tests baddies, so neither does this. It tests, in
order: the local player, then the NPC under the sprite centre, then (power > 1)
the wall. The player and NPC tests are skipped while the object is bouncing
off an NPC.
"""

from reborn_protocol.coords import LEVEL_SIZE, gmap_extent

from ..explosions import explosion_sound
from ..flyingobjects import (
    BOUNCE_COUNTER, EXPLOSION_RADIUS, EXPLOSION_TYPE, FLYING_TICK_SECONDS,
    NOT_BOUNCING, center, explodes, explosion_origin, hits_walls,
    overlaps_player,
)

# A frame hitch must not turn into an unbounded burst of ticks.
MAX_TICKS_PER_FRAME = 10


class FlyingObjectsMixin:
    """Needs: client, sound_mgr, npc_handler, gs1, gs2, _is_blocked_at."""

    def _advance_flying(self, proj: dict, dt: float) -> bool:
        """Run the 20 Hz ticks `dt` covers, then place the sprite part-way
        through the current tick. Returns False once the object is gone."""
        proj['tick_acc'] += dt
        ticks = 0
        while proj['tick_acc'] >= FLYING_TICK_SECONDS and ticks < MAX_TICKS_PER_FRAME:
            proj['tick_acc'] -= FLYING_TICK_SECONDS
            ticks += 1
            if self._flying_tick(proj):
                return False
        proj['tick_acc'] = min(proj['tick_acc'], FLYING_TICK_SECONDS)
        proj['x'] = proj['lx'] + proj['dx'] * proj['tick_acc']
        proj['y'] = proj['ly'] + proj['dy'] * proj['tick_acc']
        return True

    def _flying_tick(self, proj: dict) -> bool:
        """One TServerFlying::animate. True means the object is finished."""
        old_x, old_y = proj['lx'], proj['ly']
        proj['lx'] += proj['dx'] * FLYING_TICK_SECONDS
        proj['ly'] += proj['dy'] * FLYING_TICK_SECONDS
        x, y = proj['lx'], proj['ly']
        sprite_dir = proj['direction']
        cx, cy = center(x, y, sprite_dir)
        power = proj['power']

        if self._flying_outside_world(x, y, proj['dx'], proj['dy']):
            return True  # no side level: transferFlyingToSideLevel drops it

        if proj['bounce'] < 0:
            if self._flying_hits_player(proj, x, y):
                ux = (proj['dx'] > 0) - (proj['dx'] < 0)
                uy = (proj['dy'] > 0) - (proj['dy'] < 0)
                self.client.hurt_local_by_flying(power, float(ux), float(uy))
                self._flying_explode(proj, old_x, old_y)
                return True
            npc_id = self._flying_npc_at(cx, cy)
            if npc_id is not None:
                self._flying_shot_npc(npc_id, proj['from_player'])
                # Every script-fired object has an arrow sprite, so it turns
                # round instead of exploding (TServerFlying.cpp:253-261).
                proj['bounce'] = BOUNCE_COUNTER
                proj['dx'], proj['dy'] = -proj['dx'], -proj['dy']
        else:
            proj['bounce'] -= 1
            if proj['bounce'] == NOT_BOUNCING:
                return True

        if hits_walls(power) and self._is_blocked_at(cx, cy, check_players=True):
            self._flying_explode(proj, old_x, old_y)
            return True
        return False

    def _flying_hits_player(self, proj: dict, x: float, y: float) -> bool:
        """handleFlyingPlayerCollision's gate and box (TServerFlying.cpp:127-
        141): only objects that did not come from the player's own weapon, and
        only while the player can be hurt. (Layers are not modelled.)"""
        if proj['from_player']:
            return False
        player = self.client.player
        if not self.client.can_receive_local_hit(0, pvp=False):
            return False
        return overlaps_player(x, y, proj['direction'], player.x, player.y)

    def _flying_npc_at(self, cx: float, cy: float):
        handler = getattr(self, 'npc_handler', None)
        if handler is None:
            return None
        return handler.npc_at_point(cx, cy)

    def _flying_shot_npc(self, npc_id, by_player: bool) -> None:
        # TServerFlying.cpp:252-253 is a mislabelled setter in the decompilation;
        # event 14 is `wasshot` (TInitStatics.cpp:308-309): the mapping is an inference.
        gs1 = getattr(self, 'gs1', None)
        if gs1 is not None:
            gs1.trigger_npc_wasshot(npc_id, by_player)
        gs2 = getattr(self, 'gs2', None)
        if gs2 is not None:
            gs2.trigger_npc_wasshot(npc_id, by_player)

    def _flying_explode(self, proj: dict, old_x: float, old_y: float) -> None:
        """makeFlyingExplosion (TServerFlying.cpp:85-115)."""
        if not explodes(proj['power']):
            return
        ex, ey = explosion_origin(old_x, old_y, proj['direction'])
        self.sound_mgr.play(explosion_sound(EXPLOSION_TYPE))
        self.client.make_explosion(ex, ey, EXPLOSION_RADIUS, EXPLOSION_TYPE,
                                   0, False)

    def _flying_outside_world(self, x: float, y: float,
                             dx: float, dy: float) -> bool:
        client = self.client
        if client.in_gmap_segment:
            max_x, max_y = gmap_extent(client.gmap_width, client.gmap_height)
        else:
            max_x = max_y = LEVEL_SIZE
        # Motion determines direction, including after a bounce (:33-39).
        direction = ((2 if dy >= 0 else 0) if abs(dx) < abs(dy)
                     else (3 if dx >= 0 else 1))
        # Top-left and direction gates, before collisions (:378-388).
        if x < 0 and abs(dx) >= abs(dy) and dx < 0:
            return True
        elif y < 0 and direction == 0:
            return True
        elif x >= max_x and direction == 3:
            return True
        elif y >= max_y and direction == 2:
            return True
        return False
