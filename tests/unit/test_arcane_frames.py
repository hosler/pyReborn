"""Arcane flight stays in world space while reports use level-local points."""

from types import SimpleNamespace

import pytest

from pyreborn.gs1_client import ClientGS1

from .sibling_repos import require_workspace_dir


KEY = "weapon_ArcaneBolt"
WEAPON = require_workspace_dir("funtimes-pygserver") / "weapons/weapon-ArcaneBolt.txt"


def bolt_runtime(x=84, y=84, direction=3):
    client = SimpleNamespace(
        x=x, y=y, player=SimpleNamespace(direction=direction, account="mage"),
        npcs={}, players={}, baddies={}, weapons={}, connected=False,
        is_gmap=True, gmap_grid={(1, 1): "chicken1.nw"},
        _current_level_name="chicken1.nw",
    )
    rt = ClientGS1(client)
    rt.tile_source = lambda x, y: 0x1FF
    actions = []
    rt.on_triggeraction = lambda *args: actions.append(args)
    source = WEAPON.read_text().split("//#CLIENTSIDE", 1)[1].rsplit("SCRIPTEND", 1)[0]
    rt.load_weapon("ArcaneBolt", source)
    assert rt._progs[KEY]["prog"] is not None
    return rt, client, actions


@pytest.mark.parametrize("kind,tail", [
    ("baddy", "baddy,0,22,20"), ("npc", "npc,0,22,20"),
    ("player", "player,1,23.5,22"),
])
def test_gmap_carrier_is_local_while_flight_and_wire_position_stay_world(kind, tail):
    rt, client, actions = bolt_runtime()
    if kind == "baddy":
        client.baddies[0] = {"x": 87, "y": 84, "power": 2}
    elif kind == "npc":
        client.npcs[10] = {"x": 86, "y": 84, "image": "arcane_bolt.png"}
    else:
        client.players[2] = {"x": 23, "y": 20, "account": "target"}
    rt.trigger_event("weaponfired", name=KEY)
    image = rt._weapon_imgs[KEY][200]
    assert (image["x"], image["y"]) == (85, 84)
    rt.process_timeouts(0.05)
    assert (image["x"], image["y"]) == (86, 84)
    assert actions == [(86.0, 84.0, "serverside,ArcaneBolt,hit," + tail, -1)]
    assert 200 not in rt._weapon_imgs[KEY]


@pytest.mark.parametrize("x,y,direction,spawn_crosses", [
    (127, 84, 3, True), (64, 84, 1, True),
    (84, 127, 2, True), (84, 64, 0, True),
    (0, 20, 1, True), (20, 0, 0, True),
    (126, 84, 3, False), (65, 84, 1, False),
    (84, 126, 2, False), (84, 65, 0, False),
])
def test_bolt_stops_before_spawning_or_advancing_into_another_segment(
        x, y, direction, spawn_crosses):
    rt, _, actions = bolt_runtime(x, y, direction)
    rt.trigger_event("weaponfired", name=KEY)
    if not spawn_crosses:
        assert 200 in rt._weapon_imgs[KEY]
        rt.process_timeouts(0.05)
    assert 200 not in rt._weapon_imgs.get(KEY, {})
    assert rt._progs[KEY]["scopes"]["this"]["live"] is False
    assert not actions


def test_player_stand_point_cannot_wrap_into_the_next_segment():
    rt, client, actions = bolt_runtime(x=125)
    client.players[2] = {"x": 63, "y": 20, "account": "target"}
    rt.trigger_event("weaponfired", name=KEY)
    rt.process_timeouts(0.05)
    assert not actions
    assert 200 not in rt._weapon_imgs[KEY]
