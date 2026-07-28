"""Regressions from the 2026-07-24 live Login-server GS2 GUI/serverlist run.

Wire truths verified against loginserver.graal.in (Login/Login DEV/Login
Mobile) and the server-side parsers (GServer-v2 PlayerRequestText.cpp):

* PLI_SENDTEXT/REQUESTTEXT payloads lead with the CALLING WEAPON's name
  ("-Serverlist_Chat,irc,login,-"); engine-originated sends use
  "GraalEngine". Without it the server matched nothing and never replied.
* A top-level {array} param flattens to one wire field per element; a
  nested array collapses to ONE gtokenized field.
* PLO_SERVERTEXT replies lead with the target weapon's name; the engine
  consumes it for routing and hands scripts (texttype, textoption,
  textlines).
* Control events are wired as dotted same-script functions
  ("GlobalChat_ChatField.onAction"), not only member closures.
* GuiControlProfile is a profile definition, never rendered.
"""
from types import SimpleNamespace

import pytest

from pyreborn.gs2_client import ClientGS2, GS2ClientHost


def _client(sent):
    return SimpleNamespace(
        player=SimpleNamespace(x=0, y=0), players={},
        send_server_text=lambda request, text: sent.append((request, text)))


def _weapon_vm(rt, name="-Serverlist_Chat", functions=()):
    vm = SimpleNamespace(
        name=f"weapon:{name}",
        _gs2_owner=("weapon", name.lower()),
        _gs2_kind="weapon", _gs2_key=name.lower(),
        functions=set(functions),
        has_function=lambda fname, _f=set(functions): fname.lower() in _f,
        calls=[],
    )
    vm.call = lambda fname, *args, _vm=vm: _vm.calls.append((fname, args))
    rt.vms["weapon"][name.lower()] = vm
    return vm


def test_sendtext_prepends_calling_weapon_name():
    sent = []
    rt = ClientGS2(_client(sent))
    vm = _weapon_vm(rt)
    rt.host.call_builtin(vm, "sendtext", ["irc", "login", "-"])
    assert sent == [(False, "-Serverlist_Chat\nirc\nlogin\n-")]


def test_requesttext_engine_fallback_and_weapon_case_preserved():
    sent = []
    rt = ClientGS2(_client(sent))
    rt.host.call_builtin(None, "requesttext", ["lister", "simplelist"])
    assert sent == [(True, "GraalEngine\nlister\nsimplelist")]
    assert rt.wire_weapon_name(_weapon_vm(rt, "-Mobile/Serverlist")) == \
        "-Mobile/Serverlist"


def test_sendtext_flattens_top_level_array_params():
    sent = []
    rt = ClientGS2(_client(sent))
    vm = _weapon_vm(rt)
    # sendLogin's second call: sendtext("irc","privmsg",{"IRCBot","!geteventbots"})
    rt.host.call_builtin(vm, "sendtext",
                         ["irc", "privmsg", ["IRCBot", "!geteventbots"]])
    assert sent == [(False, "-Serverlist_Chat\nirc\nprivmsg\nIRCBot\n!geteventbots")]


def test_sendtext_nested_array_becomes_one_gtokenized_field():
    sent = []
    rt = ClientGS2(_client(sent))
    vm = _weapon_vm(rt)
    # requestServerInfo shape: privmsg {bot, {"!getserverinfo", code}} --
    # server does params[4].guntokenize(), so the inner list must arrive as
    # a single field that guntokenizes back to its elements.
    rt.host.call_builtin(vm, "sendtext",
                         ["irc", "privmsg",
                          ["IRCBot", ["!getserverinfo", "b,c"]]])
    assert sent == [(False,
                     '-Serverlist_Chat\nirc\nprivmsg\nIRCBot\n!getserverinfo,"b,c"')]


def test_server_text_routes_to_named_weapon_with_engine_arg_shape():
    rt = ClientGS2()
    vm = _weapon_vm(rt, functions=("onreceivetext",))
    seen = []
    rt._run = lambda v, event, *args: seen.append((v, event, args))
    rt.handle_server_text(
        '-Serverlist_Chat,lister,simpleserverlist,"row1,x,0","row2,y,0"')
    assert seen == [(vm, "onReceiveText",
                     ("lister", "simpleserverlist", ["row1,x,0", "row2,y,0"]))]


def test_server_text_unknown_weapon_broadcasts_without_weapon_token():
    rt = ClientGS2()
    vm = _weapon_vm(rt, functions=("onreceivetext",))
    seen = []
    rt._run = lambda v, event, *args: seen.append((event, args))
    rt.handle_server_text("GraalEngine,irc,privmsg,IRCBot,#graal,hi")
    assert seen == [("onReceiveText", ("irc", "privmsg",
                                       ["IRCBot", "#graal", "hi"]))]
    rt.handle_server_text("")            # empty login-burst 82: no-op
    assert len(seen) == 1


