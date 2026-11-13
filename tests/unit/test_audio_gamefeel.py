import pytest

from offline_game import ITEM_GREENRUPEE, spy


@pytest.fixture
def low_hearts_game(make_game, monkeypatch):
    """A real offline game with one heart of three and a recording sound
    manager (the real ``play`` is replaced: the beeps are what is asserted)."""
    game = make_game(hearts=1.0, me={"max_hearts": 3.0})
    game.beeps = []
    monkeypatch.setattr(game.sound_mgr, "play",
                        lambda *args, **kwargs: game.beeps.append((args, kwargs)))
    game._low_hearts_warning_enabled = True
    return game


def test_low_hearts_warning_repeats_once_per_second_and_is_soft(low_hearts_game):
    game = low_hearts_game
    assert game._update_low_hearts_warning(10.0) is True
    assert game._update_low_hearts_warning(10.9) is False
    assert game._update_low_hearts_warning(11.0) is True
    assert game.beeps[0] == (("beep.wav",), {"volume": 0.35})


def test_low_hearts_warning_resets_immediately_when_inactive(low_hearts_game):
    game = low_hearts_game
    game._update_low_hearts_warning(10.0)
    game.client.player.hearts = 2.0
    assert game._update_low_hearts_warning(10.1) is False
    assert game._low_hearts_next_beep == 0.0
    game.client.player.hearts = 1.0
    assert game._update_low_hearts_warning(10.2) is True

    game.client._protocol.connected = False
    assert game._update_low_hearts_warning(10.3) is False
    assert game._low_hearts_next_beep == 0.0


def test_low_hearts_warning_ignores_dead_and_single_heart_players(low_hearts_game):
    game = low_hearts_game
    game.client.player.hearts = 0
    assert game._update_low_hearts_warning(1.0) is False
    game.client.player.hearts = 1
    game.client.player.max_hearts = 1
    assert game._update_low_hearts_warning(2.0) is False


def test_local_item_pickup_request_plays_sound_for_present_item(make_game,
                                                                monkeypatch):
    game = make_game(player_xy=(10.0, 12.0),
                     items=[(10.5, 12.5, ITEM_GREENRUPEE)])
    pickups = spy(monkeypatch, game.client, "pickup_item")
    plays = spy(monkeypatch, game.sound_mgr, "play")

    assert game._pickup_ground_item() is True
    assert pickups == [((None, None), {})]
    assert plays == [(("item.wav",), {})]
