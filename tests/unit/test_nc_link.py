"""Offline tests for the NPC Control worker-link contract."""

from unittest.mock import Mock, patch

from pyreborn.nc_client import NCClient
from pyreborn import nc_link
from pyreborn.nc_link import CONNECTING, DENIED, READY, NCLink, NCSnapshot
from pyreborn.packets import PacketID


def test_commands_are_refused_and_not_queued_until_ready():
    link = NCLink("localhost", 14900, "staff", "pw")
    assert link.get_weapon_list() is False
    assert link.get_npc_script(4) is False
    assert link._commands.empty()


def test_start_without_password_denies_without_connecting():
    link = NCLink("localhost", 14900, "staff", "")
    with patch.object(NCClient, "connect") as connect:
        link.start()
    assert link.state == DENIED
    assert link.started is False
    connect.assert_not_called()


def test_snapshot_is_a_copy_not_a_live_view():
    link = NCLink("localhost", 14900, "staff", "pw")
    before = link.snapshot
    link._note("updated")
    assert before.notices == ()
    assert link.snapshot.notices == ("updated",)


def test_denied_link_is_never_retried():
    link = NCLink("localhost", 14900, "staff", "pw")
    link._set_state(DENIED, "no access")
    with patch("pyreborn.nc_link.threading.Thread") as thread:
        link.start()
    thread.assert_not_called()
    assert link.state == DENIED


def test_ready_command_is_queued_for_worker():
    link = NCLink("localhost", 14900, "staff", "pw")
    link._set_state(READY, "active")
    assert link.get_level_list() is True
    assert link._commands.qsize() == 1


def test_reconnect_clears_loaded_lists_on_the_same_link():
    link = NCLink("localhost", 14900, "staff", "pw")
    link._snapshot = NCSnapshot(
        state="closed", weapons=("old_weapon",), weapon_list_loaded=True,
        classes=("old_class",), class_list_loaded=True)

    with patch("pyreborn.nc_link.threading.Thread"):
        link.start()

    assert link.snapshot.state == CONNECTING
    assert link.snapshot.weapons == ()
    assert link.snapshot.weapon_list_loaded is False
    assert link.snapshot.classes == ()
    assert link.snapshot.class_list_loaded is False


def test_npc_attribute_replies_follow_fifo_request_ids():
    link = NCLink("localhost", 14900, "staff", "pw")
    client = nc_link._LinkedNCClient()
    link._set_state(READY, "active")
    with patch.object(client, "_send", return_value=True) as send:
        assert link.get_npc(10) is True
        assert link.get_npc(20) is True
        link._drain_commands(client)
        assert send.call_count == 1
        client._handle_packet(PacketID.PLO_NC_NPCATTRIBUTES, b"attrs-of-10")
        assert send.call_count == 2
        client._handle_packet(PacketID.PLO_NC_NPCATTRIBUTES, b"attrs-of-20")
    link._rebuild_snapshot(client)

    assert dict(link.snapshot.npc_attributes) == {
        10: ("attrs-of-10",),
        20: ("attrs-of-20",),
    }


def test_dead_npc_request_times_out_before_next_request_is_sent():
    link = NCLink("localhost", 14900, "staff", "pw")
    client = nc_link._LinkedNCClient()
    link._set_state(READY, "active")
    clock = [10.0]
    with patch.object(nc_link.time, "monotonic", side_effect=lambda: clock[0]), \
            patch.object(client, "_send", return_value=True) as send:
        assert link.get_npc(999) is True
        assert link.get_npc(20) is True
        link._drain_commands(client)
        assert send.call_count == 1
        clock[0] += nc_link.NC_REQUEST_TIMEOUT + 0.1
        client.pump_correlated_requests()
        assert send.call_count == 2
        client._handle_packet(PacketID.PLO_NC_NPCATTRIBUTES, b"attrs-of-20")

    link._rebuild_snapshot(client)
    assert dict(link.snapshot.npc_attributes) == {20: ("attrs-of-20",)}


