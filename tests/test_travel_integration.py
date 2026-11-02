"""Walk a real fixture world's directed door using the LocalWorld server."""

import pytest

from game_tester.world_graph import WorldGraph


@pytest.mark.integration
def test_travel_through_fixture_link(bots, pygserver, monkeypatch):
    bot = bots(names=['travelbot'])[0]
    # This fixture has only a return link from the QA room to the start level.
    # Position the test in that room, then prohibit cheat warps during travel.
    assert bot.warp_to('qa_testlevel.nw', 8, 8)
    bot.update(1.0)
    assert bot.level == 'qa_testlevel.nw'
    monkeypatch.setattr(bot, 'warp_to', lambda *a, **kw: pytest.fail('travel must walk'))
    graph = WorldGraph.from_world_dir(pygserver.world_dir)
    assert bot.travel_to('onlinestartlocal.nw', graph=graph, timeout=20)
    assert bot.level == 'onlinestartlocal.nw'
    assert any(action.action == 'auto_link_warp' for action in bot.action_log)
