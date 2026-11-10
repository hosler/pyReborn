"""Client ActionsMixin methods."""

from __future__ import annotations

import time
import logging
import math
from typing import Optional

from reborn_protocol import BDMODE, BDPROP
from reborn_protocol.coords import local_coord, segment_at, world_to_local

from .game.constants import BOMB_FUSE_TIME
from .packets import (
    PacketBuilder, PacketID, build_animation, build_arrow_add,
    build_arrow_count, build_attack_player, build_baddy_add,
    build_baddy_hurt, build_baddy_props, build_bomb_add, build_bomb_count, build_bomb_del,
    build_claim_pker, build_explosion_add, build_flag_del, build_flag_set,
    build_hearts, build_horse_add, build_horse_del, build_hurt_response,
    build_item_add, build_item_take, build_open_chest,
    build_player_gattrib, build_private_message,
    build_putnpc, build_shoot, build_shoot_v1, build_triggeraction,
    build_weapon_add,
)

logger = logging.getLogger(__name__)



class ActionsMixin:
    def drop_bomb(self, power: int = 1) -> bool:
        """
        Drop a bomb at current position (PLI_BOMBADD. The server runs the
        fuse, explosion, and damage).

        Args:
            power: Bomb power (1-3)

        Returns:
            True if packet sent successfully
        """
        return self.put_bomb(power=power)

    def pickup_item(self, x: Optional[float] = None, y: Optional[float] = None) -> bool:
        """
        Pick up an item at position.

        Args:
            x: Item X position (default: player position)
            y: Item Y position (default: player position)

        Returns:
            True if packet sent successfully
        """
        if self.ghost_mode or not self.connected or not self._authenticated:
            return False

        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y

        data = build_item_take(x, y)
        return self._protocol.send_packet(PacketID.PLI_ITEMTAKE, data)

    def send_item_del(self, x: float, y: float) -> bool:
        """Remove a level item without taking it (PLI_ITEMDEL).

        The server drops the item and tells the rest of the level, but gives
        the sender nothing (PLI_ITEMTAKE is the one that grants). A GS1 `take`
        NPC absorbs the item this way: TClient::sendRemoveExtra, Preagonal/
        FourPlay/quattroplay/src/TClient.cpp:1189. Coordinates are level-local
        half-tiles, the same shape as PLI_ITEMTAKE."""
        if not self.connected or not self._authenticated:
            return False
        return self._protocol.send_packet(PacketID.PLI_ITEMDEL, build_item_take(x, y))

    def set_animation(self, gani_name: str) -> bool:
        """
        Set player animation (gani).

        Args:
            gani_name: Animation name (e.g., "idle", "walk", "sword", "hurt")

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        self.player.animation = gani_name
        gs2 = getattr(self, "gs2_host", None)
        if gs2 is not None:
            gs2.note_gani(("local", getattr(self.player, "id", 0)), gani_name)
        # GS1 `replaceani` substitution (wired by the pygame client): the wire
        # prop must carry the replaced name so other clients play the level's
        # ani (and their NPC scripts see it via #m), like a real client.
        resolver = getattr(self, "ani_resolver", None)
        wire_name = gani_name
        if resolver is not None:
            try:
                wire_name = resolver(gani_name) or gani_name
            except Exception:
                pass
        # Always send local coords (0-63)
        local_x, local_y = world_to_local(self.player.x, self.player.y)
        # A GS1/GS2 script writing `playerdir` stores a FLOAT; the SPRITE
        # prop is a single byte (same int-coercion family as update()'s
        # movement props above) — uncoerced it crashed set_animation on Era
        # ("'float' object cannot be interpreted as an integer").
        data = build_animation(wire_name, local_x, local_y,
                               int(self.player.direction or 0) & 3)
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

    def send_hearts(self, hearts: Optional[float] = None) -> bool:
        """
        Send current hearts value to server.

        Args:
            hearts: Hearts value (default: use player's current hearts)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        if hearts is not None:
            from .pausing import can_heal
            flags = getattr(getattr(self, 'gs2_host', None), 'player_object', None)
            disabled = flags.get('disableapnoheal') if flags is not None else False
            if hearts > self.player.hearts and not can_heal(self.player, disabled):
                return False
            self.player.set_hearts(max(0, min(hearts, self.player.max_hearts)))

        if self.player.hearts > 0:
            self._pker_claimed = False
        data = build_hearts(self.player.hearts)
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

    def respond_to_hurt(self, damage: float, gani_name: str = "hurt", *,
                        server_forced: bool = False, knockback=None) -> bool:
        """
        Respond to being hurt by sending updated health and hurt animation.
        This should be called when the client receives a PLO_HURTPLAYER packet.

        Args:
            damage: Damage received in hearts
            gani_name: Hurt animation name (default "hurt")

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        if damage <= 0:
            return False
        if not server_forced and not self.can_receive_local_hit():
            return False
        now = time.time()
        was_immune = self.player.hurt.immune(now)
        if self.player.hearts > 0:
            self._pker_claimed = False
        new_hearts = max(0, self.player.hearts - damage)
        # A server damage notification must still change HP during immunity.
        # Local hit detection/reporting is the only path immunity suppresses.
        object.__setattr__(self.player, 'hearts', new_hearts)
        self.player.animation = gani_name
        if not was_immune:
            self.player.hurt.start(*(knockback or (0.0, 0.0)), now)
            self.player.hurt_vector_pending = knockback is None
            self.player.action_mode = 3
        self.player.hurt_timeout = self.player.hurt.until

        # Send combined hurt response with health + animation. Always send
        # LOCAL coords (0-63) via X2/Y2 - self.player.x/y are WORLD coords
        # on a GMAP (move()/sword_attack() already localize for this
        # same reason), but this used to send them verbatim. The server
        # tracks position per-level/local (pygserver player.py
        # _handle_player_props: `self.x = props[PLPROP.X2]`, no unwrap), so
        # a world value here poisoned the SERVER's notion of this player's
        # position - not just the wire relay other clients saw (BUG 1's
        # players_visible frame poisoning), but pygserver's own hurt-range
        # sanity check (combat.py handle_hurt_player: `abs(attacker.x -
        # target.x) > 6.0`), which started rejecting every subsequent hit
        # against this player as "out of range" once its tracked x/y jumped
        # by a whole segment (live repro: kills took 3-6 extra swings).
        data = build_hurt_response(
            new_hearts,
            *world_to_local(self.player.x, self.player.y),
            self.player.direction,
            gani_name,
            use_new_format=self._use_pixel_props,
        )
        if not self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data):
            return False
        self._note_position_sent()
        return True

    def send_hit_objects(self, power: float, x: float, y: float) -> bool:
        """Report a scripted hit probe (PLI_HITOBJECTS) at level-local
        (x, y) — the GS1 `hitobjects` wire half. The server runs its own hit
        detection there (fires serverside NPCs' washit). Same builder the
        sword swing uses."""
        if not self.connected or not self._authenticated:
            return False
        from .packets import build_hit_objects
        return self._protocol.send_packet(
            PacketID.PLI_HITOBJECTS, build_hit_objects(power, x, y))

    def attack_player(self, victim_id: int, damage: float = 0.5,
                      knockback_x: int = 0, knockback_y: int = 0) -> bool:
        """
        Attack another player.

        Args:
            victim_id: Player ID of the target
            damage: Damage in hearts (default 0.5 = 1 half-heart)
            knockback_x: Knockback direction X (-128 to 127)
            knockback_y: Knockback direction Y (-128 to 127)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        # Fractional radial vectors need precision in the existing integer
        # direction fields; hurt normalizes this vector at the receiver.
        if isinstance(knockback_x, float) or isinstance(knockback_y, float):
            knockback_x, knockback_y = round(knockback_x * 16), round(knockback_y * 16)
        data = build_attack_player(victim_id, knockback_x, knockback_y, damage)
        return self._protocol.send_packet(PacketID.PLI_HURTPLAYER, data)

    def shoot(self, direction: Optional[int] = None, speed: int = 3,
              gani: str = "arrow", gravity: int = 0, params: str = "") -> bool:
        """
        Shoot a projectile (arrow, fireball, etc.).

        Args:
            direction: 0=up, 1=left, 2=down, 3=right (default: player direction)
            speed: Projectile speed (1-127, default 3)
            gani: Projectile animation name (default "arrow")
            gravity: Gravity effect (0 for flat shot, 8 for arc)
            params: Projectile param string (GS1 shoot params. The receiver reads
                them via #p(n) in an actionprojectile2 handler)

        Returns:
            True if packet sent successfully
        """
        import math

        if not self.connected or not self._authenticated:
            return False

        if direction is None:
            direction = self.player.direction

        # Convert direction to angle (radians)
        # 0=up (-pi/2), 1=left (pi), 2=down (pi/2), 3=right (0)
        angles = {
            0: -math.pi / 2,  # up
            1: math.pi,       # left
            2: math.pi / 2,   # down
            3: 0              # right
        }
        angle = angles.get(direction, 0)

        # Classic servers (v2.x) only handle the old PLI_SHOOT (40); they ignore
        # PLI_SHOOT2 (48), so projectiles — and Bomber Arena's room system — never
        # relay. v6 clients use PLI_SHOOT2.
        if str(self.version).startswith("2."):
            data = build_shoot_v1(self.player.x, self.player.y, 0,
                                  angle, speed, gani, params)
            return self._protocol.send_packet(PacketID.PLI_SHOOT, data)
        data = build_shoot(
            self.player.x, self.player.y, 0,
            angle, speed, gani, params, gravity
        )
        return self._protocol.send_packet(PacketID.PLI_SHOOT2, data)

    def triggeraction(self, action: str, x: Optional[float] = None,
                      y: Optional[float] = None, npc_id: int = 0) -> bool:
        """
        Trigger a server-side action.

        Args:
            action: Action string (e.g., "warp,level.nw,30,30" or "serverside,func")
            x: X position (default: player position)
            y: Y position (default: player position)
            npc_id: NPC ID to trigger on (0 for level/weapon triggers)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y

        data = build_triggeraction(x, y, action, npc_id)
        return self._protocol.send_packet(PacketID.PLI_TRIGGERACTION, data)

    def accept_server_warp(self, info: Optional[dict] = None) -> Optional[dict]:
        """Consent to a PLO_SERVERWARP offer; return its validated target.

        The game server names the target, so the library never connects there
        on its own (the reference client only raises a script event:
        TServerList.cpp:131-160). The embedding app calls this after asking
        its user, then opens a new connection to the returned {'name', 'host',
        'port'} itself. Returns None, leaving the offer in place, when there is
        no offer or its host/port are not usable.
        """
        from .packet_codec.gameplay import validate_server_warp_target
        offer = info if info is not None else self.server_warp_info
        target = validate_server_warp_target(offer)
        if target is not None and offer is self.server_warp_info:
            self.server_warp_info = None
        return target

    def send_server_text(self, request: bool, text: str) -> bool:
        """Send a gtokenized server-list text request or command."""
        from .packets import _gtokenize
        packet_id = PacketID.PLI_REQUESTTEXT if request else PacketID.PLI_SENDTEXT
        return self._protocol.send_packet(packet_id, _gtokenize(text).encode("latin-1"))

    def send_weapon_add(self, npc_id: int) -> bool:
        """Ask the server to grant the weapon represented by a level NPC."""
        if not self.connected or not self._authenticated:
            return False
        return self._protocol.send_packet(
            PacketID.PLI_WEAPONADD, build_weapon_add(npc_id))

    def delete_npc(self, npc_id: int) -> bool:
        """Ask the server to delete a server-owned NPC."""
        if not self.connected or not self._authenticated or npc_id <= 0:
            return False
        data = PacketBuilder().write_gint3(npc_id).build()
        return self._protocol.send_packet(PacketID.PLI_NPCDEL, data)

    def send_putnpc(self, image: str, script_file: str, x: float, y: float) -> bool:
        """GS1 `putnpc image,scriptfile,x,y`: ask the server to create a level
        NPC from one of ITS script files (PLI_PUTNPC). The new NPC streams back
        to everyone in the level via normal NPC props - see build_putnpc for
        why the client must not also spawn a local copy. Gated server-side on
        `putnpcenabled` (GTA and the classic-gs1 reference configs enable it)."""
        if not self.connected or not self._authenticated:
            return False
        data = build_putnpc(image, script_file, x, y)
        return self._protocol.send_packet(PacketID.PLI_PUTNPC, data)

    def send_baddy_add(self, x: float, y: float, baddy_type: int,
                       power: int, image: str) -> bool:
        """GS1 `putcomp`/`putnewcomp`: ask the server to add a baddy
        (PLI_BADDYADD). It comes back via the level-wide PLO_BADDYPROPS
        broadcast. `power` is half-hearts."""
        if not self.connected or not self._authenticated:
            return False
        data = build_baddy_add(x, y, baddy_type, power, image)
        return self._protocol.send_packet(PacketID.PLI_BADDYADD, data)

    def kill_all_baddies(self) -> bool:
        """GS1 `removecompus`: there is no dedicated wire op for the classic
        client, but the leader-authoritative baddy channel (PLI_BADDYPROPS,
        the same one hit resolution uses - see _leader_broadcast_baddy_props)
        lets us mark every baddy dead: the server applies MODE=DEAD to its
        copy and relays it to the level (see build_baddy_props' wire-format
        citation). putcomp/BADDYADD baddies have
        respawn disabled server-side, so dead is gone. Level-placed baddies
        follow their normal respawn timer. Local state is updated in the same
        step because the relay excludes the sender when we are the leader."""
        ok = True
        baddies = self.baddies_in_level(self._current_level_name)
        for baddy_id, baddy in list(baddies.items()):
            if isinstance(baddy, dict):
                baddy['mode'] = int(BDMODE.DEAD)
            if self.connected and self._authenticated:
                data = build_baddy_props(baddy_id,
                                         {BDPROP.MODE: int(BDMODE.DEAD)})
                ok = self._protocol.send_packet(PacketID.PLI_BADDYPROPS,
                                                data) and ok
        return ok

    def set_flag(self, flag_name: str, flag_value: str = "") -> bool:
        """
        Set a player flag.

        Args:
            flag_name: Name of the flag
            flag_value: Value to set (empty for boolean true)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_flag_set(flag_name, flag_value)
        return self._protocol.send_packet(PacketID.PLI_FLAGSET, data)

    def del_flag(self, flag_name: str) -> bool:
        """
        Delete a player flag.

        Args:
            flag_name: Name of the flag to delete

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_flag_del(flag_name)
        return self._protocol.send_packet(PacketID.PLI_FLAGDEL, data)

    def delete_weapon(self, name: str) -> bool:
        """Remove a weapon from this account, locally and server-side
        (PLI_NPCWEAPONDEL — GServer erases it from account.weapons unless
        protected). This is what a weapon script's `destroy` does on the real
        client. Without it, self-destroying weapons (the Bomber arena's
        -arenaSYS/-validation) pile up on the account and their playerenters
        re-fire on every later level/login."""
        if not name:
            return False
        self.weapons.pop(name, None)
        if not self.connected or not self._authenticated:
            return False
        try:
            data = name.encode("latin-1", "replace")
        except Exception:
            return False
        return self._protocol.send_packet(PacketID.PLI_NPCWEAPONDEL, data)

    def set_gattrib(self, index: int, value: str) -> bool:
        """Set gani attribute `index` (1..30, i.e. GS1 #P<index>) and send it to
        the server, which relays it to other players (PLO_OTHERPLPROPS). Used by
        Bomber Arena's room slot lists so players see each other in the queue."""
        if not self.connected or not self._authenticated:
            return False
        # cache our own value so we read it back consistently
        self.player.gattribs = getattr(self.player, 'gattribs', {})
        self.player.gattribs[index] = value
        data = build_player_gattrib(index, value)
        if not data:
            return False
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)
    def send_pm(self, player_id: int, message: str) -> bool:
        """
        Send a private message to another player by ID.

        Args:
            player_id: Numeric player ID of the recipient
            message: Message to send

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_private_message([player_id], message)
        return self._protocol.send_packet(PacketID.PLI_PRIVATEMESSAGE, data)

    def send_pm_multi(self, player_ids: list, message: str) -> bool:
        """
        Send a private message to multiple players by ID.

        Args:
            player_ids: List of numeric player IDs
            message: Message to send

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_private_message(player_ids, message)
        return self._protocol.send_packet(PacketID.PLI_PRIVATEMESSAGE, data)

    def get_player_id_by_account(self, account: str) -> int:
        """
        Look up a player ID by account name.

        Args:
            account: Account name to search for

        Returns:
            Player ID if found, 0 otherwise
        """
        account_lower = account.lower()
        for pid, player in self.players.items():
            if player.get('account', '').lower() == account_lower:
                return pid
        return 0

    def hurt_baddy(self, baddy_id: int, damage: float = 1.0,
                   hurt_dx: float = 0.0, hurt_dy: float = 0.0) -> bool:
        """
        Attack a baddy/enemy.

        Args:
            baddy_id: ID of the baddy to attack
            damage: Damage in hearts (default 1.0)
            hurt_dx, hurt_dy: Attack direction, -1.0..1.0 per axis (default
                0,0 = no direction / environment hit) - see build_baddy_hurt.

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_baddy_hurt(baddy_id, damage, hurt_dx, hurt_dy)
        return self._protocol.send_packet(PacketID.PLI_BADDYHURT, data)

    def open_chest(self, x: Optional[float] = None, y: Optional[float] = None) -> bool:
        """
        Open a chest at the specified position.

        Args:
            x: Chest X position (default: player position)
            y: Chest Y position (default: player position)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y

        data = build_open_chest(x, y)
        return self._protocol.send_packet(PacketID.PLI_OPENCHEST, data)

    def mount_horse(self, x: Optional[float] = None, y: Optional[float] = None,
                    image: str = "horse.png", direction: Optional[int] = None) -> bool:
        """
        Add/mount a horse at the specified position.

        Args:
            x: Horse X position (default: player position)
            y: Horse Y position (default: player position)
            image: Horse image name (default "horse.png")
            direction: Horse direction (default: player direction)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y
        if direction is None:
            direction = self.player.direction

        data = build_horse_add(x, y, image, direction)
        return self._protocol.send_packet(PacketID.PLI_HORSEADD, data)

    def _level_at_world(self, x: float, y: float) -> str:
        """Level whose board holds world (x, y): its gmap segment, else the
        current level."""
        if self.in_gmap_segment:
            name = self.gmap_grid.get(segment_at(x, y))
            if name:
                return name
        return self.get_current_level_from_position()

    def put_bomb(self, x: Optional[float] = None, y: Optional[float] = None,
                power: int = 1, timer_ms: int = int(BOMB_FUSE_TIME * 1000),
                consume_ammo: bool = True,
                from_player: Optional[bool] = None) -> bool:
        """Place a bomb (PLI_BOMBADD). timer_ms is total fuse time. The wire
        counter is (counter + 1) * 50ms, so the 3s default is counter 59.

        The bomb also ticks HERE: the reference client's putBomb creates it
        ticking for owner and non-owner alike (TServerLevel.cpp:1087-1130), so
        it is registered in client.bombs and _tick_bomb_sims detonates it.
        The owner sends ticks-5 when ticks > 5 as latency compensation
        (:1117-1119) and keeps the full fuse locally.

        Ammo is client-authoritative on GServer-v2 (PLI_BOMBADD only spawns
        the projectile. The server never touches the count), so this refuses
        to fire at 0 bombs, decrements locally, and reports the new
        BOMBSCOUNT. pygserver additionally decrements server-side and echoes
        the authoritative count via PLO_PLAYERPROPS - that echo is an absolute
        value equal to our prediction, so the two do not double-decrement.

        consume_ammo=False is the GS1 `putbomb` path: a script-spawned bomb
        is a free level projectile, not a shot from the player's bag, and it
        does not carry the player-placed flag (bit 3 of the power byte,
        TClient.cpp:1661-1690). from_player overrides that flag, which the
        reference client keeps when a carried bomb is re-placed."""
        if not self.connected or not self._authenticated:
            return False
        if consume_ammo and (self.ghost_mode or self.player.bombs <= 0):
            logger.debug("put_bomb: no bombs left, not firing")
            return False
        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y
        if from_player is None:
            from_player = consume_ammo
        ticks = self._bomb_ticks(timer_ms)
        wire_ms = timer_ms - 5 * 50 if ticks > 5 else timer_ms
        data = build_bomb_add(x, y, power, wire_ms, from_player)
        ok = self._protocol.send_packet(PacketID.PLI_BOMBADD, data)
        if ok:
            lx, ly = world_to_local(x, y)
            self._register_bomb(
                self._level_at_world(x, y), int(lx * 2) / 2.0, int(ly * 2) / 2.0,
                wx=x, wy=y, owner_id=self.player.id or 0, from_player=from_player,
                power=power & 0x07, fuse_s=(ticks + 1) * 0.05,
                placed_at=time.time(), extra={'local': True})
        if ok and consume_ammo:
            self.player.bombs -= 1
            self._protocol.send_packet(PacketID.PLI_PLAYERPROPS,
                                       build_bomb_count(self.player.bombs))
        return ok

    def remove_bomb(self, x: float, y: float) -> bool:
        """Remove all bombs at this half-tile and send one PLI_BOMBDEL."""
        lx, ly = world_to_local(x, y)
        self._remove_bombs_at(self._level_at_world(x, y), lx, ly)
        if not self.connected or not self._authenticated:
            return False
        data = build_bomb_del(x, y)
        return self._protocol.send_packet(PacketID.PLI_BOMBDEL, data)

    def send_claim_pker(self, killer_id: int) -> bool:
        """Tell the server which player killed this client (PLI_CLAIMPKER)."""
        if not self.connected or not self._authenticated:
            return False
        return self._protocol.send_packet(
            PacketID.PLI_CLAIMPKER, build_claim_pker(killer_id))

    def send_explosion(self, radius: int, x: float, y: float,
                       power: int = 1) -> bool:
        """Report a client-scripted explosion (PLI_EXPLOSION and GS1
        putexplosion/putexplosion2). Coordinates are localized to the current
        segment like every other GCHAR-position packet."""
        if not self.connected or not self._authenticated:
            return False
        data = build_explosion_add(radius, *world_to_local(x, y), power)
        return self._protocol.send_packet(PacketID.PLI_EXPLOSION, data)

    def send_item_add(self, x: float, y: float, item_id: int) -> bool:
        """Drop a level item (PLI_ITEMADD and GS1 lay/lay2). The server relays a
        PLO_ITEMADD to the rest of the level."""
        if not self.connected or not self._authenticated:
            return False
        data = build_item_add(*world_to_local(x, y), item_id)
        return self._protocol.send_packet(PacketID.PLI_ITEMADD, data)

    def shoot_arrow(self, x: Optional[float] = None, y: Optional[float] = None,
                    direction: Optional[int] = None, sprite: int = 0,
                    power: int = 1) -> bool:
        """Fire an arrow (PLI_ARROWADD).

        Refuses to fire at 0 arrows, decrements the local count, and reports
        the new ARROWSCOUNT - ammo is client-authoritative on GServer-v2 (see
        put_bomb for the full parity story vs pygserver's server-side echo)."""
        if not self.connected or not self._authenticated:
            return False
        if self.ghost_mode or self.player.arrows <= 0:
            logger.debug("shoot_arrow: no arrows left, not firing")
            return False
        # ARROWADD wire coords are LEVEL-LOCAL (0-63) like move()/sword —
        # GServer-v2's msgPLI_ARROWADD treats them as local-to-segment, and
        # sending world coords on a gmap made the server drop the arrow as
        # out-of-bounds on tick 1 (arrows silently never hit anything).
        if x is None:
            x = local_coord(self.player.x)
        if y is None:
            y = local_coord(self.player.y)
        if direction is None:
            direction = self.player.direction
        data = build_arrow_add(x, y, direction, sprite, power, from_player=True)
        ok = self._protocol.send_packet(PacketID.PLI_ARROWADD, data)
        if ok:
            self.player.arrows -= 1
            self._protocol.send_packet(PacketID.PLI_PLAYERPROPS,
                                       build_arrow_count(self.player.arrows))
            # Record so a self-echo of this same arrow (servers that
            # broadcast PLI_ARROWADD to the whole level, self included -
            # see _own_recent_arrows) doesn't get simulated as an incoming
            # attack against ourselves.
            now = time.time()
            self._own_recent_arrows.append((now, direction, float(x), float(y)))
            self._own_recent_arrows = [
                e for e in self._own_recent_arrows
                if now - e[0] < self._OWN_ARROW_ECHO_WINDOW]
        return ok

    def remove_horse(self, x: float, y: float) -> bool:
        """Remove/dismount a horse at (x, y) (PLI_HORSEDEL)."""
        if not self.connected or not self._authenticated:
            return False
        data = build_horse_del(x, y)
        return self._protocol.send_packet(PacketID.PLI_HORSEDEL, data)
