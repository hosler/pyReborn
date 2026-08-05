"""The client handles combat and projectile packets.

These packets contain damage, relayed shots and explosions, and the
bomb, arrow, horse, and firespy entity families.
"""

import time

from ..packets import (
    PacketID,
    parse_arrow_add,
    parse_baddy_hurt,
    parse_bomb_add,
    parse_bomb_del,
    parse_explosion,
    parse_firespy,
    parse_hit_objects,
    parse_horse_add,
    parse_horse_del,
    parse_hurt_player,
    parse_push_away,
    parse_shoot,
    parse_throwcarried,
)
from .registry import handles


# PLO_SHOOT (175) / PLO_SHOOT2 (191) - a projectile was relayed to us.
# Same id across versions; classic uses SHOOT (v1 wire), 6.037 SHOOT2.
def _relay_shoot(client, data, v2):
    info = parse_shoot(data, v2=v2)
    if info and client.on_projectile:
        client.on_projectile(info)


@handles(PacketID.PLO_SHOOT)
def handle_shoot(client, data):
    _relay_shoot(client, data, v2=False)


@handles(PacketID.PLO_SHOOT2)
def handle_shoot2(client, data):
    _relay_shoot(client, data, v2=True)


@handles(PacketID.PLO_HURTPLAYER)
def handle_hurt_player(client, data):
    # PLO_HURTPLAYER (40) - player hurt/damage notification
    hurt_info = parse_hurt_player(data)
    if hurt_info:
        attacker_id = hurt_info.get('player_id', 0)
        damage = hurt_info.get('damage', 0)

        # Double-damage guard: a server that runs its own
        # independent arrow-flight simulation in parallel with ours
        # (pygserver's CombatManager - see _tick_arrow_sims) can end
        # up telling us about a hit we ALREADY applied to ourselves
        # via that simulation. Real GServer-v2 never sends this for
        # arrows at all (no NPCServer => arrows are a pure client-
        # authoritative relay, see msgPLI_ARROWADD), so this is a
        # pygserver-only concern in practice.
        already_applied = (
            attacker_id in client._arrow_hurt_suppress
            and time.time() < client._arrow_hurt_suppress[attacker_id])

        # We got hurt - client is source of truth for health
        # Auto-respond with new health and hurt animation
        if client.auto_respond_hurt and damage > 0 and not already_applied:
            client.respond_to_hurt(damage, client.hurt_animation)
            # This may be the server's own independent detection of
            # a hit our own arrow sim hasn't caught up to yet (it
            # might not have even started - the PLO_ARROWADD relay
            # and this PLO_HURTPLAYER aren't guaranteed to arrive in
            # any particular order). Mark the owner suppressed
            # UNCONDITIONALLY (not just when a sim already exists -
            # a sim starting moments later must still respect this)
            # and drop any in-flight sims from them so ours doesn't
            # also apply this same hit once it resolves.
            client._arrow_hurt_suppress[attacker_id] = (
                time.time() + client._ARROW_HURT_SUPPRESS_WINDOW)
            if any(s['owner_id'] == attacker_id for s in client._arrow_sims):
                client._arrow_sims = [
                    s for s in client._arrow_sims if s['owner_id'] != attacker_id]
            if any(p['owner_id'] == attacker_id for p in client._pending_arrow_hits):
                client._pending_arrow_hits = [
                    p for p in client._pending_arrow_hits if p['owner_id'] != attacker_id]

        # Callback (after responding, so player.hearts is updated)
        if client.on_hurt:
            client.on_hurt(
                attacker_id,
                damage,
                hurt_info.get('damage_type', 0),
                hurt_info.get('source_x', 0),
                hurt_info.get('source_y', 0)
            )


@handles(PacketID.PLO_EXPLOSION)
def handle_explosion(client, data):
    # Explosion effect (packet 36)
    exp = parse_explosion(data)
    if exp:
        client.active_explosions.append({
            'x': exp['x'],
            'y': exp['y'],
            'radius': exp['radius'],
            'power': exp['power'],
            'time': time.time()
        })
        if client.on_explosion:
            client.on_explosion(exp['x'], exp['y'], exp['radius'], exp['power'])


