"""Walk-over pickup against the live client model (no mock client).

`Client.pickup_item` removes the item from the local dict as the take is sent,
so the pickup sound must be chosen from the kind read BEFORE the call (a
KeyError here crashed a rendered frame)."""
from unittest.mock import Mock

from pyreborn.packets import PacketID

GREENRUPEE = 0      # reported with PLI_ITEMTAKE
HEART = 5
GLOVE = 6           # absorbed locally, never reported


def _takes(game):
    return [1 for pid, _ in game.client._protocol.sent
            if pid == int(PacketID.PLI_ITEMTAKE)]


def _stand_on(make_game, kind):
    game = make_game(player_xy=(14.0, 14.0), items=[(14.0, 14.0, kind)])
    game.sound_mgr = Mock()
    return game


def test_reported_item_is_taken_once_and_plays_its_sound(make_game):
    game = _stand_on(make_game, GREENRUPEE)
    level = game.client.get_current_level_from_position()
    assert game.client.items_in_level(level)
    game.frames(40)                       # past the four-tick grace period
    assert len(_takes(game)) == 1
    assert game.client.items_in_level(level) == {}
    game.sound_mgr.play.assert_called_once_with("item.wav")
    game.frames(10)
    assert len(_takes(game)) == 1


def test_heart_uses_the_heart_sound(make_game):
    game = _stand_on(make_game, HEART)
    game.frames(40)
    assert len(_takes(game)) == 1
    game.sound_mgr.play.assert_called_once_with("item2.wav")


def test_absorbed_kind_is_removed_locally_without_a_take(make_game):
    game = _stand_on(make_game, GLOVE)
    level = game.client.get_current_level_from_position()
    game.frames(40)
    assert _takes(game) == []
    assert game.client.items_in_level(level) == {}
    game.sound_mgr.play.assert_called_once()
