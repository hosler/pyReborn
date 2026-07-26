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


def test_named_gui_controls_resolve_as_globals_and_isobject():
    # Live Login server, -Rescripted/IRC/Login3: `GuiRC.visible = true;` and
    # `if (isObject("Serverlist_Panel")) ...` address controls by their ctor
    # name as bare globals -- get_object must consult the GUI name registry.
    rt = ClientGS2()
    panel = rt.gui.create_control("GuiWindowCtrl", "Serverlist_Panel")
    rt.gui.addcontrol(panel)
    assert rt.host.get_object("Serverlist_Panel") is panel
    assert rt.host.get_object("serverlist_panel") is panel
    assert call(rt, "isobject", ["Serverlist_Panel"]) == 1.0
    assert call(rt, "isobject", ["GuiRC"]) == 0.0
    assert rt.host.get_object("guirc") is None


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
    # players[] INDICES (0 = us), nearest first: we stand at the probe point
    # and player 1 is nearer than player 2. players{} insertion order gives
    # 2 -> index 1 and 1 -> index 2.
    assert call(rt, "getnearestplayers", [131.5, 67]) == [0.0, 2.0, 1.0]
    call(rt, "setzoom", [1.75])
    call(rt, "enabledefaultcamera")
    assert camera.zoom == 1.75 and rt.game_shell._camera_enabled is True


def test_headless_coordinate_fallback_and_text_channels():
    sent = []
    client = SimpleNamespace(player=SimpleNamespace(x=0, y=0), players={},
                             send_server_text=lambda request, text: sent.append((request, text)))
    rt = ClientGS2(client)
    assert call(rt, "screenx", [12]) == 12 and call(rt, "screeny", [13]) == 13
    # vm=None -> engine-originated send: the wire prepends "GraalEngine"
    # (the reference client's convention; a weapon vm would prepend its own
    # name -- see wire_weapon_name)
    call(rt, "requesttext", ["lister", "simplelist"])
    call(rt, "sendtext", ["irc", "login"])
    assert sent == [(True, "GraalEngine\nlister\nsimplelist"),
                    (False, "GraalEngine\nirc\nlogin")]


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
    assert GS2ClientHost.stubbed == frozenset({
        "hit", "modifyclientr", "adventure_getsystemid", "des_encrypt",
        "reconnect", "savegraaloptions", "setaccountname", "setnickname",
        "setpassword",
        # Adventure-engine prefixed bindings of the same surface (live
        # Login Mobile corpus calls these forms)
        "adventure_setaccountname", "adventure_setnickname",
        "adventure_setpassword", "adventure_savegraaloptions",
        "adventure_reconnect",
        # native-canvas rebuild toggle (Login serverlist init); no native
        # canvas exists here
        "adventure_setgraalcontrolrecreate",
        # credential surface (2026-07-24 Login corpus)
        "setpasswordofaccount", "applypassword", "clearpassword",
        "adventure_geteditnickname", "adventure_geteditaccountnames",
        # credential surface (2026-07-26 mobile Login corpus): decrypt is
        # policy-inert exactly like des_encrypt
        "des_decrypt",
        # iphone-build display reconfiguration; unreachable platform here
        "initializeiphonedisplay",
        # external-application / URL surface
        "opengraalurl", "gotowebpage", "adventure_openexternaloptions",
        "showupdatewindow", "startgraalstreaming",
        "showfriendinvitationwindow", "showgiftinvitationwindow",
        # native platform toggles
        "adventure_startofflinemode", "adventure_setallowedsocketsconnect",
        "adventure_setfullscreen", "adventure_setchat",
        "createsmartphoneui", "mouselock",
        # serverlist connect-through (pyReborn joins from its own browser)
        "connecttoselectedserver", "serverdirectconnect", "startscriptedrc",
        "initserverlist", "requestserverinfo", "selectservercategory",
        # platform account windows
        "showshop", "showprofile", "showoptions", "openchat", "haspanel",
        # no directory query exists in the file protocol
        "loadfolder",
        # native patcher status (terminating constants, see below)
        "gettotalupdatepackagesize", "getdownloadedupdatepackagesize",
        "getpackagesdownloaded", "isdownloadingfiles",
        "getpackagesdownloadcomplete", "getdownloadingpackage"})
    for name in GS2ClientHost.stubbed:
        assert classify_host_call(name, set(), set(GS2ClientHost.stubbed)) == "implemented_stub"
        assert call(ClientGS2(), name) == \
            GS2ClientHost._PATCHER_STUB_VALUES.get(name, 0.0)


def test_patcher_stubs_answer_with_terminating_values():
    """IRC_Installer polls the update-package counters in a progress loop;
    an all-zero answer for getPackagesDownloadComplete() spins forever."""
    rt = ClientGS2()
    assert call(rt, "getpackagesdownloadcomplete") == 1.0
    assert call(rt, "gettotalupdatepackagesize") == 0.0
    assert call(rt, "getdownloadedupdatepackagesize") == 0.0
    assert call(rt, "isdownloadingfiles") == 0.0
    assert call(rt, "getdownloadingpackage") == ""


def test_all_gap_calls_remain_classified_as_implemented_or_stubbed():
    real = {
        "addcontainer", "addguicontainer", "getchild", "setactive",
        "hidecontrols", "makefirstresponder", "trigger", "animatecontrol",
        "sort", "savelines", "screenx", "screeny", "getmapx", "getmapy",
        "getmusicfilename", "getnearestplayers", "findplayerbyid", "findimg",
        "enabledefaultcamera", "setzoom", "sendtext", "requesttext",
        # 2026-07-24 Login-corpus gaps closed with real behavior
        "gettextheight", "md5", "extractfilename", "extractfilebase",
        "extractfileext", "fileexists", "pushdialog", "popdialog",
        "bringtofront", "isfullscreenmode", "scheduleevent", "cancelevents",
        # 2026-07-24 Zelda-corpus gaps (see test_gs2_zelda_host_gaps.py)
        "findnearestplayers", "findnearestplayer", "getstringkeys",
        "getcallstack", "isinclass", "leave",
    }
    surface = set(GS2ClientHost.host_surface())
    for name in real:
        assert classify_host_call(name, surface, set(GS2ClientHost.stubbed)) == "implemented"
    for name in GS2ClientHost.stubbed:
        assert classify_host_call(name, surface, set(GS2ClientHost.stubbed)) == "implemented_stub"
    assert len(real | set(GS2ClientHost.stubbed)) == 93


def test_addcontrol_still_adds_to_gui_root():
    rt = ClientGS2()
    ctrl = rt.gui.create_control("GuiControl", "root")
    call(rt, "addcontrol", [ctrl])
    assert ctrl in rt.gui.roots
