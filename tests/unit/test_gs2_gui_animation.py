import os
from pathlib import Path
import shutil
import subprocess

import pytest

from pyreborn.gs2_client import ClientGS2


def _call(rt, name, args=(), obj=None):
    return rt.host.call_builtin(None, name, list(args), obj=obj)


def _compiler():
    candidates = (
        os.environ.get("GS2TEST_BIN"),
        Path(__file__).parents[3] / "reborn-protocol/tests/tools/gs2test",
        shutil.which("gs2test"),
    )
    return next((str(path) for path in candidates
                 if path and Path(path).is_file() and os.access(path, os.X_OK)),
                None)


GS2TEST = _compiler()


def _compile(source, tmp_path):
    src = tmp_path / "animation.gs2"
    out = tmp_path / "animation.gs2bc"
    src.write_text(source)
    result = subprocess.run([GS2TEST, str(src), "-o", str(out)],
                            capture_output=True, text=True, timeout=30)
    assert out.exists(), result.stderr
    return out.read_bytes()


@pytest.mark.skipif(GS2TEST is None, reason="gs2test compiler binary not built")
def test_script_createanimation_with_property_writes(tmp_path):
    blob = _compile("""
function onCreated() {
  new GuiControl("animated") {
    alpha = 1;
    onAnimationFinished = function(kind) {
      this.finished = kind;
    };
  }
  this.ani = animated.createanimation();
  with (this.ani) {
    duration = 2;
    transition = "transform";
    alpha = 0;
  }
}
""", tmp_path)
    rt = ClientGS2()
    vm = rt.load_bytecode("npc", 71, blob)
    ctrl = rt.gui._named["animated"]
    animation = vm.this.get("ani")

    assert animation.get("duration") == 2.0
    assert animation.get("amplitude") == 32.0
    assert animation.get("interval") == 1.0
    assert animation.get("tabfirstonshow") == 1.0
    rt.gui.tick(0.5)
    assert ctrl.alpha == pytest.approx(0.75)
    assert ctrl.get("isinanimation") == 1.0
    rt.gui.tick(1.5)
    assert ctrl.alpha == pytest.approx(0.0)
    assert ctrl.get("isinanimation") == 0.0
    assert vm.this.get("finished") == "transform"


def test_bounds_playback_and_stopanimations():
    rt = ClientGS2()
    ctrl = rt.gui.create_control("GuiControl", "moving")
    rt.gui.addcontrol(ctrl)
    animation = _call(rt, "createanimation", obj=ctrl)
    animation.set("duration", 2)
    animation.set("transition", "transform")
    animation.set("bounds", "20 30 200 80")

    rt.gui.tick(0.5)
    assert ctrl.animation_bounds() == (5, 8, 98, 68)
    _call(rt, "stopanimations", obj=ctrl)
    stopped = ctrl.animation_bounds()
    rt.gui.tick(10)
    assert ctrl.animation_bounds() == stopped
    assert ctrl.get("isinanimation") == 0.0


def test_fade_and_stopinoutanimations():
    rt = ClientGS2()
    ctrl = rt.gui.create_control("GuiControl", "fading")
    fade = ctrl.create_animation()
    fade.set("transition", "fadeout")
    transform = ctrl.create_animation()
    transform.set("transition", "transform")
    assert ctrl.get("isininoutanimation") == 1.0

    ctrl.stop_in_out_animations()
    assert ctrl.animations == [transform]
    assert ctrl.get("isininoutanimation") == 0.0


def test_createanimation_reference_capacity_boundary():
    rt = ClientGS2()
    ctrl = rt.gui.create_control("GuiControl", "capacity")
    created = [ctrl.create_animation() for _ in range(1000)]
    assert all(animation is not None for animation in created)
    assert ctrl.create_animation() is None
