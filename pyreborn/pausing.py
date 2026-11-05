"""Pause input and status, TPlayer.cpp:2141, :2170-2196, :2683-2692."""

from reborn_protocol import PLPROP, PLSTATUS


def toggle_pause(game):
    player = game.client.player
    gs2 = getattr(game.client, 'gs2_host', None)
    flags = getattr(gs2, 'player_object', None)
    level = getattr(gs2, 'level_object', None)
    # Only ENTERING pause is gated; a paused player can always release it,
    # even after a server-side HP set left them dead while paused.
    if (not player.status & PLSTATUS.PAUSED and (
            player.hearts <= 0 or player.action_mode == 11
            or getattr(game.client, 'ghost_mode', False)
            or (flags is not None and flags.get('disablepause'))
            or (level is not None and level.get('isnopausezone')))):
        return
    player.status ^= PLSTATUS.PAUSED
    game.is_moving = False
    game.client._send_appearance_prop(PLPROP.STATUS, player.status)


def can_heal(player, disabled=False):
    # changePower2, TPlayer.cpp:5731: no healing at alignment <=39.
    return disabled or player.ap > 39
