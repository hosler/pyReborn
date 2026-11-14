"""Phase 4: the client keeps every visited level and warps back with its mod time.

The server marks a level visited per session and then streams no board, links
or signs for it, only a mod-time comparison. Reference client: TClient.cpp
sendLevelLinking sends PLI_LEVELWARPMOD (id 30) for a level it holds.

Mutations (each fails the named assertion):
  * _send_level_warp always sends PLI_LEVELWARP
    -> test_reentry_to_a_cached_level_sends_the_mod_time_warp (id == 30)
  * make _send_level_warp require ``mod_time`` (``if mod_time and ...``)
    -> test_a_held_level_with_mod_time_zero_still_sends_id_30
  * drop the ``level_name in self.levels`` test in _send_level_warp
    -> test_an_uncached_level_sends_the_plain_warp (id == 0)
  * give client_state.py ``self.levels = BoundedLRU(512)`` again
    -> test_the_level_store_does_not_evict (len == 600)
  * delete the ``client.links.pop`` line in handle_board_packet
    -> test_a_resent_board_replaces_the_cached_level (links == fresh link)
  * make handle_level_board (id 0) call handle_board_packet on empty data
    -> test_an_empty_level_board_keeps_the_cached_level (levels unchanged)
  * drop ``and not same_map`` in _send_level_warp (``if level_name in self.levels:``)
    -> test_a_warp_to_the_level_we_stand_in_on_the_gmap_stays_a_plain_warp
  * make warp_to_level send a warp for a hop inside the loaded gmap
    -> test_a_hop_inside_the_loaded_gmap_sends_props_and_no_warp
  * make _is_gmap_hop true for a level outside the grid
    -> test_a_warp_out_of_the_loaded_gmap_is_still_a_warp
  * drop the ``_restore_cached_layers`` call in warp_to_level
    -> test_extra_layers_survive_leaving_and_returning
  * key handle_level_mod_time on ``client.active_level`` again (drop
    ``level_state.streaming_level_name``)
    -> test_the_mod_time_is_stored_under_the_level_being_streamed and
       test_an_adjacent_preloads_mod_time_leaves_the_current_levels_alone
  * delete the ``client.level_state.level_layers.pop`` line in handle_board_packet
    -> test_a_resent_board_replaces_the_cached_level (layer store empty)
  * delete the ``client.sign_lists.pop`` line there
    -> test_a_resent_board_replaces_the_cached_level (sign_lists)
  * delete the ``client.board_layers.clear()`` line there
    -> test_a_resent_board_clears_the_live_layers_of_its_level
  * delete ``self.level_modtimes.clear()`` or ``level_layers.clear()`` in connect
    -> test_a_new_connection_forgets_mod_times_and_layers
  * make request_level send ``write_gint5(0)``
    -> test_request_level_sends_the_stored_mod_time
  * make _restore_failed_warp skip the layer restore, or the clear
    -> test_a_rejected_warp_restores_the_previous_levels_layers; skip the clear
       -> test_a_rejected_warp_leaves_no_layers_when_the_previous_level_had_none
"""

from pyreborn.packets import PacketBuilder, PacketID

TILES = [7] * 4096


def _packets(client, packet_id):
    return [data for pid, data in client._protocol.sent if pid == int(packet_id)]


def _warp(client, name, x, y):
    """warp_to_level, then hand what it sent to the in-process pygserver and
    deliver the answer (the fixture only dispatches replies sent during a pump)."""
    start = len(client._protocol.sent)
    assert client.warp_to_level(name, x, y)
    sent = client._protocol.sent[start:]

    async def dispatch(world):
        for packet_id, data in sent:
            await world.me._dispatch_packet(packet_id, data)
    client.server.run(dispatch)


def _visit(client, name, mod_time):
    """Warp to `name`, let pygserver stream it, then record the mod time the
    way a reference server's PLO_LEVELMODTIME would (pygserver sends none)."""
    _warp(client, name, 10.0, 12.0)
    assert client._pending_level_name == name
    client.feed(PacketID.PLO_LEVELMODTIME, PacketBuilder().write_gint5(mod_time).build())


def _board_bytes(tile):
    return bytes([tile & 0xFF, tile >> 8]) * 4096


def test_reentry_to_a_cached_level_sends_the_mod_time_warp(make_client):
    client = make_client(extra_levels={"other.nw": None})
    _visit(client, "other.nw", 1234567)
    _warp(client, "fixture.nw", 5.0, 5.0)
    client._protocol.sent.clear()
    client.warp_to_level("other.nw", 10.0, 12.0)
    assert len(_packets(client, PacketID.PLI_LEVELWARPMOD)) == 1
    assert not _packets(client, PacketID.PLI_LEVELWARP)
    expected = (PacketBuilder().write_gint5(1234567).build()
                + bytes([32 + 20, 32 + 24]) + b"other.nw")
    assert _packets(client, PacketID.PLI_LEVELWARPMOD)[0] == expected


