"""Event waits share the runtime's cooperative sleep scheduler."""
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from reborn_protocol.gs2 import GS2Object
from pyreborn.gs2_client import ClientGS2
import pyreborn.gs2_client.runtime as runtime_module

VECTOR = (Path(__file__).parents[3] / "reborn-protocol/tests/fixtures/gs2/vm/08_waitfor.gs2bc")


def _runtime():
    runtime = ClientGS2()
    vm = runtime.load_bytecode("weapon", "waiter", VECTOR.read_bytes())
    return runtime, vm


def _wait(runtime, vm, target=None, event="ReAdY", timeout=0.5):
    runtime._run(vm, "awaitEvent", vm.this if target is None else target,
                 event, timeout)
    assert vm.this.get("continued") is None
    assert runtime._event_waiters


def _done(runtime, vm, value):
    assert vm.this.get("result") == value
    assert vm.this.get("saved") == 7.0
    assert vm.this.get("continued") == 1.0
    assert runtime._coros == []
    assert runtime._event_waiters == {}
    assert runtime._active_coro_keys == set()


@pytest.mark.parametrize("delivery", ["schedule", "trigger", "server"])
def test_same_object_event_wakes_while_coroutine_key_is_active(delivery):
    runtime, vm = _runtime()
    _wait(runtime, vm, event="onReady", timeout=5.0)
    assert runtime._timeout_key(vm) in runtime._active_coro_keys
    if delivery == "schedule":
        runtime.schedule_event(vm, 0.01, "onReady", [42.0])
        runtime.process_timeouts(0.1)
    elif delivery == "trigger":
        caller = runtime.load_bytecode("weapon", "caller", VECTOR.read_bytes())
        caller.call("fire", vm.this, "onReady")
    else:
        runtime.trigger_weapon_event("waiter", "onReady", 42.0)
    assert vm.this.get("handled") == 42.0
    runtime.process_coroutines(0.0)
    _done(runtime, vm, 1.0)


def test_queued_events_drain_when_handler_parks_in_event_wait():
    runtime, vm = _runtime()
    target = GS2Object()

    def sleeping_handler():
        yield 0.01

    runtime._drive(sleeping_handler(), vm, runtime._timeout_key(vm), "sleeping")
    runtime._run(vm, "awaitEvent", target, "signal", 5.0)
    runtime._run(vm, "onReady", 42.0)
    assert len(runtime._pending_events[runtime._timeout_key(vm)]) == 2
    runtime.process_coroutines(0.02)
    assert vm.this.get("handled") == 42.0
    assert vm.this.get("continued") is None
    assert runtime._pending_events == {}
    runtime.wake_event_waiters(runtime.event_waiters(target, "signal"))
    runtime.process_coroutines(0.0)
    _done(runtime, vm, 1.0)


def test_event_before_timeout_runs_handler_then_resumes_with_one():
    runtime, vm = _runtime()
    _wait(runtime, vm)
    runtime.trigger_weapon_event("waiter", "onReady", 42.0)
    assert vm.this.get("handled") == 42.0
    assert vm.this.get("continued") is None
    runtime.process_coroutines(0.1)
    _done(runtime, vm, 1.0)
    assert vm.this.get("handler_seen") == 42.0


def test_timeout_and_late_trigger_do_not_resurrect_continuation():
    runtime, vm = _runtime()
    _wait(runtime, vm)
    runtime.process_coroutines(0.51)
    _done(runtime, vm, 0.0)
    runtime.trigger_weapon_event("waiter", "onReady", 42.0)
    runtime.process_coroutines(0.1)
    _done(runtime, vm, 0.0)


@pytest.mark.parametrize("event", ["ready", "onREADY", "NoHandler"])
def test_object_trigger_wakes_case_insensitive_wait_even_without_handler(event):
    runtime, vm = _runtime()
    _wait(runtime, vm, event=event)
    vm.call("fire", vm.this, event)
    runtime.process_coroutines(0.01)
    _done(runtime, vm, 1.0)


def test_wrong_object_and_wrong_event_do_not_wake_waiter():
    runtime, vm = _runtime()
    target = GS2Object()
    _wait(runtime, vm, target)
    vm.call("fire", GS2Object(), "ready")
    vm.call("fire", target, "other")
    runtime.process_coroutines(0.1)
    assert vm.this.get("continued") is None
    vm.call("fire", target, "ready")
    runtime.process_coroutines(0.1)
    _done(runtime, vm, 1.0)


