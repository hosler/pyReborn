"""GS1-driven board edits and hurt reach add_listener subscribers.

These emission sites used to fetch the `on_*` slot and call it directly, so a
subscriber that only used `add_listener` heard nothing."""
from pyreborn.gs1_client import board_tile_write, board_update_region
from .test_board_scripting import _client
from .test_gs1_combat_family import _fake_connected_client, _npc_gs1


def test_listener_only_subscriber_hears_gs1_tile_write():
    c = _client(board_tile=7)
    heard = []
    c.add_listener("on_board_modify", heard.append)
    assert c.on_board_modify is None
    assert board_tile_write(c, 10, 5, 684) is True
    assert heard == [{"layer": 0, "x": 10, "y": 5, "width": 1, "height": 1,
                      "tiles": [684]}]


def test_slot_and_listener_both_hear_a_region_update():
    c = _client(board_tile=7)
    slot, heard = [], []
    c.on_board_modify = slot.append
    c.add_listener("on_board_modify", heard.append)
    board_update_region(c, 8, 4, 2, 3)
    assert len(slot) == 1 and slot == heard
    assert (slot[0]["x"], slot[0]["y"], slot[0]["width"],
            slot[0]["height"]) == (8, 4, 2, 3)


def test_listener_only_subscriber_hears_gs1_hurt():
    client = _fake_connected_client()
    client.player.hearts = 3.0
    heard = []
    client.add_listener("on_hurt", lambda *a: heard.append(a))
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { hurt 2; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert len(heard) == 1 and heard[0][1] == 1.0