def test_an_uncached_level_sends_the_plain_warp(make_client):
    client = make_client(extra_levels={"other.nw": None})
    client.level_modtimes["other.nw"] = 99     # a mod time alone is not a copy
    client._protocol.sent.clear()
    client.warp_to_level("other.nw", 10.0, 12.0)
    assert len(_packets(client, PacketID.PLI_LEVELWARP)) == 1
    assert not _packets(client, PacketID.PLI_LEVELWARPMOD)


def test_a_held_level_with_mod_time_zero_still_sends_id_30(make_client):
    client = make_client(extra_levels={"other.nw": None})
    _visit(client, "other.nw", 0)
    _warp(client, "fixture.nw", 5.0, 5.0)
    client._protocol.sent.clear()
    client.warp_to_level("other.nw", 10.0, 12.0)
    assert _packets(client, PacketID.PLI_LEVELWARPMOD) == [
        bytes([32] * 5) + bytes([32 + 20, 32 + 24]) + b"other.nw"]
    assert not _packets(client, PacketID.PLI_LEVELWARP)


def test_the_level_store_does_not_evict(make_client):
    client = make_client()
    held = len(client.levels)
    for i in range(600):
        client.levels[f"v{i}.nw"] = [i] * 4096
    assert len(client.levels) == held + 600
    assert client.levels["v0.nw"][0] == 0


def test_a_resent_board_replaces_the_cached_level(make_client):
    client = make_client()
    client._pending_level_name = "other.nw"
    client.levels["other.nw"] = list(TILES)
    client.links["other.nw"] = [{"stale": True}]
    client.signs["other.nw"] = {(1, 1): "old"}
    client.sign_lists["other.nw"] = [{"old": True}]
    client.level_state.level_layers["other.nw"] = {1: b"old-layer"}
    client.feed(PacketID.PLO_BOARDPACKET, _board_bytes(9))
    assert client.levels["other.nw"] == [9] * 4096
    assert "other.nw" not in client.signs
    assert "other.nw" not in client.sign_lists
    assert "other.nw" not in client.level_state.level_layers
    client.feed(PacketID.PLO_LEVELLINK, b"dest.nw 0 0 2 2 1 1")
    assert [link["dest_level"] for link in client.links["other.nw"]] == ["dest.nw"]


def test_an_empty_level_board_keeps_the_cached_level(make_client):
    client = make_client()
    client._pending_level_name = "other.nw"
    client.levels["other.nw"] = list(TILES)
    client.links["other.nw"] = [{"keep": True}]
    client.signs["other.nw"] = {(1, 1): "kept"}
    client.feed(PacketID.PLO_LEVELBOARD, b"")
    assert client.levels["other.nw"] == TILES
    assert client.links["other.nw"] == [{"keep": True}]
    assert client.signs["other.nw"] == {(1, 1): "kept"}


def test_extra_layers_survive_leaving_and_returning(make_client):
    client = make_client(extra_levels={"other.nw": None})
    _visit(client, "other.nw", 5)
    client._board_layers_level_name = "other.nw"
    client.board_layers[1] = b"layer-one"
    _warp(client, "fixture.nw", 5.0, 5.0)
    assert not client.board_layers
    client.warp_to_level("other.nw", 10.0, 12.0)
    assert client.board_layers == {1: b"layer-one"}


def test_a_hop_inside_the_loaded_gmap_sends_props_and_no_warp(make_client):
    """A held neighbour that is a cell of the loaded gmap: the reference sends
    no warp (TClient.cpp:1354-1358), only the position in the new cell's
    frame and the changed GMAPLEVELX (fixture_a is cell (0, 0), fixture_b is
    (1, 0)). Mutation: send the plain or the mod-time warp and this fails."""
    from offline_game import sent_player_props
    client = make_client(gmap=True)
    assert "fixture_b.nw" in client.levels          # preloaded neighbour
    client._protocol.sent.clear()
    assert client.warp_to_level("fixture_b.nw", 10.0, 12.0)
    assert not _packets(client, PacketID.PLI_LEVELWARP)
    assert not _packets(client, PacketID.PLI_LEVELWARPMOD)
    (pairs,) = sent_player_props(client._protocol.sent)
    props = dict(pairs)
    assert (props[78], props[79]) == (10.0, 12.0)
    assert props[43] == 1 and 44 not in props


