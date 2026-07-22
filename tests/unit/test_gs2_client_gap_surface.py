from types import SimpleNamespace

from reborn_protocol.gs2 import GS2Object

from game_tester.server_crawl import classify_host_call
from pyreborn.client import Client
from pyreborn.packets import PacketID
from pyreborn.gs2_client import ClientGS2, GS2ClientHost
import pyreborn.gs2_client as gs2_client_module


def call(rt, name, args=(), obj=None):
    return rt.host.call_builtin(None, name, list(args), obj=obj)


def test_gui_container_control_gap_methods():
    rt = ClientGS2()
    parent = rt.gui.create_control("GuiWindowCtrl", "parent")
    child = rt.gui.create_control("GuiTextEditCtrl", "child")
    rt.gui.addcontrol(child)
    rt.gui.addcontrol(parent)
    call(rt, "addcontainer", [parent, child])
    assert call(rt, "getchild", ["child"], parent) is child
    call(rt, "setactive", [0], child)
    assert child.visible is False
    child.visible = True
    call(rt, "hidecontrols", [], parent)
    assert child.visible is False
    call(rt, "makefirstresponder", [], child)
    assert rt.gui._focus is child
    fired = []
    child.set("onaction", lambda *args: fired.extend(args))
    assert call(rt, "trigger", [7], child) == 1.0 and fired == [7]
    call(rt, "animatecontrol", [1, 2, 30, 40], child)
    assert (child.x, child.y, child.width, child.height) == (1, 2, 30, 40)
    other = rt.gui.create_control("GuiControl", "other")
    rt.gui.addcontrol(other)
    call(rt, "addguicontainer", [parent, other])
    assert other.parent is parent