@pytest.mark.parametrize("qualified", [False, True])
def test_scheduled_event_wakes_waiter(qualified):
    runtime, vm = _runtime()
    target = GS2Object() if qualified else vm.this
    _wait(runtime, vm, target)
    runtime.host.call_builtin(vm, "scheduleevent", [0.05, "ready", 42.0],
                              obj=target if qualified else None)
    runtime.process_timeouts(0.1)
    runtime.process_coroutines(0.1)
    _done(runtime, vm, 1.0)


@pytest.mark.parametrize("destroy_owner", [False, True])
def test_destroy_cancels_wait_without_resuming(destroy_owner):
    runtime, vm = _runtime()
    target = GS2Object()
    _wait(runtime, vm, target)
    runtime.host.call_builtin(vm, "destroy", [], obj=vm.this if destroy_owner else target)
    vm.call("fire", target, "ready")
    runtime.process_coroutines(1.0)
    assert vm.this.get("continued") is None
    assert runtime._event_waiters == {}
    assert runtime._coros == []


@pytest.mark.parametrize("timeout,event", [(0.0, "ready"), (-1.0, "ready"), (1.0, "")])
def test_invalid_wait_returns_zero_immediately(timeout, event):
    runtime, vm = _runtime()
    runtime._run(vm, "awaitEvent", vm.this, event, timeout)
    _done(runtime, vm, 0.0)


def test_session_reset_discards_waits():
    runtime, vm = _runtime()
    _wait(runtime, vm)
    runtime.reset_session()
    runtime.trigger_weapon_event("waiter", "onReady")
    runtime.process_coroutines(1.0)
    assert vm.this.get("continued") is None
    assert runtime._event_waiters == {}


def test_cancellation_during_scheduler_pass_does_not_restore_parked_frame():
    runtime, vm = _runtime()
    _wait(runtime, vm)
    killer = runtime.load_bytecode("weapon", "killer", VECTOR.read_bytes())

    def destroy_waiter():
        yield 0.01
        runtime.host.call_builtin(killer, "destroy", [], obj=vm.this)

    runtime._drive(destroy_waiter(), killer, runtime._timeout_key(killer), "destroy")
    runtime.process_coroutines(0.02)
    runtime.process_coroutines(1.0)
    assert vm.this.get("continued") is None
    assert runtime._coros == []
    assert runtime._event_waiters == {}
    assert runtime._active_coro_keys == set()