def test_slow_npc_reply_within_timeout_remains_attributed():
    client = nc_link._LinkedNCClient()
    clock = [10.0]
    with patch.object(nc_link.time, "monotonic", side_effect=lambda: clock[0]), \
            patch.object(client, "_send", return_value=True):
        assert client.get_npc(42) is True
        clock[0] += nc_link.NC_REQUEST_TIMEOUT - 0.1
        client.pump_correlated_requests()
        client._handle_packet(PacketID.PLO_NC_NPCATTRIBUTES, b"slow-42")

    assert client.npc_attributes == {42: ("slow-42",)}


def test_failed_npc_send_stays_queued_for_the_next_pump():
    client = nc_link._LinkedNCClient()
    with patch.object(client, "_send", side_effect=(False, True)) as send:
        assert client.get_npc(42) is True
        assert list(client._npc_attribute_requests) == [42]
        assert client._npc_attribute_outstanding is None

        client.pump_correlated_requests()

    assert send.call_count == 2
    assert not client._npc_attribute_requests
    assert client._npc_attribute_outstanding is not None
    assert client._npc_attribute_outstanding[1] == 42


def test_failed_local_npc_send_stays_queued_for_the_next_pump():
    client = nc_link._LinkedNCClient()
    with patch.object(client, "_send", side_effect=(False, True)) as send:
        assert client.get_local_npcs("level-a.nw") is True
        assert list(client._local_npc_requests) == ["level-a.nw"]
        assert client._local_npc_outstanding is None

        client.pump_correlated_requests()

    assert send.call_count == 2
    assert not client._local_npc_requests
    assert client._local_npc_outstanding is not None
    assert client._local_npc_outstanding[1] == "level-a.nw"


def test_local_npc_replies_follow_fifo_request_levels():
    link = NCLink("localhost", 14900, "staff", "pw")
    client = nc_link._LinkedNCClient()
    link._set_state(READY, "active")
    with patch.object(client, "_send", return_value=True) as send:
        assert link.get_local_npcs("level-a.nw") is True
        assert link.get_local_npcs("level-b.nw") is True
        link._drain_commands(client)
        assert send.call_count == 1
        client._handle_packet(PacketID.PLO_NC_LEVELDUMP, b"dump-a")
        assert send.call_count == 2
        client._handle_packet(PacketID.PLO_NC_LEVELDUMP, b"dump-b")
    link._rebuild_snapshot(client)

    assert dict(link.snapshot.local_npcs) == {
        "level-a.nw": "dump-a",
        "level-b.nw": "dump-b",
    }


def test_new_client_after_disconnect_has_no_request_state():
    old_client = nc_link._LinkedNCClient()
    with patch.object(old_client, "_send", return_value=True):
        old_client.get_npc(10)
        old_client.get_npc(20)
        old_client.get_local_npcs("old.nw")

    replacement = nc_link._LinkedNCClient()
    assert replacement._npc_attribute_outstanding is None
    assert not replacement._npc_attribute_requests
    assert replacement._local_npc_outstanding is None
    assert not replacement._local_npc_requests


def test_restart_discards_commands_from_the_dead_session():
    link = NCLink("localhost", 14900, "staff", "pw")
    link._set_state(READY, "active")
    assert link.delete_npc(7) is True
    link._set_state("closed", "dropped")
    with patch("pyreborn.nc_link.threading.Thread") as thread:
        link.start()
    assert link._commands.empty()
    thread.return_value.start.assert_called_once()


def test_close_keeps_a_blocked_worker_stopped_and_tracked():
    link = NCLink("localhost", 14900, "staff", "pw")
    worker = Mock()
    worker.is_alive.return_value = True
    link._thread = worker
    old_stop = link._stop
    link.close(timeout=0)
    assert old_stop.is_set()
    assert link._thread is worker
    link.start()
    assert link._stop is old_stop


def test_stop_during_access_proof_closes_without_a_denial():
    link = NCLink("localhost", 14900, "staff", "pw")
    link._set_state("connecting", "proving access")
    stop_event = nc_link.threading.Event()
    client = Mock()
    client.connect.return_value = True
    client.login.return_value = True

    def stop_proof(_client, _stop_event):
        stop_event.set()
        return False

    with patch("pyreborn.nc_link._LinkedNCClient", return_value=client), \
            patch.object(link, "_await_nc_proof", side_effect=stop_proof):
        link._run(stop_event)
    assert link.state == "closed"