def test_named_weapon_without_handler_swallows_instead_of_broadcast():
    rt = ClientGS2()
    _weapon_vm(rt, functions=())                      # the addressed weapon
    other = _weapon_vm(rt, "-Other", functions=("onreceivetext",))
    seen = []
    rt._run = lambda v, event, *args: seen.append(v)
    rt.handle_server_text("-Serverlist_Chat,irc,join,#graal")
    assert seen == [] and other.calls == []


def test_host_surface_is_memoized_and_survives_source_desync(monkeypatch):
    import inspect
    first = GS2ClientHost.host_surface()
    # simulate the on-disk edit that broke the 07-22 crawl (linecache
    # desync -> ast.parse SyntaxError on every call)
    monkeypatch.setattr(inspect, "getsource",
                        lambda *_: (_ for _ in ()).throw(OSError("desync")))
    assert GS2ClientHost.host_surface() is first
    assert "sendtext" in first and "lowercase" in first


def test_native_list_methods_pass_through_to_vm():
    # The shared VM implements add/addarray/size/clear/index/sortbyvalue
    # natively and gives the host first refusal with obj= a plain list --
    # the host must NOT swallow them (NOT_HANDLED falls through to the
    # VM), while its own sort/savelines overrides stay handled.
    from reborn_protocol.gs2 import NOT_HANDLED
    rt = ClientGS2()
    rows = [["b"], ["a"]]
    for method in ("addarray", "add", "size", "clear", "index", "sortbyvalue"):
        assert rt.host.call_builtin(None, method, [0], obj=rows) is NOT_HANDLED
    assert rows == [["b"], ["a"]]
    assert rt.host.call_builtin(None, "sort", [], obj=["b", "a"]) == ["a", "b"]


def test_lowercase_uppercase_builtins():
    rt = ClientGS2()
    assert rt.host.call_builtin(None, "lowercase", ["#GRAAL"]) == "#graal"
    assert rt.host.call_builtin(None, "uppercase", ["abc"]) == "ABC"


def test_findplayerbyid_roster_lookup():
    client = SimpleNamespace(
        player=SimpleNamespace(id=5, account="me", nickname="Me", x=3.0, y=4.0),
        x=3.0, y=4.0,
        players={16000: {"account": "irc:#graal", "nickname": "#graal (1,0)",
                         "x": 0, "y": 0}})
    rt = ClientGS2(client)
    hit = rt.host.call_builtin(None, "findplayerbyid", [16000])
    assert hit.get("account") == "irc:#graal"
    # PERSISTENT wrappers, not snapshots (windows spec section 5): the local
    # hit is the very object `player` resolves to, and a remote id hands
    # back the same per-id object every call -- -Playerlist stamps state
    # onto these and expects to see it again.
    assert hit is rt.host.call_builtin(None, "findplayerbyid", [16000])
    me = rt.host.call_builtin(None, "findplayerbyid", [5])
    assert me is rt.player_object
    assert me.get("account") == "me" and me.get("x") == 3.0
    assert rt.host.call_builtin(None, "findplayerbyid", [42]) == 0.0


def test_base64_and_credential_stubs():
    rt = ClientGS2()
    assert rt.host.call_builtin(None, "base64encode", ["abc"]) == "YWJj"
    assert rt.host.call_builtin(None, "base64decode", ["YWJj"]) == "abc"
    # credential surface is inert by policy (never real data)
    for stub in ("des_encrypt", "setpassword", "setaccountname",
                 "setnickname", "reconnect", "savegraaloptions"):
        assert rt.host.call_builtin(None, stub, ["secret"]) == 0.0
    assert "des_encrypt" in GS2ClientHost.host_surface()


