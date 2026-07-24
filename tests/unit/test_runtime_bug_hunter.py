import os
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../reborn-protocol"))

from reborn_protocol.gs2 import GS2Container
from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2


class _Wire:
    def __init__(self):
        self.sent = []

    def set_flag(self, name, value):
        self.sent.append((name, value))


def test_throttled_flags_remain_eligible_for_same_value_resend():
    wire = _Wire()
    rt = ClientGS1(wire)
    for scope_name, prefix in (("server", "server."), ("client", "client.")):
        scope = rt._shared[scope_name]
        rt._flag_tokens = 0.0
        rt._flag_last_refill = time.time()
        scope["retry"] = "value"
        assert wire.sent == []
        rt._flag_tokens = 1.0
        rt._flag_last_refill = 0.0
        scope["retry"] = "value"
        assert wire.sent.pop() == (prefix + "retry", "value")


def test_client_replica_write_is_local_and_readable():
    wire = _Wire()
    gs1 = ClientGS1(wire)
    obj = ClientGS2(wire, gs1).flag_scope_object("clientr")
    obj.set("serverOwned", "local")
    assert obj.get("serverOwned") == "local"
    assert wire.sent == []


class _EventVM:
    def __init__(self, kind, key, seen):
        self.name = f"{kind}:{key}"
        self._gs2_kind = kind
        self._gs2_key = key
        self._gs2_owner = (kind, key)
        self.seen = seen

    def has_function(self, event):
        return event != "onPlayerEnters"

    def iter_call(self, event, *args):
        if event == "start":
            yield 1.0
        self.seen.append((event, args))


def test_sleeping_vm_drains_pending_events_in_fifo_order():
    seen = []
    rt = ClientGS2()
    vm = _EventVM("weapon", "queue", seen)
    rt.vms["weapon"]["queue"] = vm
    rt._run(vm, "start", "original")
    rt._run(vm, "trigger", "first", 1)
    rt._run(vm, "trigger", "second", 2)
    rt.process_coroutines(1.0)
    assert seen == [
        ("start", ("original",)),
        ("trigger", ("first", 1)),
        ("trigger", ("second", 2)),
    ]


def test_level_change_keeps_weapon_sleep_but_drops_npc_sleep():
    client = SimpleNamespace(_current_level_name="old", npcs={})
    rt = ClientGS2(client)
    weapon = _EventVM("weapon", "w", [])
    npc = _EventVM("npc", 7, [])
    rt.vms["weapon"]["w"] = weapon
    rt.vms["npc"][7] = npc
    rt._run(weapon, "start")
    rt._run(npc, "start")
    rt._entered_level = "old"
    client._current_level_name = "new"
    rt.pump_level_events()
    assert [c["vm"] for c in rt._coros] == [weapon]
    assert ("weapon", "w") in rt._active_coro_keys
    assert ("npc", 7) not in rt._active_coro_keys
    rt.process_coroutines(1.0)
    assert weapon.seen == [("start", ())]
    assert npc.seen == []


def test_reloading_vm_cancels_old_parked_event_and_unblocks_new_vm():
    rt = ClientGS2()
    old = rt.load_bytecode("weapon", "repeat", GS2Container())
    key = rt._timeout_key(old)
    rt._active_coro_keys.add(key)
    rt._coros.append({"gen": iter(()), "vm": old, "key": key,
                      "event": "old", "remaining": 10.0})
    new = rt.load_bytecode("weapon", "repeat", GS2Container())
    assert new is not old
    assert key not in rt._active_coro_keys
    assert all(c["vm"] is not old for c in rt._coros)
    seen = []

    def fresh_event(event, *args):
        seen.append((event, args))
        if False:
            yield 0

    new.iter_call = fresh_event
    rt._run(new, "fresh", 9)
    assert seen == [("fresh", (9,))]


def test_npc_identity_lives_on_vm_and_churn_leaves_no_registry():
    rt = ClientGS2()
    for npc_id in range(100):
        vm = rt.load_bytecode("npc", npc_id, GS2Container())
        assert rt._timeout_key(vm) == ("npc", npc_id)
        assert rt._gs1_ctx(vm)._npc_id == npc_id
        rt.forget_npc(npc_id)
    assert not hasattr(rt, "_vm_keys")
    assert not hasattr(rt, "_vm_owners")
