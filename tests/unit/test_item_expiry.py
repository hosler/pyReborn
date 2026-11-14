"""Level items expire on the client's own timer (library layer, no pygame).

The reference server removes a dropped item after 8.2 s without sending
PLO_ITEMDEL (GServer-v2 Level.cpp:711-716), so each client ages its copy: 164
ticks of 0.05 s from receipt, then deletes it (reference client
TServerLevel.cpp:1400-1470, putExtra 0xa4 at TClient.cpp:3685). The tests drive
an injected clock; nothing sleeps.
"""
from unittest.mock import Mock

from pyreborn import Client, ground_items
from pyreborn.packets import PacketID

# half-tile gchar bytes for tile (7.0, 9.0), item id 33 (bluerupee)
ADD = bytes((46, 50, 33))
DEL = bytes((46, 50))
KEY = (7.0, 9.0)


def make_client():
    client = Client("localhost", 14900)
    client._current_level_name = "A.nw"
    client._level_scope = "A.nw"
    clock = [100.0]
    client.item_clock = lambda: clock[0]
    client.on_item = Mock()
    return client, clock


def test_lifetime_is_164_ticks_of_a_twentieth_of_a_second():
    assert abs(ground_items.ITEM_LIFETIME_TICKS * ground_items.TICK - 8.2) < 1e-9


def test_item_is_pruned_when_its_lifetime_runs_out():
    client, clock = make_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    assert client.items_in_level("A.nw") == {KEY: "bluerupee"}
    clock[0] += 8.2                       # tick 164 -> time 0: still there
    assert client.expire_items() == []
    assert KEY in client.items_in_level("A.nw")
    clock[0] += 0.06                      # one tick later: time < 0
    assert client.expire_items() == [("A.nw", 7.0, 9.0, "bluerupee")]
    assert client.items_in_level("A.nw") == {}
    assert client.item_stamps == {}
    client.on_item.assert_called_with(7.0, 9.0, "bluerupee", False)


def _headless_frames(client):
    """Drive the client's frame time by hand: returns a function that
    advances it, so update() runs its own ticks (Clock.pump_headless)."""
    frame = [0.0]
    client.clock.set_sources(source=lambda: frame[0])

    def advance(seconds):
        frame[0] += seconds
    return advance


def test_update_drives_the_expiry_so_headless_bots_see_it(monkeypatch):
    client, clock = make_client()
    client._protocol = Mock()
    client._protocol.recv_packets.return_value = []
    advance = _headless_frames(client)
    client.update(timeout=0)              # the headless pump starts measuring
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    clock[0] += 9.0
    advance(client.clock.tick_length)     # one tick of frame time
    client.update(timeout=0)
    assert client.items_in_level("A.nw") == {}


def test_itemdel_for_an_already_expired_item_is_a_no_op():
    client, clock = make_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    clock[0] += 9.0
    client.expire_items()
    client.on_item.reset_mock()
    client._handle_packet(PacketID.PLO_ITEMDEL, DEL)
    client._handle_packet(PacketID.PLO_ITEMDEL, DEL)
    assert client.items_in_level("A.nw") == {}
    client.on_item.assert_not_called()


def test_itemdel_before_expiry_removes_it_and_its_stamp():
    client, clock = make_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    client._handle_packet(PacketID.PLO_ITEMDEL, DEL)
    assert client.items_in_level("A.nw") == {}
    assert client.item_stamps == {}
    client.on_item.assert_called_with(7.0, 9.0, "bluerupee", False)


def test_a_redrop_at_the_same_spot_gets_a_fresh_timer():
    client, clock = make_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    clock[0] += 6.0
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    clock[0] += 6.0                       # 12 s after the first, 6 s after the second
    client.expire_items()
    assert KEY in client.items_in_level("A.nw")


def test_items_present_on_entry_start_their_timer_on_receipt():
    client, clock = make_client()
    clock[0] = 500.0
    client._level_scope = client._current_level_name = "B.nw"
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)        # entry stream, long after the drop
    clock[0] += 5.0
    client.expire_items()
    assert KEY in client.items_in_level("B.nw")
    clock[0] += 3.3
    client.expire_items()
    assert client.items_in_level("B.nw") == {}