@handles(PacketID.PLO_HITOBJECTS)
def handle_hit_objects(client, data):
    # Hit objects feedback (packet 46)
    hit = parse_hit_objects(data)
    if hit and client.on_hit_objects:
        client.on_hit_objects(hit['x'], hit['y'], hit['power'], hit['player_id'])


@handles(PacketID.PLO_BADDYHURT)
def handle_baddy_hurt(client, data):
    # A baddy was hurt (packet 27) - relayed to the level leader.
    bh = parse_baddy_hurt(data)
    bid = bh['baddy_id']
    found = client.find_baddy(bid)
    if found is not None:
        _, baddy = found
        if client.is_leader:
            # We're this level's leader: GServer-v2 only ever relays
            # another player's PLI_BADDYHURT to us (see the
            # docstring above _leader_apply_baddy_damage) - nobody
            # else will apply it, so we must apply it locally and
            # tell the rest of the level the result.
            client._leader_apply_baddy_damage(bid, bh['power'])
        else:
            baddy['power'] = max(0, baddy.get('power', 0) - bh['power'])
    if client.on_baddy_hurt:
        client.on_baddy_hurt(bid, bh['power'])


@handles(PacketID.PLO_BOMBADD)
def handle_bomb_add(client, data):
    # Bomb placed by another player (packet 11).
    info = parse_bomb_add(data)
    level_name = client._pending_level_name or client._current_level_name
    client.bombs.setdefault(level_name, {})[(info['x'], info['y'])] = info
    if client.on_bomb_add:
        client.on_bomb_add(info)


@handles(PacketID.PLO_BOMBDEL)
def handle_bomb_del(client, data):
    # Bomb removed/exploded (packet 12).
    info = parse_bomb_del(data)
    level_name = client._pending_level_name or client._current_level_name
    client.bombs.setdefault(level_name, {}).pop((info['x'], info['y']), None)
    if client.on_bomb_del:
        client.on_bomb_del(info['x'], info['y'])


@handles(PacketID.PLO_ARROWADD)
def handle_arrow_add(client, data):
    # Arrow fired by another player (packet 19). Transient - no removal
    # packet exists, so just keep a bounded recent-arrows list.
    info = parse_arrow_add(data)
    client.arrows.append(info)
    if len(client.arrows) > 64:
        client.arrows = client.arrows[-64:]
    if client.on_arrow_add:
        client.on_arrow_add(info)
    client._start_arrow_sim(info)


@handles(PacketID.PLO_HORSEADD)
def handle_horse_add(client, data):
    # Horse placed/mounted by another player (packet 17).
    info = parse_horse_add(data)
    level_name = client._pending_level_name or client._current_level_name
    client.horses.setdefault(level_name, {})[(info['x'], info['y'])] = info
    if client.on_horse_add:
        client.on_horse_add(info)


@handles(PacketID.PLO_HORSEDEL)
def handle_horse_del(client, data):
    # Horse removed (packet 18).
    info = parse_horse_del(data)
    level_name = client._pending_level_name or client._current_level_name
    client.horses.setdefault(level_name, {}).pop((info['x'], info['y']), None)
    if client.on_horse_del:
        client.on_horse_del(info['x'], info['y'])


@handles(PacketID.PLO_FIRESPY)
def handle_firespy(client, data):
    # Fire spy weapon effect from another player (packet 20).
    info = parse_firespy(data)
    if client.on_firespy:
        client.on_firespy(info)


@handles(PacketID.PLO_THROWCARRIED)
def handle_throw_carried(client, data):
    # Another player threw their carried object/npc (packet 21).
    info = parse_throwcarried(data)
    if client.on_throwcarried:
        client.on_throwcarried(info['owner_id'])


@handles(PacketID.PLO_PUSHAWAY)
def handle_push_away(client, data):
    # Push-away/knockback impulse (packet 38). See packets.parse_push_away
    # for the GCHAR decode this uses (GServer-v2's IEnums.h doc comment is
    # the only reference for this packet in this workspace).
    push = parse_push_away(data)
    if push and client.on_pushaway:
        client.on_pushaway(push['dx'], push['dy'])
