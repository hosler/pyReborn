"""Client-owned Login native-window controls."""

import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../reborn-protocol"))

from pyreborn.game.gs2_gui import GuiWindowCtrl
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


SHOW_NATIVE_LOG = _compile("""
function onCreated() {
  new GuiWindowCtrl("Cover") { visible = true; }
  F2LogWindow_Window.showtop();
}
""")

@pytest.mark.parametrize(("name", "geometry"), [
    ("PlayerList_Window", (188.0, 503.0)),
    ("DownloadProgress_Window", (400.0, 170.0)),
    ("IRC_Test_UpdateWindow", (590.0, 370.0)),
])
def test_compiled_native_window_showtop_resolves_and_raises(
        caplog, name, geometry):
    runtime = ClientGS2()
    window = runtime.host.get_object(name)
    bytecode = _compile(f"""
function onCreated() {{
  new GuiWindowCtrl("Cover") {{ visible = true; }}
  {name}.showtop();
}}
""")

    assert isinstance(window, GuiWindowCtrl)
    assert (window.width, window.height) == geometry
    assert window.visible is False

    with caplog.at_level(logging.WARNING):
        runtime.load_bytecode("weapon", f"native-{name}", bytecode)

    assert "unknown method showtop()" not in caplog.text
    assert window.visible is True
    assert runtime.gui.roots[-1] is window


def test_compiled_native_log_window_showtop_resolves_and_raises(caplog):
    runtime = ClientGS2()
    window = runtime.host.get_object("F2LogWindow_Window")

    assert isinstance(window, GuiWindowCtrl)
    assert (window.width, window.height, window.visible) == (500.0, 200.0, False)

    with caplog.at_level(logging.WARNING):
        runtime.load_bytecode("weapon", "native-log-window", SHOW_NATIVE_LOG)

    assert "unknown method showtop()" not in caplog.text
    assert window.visible is True
    assert runtime.gui.roots[-1] is window
