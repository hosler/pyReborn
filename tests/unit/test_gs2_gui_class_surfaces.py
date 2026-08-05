"""Reference-table coverage for the per-class GUI surfaces."""

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


def make(rt, kind, name):
    item = rt.gui.create_control(kind, name)
    rt.gui.addcontrol(item)
    return item


def test_mltext_navigation_selection_and_replacement():
    item = make(ClientGS2(), "GuiMLTextCtrl", "ml")
    item.set("text", "Alpha\nbeta Alpha")
    assert item.get("getlinecount")() == 2
    assert item.get("getline")(1) == "beta Alpha"
    assert item.get("findtext")("alpha", 0) == 0
    assert item.get("findtextat")("Alpha", 1, 2) == 11
    assert item.get("getcolumnandlineofposition")(8) == "2,1"
    assert item.get("selecttext")(6, 4) is True
    assert item.get("getselectedposition")() == 6
    assert item.get("getselectedlength")() == 4
    item.get("deselecttext")()
    assert item.get("getselectedposition")() == -1
    assert item.get("replacetext")("alpha", "X", 0) == 2
    assert item.text == "X\nbeta X"
    item.get("setcursorcolumnandline")(2, 1)
    assert item.get("getcursorline")() == 1


def test_text_list_table_and_real_entry_properties():
    item = make(ClientGS2(), "GuiTextListCtrl", "list")
    item.set("enumerate", 1)
    item.set("resizecell", 1)
    item.set("sortcolumn", 3)
    row = item.get("addrow")(9, "Zulu")
    assert item.get("enumerate") == item.get("resizecell") == 1
    assert item.get("sortcolumn") == 3
    assert item.get("iconheight") == 0
    assert row.get("active") == 1 and row.get("flickertime") == 1
    assert row.get("image") == 0 and row.get("selectedimage") == 1
    row.set("sortgroup", 4)
    row.set("sortvalue", 7)
    row.get("settext")("Alpha")
    assert row.get("gettext")() == "Alpha"
    assert row.get("sortgroup") == 4 and row.get("sortvalue") == 7
    assert row.get("extent") == "0,0" and row.get("position") == "0,0"
    second = item.get("addrow")(10, "Zulu\tAble")
    row.set("text", "Alpha\tZulu")
    item.set("sortcolumn", 1)
    item.set("sortmode", "lexical")
    item.get("sort")()
    assert item.list_rows == [second, row]


def test_popup_scroll_edit_bitmap_profile_and_render_state():
    rt = ClientGS2()
    popup = make(rt, "GuiPopUpMenuCtrl", "popup")
    popup.get("addrow")(10, "Ten")
    popup.get("addrow")(20, "Twenty")
    popup.get("setselected")(20)
    assert popup.get("getselected")() == 20
    popup.popup_open = True
    popup.get("forceclose")()
    assert popup.popup_open is False

    scroll = make(rt, "GuiScrollCtrl", "scroll")
    scroll.set("extent", "100 80")
    child = rt.gui.create_control("GuiControl", "content")
    child.set("extent", "300 250")
    scroll.add_child(child)
    scroll.get("scrollrectvisible")(180, 160, 20, 20)
    assert scroll.get("scrollpos") == [100.0, 100.0]

    edit = make(rt, "GuiTextEditCtrl", "edit")
    edit.set("text", "one")
    edit.set("text", "two")
    edit.get("undo")()
    assert edit.text == "one"
    bitmap = make(rt, "GuiBitmapCtrl", "bitmap")
    bitmap.get("setvalue")(3, 4)
    assert (bitmap.value_x, bitmap.value_y) == (3, 4)
    profile = rt.gui.create_control("GuiControlProfile", "profile")
    assert profile.get("preloadfont")() == 0
    viewport = make(rt, "GuiGraalCtrl", "viewport")
    viewport.set("isrendering", 1)
    assert viewport.get("isrendering") == 1


def test_show_image_and_browser_state_only_surface():
    rt = ClientGS2()
    image = make(rt, "GuiShowImgCtrl", "image")
    for key, value in {"ani": "walk", "dir": 2, "layer": 3,
                       "offsetx": -4, "offsety": 5}.items():
        image.set(key, value)
        assert image.get(key) == value
    browser = make(rt, "GuiBrowserCtrl", "browser")
    assert browser.get("allowzoom") == 0
    browser.set("allowzoom", 1)
    browser.set("url", "https://example.invalid/")
    assert browser.get("url") == "https://example.invalid/" and browser.text == ""
    browser.set("text", "<b>local</b>")
    assert browser.text == "<b>local</b>" and browser.get("url") == ""


@pytest.mark.skipif(GS2TEST is None, reason="gs2test compiler binary not built")
def test_compiled_per_class_writes_and_calls(tmp_path):
    source = tmp_path / "class_surfaces.gs2"
    bytecode = tmp_path / "class_surfaces.gs2bc"
    source.write_text('''
function onCreated() {
  new GuiMLTextCtrl("wave") { text = "One\\nTwo One"; }
  wave.selectText(4, 3);
  new GuiTextListCtrl("rows") { enumerate = true; resizecell = true; sortcolumn = 2; }
  temp.row = rows.addRow(42, "Before"); temp.row.setText("After");
  new GuiButtonCtrl("choice") { buttonType = "RadioButton"; checked = true; groupNum = 8; text = "Pick"; }
  new GuiPopUpMenuCtrl("menu") { menu.addRow(9, "Nine"); menu.setSelected(9); }
  new GuiShowImgCtrl("sprite") { ani = "idle"; dir = 1; layer = 2; offsetx = 3; offsety = 4; }
  new GuiBrowserCtrl("page") { allowzoom = true; url = "https://example.invalid/"; }
  this.result = wave.getSelectedLength() @ "|" @ rows.enumerate @ "|" @
    rows.resizecell @ "|" @ rows.sortcolumn @ "|" @ temp.row.getText() @ "|" @
    choice.checked @ "|" @ choice.groupnum @ "|" @ choice.getText() @ "|" @
    menu.getSelected() @ "|" @ sprite.ani @ "|" @ page.allowzoom;
}
''')
    result = subprocess.run([GS2TEST, str(source), "-o", str(bytecode)],
                            capture_output=True, text=True, timeout=30)
    assert bytecode.exists(), result.stderr
    vm = ClientGS2().load_bytecode("npc", 93, bytecode.read_bytes())
    assert vm.this.get("result") == "3|1|1|2|After|1|8|Pick|9|idle|1"