def test_levels_age_independently():
    client, clock = make_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    clock[0] += 5.0
    # the player moves to B: items are filed under the player's own level
    # (the reference drops items of any other, TClient.cpp:3665)
    client._level_scope = client._current_level_name = "B.nw"
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    clock[0] += 4.0
    client.expire_items()
    assert client.items_in_level("A.nw") == {}
    assert KEY in client.items_in_level("B.nw")


def test_an_unstamped_local_item_starts_its_clock_at_first_sight():
    client, clock = make_client()
    client.items.setdefault("A.nw", {})[KEY] = "heart"      # a GS1 or local drop
    client.expire_items()
    clock[0] += 5.0
    client.expire_items()
    assert KEY in client.items_in_level("A.nw")
    clock[0] += 4.0
    client.expire_items()
    assert client.items_in_level("A.nw") == {}


def test_the_drawn_age_follows_the_receipt_stamp():
    client, clock = make_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    clock[0] += 3.0
    owner = type("Owner", (), {})()
    owner.client = client
    ages = ground_items.item_ages(owner, "A.nw", client.items_in_level("A.nw"), clock[0])
    assert ages[KEY] == 3.0


def test_warp_forgets_the_stamps_with_the_items():
    client, clock = make_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    assert client.item_stamps
    client._handle_packet(PacketID.PLO_LEVELNAME, b"B.nw")     # a real level change
    assert client._current_level_name == "B.nw"
    assert client.items == {}
    assert client.item_stamps == {}
    client.expire_items()
    assert client.item_stamps == {}


def test_a_client_warp_forgets_the_stamps_too():
    client, clock = make_connected_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    assert client.warp_to_level("B.nw", 10.0, 10.0)
    assert client.items == {} and client.item_stamps == {}


def test_a_gmap_segment_crossing_keeps_the_items_and_their_stamps():
    client, clock = make_client()
    client.gmap_width = 2
    client.gmap_height = 1
    client.gmap_grid = {(0, 0): "A.nw", (1, 0): "B.nw"}
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    stamps = dict(client.item_stamps)
    client._handle_packet(PacketID.PLO_LEVELNAME, b"B.nw")     # neighbour segment streamed in
    assert client.items_in_level("A.nw") == {KEY: "bluerupee"}
    assert client.item_stamps == stamps


def test_a_reconnect_starts_with_no_items_or_stamps():
    client, clock = make_client()
    client._protocol = Mock()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    client.connect()
    assert client.items == {}
    assert client.item_stamps == {}


def test_a_second_drop_on_a_tile_replaces_and_restamps_the_first():
    # one tile holds one item: the key is the position, so the later drop wins
    client, clock = make_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    clock[0] += 4.0
    client._handle_packet(PacketID.PLO_ITEMADD, bytes((46, 50, 34)))   # a different item id
    bucket = client.items_in_level("A.nw")
    assert len(bucket) == 1 and KEY in bucket and bucket[KEY] != "bluerupee"
    assert client.item_stamps[("A.nw", KEY)] == clock[0]


# --- PLI_ITEMDEL on timer expiry (reference client TServerLevel.cpp:1469) ----

def make_connected_client():
    client, clock = make_client()
    client._protocol = Mock()
    client._protocol.send_packet.return_value = True
    client._protocol.connected = True
    client._authenticated = True
    return client, clock


def sent_itemdels(client):
    return [c.args[1] for c in client._protocol.send_packet.call_args_list
            if c.args[0] == PacketID.PLI_ITEMDEL]


def test_expiry_sends_one_itemdel_with_the_item_position():
    client, clock = make_connected_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    clock[0] += 8.2
    client.expire_items()
    assert sent_itemdels(client) == []                   # not yet expired
    clock[0] += 0.06
    client.expire_items()
    client.expire_items()
    client.expire_items()
    assert sent_itemdels(client) == [DEL]                # (7.0, 9.0) -> bytes 46, 50


def test_update_sends_the_itemdel_for_headless_bots():
    client, clock = make_connected_client()
    client._protocol.recv_packets.return_value = []
    advance = _headless_frames(client)
    client.update(timeout=0)
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    clock[0] += 9.0
    advance(client.clock.tick_length)
    client.update(timeout=0)
    advance(client.clock.tick_length)
    client.update(timeout=0)
    assert sent_itemdels(client) == [DEL]


