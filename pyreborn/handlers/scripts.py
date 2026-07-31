"""The client handles weapon and script transport.

This transport adds and removes weapons. It carries GS1 weapon scripts and GS2
bytecode, which the client only parses and stores. Inbound triggeractions fire
the attached GS1 and GS2 hosts.
"""

from ..packets import (
    PacketID,
    parse_gani_script,
    parse_loadgani,
    parse_loadscript,
    parse_npc_bytecode,
    parse_npcweapondel,
    parse_npcweaponscript,
    parse_triggeraction_in,
    parse_weapon_add,
)
from .registry import handles


@handles(PacketID.PLO_NPCWEAPONADD)
def handle_npc_weapon_add(client, data):
    # PLO_NPCWEAPONADD (33) - weapon being added to player
    weapon = parse_weapon_add(data)
    if weapon and weapon.get('name'):
        weapon.setdefault('image', '')
        weapon.setdefault('script', '')
        client.weapons[weapon['name']] = weapon
        # Callback for weapon added
        if client.on_weapon_add:
            client.on_weapon_add(weapon['name'], weapon)


@handles(PacketID.PLO_TRIGGERACTION)
def handle_triggeraction(client, data):
    # Inbound triggeraction (packet 48) - from serverside scripts
    # (triggerClient) or relayed from other players.
    info = parse_triggeraction_in(data)
    if client.on_triggeraction:
        client.on_triggeraction(info)
    # Route into the GS1 host (if attached) so clientside scripts with
    # a matching `if (action<name>)` handler run, mirroring the real
    # client. Action name = first CSV token.
    if client.gs1_host is not None and info['action']:
        try:
            action_name = info['action'].split(',', 1)[0].strip()
            if action_name:
                client.gs1_host.trigger_event('action' + action_name)
        except Exception:
            pass
    # GS2 counterpart: fire onAction<name>(params...) on loaded VMs.
    if client.gs2_host is not None and info['action']:
        try:
            client.gs2_host.handle_triggeraction(info['action'])
        except Exception:
            pass


@handles(PacketID.PLO_NPCBYTECODE)
def handle_npc_bytecode(client, data):
    # Compiled NPC script (packet 131, arrives via RAWDATA).
    info = parse_npc_bytecode(data)
    client.gs2_bytecode['npc'][info['npc_id']] = info['bytecode']
    if client.on_gs2_bytecode:
        client.on_gs2_bytecode('npc', info['npc_id'], info['bytecode'])


@handles(PacketID.PLO_GANISCRIPT)
def handle_gani_script(client, data):
    # Compiled gani script (packet 134, arrives via RAWDATA).
    info = parse_gani_script(data)
    client.gs2_bytecode['gani'][info['gani']] = info['bytecode']
    if client.on_gs2_bytecode:
        client.on_gs2_bytecode('gani', info['gani'], info['bytecode'])


@handles(PacketID.PLO_NPCWEAPONSCRIPT)
def handle_npc_weapon_script(client, data):
    # Weapon (or unknown-class stub) bytecode (packet 140).
    info = parse_npcweaponscript(data)
    kind = info['type'] if info['type'] in client.gs2_bytecode else 'weapon'
    if info['name']:
        client.gs2_bytecode[kind][info['name']] = info['bytecode']
        client.gs2_script_headers[info['name']] = info
    if client.on_gs2_bytecode:
        client.on_gs2_bytecode(kind, info['name'], info['bytecode'])


@handles(PacketID.PLO_LOADGANI)
def handle_load_gani(client, data):
    # Load-gani instruction (packet 195).
    info = parse_loadgani(data)
    if info['gani']:
        client.gani_setbackto[info['gani']] = info['setbackto']


@handles(PacketID.PLO_LOADSCRIPT)
def handle_load_script(client, data):
    # Script header announcement / class bytecode (packet 197).
    info = parse_loadscript(data)
    if info['name']:
        client.gs2_script_headers[info['name']] = info
        if info['bytecode']:
            kind = info['type'] if info['type'] in client.gs2_bytecode else 'class'
            client.gs2_bytecode[kind][info['name']] = info['bytecode']
            if kind == 'class' and client.gs1_host is not None:
                try:
                    client.gs1_host.receive_class_source(
                        info['name'], info['bytecode'])
                except Exception:
                    pass
            if client.on_gs2_bytecode:
                client.on_gs2_bytecode(kind, info['name'], info['bytecode'])
        elif info['type'] == 'weapon':
            # Header-only announcement (Weapon.cpp
            # registerWeaponWithPlayer): the server waits for the
            # client to pull the bytecode with PLI_UPDATESCRIPT (a
            # real client skips the pull only on a local-cache CRC
            # hit; we keep no disk cache, so always fetch). Once per
            # (name, crc) so a re-announced unchanged script doesn't
            # re-request forever.
            req_key = (info['name'], info['crc'])
            if req_key not in client._gs2_requested:
                if client.request_weapon_bytecode(info['name']):
                    client._gs2_requested.add(req_key)


@handles(PacketID.PLO_NPCWEAPONDEL)
def handle_npc_weapon_del(client, data):
    # Remove a weapon from inventory (packet 34).
    name = parse_npcweapondel(data)
    client.weapons.pop(name, None)


@handles(PacketID.PLO_CLEARWEAPONS)
def handle_clear_weapons(client, data):
    # Clear all weapons before the server resends the list (packet 194).
    client.weapons.clear()
