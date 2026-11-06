"""Server synchronization for script-written local player stats."""

from reborn_protocol import PLPROP


# Reference setters mark writable stats changed, then testProperties sends them:
# Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:8277-8283, :8313-8345,
# :8378-8397, :2459-2474;
# Preagonal/FourPlay/quattroplay/src/TClient.cpp:4231-4246.
# The reconstructed currency setter (:8303-8306) only stores the value; its
# script binding is TServerPlayerProperties.cpp:127-130, :672-676. Currency
# must also use PLAYERPROPS, as reported in live reference testing.
# Do not infer script writability from a native setter: fullhearts/maxhp and
# swordpower/shieldpower have null script setters in
# Preagonal/FourPlay/quattroplay/src/TServerPlayerProperties.cpp:357-361,
# :582-586, :690-712. Position continues through movement synchronization.
_STAT_PROPS = {
    "rupees": PLPROP.RUPEESCOUNT,
    "hearts": PLPROP.CURPOWER,
    "arrows": PLPROP.ARROWSCOUNT,
    "bombs": PLPROP.BOMBSCOUNT,
    "glove_power": PLPROP.GLOVEPOWER,
    "ap": PLPROP.ALIGNMENT,
    "mp": PLPROP.MAGICPOINTS,
}


def sync_script_player_stat(client, player, attr, previous):
    """Send the stored value after a changed local-player stat assignment."""
    if player is not getattr(client, "player", None) or attr not in _STAT_PROPS:
        return
    value = getattr(player, attr)
    if value == previous:
        return
    sender = getattr(client, "_send_appearance_prop", None)
    if sender is not None:
        sender(_STAT_PROPS[attr], int(value * 2) if attr == "hearts" else int(value))
