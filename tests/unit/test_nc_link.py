"""Offline tests for the NPC Control worker-link contract."""

from unittest.mock import Mock, patch

from pyreborn.nc_client import NCClient
from pyreborn import nc_link
from pyreborn.nc_link import DENIED, READY, NCLink


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