def test_savevars_is_path_confined_and_skips_callables(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    rt = ClientGS2(SimpleNamespace(server_name="loginish"))
    vm = _weapon_vm(rt)
    vm.this = SimpleNamespace(_members={"account": "abc", "count": 3,
                                        "_hidden": "no", "fn": lambda: 0})
    rt.host.call_builtin(vm, "savevars", ["../../creds.txt"])
    files = list(tmp_path.rglob("creds.txt"))
    assert len(files) == 1 and tmp_path in files[0].parents
    text = files[0].read_text()
    assert "account=abc" in text and "count=3" in text
    assert "_hidden" not in text and "fn" not in text


pygame = pytest.importorskip("pygame")
from pyreborn.game.gs2_gui import GuiControlProfile  # noqa: E402


def test_dotted_handler_dispatch_and_owner_vm_stamping():
    rt = ClientGS2()
    vm = _weapon_vm(rt, functions=("globalchat_chatfield.onaction",))
    field = rt.gui.create_control("GuiTextEditCtrl", "GlobalChat_ChatField")
    # auto-emitted addcontrol runs through call_builtin with the vm
    rt.host.call_builtin(vm, "addcontrol", [field])
    assert field._owner_vm is vm
    field.text = "hello"
    assert field.fire_action(field.text) is True
    assert vm.calls == [("globalchat_chatfield.onaction", ("hello",))]
    # the member closure and the dotted function are SEPARATE catchers and
    # both run for one event (the reference's self-catch variable fallback
    # plus the implicit dotted registration -- TScriptSpace.cpp:424-443,
    # TScript.cpp:1018-1073); the old member-shadows-dotted model is gone
    hits = []
    field.set("onaction", lambda *a: hits.append(a))
    field.fire_action("again")
    assert hits == [("again",)]
    assert vm.calls[-1] == ("globalchat_chatfield.onaction", ("again",))


def test_with_scope_addcontrol_also_stamps_owner(monkeypatch):
    rt = ClientGS2()
    vm = _weapon_vm(rt, functions=("win.onaction",))
    win = rt.gui.create_control("GuiWindowCtrl", "Win")
    container = rt.host.get_object("guicontainer")
    # the VM routes the compiler-emitted addcontrol as a method of the
    # enclosing with-target (obj=)
    rt.host.call_builtin(vm, "addcontrol", ["Win"], obj=container)
    assert win._owner_vm is vm and win in rt.gui.roots
    assert win.fire_event("onaction") is True
    assert vm.calls == [("win.onaction", ())]


def test_control_profile_registers_but_never_renders():
    rt = ClientGS2()
    vm = _weapon_vm(rt)
    prof = rt.gui.create_control("GuiControlProfile", "GR_Serverlist_Profile")
    assert isinstance(prof, GuiControlProfile)
    rt.host.call_builtin(vm, "addcontrol", [prof])
    container = rt.host.get_object("guicontainer")
    rt.host.call_builtin(vm, "addcontrol", ["GR_Serverlist_Profile"],
                         obj=container)
    assert prof not in rt.gui.roots and not rt.gui._construction_stack
    assert rt.gui._named["gr_serverlist_profile"] is prof
    assert prof.visible is False
    # subsequent real controls are unaffected by the profile's presence
    win = rt.gui.create_control("GuiWindowCtrl", "W")
    rt.host.call_builtin(vm, "addcontrol", [win])
    assert win in rt.gui.roots


def test_popup_select_row_fires_dotted_onselect_with_engine_args():
    rt = ClientGS2()
    vm = _weapon_vm(rt, functions=("menu.onselect",))
    menu = rt.gui.create_control("GuiPopUpEditCtrl", "Menu")
    rt.host.call_builtin(vm, "addcontrol", [menu])
    menu.add_row("id7", "Row Seven")
    assert menu.select_row(0) is True
    assert vm.calls == [("menu.onselect", ("id7", "Row Seven", 0.0))]


def test_enter_in_text_edit_passes_field_text():
    rt = ClientGS2()
    vm = _weapon_vm(rt, functions=("f.onaction",))
    field = rt.gui.create_control("GuiTextEditCtrl", "F")
    rt.host.call_builtin(vm, "addcontrol", [field])
    rt.gui.focus(field)
    field.text = "/join #graal"
    event = SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_RETURN,
                            unicode="\r")
    assert rt.gui.handle_event(event) is True
    assert vm.calls == [("f.onaction", ("/join #graal",))]


def test_servername_bare_global_resolves_from_client():
    rt = ClientGS2(SimpleNamespace(
        player=SimpleNamespace(x=0, y=0), players={}, server_name="Login"))
    assert rt.host.get_object("servername") == "Login"
    # no client / no attribute -> empty string, never None (scripts do
    # servername.starts(...) unconditionally)
    assert ClientGS2().host.get_object("servername") == ""


def test_graalcontrol_answers_geometry_and_script_height_wins():
    rt = ClientGS2()
    obj = rt.host.get_object("graalcontrol")
    assert obj is rt.host.get_object("graalcontrol")      # persistent
    assert obj.get("clientwidth") == 800.0                # gs1 default dims
    assert obj.get("clientheight") == 600.0
    # initGraalControlSize writes `height = parent.clientheight - taskbar`
    # via with-scope (existence-gated -> the member must pre-exist)
    assert obj.has("height")
    obj.set("height", 570.0)
    assert rt.host.get_object("graalcontrol").get("clientheight") == 570.0
    # parent chain reaches the GUIContainer canvas
    assert obj.get("parent") is rt.host.get_object("guicontainer")
