from types import SimpleNamespace
from unittest.mock import Mock

from pyreborn.game.setup import SetupMixin
from pyreborn.game.actions import ActionsMixin


class _Harness(SetupMixin):
    def __init__(self):
        self.client = SimpleNamespace(
            connected=True,
            player=SimpleNamespace(hearts=1.0, max_hearts=3.0),
        )
        self.sound_mgr = Mock()
        self._low_hearts_warning_enabled = True


def test_low_hearts_warning_repeats_once_per_second_and_is_soft():
    game = _Harness()
    assert game._update_low_hearts_warning(10.0) is True
    assert game._update_low_hearts_warning(10.9) is False
    assert game._update_low_hearts_warning(11.0) is True
    assert game.sound_mgr.play.call_args_list[0].args == ("beep.wav",)
    assert game.sound_mgr.play.call_args_list[0].kwargs == {"volume": 0.35}


def test_low_hearts_warning_resets_immediately_when_inactive():
    game = _Harness()
    game._update_low_hearts_warning(10.0)
    game.client.player.hearts = 2.0
    assert game._update_low_hearts_warning(10.1) is False
    assert game._low_hearts_next_beep == 0.0
    game.client.player.hearts = 1.0
    assert game._update_low_hearts_warning(10.2) is True

    game.client.connected = False
    assert game._update_low_hearts_warning(10.3) is False
    assert game._low_hearts_next_beep == 0.0


def test_low_hearts_warning_ignores_dead_and_single_heart_players():
    game = _Harness()
    game.client.player.hearts = 0
    assert game._update_low_hearts_warning(1.0) is False
    game.client.player.hearts = 1
    game.client.player.max_hearts = 1
    assert game._update_low_hearts_warning(2.0) is False


def test_local_item_pickup_request_plays_sound_for_present_item():
    game = SimpleNamespace(
        client=SimpleNamespace(
            player=SimpleNamespace(x=10.0, y=12.0),
            items={(10.5, 12.5): 'greenrupee'},
            pickup_item=Mock(return_value=True),
        ),
        sound_mgr=Mock(),
    )

    assert ActionsMixin._pickup_ground_item(game) is True
    game.client.pickup_item.assert_called_once_with(None, None)
    game.sound_mgr.play.assert_called_once_with("item.wav")