def test_sort_and_savelines_are_real(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    rt = ClientGS2(SimpleNamespace(server_name="test server"))
    values = ["z", "A", "b"]
    assert call(rt, "sort", obj=values) == ["A", "b", "z"]
    call(rt, "savelines", ["../../notes.txt"], values)
    files = list(tmp_path.rglob("notes.txt"))
    assert len(files) == 1 and files[0].read_text() == "A\nb\nz"
    assert tmp_path in files[0].parents


def test_savelines_rejects_input_caps_and_embedded_nul(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    rt = ClientGS2(SimpleNamespace(server_name="caps"))
    assert not rt.save_lines("too-many.txt", [""] *
                             (gs2_client_module.SAVE_LINES_MAX_LINES + 1))
    assert not rt.save_lines("too-long.txt", ["x" *
                             (gs2_client_module.SAVE_LINES_MAX_CHARS_PER_LINE + 1)])
    assert not rt.save_lines("bad\x00name.txt", ["safe"])
    assert not list(tmp_path.rglob("*.txt"))


def test_savelines_enforces_server_cache_byte_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(gs2_client_module, "SAVE_LINES_CACHE_MAX_BYTES", 8)
    rt = ClientGS2(SimpleNamespace(server_name="tiny-cache"))
    assert rt.save_lines("first.txt", ["1234"])
    assert not rt.save_lines("second.txt", ["56789"])
    assert not list(tmp_path.rglob("second.txt"))


def test_gui_object_methods_ignore_non_controls():
    rt = ClientGS2()
    target = GS2Object(name="not-a-control")
    target.set("visible", "unchanged")
    target.set("x", 99)
    assert call(rt, "setactive", [0], target) == 0.0
    assert call(rt, "animatecontrol", [1, 2, 3, 4], target) == 0.0
    assert call(rt, "trigger", [7], target) == 0.0
    assert target.get("visible") == "unchanged"
    assert target.get("x") == 99


def test_coordinates_map_music_camera_and_nearest_players():
    local = SimpleNamespace(x=130, y=65)
    players = {
        2: SimpleNamespace(x=133, y=69, account="far", nickname="Far"),
        1: SimpleNamespace(x=131, y=65, account="near", nickname="Near"),
    }
    client = SimpleNamespace(player=local, players=players)
    camera = SimpleNamespace(zoom=1.0,
                             world_to_screen=lambda x, y: (x * 16 + 5, y * 16 + 7))
    rt = ClientGS2(client)
    rt.game_shell = SimpleNamespace(camera=camera,
                                    sound_mgr=SimpleNamespace(_current_music="theme.ogg"))
    assert call(rt, "screenx", [2]) == 37
    assert call(rt, "screeny", [3]) == 55
    assert call(rt, "getmapx") == 2 and call(rt, "getmapy") == 1
    assert call(rt, "getmusicfilename") == "theme.ogg"
    nearest = call(rt, "getnearestplayers", [130, 65])
    assert [item.get("id") for item in nearest] == [1, 2]
    call(rt, "setzoom", [1.75])
    call(rt, "enabledefaultcamera")
    assert camera.zoom == 1.75 and rt.game_shell._camera_enabled is True


def test_headless_coordinate_fallback_and_text_channels():
    sent = []
    client = SimpleNamespace(player=SimpleNamespace(x=0, y=0), players={},
                             send_server_text=lambda request, text: sent.append((request, text)))
    rt = ClientGS2(client)
    assert call(rt, "screenx", [12]) == 12 and call(rt, "screeny", [13]) == 13
    call(rt, "requesttext", ["weapon", "lister", "simplelist"])
    call(rt, "sendtext", ["weapon", "irc", "login"])
    assert sent == [(True, "weapon\nlister\nsimplelist"),
                    (False, "weapon\nirc\nlogin")]


def test_server_text_wire_ids_and_gtokenized_payload():
    sent = []
    target = SimpleNamespace(
        _protocol=SimpleNamespace(
            send_packet=lambda packet_id, data: sent.append((packet_id, data)) or True))
    assert Client.send_server_text(target, True, "weapon\nlister\nsimplelist")
    assert Client.send_server_text(target, False, "weapon\nirc\nlogin")
    assert sent == [
        (PacketID.PLI_REQUESTTEXT, b"weapon,lister,simplelist"),
        (PacketID.PLI_SENDTEXT, b"weapon,irc,login"),
    ]


def test_findimg_returns_script_object():
    layers = {8: {"image": "icon.png", "x": 3}}
    host = SimpleNamespace(_layer_store=lambda ctx: layers)
    rt = ClientGS2(gs1=SimpleNamespace(_host=host))
    image = call(rt, "findimg", [8])
    assert isinstance(image, GS2Object) and image.get("image") == "icon.png"
    assert call(rt, "findimg", [9]) == 0.0


def test_documented_stubs_are_classified_separately():
    assert GS2ClientHost.stubbed == frozenset({"hit", "modifyclientr"})
    for name in GS2ClientHost.stubbed:
        assert classify_host_call(name, set(), set(GS2ClientHost.stubbed)) == "implemented_stub"
        assert call(ClientGS2(), name) == 0.0


def test_all_gap_calls_remain_classified_as_implemented_or_stubbed():
    real = {
        "addcontainer", "addguicontainer", "getchild", "setactive",
        "hidecontrols", "makefirstresponder", "trigger", "animatecontrol",
        "sort", "savelines", "screenx", "screeny", "getmapx", "getmapy",
        "getmusicfilename", "getnearestplayers", "findimg",
        "enabledefaultcamera", "setzoom", "sendtext", "requesttext",
    }
    surface = set(GS2ClientHost.host_surface())
    for name in real:
        assert classify_host_call(name, surface, set(GS2ClientHost.stubbed)) == "implemented"
    for name in GS2ClientHost.stubbed:
        assert classify_host_call(name, surface, set(GS2ClientHost.stubbed)) == "implemented_stub"
    assert len(real | set(GS2ClientHost.stubbed)) == 23


def test_addcontrol_still_adds_to_gui_root():
    rt = ClientGS2()
    ctrl = rt.gui.create_control("GuiControl", "root")
    call(rt, "addcontrol", [ctrl])
    assert ctrl in rt.gui.roots