def test_wall_clock_does_not_expire_wait_before_timer_pump(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("time.monotonic", lambda: clock[0])
    runtime, vm = _runtime()
    _wait(runtime, vm)
    clock[0] = 11.0
    runtime.process_coroutines(0.0)
    assert vm.this.get("continued") is None
    runtime.trigger_weapon_event("waiter", "onReady")
    runtime.process_coroutines(0.0)
    _done(runtime, vm, 1.0)


def test_reentrant_coroutine_pump_preserves_dt_for_waits_and_sleep():
    runtime, vm = _runtime()
    _wait(runtime, vm)
    sleeper = runtime.load_bytecode("weapon", "sleeper", VECTOR.read_bytes())

    def sleeping_handler():
        yield 0.5
        sleeper.this.set("finished", 1.0)

    def pumping_handler():
        yield 0.01
        runtime.process_coroutines(0.5)

    runtime._drive(sleeping_handler(), sleeper, runtime._timeout_key(sleeper), "sleep")
    runtime._drive(pumping_handler(), sleeper, runtime._timeout_key(sleeper), "pump")
    runtime.process_coroutines(0.01)
    _done(runtime, vm, 0.0)
    assert sleeper.this.get("finished") == 1.0
    assert runtime._wait_time == pytest.approx(0.51)


@pytest.mark.parametrize("delivery", ["public", "catcher", "dotted"])
def test_non_suspendable_wait_warns_once_per_script_and_event(delivery, caplog):
    runtime, vm = _runtime()
    target = runtime.gui.create_control("GuiControl", "Signal")
    if delivery == "catcher":
        runtime.host.call_builtin(vm, "catchevent", [target, "onAction", "awaitEvent"])
        fire = lambda event: target.fire_action(event, 5.0)
    elif delivery == "dotted":
        vm.functions["signal.onaction"] = vm.functions["awaitevent"]
        fire = lambda event: target.fire_action(target, event, 5.0)
    else:
        fire = lambda event: runtime.call_public_event(vm, "awaitEvent", target, event, 5.0)
    with caplog.at_level(logging.WARNING):
        fire("onReady")
        fire("onReady")
        fire("onOther")
        second = runtime.load_bytecode("weapon", "second", VECTOR.read_bytes())
        runtime.call_public_event(second, "awaitEvent", target, "onReady", 5.0)
    messages = [record.getMessage() for record in caplog.records
                if "non-suspendable context" in record.getMessage()]
    assert len(messages) == 3
    assert sum("waitfor(onReady) in a non-suspendable context returned 0" in m
               for m in messages) == 2
    assert vm.this.get("result") == 0.0
    assert second.this.get("result") == 0.0
    assert runtime._event_waiters == {}


def test_script_trigger_prefers_last_other_owner_and_returns_result():
    runtime, caller = _runtime()
    target = GS2Object()
    calls = []
    first = SimpleNamespace(has_function=lambda event: event == "onReady",
                            call=lambda *args: calls.append("first"))

    def last_call(event, *args):
        calls.append((event, args))
        assert caller.this.get("continued") is None
        return 17.0

    last = SimpleNamespace(has_function=lambda event: event == "onReady", call=last_call)
    target.script_vms = [first, last, caller]
    _wait(runtime, caller, target, "onReady")
    result = runtime.host.call_builtin(caller, "trigger", ["onReady", 7.0], obj=target)
    assert result == 17.0
    assert calls == [("onReady", (7.0,))]
    runtime.process_coroutines(0.0)
    _done(runtime, caller, 1.0)


def test_script_trigger_preserves_handler_exceptions_and_wakes_after_call():
    runtime, vm = _runtime()
    target = GS2Object()

    def failing_call(*args):
        raise ValueError("handler failed")

    target.script_vms = [SimpleNamespace(has_function=lambda event: True, call=failing_call)]
    _wait(runtime, vm, target)
    with pytest.raises(ValueError, match="handler failed"):
        runtime.host.call_builtin(vm, "trigger", ["onReady"], obj=target)
    runtime.process_coroutines(0.0)
    _done(runtime, vm, 1.0)


def test_gui_trigger_fires_action_and_wait_alone_does_not_handle_input():
    runtime, vm = _runtime()
    target = runtime.gui.create_control("GuiControl", "Signal")
    _wait(runtime, vm, target, "onAction")
    assert target.fire_action(7.0) is False
    runtime.process_coroutines(0.0)
    _done(runtime, vm, 1.0)
    got = []
    target.set("onaction", lambda value: got.append(value))
    assert runtime.host.call_builtin(vm, "trigger", [7.0], obj=target) == 1.0
    assert got == [7.0]


@pytest.mark.parametrize("event", ["onUpdate", "onTimeout", "onNoHandler"])
def test_builtin_dispatch_wakes_wait_without_event_handler(event):
    runtime, vm = _runtime()
    _wait(runtime, vm, event=event)
    if event == "onTimeout":
        runtime.host.call_builtin(vm, "settimer", [0.01])
        runtime.process_timeouts(0.1)
    elif event == "onUpdate":
        runtime.process_timeouts(0.1)
    else:
        runtime.trigger_event(event)
    runtime.process_coroutines(0.1)
    _done(runtime, vm, 1.0)


@pytest.mark.parametrize("delivery", ["builtin", "trigger", "schedule", "destroy"])
def test_gui_control_waits(delivery):
    pytest.importorskip("pygame")
    runtime, vm = _runtime()
    target = runtime.gui.create_control("GuiControl", "Signal")
    _wait(runtime, vm, target, "onAction" if delivery == "trigger" else "ready")
    if delivery == "builtin":
        target.fire_event("onReady")
    elif delivery == "trigger":
        vm.call("fire", target, "ready")
    elif delivery == "schedule":
        runtime.host.call_builtin(vm, "scheduleevent", [0.01, "ready"], obj=target)
        runtime.process_timeouts(0.1)
    else:
        runtime.gui.destroy(target)
    runtime.process_coroutines(0.1)
    if delivery == "destroy":
        assert vm.this.get("continued") is None
        assert runtime._event_waiters == {}
        assert runtime._coros == []
    else:
        _done(runtime, vm, 1.0)
