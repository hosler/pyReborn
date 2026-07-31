"""GameBot's action registry and the playtest daemon's transport over it.

These pin the daemon's /act contract - command names, parameter coercion and
the warp guard - because LLM playtest agents drive that endpoint from prompts
written against it (game_tester/PLAYTEST_BRIEF.md).
"""

import pytest

from game_tester.game_bot import GameBot
from game_tester.playtest_daemon import do_act


class RecordingBot:
    """Records which bot method the registry dispatched to, with what."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(**kwargs):
            self.calls.append((name, kwargs))
            return f"{name}-ok"
        return record


def act(query):
    """Drive do_act() with a parsed-query-string-shaped dict."""
    bot = RecordingBot()
    result = do_act(bot, {key: [value] for key, value in query.items()})
    return bot.calls, result


def only_call(query):
    calls, _ = act(query)
    assert len(calls) == 1, calls
    return calls[0]


def test_registry_covers_every_documented_command():
    assert set(GameBot.ACTIONS) == {
        'move', 'walkto', 'say', 'sword', 'bomb', 'arrow', 'grab', 'attack',
        'pm', 'warp', 'open_chest', 'pickup'}


def test_every_registered_action_names_a_real_bot_method():
    for action in GameBot.ACTIONS.values():
        assert callable(getattr(GameBot, action.method)), action.name


def test_unknown_command_is_reported_not_raised():
    calls, result = act({'cmd': 'fly'})
    assert calls == []
    assert result == "unknown cmd 'fly'"


def test_result_is_the_bot_methods_return_value():
    assert act({'cmd': 'grab'})[1] == "grab-ok"


def test_move_coerces_ints_and_defaults_to_standing_still():
    assert only_call({'cmd': 'move', 'dx': '1', 'dy': '-1'}) == (
        'move', {'dx': 1, 'dy': -1, 'follow_links': True})
    assert only_call({'cmd': 'move'}) == (
        'move', {'dx': 0, 'dy': 0, 'follow_links': True})


@pytest.mark.parametrize("raw,expected", [('0', False), ('false', False),
                                          ('False', False), ('1', True),
                                          ('yes', True)])
def test_follow_links_flag(raw, expected):
    _, kwargs = only_call({'cmd': 'move', 'follow_links': raw})
    assert kwargs['follow_links'] is expected


def test_walkto_requires_coordinates_and_pins_the_timeout():
    assert only_call({'cmd': 'walkto', 'x': '10.5', 'y': '2'}) == (
        'walk_to', {'target_x': 10.5, 'target_y': 2.0, 'follow_links': True,
                    'timeout': 8.0})
    # Missing x/y is a caller error the daemon turns into a 400, not a bot
    # walking to (0, 0) - see Handler.do_GET's ValueError/TypeError branch.
    with pytest.raises(TypeError):
        act({'cmd': 'walkto', 'y': '2'})


def test_say_goes_through_the_echo_check_and_defaults_to_empty():
    assert only_call({'cmd': 'say', 'msg': 'hi'}) == (
        'say_and_wait_echo', {'message': 'hi'})
    assert only_call({'cmd': 'say'}) == ('say_and_wait_echo', {'message': ''})


def test_sword_and_arrow_direction_defaults_to_the_bots_facing():
    assert only_call({'cmd': 'sword'}) == ('sword_attack', {'direction': None})
    assert only_call({'cmd': 'sword', 'dir': '2'}) == (
        'sword_attack', {'direction': 2})
    assert only_call({'cmd': 'arrow', 'dir': '3'}) == (
        'shoot_arrow', {'direction': 3})


def test_bomb_power_defaults_to_one():
    assert only_call({'cmd': 'bomb'}) == ('drop_bomb', {'power': 1})
    assert only_call({'cmd': 'bomb', 'power': '3'}) == ('drop_bomb', {'power': 3})


def test_attack_and_pm_require_a_player_id():
    assert only_call({'cmd': 'attack', 'pid': '7'}) == (
        'attack_player', {'player_id': 7})
    assert only_call({'cmd': 'pm', 'pid': '7'}) == (
        'send_pm', {'player_id': 7, 'message': ''})
    with pytest.raises(TypeError):
        act({'cmd': 'attack'})


def test_warp_defaults_to_30_30_unforced():
    assert only_call({'cmd': 'warp', 'level': 'qa.nw'}) == (
        'warp_to_checked',
        {'level_name': 'qa.nw', 'x': 30.0, 'y': 30.0, 'force': False})
    assert only_call({'cmd': 'warp', 'level': 'qa.nw', 'force': '1'})[1][
        'force'] is True


@pytest.mark.parametrize("cmd,method", [('open_chest', 'open_chest'),
                                        ('pickup', 'pickup_item')])
def test_chest_and_pickup_coords_are_optional(cmd, method):
    assert only_call({'cmd': cmd}) == (method, {'x': None, 'y': None})
    assert only_call({'cmd': cmd, 'x': '5', 'y': '6'}) == (
        method, {'x': 5.0, 'y': 6.0})
    # Tile 0 is a real coordinate, not "auto-target": the daemon's original
    # `float(x) if x else None` tested the query STRING, and "0" is truthy.
    assert only_call({'cmd': cmd, 'x': '0', 'y': '0'}) == (
        method, {'x': 0.0, 'y': 0.0})


# --------------------------------------------------------------------------
# Warp guard (moved out of the daemon into GameBot.warp_to_checked)
# --------------------------------------------------------------------------

class StubClient:
    def __init__(self, tiles):
        self.tiles = tiles
        self.levels = {}
        self._current_level_name = "qa.nw"
        self.in_gmap_segment = False
        self.gmap_grid = {}
        self.is_gmap = False
        self.x = self.y = 30.0


def _guard_bot(tiles):
    bot = GameBot("qa_warp_bot", "127.0.0.1", 1)
    bot.client = StubClient(tiles)
    bot.warp_to = lambda level_name, x, y: ("warped", level_name, x, y)
    return bot


def test_warp_guard_refuses_a_blocking_destination():
    bot = _guard_bot([18] * 4096)  # 18 is a TileType-blocking wall tile
    result = bot.warp_to_checked("qa.nw", 30.0, 30.0)
    assert result == ("warp destination (30.0,30.0) on 'qa.nw' is blocking "
                      "(tile=18); pass force=1 to override")


def test_warp_guard_allows_a_clear_destination():
    bot = _guard_bot([0] * 4096)
    assert bot.warp_to_checked("qa.nw", 30.0, 30.0) == (
        "warped", "qa.nw", 30.0, 30.0)


def test_warp_guard_is_skipped_when_forced():
    bot = _guard_bot([18] * 4096)
    assert bot.warp_to_checked("qa.nw", 30.0, 30.0, force=True) == (
        "warped", "qa.nw", 30.0, 30.0)


def test_warp_guard_lets_an_unknown_level_through():
    """Nothing to check against for a level we have never streamed."""
    bot = _guard_bot([18] * 4096)
    assert bot.warp_to_checked("never_visited.nw", 5.0, 5.0) == (
        "warped", "never_visited.nw", 5.0, 5.0)