def test_no_itemdel_after_a_server_itemdel():
    client, clock = make_connected_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    client._handle_packet(PacketID.PLO_ITEMDEL, DEL)
    clock[0] += 9.0
    client.expire_items()
    assert sent_itemdels(client) == []


def test_level_change_sends_no_burst_for_the_old_levels_items():
    client, clock = make_connected_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    client._handle_packet(PacketID.PLO_ITEMADD, bytes((48, 52, 33)))
    client._handle_packet(PacketID.PLO_LEVELNAME, b"B.nw")        # the real level change
    assert client.items == {}
    clock[0] += 9.0
    client.expire_items()
    assert sent_itemdels(client) == []


def test_a_bucket_for_another_level_is_pruned_silently():
    client, clock = make_connected_client()
    client._level_scope = client._current_level_name = "B.nw"
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)      # stored under B.nw
    client._level_scope = client._current_level_name = "A.nw"   # then the player leaves
    clock[0] += 9.0
    assert client.expire_items() == [("B.nw", 7.0, 9.0, "bluerupee")]
    assert sent_itemdels(client) == []


def test_no_itemdel_when_not_connected():
    client, clock = make_connected_client()
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    client._protocol.connected = False
    clock[0] += 9.0
    assert client.expire_items() == [("A.nw", 7.0, 9.0, "bluerupee")]
    assert sent_itemdels(client) == []


# --- the taker removes its own copy; the server does not echo (reference client
# TServerLevel.cpp:1453-1457: sendTakeExtra then the extra is deleted) ----------

def sent_itemtakes(client):
    return [c.args[1] for c in client._protocol.send_packet.call_args_list
            if c.args[0] == PacketID.PLI_ITEMTAKE]


def make_taker():
    client, clock = make_connected_client()
    client.ghost_mode = False
    client.player.x, client.player.y = 7.0, 9.0
    client._handle_packet(PacketID.PLO_ITEMADD, ADD)
    client.on_item.reset_mock()
    return client, clock


def test_pickup_removes_the_item_and_its_stamp_when_the_take_is_sent():
    client, clock = make_taker()
    assert client.pickup_item(7.0, 9.0)
    assert sent_itemtakes(client) == [DEL]
    assert client.items_in_level("A.nw") == {}
    assert client.item_stamps == {}
    client.on_item.assert_called_once_with(7.0, 9.0, "bluerupee", False)


def test_pickup_at_the_player_position_removes_the_item_there():
    client, clock = make_taker()
    assert client.pickup_item()
    assert client.items_in_level("A.nw") == {}


def test_pickup_leaves_other_items_alone():
    client, clock = make_taker()
    client._handle_packet(PacketID.PLO_ITEMADD, bytes((48, 52, 33)))
    client.pickup_item(7.0, 9.0)
    assert list(client.items_in_level("A.nw")) == [(8.0, 10.0)]


def test_no_expiry_itemdel_after_a_pickup():
    client, clock = make_taker()
    client.pickup_item(7.0, 9.0)
    clock[0] += 9.0
    client.expire_items()
    assert sent_itemdels(client) == []


def test_late_echo_after_a_pickup_is_a_no_op_with_no_second_callback():
    client, clock = make_taker()
    client.pickup_item(7.0, 9.0)
    client._handle_packet(PacketID.PLO_ITEMDEL, DEL)       # an older server echoes
    assert client.on_item.call_count == 1
    assert client.items_in_level("A.nw") == {}


def test_a_failed_send_keeps_the_item():
    client, clock = make_taker()
    client._protocol.send_packet.return_value = False
    assert not client.pickup_item(7.0, 9.0)
    assert KEY in client.items_in_level("A.nw")
    assert client.item_stamps


def test_pickup_of_an_unknown_spot_still_sends_and_calls_nothing_back():
    client, clock = make_taker()
    client.pickup_item(20.0, 20.0)
    assert len(sent_itemtakes(client)) == 1
    assert KEY in client.items_in_level("A.nw")
    client.on_item.assert_not_called()
