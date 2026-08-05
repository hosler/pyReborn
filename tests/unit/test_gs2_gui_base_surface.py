"""Reference-pinned GuiControl base property and method surface."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from pyreborn.gs2_client import ClientGS2


GS2TEST = next((str(path) for path in (
    os.environ.get("GS2TEST_BIN"),
    Path(__file__).parents[3] / "reborn-protocol/tests/tools/gs2test",
    shutil.which("gs2test"),
) if path and Path(path).is_file() and os.access(path, os.X_OK)), None)


def control(rt, name):
    item = rt.gui.create_control("GuiControl", name)
    rt.gui.addcontrol(item)
    return item


def test_constructor_defaults_and_registered_reads():
    rt = ClientGS2()
    item = control(rt, "base")
    assert item.get("bounds") == "0,0,64,64"
    assert item.get("minsize") == "8,8"
    assert item.get("color") == "255,255,255"
    assert item.get("awake") == 1.0
    assert item.get("alpha") == item.get("red") == 1.0
    assert item.get("green") == item.get("blue") == 1.0
    assert item.get("mode") == 1.0
    assert item.get("flickertime") == 1.0
    assert item.get("flickerbasetime") == 0.0
    assert item.get("hinttime") == 0.5
    assert item.get("scrolllinex") == 30.0
    assert item.get("scrollliney") == 10.0
    assert item.get("clipmove") == item.get("showhint") == 1.0
    assert item.get("resizewidth") == item.get("resizeheight") == 1.0
    for name in ("bitmapcache", "editing", "fastchildrender", "flickering",
                 "lockmousedown", "alwaysontop"):
        assert item.get(name) == 0.0


def test_property_round_trips_and_coupling():
    rt = ClientGS2()
    item = control(rt, "base")
    item.set("bounds", "4 5 80 90")
    item.set("color", "10,20,30,40")
    assert item.get("bounds") == "4,5,80,90"
    assert item.get("color") == "10,20,30,40"
    assert item.get("red") == pytest.approx(10 / 255)
    item.set("green", 0.5)
    assert item.get("color") == "10,128,30,40"
    item.set("areaclickpriority", 99)
    item.set("scrolllinex", -4)
    assert item.get("areaclickpriority") == 2.0
    assert item.get("scrolllinex") == 0.0
    for name, value in {
        "bitmapcache": 1, "clipmove": 0, "cursor": "arrow",
        "editing": 1, "mode": 3, "fastchildrender": 1,
        "flickering": 1, "flickerbasetime": 2.5, "flickertime": 0.25,
        "hinttime": 3, "lockmousedown": 1, "minsize": "7 9",
        "resizewidth": 0, "resizeheight": 0, "rotation": 1.25,
        "rotationcenter": "11 12", "scrollliney": 6, "showhint": 0,
        "alwaysontop": 1,
    }.items():
        item.set(name, value)
        assert item.has(name)
    assert item.get("cursor") == "pointer"
    assert item.get("minsize") == "7,9"
    assert item.get("rotationcenter") == "11,12"


def test_findcontrol_is_recursive_point_hit_not_name_search():
    rt = ClientGS2()
    parent = control(rt, "parent")
    parent.set("bounds", "0 0 200 200")
    child = rt.gui.create_control("GuiControl", "child")
    child.set("bounds", "20 30 40 50")
    parent.add_child(child)
    child.awaken()
    assert parent._m_findcontrol("25 35") is child
    assert parent._m_findcontrol("child") is None


def test_parent_sort_and_canvas_parent():
    rt = ClientGS2()
    parent = control(rt, "parent")
    a = rt.gui.create_control("GuiControl", "a")
    b = rt.gui.create_control("GuiControl", "b")
    c = rt.gui.create_control("GuiControl", "c")
    for child, pos in ((a, (5, 20)), (b, (9, 10)), (c, (1, 10))):
        child.set("position", pos)
        parent.add_child(child)
    parent._m_sortcontrols()
    assert parent.children == [c, b, a]
    assert a._m_getparent() is parent
    assert parent._m_getparent() is rt.gui.canvas_object()


def test_per_device_mouse_lock_ownership():
    rt = ClientGS2()
    a = control(rt, "a")
    b = control(rt, "b")
    a._m_mouselock(2)
    assert a._m_ismouselocked(2) == 1.0
    b._m_mouseunlock(2)
    assert a._m_ismouselocked(2) == 1.0
    b._m_mouselock(3)
    a._m_mouseunlockall()
    assert a._m_ismouselocked(2) == 0.0
    assert b._m_ismouselocked(3) == 1.0


@pytest.mark.skipif(GS2TEST is None, reason="gs2test compiler binary not built")
def test_compiled_with_block_property_writes(tmp_path):
    source = tmp_path / "base_surface.gs2"
    bytecode = tmp_path / "base_surface.gs2bc"
    source.write_text("""
function onCreated() {
  new GuiControl("roundtrip") {
    bounds = "3 4 70 80";
    color = "12,34,56,78";
    rotationcenter = "9 10";
    areaclickpriority = 99;
    showhint = false;
  }
  this.result = roundtrip.bounds @ "|" @ roundtrip.color @ "|" @
    roundtrip.rotationcenter @ "|" @ roundtrip.areaclickpriority @ "|" @
    roundtrip.showhint;
}
""")
    result = subprocess.run([GS2TEST, str(source), "-o", str(bytecode)],
                            capture_output=True, text=True, timeout=30)
    assert bytecode.exists(), result.stderr
    rt = ClientGS2()
    vm = rt.load_bytecode("npc", 72, bytecode.read_bytes())
    assert vm.this.get("result") == "3,4,70,80|12,34,56,78|9,10|2|0"