def test_a_warp_to_the_level_we_stand_in_on_the_gmap_stays_a_plain_warp(make_client):
    """Not a hop: the reference's same-level branch is unclear, so it keeps
    the plain warp."""
    client = make_client(gmap=True)
    client._protocol.sent.clear()
    assert client.warp_to_level("fixture_a.nw", 10.0, 12.0)
    assert len(_packets(client, PacketID.PLI_LEVELWARP)) == 1
    assert not _packets(client, PacketID.PLI_LEVELWARPMOD)


def test_a_warp_out_of_the_loaded_gmap_is_still_a_warp(make_client):
    """A level that is no cell of the gmap is warped to, never hopped to."""
    client = make_client(gmap=True, extra_levels={"elsewhere.nw": None})
    client._protocol.sent.clear()
    assert client.warp_to_level("elsewhere.nw", 10.0, 12.0)
    assert len(_packets(client, PacketID.PLI_LEVELWARP)) == 1
    assert not _packets(client, PacketID.PLI_PLAYERPROPS)


def test_a_resent_board_clears_the_live_layers_of_its_level(make_client):
    client = make_client()
    client._pending_level_name = "other.nw"
    client._board_layers_level_name = "other.nw"
    client.board_layers[1] = b"old-layer"
    client.feed(PacketID.PLO_BOARDPACKET, _board_bytes(9))
    assert client.board_layers == {}


def _mod_time(value):
    return PacketBuilder().write_gint5(value).build()


def test_the_mod_time_is_stored_under_the_level_being_streamed(make_client):
    # Reference order (PlayerClient.cpp:1513-1555): LEVELNAME, ..., MODTIME,
    # SETACTIVELEVEL. The mod time arrives while the previous level is active.
    client = make_client(extra_levels={"other.nw": None})
    here = client.active_level = client._current_level_name
    client.level_modtimes[here] = 100
    client.feed(PacketID.PLO_LEVELNAME, b"other.nw")
    client.feed(PacketID.PLO_LEVELMODTIME, _mod_time(900))
    client.feed(PacketID.PLO_SETACTIVELEVEL, b"other.nw")
    assert client.level_modtimes["other.nw"] == 900
    assert client.level_modtimes[here] == 100


def test_an_adjacent_preloads_mod_time_leaves_the_current_levels_alone(make_client):
    client = make_client(extra_levels={"other.nw": None})
    here = client.active_level = client._current_level_name
    client.level_modtimes[here] = 100
    client._adjacent_level_requests.add("other.nw")
    client.feed(PacketID.PLO_LEVELNAME, b"other.nw")
    client.feed(PacketID.PLO_LEVELMODTIME, _mod_time(5000))
    assert client.level_modtimes["other.nw"] == 5000
    assert client.level_modtimes[here] == 100
    assert client.active_level == here


def test_a_new_connection_forgets_mod_times_and_layers(make_client, monkeypatch):
    client = make_client()
    client.level_modtimes["x.nw"] = 7
    client.level_state.level_layers["x.nw"] = {1: b"layer"}
    monkeypatch.setattr(client._protocol, "connect", lambda: True, raising=False)
    client.connect()
    assert client.level_modtimes == {}
    assert client.level_state.level_layers == {}


def test_request_level_sends_the_stored_mod_time(make_client):
    client = make_client()
    client.level_modtimes["near.nw"] = 4321
    client._protocol.sent.clear()
    assert client.request_level("near.nw")
    assert _packets(client, PacketID.PLI_ADJACENTLEVEL) == [
        _mod_time(4321) + b"near.nw"]


def test_a_rejected_warp_restores_the_previous_levels_layers(make_client):
    client = make_client(extra_levels={"other.nw": None})
    here = client._current_level_name
    client.level_state.level_layers[here] = {2: b"home-layer"}
    client._board_layers_level_name = "other.nw"
    client.board_layers[1] = b"target-layer"
    client._warp_fallback = (here, 5.0, 6.0)
    client._awaiting_warp_confirm = "other.nw"
    client._restore_failed_warp("test")
    assert client.board_layers == {2: b"home-layer"}
    assert client._board_layers_level_name == here


def test_a_rejected_warp_leaves_no_layers_when_the_previous_level_had_none(make_client):
    client = make_client(extra_levels={"other.nw": None})
    here = client._current_level_name
    client._board_layers_level_name = "other.nw"
    client.board_layers[1] = b"target-layer"
    client._warp_fallback = (here, 5.0, 6.0)
    client._awaiting_warp_confirm = "other.nw"
    client._restore_failed_warp("test")
    assert client.board_layers == {}
