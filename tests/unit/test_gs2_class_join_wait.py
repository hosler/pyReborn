"""Late class joins suspend an event until the requested bytecode arrives."""

import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../reborn-protocol"))

import pyreborn.gs2_client.runtime as runtime_module
from pyreborn.gs2_client import ClientGS2


COMPILER = (Path(__file__).parents[3] / "reborn-protocol" / "tests" /
            "tools" / "gs2test")


def _compile(source):
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "script.gs2"
        output_path = Path(temp_dir) / "script.gs2bc"
        source_path.write_text(source)
        result = subprocess.run(
            [str(COMPILER), str(source_path), "-o", str(output_path)],
            capture_output=True, text=True, timeout=30)
        assert output_path.exists(), result.stderr
        return output_path.read_bytes()


def _client():
    client = SimpleNamespace(
        connected=False,
        gs2_bytecode={"class": {}, "weapon": {}, "npc": {}, "gani": {}},
    )
    client.requested_classes = []
    client.request_class_bytecode = client.requested_classes.append
    return client


WEAPON = _compile("""
function onCreated() {
  join("gui_factory");
  makeControl();
  this.finished = 1;
}
function onLater() { this.later = 1; }
""")

CLASS = _compile("""
public function makeControl() {
  new GuiControl("ControlCanvas") { width = 64; height = 32; }
}
""")

TWO_JOINS = _compile("""
function onCreated() {
  join("first_factory");
  join("second_factory");
  makeControl();
  this.finished = 1;
}
""")

SYNC_HELPER = _compile("""
public function doSomething() {
  temp.result = join("late_class");
  this.result = temp.result;
  this.finished = 1;
}
""")

SYNC_OUTER = _compile("""
function onCreated() {
  ("helper").doSomething();
  this.finished = 1;
}
""")

SYNC_CACHED_HELPER = _compile("""
public function buildNow() {
  join("gui_factory");
  makeControl();
  this.finished = 1;
}
""")

SYNC_CACHED_OUTER = _compile("""
function onCreated() {
  CachedHelper = this;
}
public function runNow() {
  ("cached-helper").buildNow();
}
""")

SLEEP_THEN_JOIN = _compile("""
function onSleepThenJoin() {
  sleep(0.01);
  join("late_class");
  this.finished = 1;
}
""")

PARKED_LATE_JOIN = _compile("""
function onCreated() {
  join("late_class");
  this.finished = 1;
}
""")

GATED_TARGET = _compile("""
function onCreated() { join("gui_helpers"); }
public function startGame(value) {
  addExitButton();
  this.order.add(value);
}
""")

GATED_CLASS = _compile("""
public function addExitButton() { this.classresolved = 1; }
""")

GATED_CALLER = _compile("""
public function invoke(value) { TargetObject.startGame(value); }
""")

SHOWTOP_SCRIPT = _compile("""
function onCreated() {
  new GuiControl("First") { visible = false; }
  new GuiControl("Buried") { visible = false; }
  new GuiTextEditCtrl("Focusable") { tabable = true; }
  Buried.addcontrol(Focusable);
  Buried.showtop();
}
""")


def test_late_class_arrival_resumes_before_post_join_statements():
    client = _client()
    runtime = ClientGS2(client)
    weapon = runtime.load_bytecode("weapon", "menu", WEAPON)

    assert "controlcanvas" not in runtime.gui._named
    assert weapon.this.get("finished") is None
    assert client.requested_classes == ["gui_factory"]

    runtime.load_bytecode("class", "gui_factory", CLASS)

    assert "controlcanvas" in runtime.gui._named
    assert runtime.gui.roots
    assert weapon.this.get("finished") == 1.0


def test_missing_class_times_out_once_and_later_events_run(monkeypatch, caplog):
    monkeypatch.setattr(runtime_module, "CLASS_JOIN_WAIT_PUMPS", 2)
    client = _client()
    runtime = ClientGS2(client)
    weapon = runtime.load_bytecode("weapon", "menu", WEAPON)

    with caplog.at_level(logging.WARNING):
        runtime.process_coroutines(0.0)
        runtime.process_coroutines(0.0)
        runtime.process_coroutines(0.0)

    warnings = [record for record in caplog.records
                if "gui_factory" in record.getMessage()
                and "timed out" in record.getMessage()]
    assert len(warnings) == 1
    assert weapon.this.get("finished") == 1.0
    assert runtime.trigger_weapon_event("menu", "onLater")
    assert weapon.this.get("later") == 1.0


def test_cached_class_join_remains_synchronous():
    client = _client()
    runtime = ClientGS2(client)
    runtime.load_bytecode("class", "gui_factory", CLASS)
    weapon = runtime.load_bytecode("weapon", "menu", WEAPON)

    assert weapon.this.get("finished") == 1.0
    assert "controlcanvas" in runtime.gui._named
    assert runtime._coros == []
    assert client.requested_classes == []


def test_sync_cross_vm_join_attaches_cached_class_within_same_call():
    client = _client()
    runtime = ClientGS2(client)
    client.gs2_bytecode["class"]["GUI_Factory"] = CLASS
    helper = runtime.load_bytecode("weapon", "cached-helper", SYNC_CACHED_HELPER)
    outer = runtime.load_bytecode("weapon", "outer", SYNC_CACHED_OUTER)

    assert helper.joined == []
    assert outer.call("runNow") == 0.0

    assert helper.this.get("finished") == 1.0
    assert "controlcanvas" in runtime.gui._named
    assert [joined._gs2_key for joined in helper.joined] == ["gui_factory"]
    assert runtime._coros == []


