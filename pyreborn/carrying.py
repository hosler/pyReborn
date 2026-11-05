"""Carry presentation shared by local and remote players."""

import math

from .throwing import carry_code, carry_object

# TInitStatics.cpp:1174-1181: probe-side origins and lift interpolation.
CARRY_OFFSETS = ((0, -2), (-2, 0), (0, 2), (2, 0))
LIFT_DELTA = (0.0, 0.9, 1.5, 1.8, 2.0)
BOMB_SPRITES = (0x41, 0x42, 0x141, 0x42, 0x15b, 0x15c)  # TInitStatics.cpp:1139.
BOMB_CODES = tuple(carry_code(sprite) for sprite in BOMB_SPRITES)


def bomb_sprite(bomb, now):
    if 'sprite' in bomb:
        return bomb['sprite']
    # TServerLevel.cpp:1106-1108,1322-1328: initial sprite, then fuse flicker.
    power = max(1, min(3, bomb.get('power', 1)))
    ticks = max(0, math.ceil((bomb['time'] + bomb.get('fuse_time', 3) - now) / .05 - 1e-8) - 1)
    return BOMB_SPRITES[power - 1] if ticks > 29 else BOMB_SPRITES[ticks % 2 + (power - 1) * 2]


def carry_position(direction, counter=None):
    # TServerPlayer.cpp:1110-1156: counter is the current gani step's subframe.
    if counter is None:
        return .5, -1.375, None
    frame = max(0, min(4, 4 - counter))
    dx, dy = CARRY_OFFSETS[direction]
    x, y = .5 + dx, 1 + dy
    shadow_y = y
    if direction == 1:
        x += 2 - LIFT_DELTA[frame]
        y -= LIFT_DELTA[4 - frame]
    elif direction == 0:
        shadow_y += LIFT_DELTA[4 - frame]
    elif direction == 2:
        y += LIFT_DELTA[frame] - 2 - LIFT_DELTA[4 - frame]
        shadow_y -= LIFT_DELTA[4 - frame]
    else:
        x += LIFT_DELTA[frame] - 2
        y -= LIFT_DELTA[4 - frame]
    return x, y, shadow_y + 1.25


def carry_tiles(code):
    carried = carry_object(code)
    return carried[1] if carried else ()


def standing_carry(game):
    # lift.gani:119: SETBACKTO carrystill; older asset sets can omit it.
    if game.gani_parser.parse('carrystill') is not None:
        return 'carrystill'
    request = getattr(game, '_request_asset', None)
    if request is not None:
        request('carrystill.gani')
    return 'carry'


def publish_carry(client, code):
    from reborn_protocol import PLPROP
    client.player.carry_sprite = code
    if code == -1:
        from .packets import PacketID
        if getattr(client, 'connected', False) and getattr(client, '_authenticated', False):
            client._protocol.send_packet(PacketID.PLI_PLAYERPROPS,
                                         bytes([PLPROP.CARRYSPRITE + 32, 0x1f]))
        return
    send = getattr(client, '_send_appearance_prop', None)
    if send is not None:
        send(PLPROP.CARRYSPRITE, code)
