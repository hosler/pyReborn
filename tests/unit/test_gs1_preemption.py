from types import SimpleNamespace

from reborn_protocol.gs1.interp import PREEMPTED

from pyreborn.gs1_client import (
    ClientGS1,
    _GS1_PREEMPT_BOARD_WAIT_FRAMES,
)


def _client():
    return SimpleNamespace(
        player=SimpleNamespace(), npcs={},
        _current_level_name="test.nw",
        _tiles_level_name="test.nw",
        tiles=[0] * 4096,
    )


def _park(gs1, first_delay, advanced, key="weapon_probe"):
    def event():
        yield first_delay
        advanced.append("resumed")

    entry = {"npc_id": -1, "weapon_name": "probe"}
    gs1._drive(event(), SimpleNamespace(steps=0), key, entry, "playerenters")
    return key


def test_preempted_script_stays_active_and_cannot_start_a_duplicate():
    gs1 = ClientGS1(_client())
    increments = "\n".join("this.total += 1;" for _ in range(4_500))
    gs1.load_weapon("long", f"if (playerenters) {{ {increments} }}")
    key = "weapon_long"

    gs1.trigger_event("playerenters", key)

    assert len(gs1._coros) == 1
    assert key in gs1._active_coro_keys
    gs1.trigger_event("playerenters", key)
    assert len(gs1._coros) == 1

    while gs1._coros:
        gs1.process_coroutines(0.0)

    assert key not in gs1._active_coro_keys
    assert gs1._progs[key]["scopes"]["this"]["total"] == 4_500.0


def test_preempted_coroutine_waits_for_board_and_keeps_active_key(monkeypatch):
    gs1 = ClientGS1(_client())
    advanced = []
    key = _park(gs1, PREEMPTED, advanced)
    monkeypatch.setattr(gs1, "board_ready", lambda: False)

    gs1.process_coroutines(0.0)

    assert advanced == []
    assert len(gs1._coros) == 1
    assert key in gs1._active_coro_keys

    monkeypatch.setattr(gs1, "board_ready", lambda: True)
    gs1.process_coroutines(0.0)

    assert advanced == ["resumed"]
    assert gs1._coros == []
    assert key not in gs1._active_coro_keys


def test_sleep_coroutine_still_resumes_without_board(monkeypatch):
    gs1 = ClientGS1(_client())
    advanced = []
    key = _park(gs1, 0.0, advanced)
    monkeypatch.setattr(gs1, "board_ready", lambda: False)

    gs1.process_coroutines(0.0)

    assert advanced == ["resumed"]
    assert gs1._coros == []
    assert key not in gs1._active_coro_keys


def test_preempted_coroutine_resumes_when_board_wait_bound_expires(
        monkeypatch):
    gs1 = ClientGS1(_client())
    advanced = []
    key = _park(gs1, PREEMPTED, advanced)
    gs1._coros[0]["board_wait_frames"] = _GS1_PREEMPT_BOARD_WAIT_FRAMES
    monkeypatch.setattr(gs1, "board_ready", lambda: False)

    gs1.process_coroutines(0.0)

    assert advanced == ["resumed"]
    assert gs1._coros == []
    assert key not in gs1._active_coro_keys