def test_event_with_two_missing_joins_waits_for_both_classes():
    client = _client()
    runtime = ClientGS2(client)
    weapon = runtime.load_bytecode("weapon", "menu", TWO_JOINS)

    runtime.load_bytecode("class", "first_factory", CLASS)
    assert client.requested_classes == ["first_factory", "second_factory"]
    assert weapon.this.get("finished") is None

    runtime.load_bytecode("class", "second_factory", CLASS)
    assert weapon.this.get("finished") == 1.0
    assert "controlcanvas" in runtime.gui._named


def test_session_reset_discards_parked_join_frames():
    runtime = ClientGS2(_client())
    runtime.load_bytecode("weapon", "menu", WEAPON)
    assert runtime._coros
    assert runtime._pending_joins

    runtime.reset_session()

    assert runtime._coros == []
    assert runtime._active_coro_keys == set()
    assert runtime._pending_events == {}
    assert runtime._pending_joins == {}


def test_missing_join_from_nested_sync_frame_never_leaks_wait_value():
    client = _client()
    runtime = ClientGS2(client)
    helper = runtime.load_bytecode("weapon", "helper", SYNC_HELPER)
    outer = runtime.load_bytecode("weapon", "outer", SYNC_OUTER)

    result = helper.this.get("result")
    assert isinstance(result, (int, float, str, list))
    assert "_ClassJoinWait" not in type(result).__name__
    assert helper.this.get("finished") == 1.0
    assert outer.this.get("finished") == 1.0
    assert client.requested_classes == ["late_class"]

    runtime.load_bytecode("class", "late_class", CLASS)
    assert any(joined._gs2_key == "late_class" for joined in helper.joined)


def test_cached_join_during_coroutine_pump_is_not_reentrant(caplog):
    client = _client()
    runtime = ClientGS2(client)
    parked = runtime.load_bytecode("weapon", "parked", PARKED_LATE_JOIN)
    joining = runtime.load_bytecode("weapon", "joining", SLEEP_THEN_JOIN)
    runtime.trigger_weapon_event("joining", "onSleepThenJoin")
    client.gs2_bytecode["class"]["late_class"] = CLASS

    with caplog.at_level(logging.WARNING):
        runtime.process_coroutines(0.05)

    assert not any("generator already executing" in record.getMessage()
                   for record in caplog.records)
    assert joining.this.get("finished") == 1.0
    assert parked.this.get("finished") == 1.0
    assert runtime._coros == []
    assert runtime._active_coro_keys == set()


def test_cross_vm_event_waits_for_join_then_resolves_class_function():
    runtime = ClientGS2(_client())
    target = runtime.load_bytecode("weapon", "target", GATED_TARGET)
    caller = runtime.load_bytecode("weapon", "caller", GATED_CALLER)
    runtime.globals_store["targetobject"] = target.this

    assert caller.call("invoke", 7.0) == 0.0
    assert target.this.get("classresolved") is None
    assert target.this.get("order") in (None, [])

    runtime.load_bytecode("class", "gui_helpers", GATED_CLASS)

    assert target.this.get("classresolved") == 1.0
    assert target.this.get("order") == [7.0]


def test_multiple_join_gated_events_preserve_arrival_order():
    runtime = ClientGS2(_client())
    target = runtime.load_bytecode("weapon", "target", GATED_TARGET)
    caller = runtime.load_bytecode("weapon", "caller", GATED_CALLER)
    runtime.globals_store["targetobject"] = target.this

    caller.call("invoke", 1.0)
    caller.call("invoke", 2.0)
    caller.call("invoke", 3.0)
    runtime.load_bytecode("class", "gui_helpers", GATED_CLASS)

    assert target.this.get("order") == [1.0, 2.0, 3.0]


def test_join_timeout_flushes_gated_events(monkeypatch):
    monkeypatch.setattr(runtime_module, "CLASS_JOIN_WAIT_PUMPS", 1)
    runtime = ClientGS2(_client())
    target = runtime.load_bytecode("weapon", "target", GATED_TARGET)
    caller = runtime.load_bytecode("weapon", "caller", GATED_CALLER)
    runtime.globals_store["targetobject"] = target.this
    caller.call("invoke", 9.0)

    runtime.process_coroutines(0.0)
    runtime.process_coroutines(0.0)

    assert target.this.get("order") == [9.0]
    assert runtime._join_gated_events == {}


def test_session_reset_discards_join_gated_events():
    runtime = ClientGS2(_client())
    target = runtime.load_bytecode("weapon", "target", GATED_TARGET)
    caller = runtime.load_bytecode("weapon", "caller", GATED_CALLER)
    runtime.globals_store["targetobject"] = target.this
    caller.call("invoke", 4.0)
    assert runtime._join_gated_events

    runtime.reset_session()
    runtime.load_bytecode("class", "gui_helpers", GATED_CLASS)

    assert target.this.get("order") in (None, [])
    assert runtime._join_gated_events == {}


def test_compiled_showtop_shows_raises_and_focuses_first_tabable():
    runtime = ClientGS2(_client())
    runtime.load_bytecode("weapon", "showtop", SHOWTOP_SCRIPT)

    buried = runtime.gui._named["buried"]
    focusable = runtime.gui._named["focusable"]
    assert buried.visible is True
    assert runtime.gui.roots[-1] is buried
    assert runtime.gui._first_responder is focusable
