"""GS2 client builtin gaps closed from the 2026-11-11 gap rank.

Each test compiles real GS2 source with the reference compiler binary and runs
it through the VM and the client host, so the builtin is exercised the way a
server script reaches it. Reference citations live next to the code they
justify (gs2_client/host_bare.py, client_actions.py, game/gs2_gui/).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

from pyreborn.client import Client, PacketID
from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2

GS2TEST = next((str(path) for path in (
    os.environ.get("GS2TEST_BIN"),
    Path(__file__).parents[3] / "reborn-protocol/tests/tools/gs2test",
    shutil.which("gs2test"),
) if path and Path(path).is_file() and os.access(path, os.X_OK)), None)

needs_compiler = pytest.mark.skipif(
    GS2TEST is None, reason="gs2test compiler binary not built")


def compile_gs2(tmp_path, body: str) -> bytes:
    """Compile `body` as a weapon script and return its bytecode."""
    source = tmp_path / "case.gs2"
    bytecode = tmp_path / "case.gs2bc"
    source.write_text(body)
    result = subprocess.run([GS2TEST, str(source), "-o", str(bytecode)],
                            capture_output=True, text=True, timeout=30)
    assert bytecode.exists(), result.stderr
    return bytecode.read_bytes()


class _FakeProtocol:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def online_runtime():
    """A real Client with a capturing protocol, wrapped in a real ClientGS2."""
    client = Client()
    client._protocol = _FakeProtocol()
    client._authenticated = True
    rt = ClientGS2(client, ClientGS1(client))
    return client, rt


def run(rt, tmp_path, body: str):
    vm = rt.load_bytecode("weapon", "case", compile_gs2(tmp_path, body))
    assert vm is not None
    return vm


# -- serverwarp -------------------------------------------------------------

@needs_compiler
def test_serverwarp_sends_pli_serverwarp_with_the_name(tmp_path):
    client, rt = online_runtime()
    run(rt, tmp_path, 'function onCreated() { serverwarp("Login"); }')
    assert client._protocol.sent == [(PacketID.PLI_SERVERWARP, b"Login")]


@needs_compiler
def test_serverwarp_drops_empty_and_repeated_destinations(tmp_path):
    client, rt = online_runtime()
    run(rt, tmp_path, """
function onCreated() {
  serverwarp("");
  serverwarp("Login");
  serverwarp("Login");
}""")
    assert client._protocol.sent == [(PacketID.PLI_SERVERWARP, b"Login")]


@needs_compiler
def test_serverwarp_rate_limits_different_destinations(tmp_path):
    client, rt = online_runtime()
    run(rt, tmp_path, """
function onCreated() {
  serverwarp("A");
  serverwarp("B");
}""")
    assert client._protocol.sent == [(PacketID.PLI_SERVERWARP, b"A")]
    client.last_server_warp_at -= 5.0
    client.send_server_warp("B")
    assert client._protocol.sent[-1] == (PacketID.PLI_SERVERWARP, b"B")


def test_serverwarp_refuses_control_characters_and_long_names():
    client, _rt = online_runtime()
    assert client.send_server_warp("a\nb") is False
    assert client.send_server_warp("x" * (client.SERVER_WARP_MAX_CHARS + 1)) is False
    assert client.send_server_warp("caf€") is False  # not latin-1
    assert client._protocol.sent == []


def test_serverwarp_needs_a_session():
    client, _rt = online_runtime()
    client._authenticated = False
    assert client.send_server_warp("Login") is False


def test_serverwarp_answer_reaches_the_headless_callback():
    """PLO_SERVERWARP is the answer; a headless client gets on_server_warp."""
    from pyreborn.handlers.session import handle_server_warp
    client, _rt = online_runtime()
    client.send_server_warp("Login")
    assert client.last_server_warp == "Login"
    seen = []
    client.on_server_warp = seen.append
    from pyreborn.packets import _gtokenize
    handle_server_warp(
        client, _gtokenize("Login\nLogin\n10.0.0.5\n14900").encode("latin-1"))
    # the reply clears the repeat guard so a declined offer can be re-asked
    assert client.last_server_warp == ""
    assert len(seen) == 1
    assert seen[0]["host"] == "10.0.0.5" and seen[0]["port"] == 14900


def test_gs1_serverwarp_command_uses_the_same_request():
    client, rt = online_runtime()
    rt.gs1._host.call_command("serverwarp", ["Some", "Server"],
                              rt._gs1_ctx(None))
    assert client._protocol.sent == [(PacketID.PLI_SERVERWARP, b"Some,Server")]


# -- GuiControl.controls ----------------------------------------------------

@needs_compiler
def test_controls_reads_the_child_array(tmp_path):
    client, rt = online_runtime()
    vm = run(rt, tmp_path, """
function onCreated() {
  new GuiControl("outer") {
    new GuiControl("inner_a") { }
    new GuiControl("inner_b") { }
  }
  this.count = outer.controls.size();
  this.first = outer.controls[0].name;
  this.second = outer.controls[1].name;
  this.walked = "";
  for (c : outer.controls) this.walked = this.walked @ c.name @ ";";
}""")
    assert vm.this.get("count") == 2.0
    assert vm.this.get("first") == "inner_a"
    assert vm.this.get("second") == "inner_b"
    assert vm.this.get("walked") == "inner_a;inner_b;"


def test_controls_is_a_snapshot_and_bounded():
    from pyreborn.game.gs2_gui import base
    rt = ClientGS2()
    outer = rt.gui.create_control("GuiControl", "outer")
    rt.gui.addcontrol(outer)
    for i in range(base.MAX_CONTROLS_VIEW + 5):
        kid = base.GuiControl(f"k{i}")
        outer.add_child(kid)
    view = outer.get("controls")
    assert len(view) == base.MAX_CONTROLS_VIEW
    view.clear()                                   # editing the view...
    assert len(outer.children) == base.MAX_CONTROLS_VIEW + 5   # ...is harmless
    outer.set("controls", [])                      # and a write is ignored
    assert len(outer.children) == base.MAX_CONTROLS_VIEW + 5
    assert outer.has("controls")


# -- profile.modal ----------------------------------------------------------

@needs_compiler
def test_modal_profile_fits_a_root_control_to_the_canvas(tmp_path):
    client, rt = online_runtime()
    run(rt, tmp_path, """
function onCreated() {
  new GuiControlProfile("ModalFill") { modal = true; }
  new GuiControlProfile("Plain") { modal = false; }
  new GuiControl("full") { profile = ModalFill; bounds = "10 10 100 100"; }
  new GuiControl("small") { profile = Plain; bounds = "10 10 100 100"; }
  this.flag = ModalFill.modal;
}""")
    gui = rt.gui
    full, small = gui._named["full"], gui._named["small"]
    gui.on_canvas_resize(640, 480)
    assert (full.x, full.y, full.width, full.height) == (0.0, 0.0, 640.0, 480.0)
    assert (small.x, small.y, small.width, small.height) == (10.0, 10.0, 100.0, 100.0)
    gui.on_canvas_resize(800, 600)                 # every window resize refits
    assert (full.width, full.height) == (800.0, 600.0)
    assert (small.width, small.height) == (100.0, 100.0)
    full.set("visible", 0.0)
    gui.on_canvas_resize(1024, 768)                # hidden controls are skipped
    assert (full.width, full.height) == (800.0, 600.0)


def test_modal_defaults_off_and_reads_back():
    from pyreborn.game.gs2_gui import profiles
    assert profiles._profile_from_fields({"fillcolor": (1, 2, 3)}).modal is False
    assert profiles._profile_from_fields({"modal": 1.0}).modal is True


# -- text-style profile fields ---------------------------------------------

def _fonts():
    import pygame
    from pyreborn.game.assets import FontManager
    pygame.font.init()
    return FontManager()


def _pixels_of(surface, color):
    import pygame
    width, height = surface.get_size()
    return sum(1 for x in range(width) for y in range(height)
               if tuple(surface.get_at((x, y)))[:3] == color)


def _styled_button(rt, **fields):
    from pyreborn.game.gs2_gui import GuiControlProfile
    prof = rt.gui.create_control("GuiControlProfile", "StyleP")
    prof.parent_profile_name = "guibluebuttonprofile"
    for key, value in dict(fillcolor=(0, 0, 0, 255), border=0, bitmap="",
                           opaque=True, fontcolor=(255, 255, 255),
                           fontsize=24, **fields).items():
        prof.set(key, value)
    btn = rt.gui.create_control("GuiButtonCtrl", "styled")
    btn.set("text", "Hello")
    btn.x, btn.y, btn.width, btn.height = 4, 4, 120, 40
    btn.profile_obj = prof
    btn.profile_name = "StyleP"
    rt.gui.addcontrol(btn)
    return btn, prof


def _render(rt, btn):
    import pygame
    surf = pygame.Surface((140, 60))
    surf.fill((0, 0, 0))
    rt.gui.render(surf, _fonts())
    return surf


def test_shadowcolor_and_offset_are_rendered_for_a_text_shadow():
    rt = ClientGS2()
    btn, prof = _styled_button(rt, textshadow=True,
                               shadowcolor=(255, 0, 0, 255),
                               shadowoffset=(6, 6))
    surf = _render(rt, btn)
    assert _pixels_of(surf, (255, 0, 0)) > 20
    # moving the offset moves where the red shadow lands
    prof.set("shadowoffset", (-6, -6))
    other = _render(rt, btn)
    assert surf.get_buffer().raw != other.get_buffer().raw
    # textshadow off: no shadow at all
    prof.set("textshadow", False)
    plain = _render(rt, btn)
    assert _pixels_of(plain, (255, 0, 0)) == 0


def test_default_shadow_stays_the_one_pixel_black_drop():
    from pyreborn.game.gs2_gui import profiles
    shadow = profiles._profile_from_fields({"textshadow": 1}).text_shadow
    assert shadow and (shadow.dx, shadow.dy, shadow.color) == (1, 1, (0, 0, 0, 255))
    assert not profiles._profile_from_fields({"fontsize": 10}).text_shadow


def test_shadow_offset_is_clamped_and_malformed_input_defaults():
    from pyreborn.game.gs2_gui import profiles
    far = profiles._profile_from_fields(
        {"textshadow": 1, "shadowoffset": (9999, -9999)}).text_shadow
    assert (far.dx, far.dy) == (profiles.MAX_SHADOW_OFFSET,
                                -profiles.MAX_SHADOW_OFFSET)
    junk = profiles._profile_from_fields(
        {"textshadow": 1, "shadowoffset": "nonsense", "shadowcolor": "x"}
    ).text_shadow
    assert (junk.dx, junk.dy, junk.color) == (1, 1, (0, 0, 0, 255))


def test_fontcolorhl_colours_a_hovered_button_only():
    rt = ClientGS2()
    btn, _prof = _styled_button(rt, fontcolorhl=(0, 0, 255))
    idle = _render(rt, btn)
    assert _pixels_of(idle, (0, 0, 255)) == 0
    btn.hovered = True
    hover = _render(rt, btn)
    assert _pixels_of(hover, (0, 0, 255)) > 20


def test_fontcolorsel_colours_the_selected_list_row():
    import pygame
    rt = ClientGS2()
    prof = rt.gui.create_control("GuiControlProfile", "ListP")
    prof.parent_profile_name = "guitextlistprofile"
    for key, value in dict(fillcolor=(0, 0, 0, 255), fillcolorhl=(0, 0, 0, 255),
                           fontcolor=(255, 255, 255), fontcolorhl=(0, 255, 0),
                           fontcolorsel=(255, 0, 255), fontsize=18).items():
        prof.set(key, value)
    lst = rt.gui.create_control("GuiTextListCtrl", "rows")
    lst.profile_obj, lst.profile_name = prof, "ListP"
    lst.x, lst.y, lst.width, lst.height = 0, 0, 120, 60
    rt.gui.addcontrol(lst)
    lst._m_addrow(1, "First")
    lst._m_addrow(2, "Second")
    surf = pygame.Surface((140, 80))
    surf.fill((0, 0, 0))
    rt.gui.render(surf, _fonts())
    assert _pixels_of(surf, (0, 255, 0)) > 20           # ordinary rows
    assert _pixels_of(surf, (255, 0, 255)) == 0
    lst._m_setselectedrow(1)
    surf.fill((0, 0, 0))
    rt.gui.render(surf, _fonts())
    assert _pixels_of(surf, (255, 0, 255)) > 20          # selected row


def test_text_edit_selection_uses_fontcolorhl_over_fillcolorhl():
    import pygame
    rt = ClientGS2()
    prof = rt.gui.create_control("GuiControlProfile", "EditP")
    prof.parent_profile_name = "guitexteditprofile"
    for key, value in dict(fillcolor=(0, 0, 0, 255), fillcolorhl=(200, 0, 0, 255),
                           fontcolor=(255, 255, 255), fontcolorhl=(0, 255, 255),
                           bitmap="", border=0, fontsize=22).items():
        prof.set(key, value)
    edit = rt.gui.create_control("GuiTextEditCtrl", "edit")
    edit.profile_obj, edit.profile_name = prof, "EditP"
    edit.x, edit.y, edit.width, edit.height = 0, 0, 130, 30
    rt.gui.addcontrol(edit)
    edit.text = "Selected"
    edit.focused = True
    edit.selection = (0, 3)
    surf = pygame.Surface((140, 40))
    surf.fill((0, 0, 0))
    rt.gui.render(surf, _fonts())
    assert _pixels_of(surf, (200, 0, 0)) > 20
    assert _pixels_of(surf, (0, 255, 255)) > 20


def test_fonttype_resolves_only_inside_the_asset_directories():
    from pyreborn.game.gs2_gui import profiles
    bundled = profiles.resolve_font_file("rebornfont", False)
    assert bundled is not None and bundled.endswith("assets/rebornfont.ttf")
    assert profiles.resolve_font_file("RebornFont.ttf", False) == bundled
    # a name that is not a plain stem never reaches the filesystem
    for bad in ("../rebornfont", "/etc/passwd", "a/b", "..", "", "x" * 80,
                "reborn font", "reborn\x00font"):
        assert profiles.resolve_font_file(bad, False) is None
    assert profiles.resolve_font_file("friz", True) is None   # not installed
    got = profiles._profile_from_fields({"fonttype": "rebornfont"})
    assert got.font_type == "rebornfont" and got.font_path == bundled
    assert profiles._profile_from_fields({"fonttype": "friz"}).font_path is None


def test_fonttype_changes_the_rendered_face():
    rt = ClientGS2()
    btn, prof = _styled_button(rt)
    default = _render(rt, btn)
    prof.set("fonttype", "rebornfont")
    named = _render(rt, btn)
    assert default.get_buffer().raw != named.get_buffer().raw
    prof.set("fonttype", "no-such-face")
    assert _render(rt, btn).get_buffer().raw == default.get_buffer().raw


# -- openurl ----------------------------------------------------------------

@needs_compiler
def test_openurl_stays_dropped_but_logs_once_at_debug(tmp_path, caplog):
    import logging
    client, rt = online_runtime()
    with caplog.at_level(logging.DEBUG, logger="pyreborn.gs1_client"):
        run(rt, tmp_path, """
function onCreated() {
  openurl("http://example.invalid/a");
  openurl("http://example.invalid/a");
  openurl("http://example.invalid/b");
}""")
    hits = [r for r in caplog.records if "dropped by policy" in r.getMessage()]
    assert len(hits) == 2
    assert all(r.levelno == logging.DEBUG for r in hits)
    assert client._protocol.sent == []


# -- hideplayer -------------------------------------------------------------

@needs_compiler
def test_hideplayer_sets_status_bit_two_and_tells_the_server(tmp_path):
    from reborn_protocol import PLSTATUS
    client, rt = online_runtime()
    client.player.status = 0
    run(rt, tmp_path, "function onCreated() { hideplayer(0.5); }")
    assert client.player.status & PLSTATUS.HIDDEN
    (packet_id, payload), = client._protocol.sent
    assert packet_id == PacketID.PLI_PLAYERPROPS
    assert payload[0] == 18 + 32                      # PLPROP.STATUS
    assert payload[1] - 32 == PLSTATUS.HIDDEN


def test_hideplayer_converts_and_clamps_seconds_like_the_reference():
    """TInitStatics.cpp:3425-3439: clamp 0-10 s, x60 ticks, +0.5, truncate;
    a counter n is hidden for n+1 ticks."""
    import time
    client, _rt = online_runtime()
    now = time.monotonic()
    client.hide_player(99.0)
    assert 10.0 < client.hide_player_until - now <= 10.1
    client.player.status = 0
    client.hide_player(-5.0)
    assert 0.0 < client.hide_player_until - time.monotonic() <= 2 / 60.0
    client.hide_player(float("nan"))
    assert client.hide_player_until - time.monotonic() <= 2 / 60.0
    assert client.hide_player("junk") is False


def test_hideplayer_ends_on_expiry_and_on_damage():
    import time
    from reborn_protocol import PLSTATUS
    client, _rt = online_runtime()
    client.player.status = 0
    client.player.hearts = 3.0
    client.hide_player(5.0)
    client._tick_hide_player()
    assert client.player.status & PLSTATUS.HIDDEN      # still hidden
    client.player.hearts = 2.0                         # damage ends it early
    client._tick_hide_player()
    assert not client.player.status & PLSTATUS.HIDDEN
    assert client.hide_player_until == 0.0

    client.hide_player(0.0)
    client.hide_player_until = time.monotonic() - 1.0  # expiry
    client._tick_hide_player()
    assert not client.player.status & PLSTATUS.HIDDEN
    status_packets = [p for p in client._protocol.sent
                      if p[0] == PacketID.PLI_PLAYERPROPS]
    assert len(status_packets) == 4                    # set, clear, set, clear


# -- savestring / savevars (method forms) ----------------------------------

def _cache_files(cfg):
    return sorted((cfg / "pyreborn" / "client-cache").rglob("*.txt"))


@needs_compiler
def test_savestring_writes_the_value_and_mode_one_appends(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    client, rt = online_runtime()
    run(rt, tmp_path, """
function onCreated() {
  "first line".savestring("log.txt", 0);
  "second line".savestring("log.txt", 1);
  "gone".savestring("../../../escape.txt", 0);
}""")
    files = _cache_files(cfg)
    names = {path.name: path.read_text() for path in files}
    # the reference saves the raw bytes: mode 1 appends with no separator
    assert names["log.txt"] == "first linesecond line"
    assert "escape.txt" in names                    # confined to the leaf name
    assert all(cfg in path.parents for path in files)
    assert not (tmp_path / "escape.txt").exists()


@needs_compiler
def test_savevars_method_form_writes_sorted_members(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    client, rt = online_runtime()
    run(rt, tmp_path, """
function onCreated() {
  this.opts = new TStaticVar();
  this.opts.zeta = 2;
  this.opts.alpha = "a";
  this.opts.savevars("opts.txt", 0);
}""")
    names = {path.name: path.read_text() for path in _cache_files(cfg)}
    assert names["opts.txt"].split("\n") == ["alpha=a", "zeta=2"]


def test_savestring_respects_the_cache_caps(tmp_path, monkeypatch):
    from pyreborn.gs2_client import registry
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    client, rt = online_runtime()
    assert rt.save_lines("big.txt", ["x" * 100], append=False)
    monkeypatch.setattr("pyreborn.gs2_client.runtime.SAVE_LINES_CACHE_MAX_BYTES",
                        150)
    assert rt.save_lines("big.txt", ["y" * 40], append=True) is True
    assert rt.save_lines("big.txt", ["z" * 40], append=True) is False


def test_savestring_mode_one_appends_raw_bytes_and_empty_mode_zero_deletes(
        tmp_path, monkeypatch):
    """TStream::SaveToFile (TStream.cpp:281-327): mode 1 appends the raw
    bytes with no separator, another mode replaces, an empty value with mode
    0 deletes the file, an empty value with any other mode does nothing."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    _client, rt = online_runtime()
    read = lambda: _cache_files(tmp_path / "cfg")[0].read_bytes()  # noqa: E731
    assert rt.save_text("s.txt", "ab", 0)
    assert rt.save_text("s.txt", "cd", 1)
    assert rt.save_text("s.txt", "ef", 1)
    assert read() == b"abcdef"
    assert rt.save_text("s.txt", "x\ny", 5)          # any non-1 mode replaces
    assert read() == b"x\ny"
    assert rt.save_text("s.txt", "", 1)              # empty + mode 1: nothing
    assert read() == b"x\ny"
    assert rt.save_text("s.txt", "", 0)              # empty + mode 0: delete
    assert _cache_files(tmp_path / "cfg") == []
    assert rt.save_text("s.txt", "", 0)              # nothing to delete: fine


def test_save_text_respects_the_cache_cap_and_leaf_confinement(
        tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    _client, rt = online_runtime()
    monkeypatch.setattr("pyreborn.gs2_client.runtime.SAVE_LINES_CACHE_MAX_BYTES",
                        150)
    assert rt.save_text("big.txt", "x" * 100, 0)
    assert rt.save_text("big.txt", "y" * 40, 1) is True
    assert rt.save_text("big.txt", "z" * 40, 1) is False
    assert rt.save_text("../up.txt", "ok", 0) is True
    assert all((tmp_path / "cfg") in p.parents
               for p in _cache_files(tmp_path / "cfg"))
    assert rt.save_text("..", "no", 0) is False


# -- review round: serverwarp consent and rate limits ----------------------

def _warp_reply(client, host="10.0.0.5", port=14900, name="A"):
    from pyreborn.handlers.session import handle_server_warp
    from pyreborn.packets import _gtokenize
    handle_server_warp(client, _gtokenize(
        f"{name}\n{name}\n{host}\n{port}").encode("latin-1"))


def test_serverwarp_interval_uses_the_timestamp_not_the_pending_flag():
    """sw.py: a reply used to clear the guard, so alternating destinations
    went out back to back."""
    client, _rt = online_runtime()
    for i in range(5):
        client.send_server_warp("A" if i % 2 == 0 else "B")
        _warp_reply(client)
    assert len(client._protocol.sent) == 1
    client.last_server_warp_at -= client.SERVER_WARP_MIN_INTERVAL + 0.1
    assert client.send_server_warp("B") is True
    assert len(client._protocol.sent) == 2


def test_serverwarp_decline_starts_a_global_cooldown():
    client, _rt = online_runtime()
    assert client.send_server_warp("A")
    client.note_server_warp_declined()
    client.last_server_warp_at -= 10.0               # interval long over
    assert client.send_server_warp("B") is False     # a different destination
    assert client.note_server_warp_offer() is False
    client.server_warp_declined_until = 0.0          # cooldown elapsed
    assert client.send_server_warp("B") is True
    assert client.SERVER_WARP_DECLINE_COOLDOWN == 30.0


def test_serverwarp_offers_are_capped_until_the_player_uses_the_browser():
    client, _rt = online_runtime()
    for _ in range(client.SERVER_WARP_MAX_OFFERS):
        assert client.note_server_warp_offer() is True
    assert client.note_server_warp_offer() is False
    client.last_server_warp_at = 0.0
    assert client.send_server_warp("A") is False     # script sends ignored
    client.reset_server_warp_limits()                # the player opened F8
    assert client.send_server_warp("A") is True
    assert client.SERVER_WARP_MAX_OFFERS == 5


def test_blocked_script_warp_fires_the_headless_callback_once_per_interval():
    client, _rt = online_runtime()
    seen = []
    client.on_server_warp_blocked = seen.append
    client.note_server_warp_declined()
    for name in ("A", "B", "C"):
        assert client.send_server_warp(name) is False
    assert seen == ["A"]                       # one notice per 5 s
    client.server_warp_notice_at -= client.SERVER_WARP_NOTICE_INTERVAL + 1
    client.send_server_warp("D")
    assert seen == ["A", "D"]
    client.server_warp_declined_until = 0.0
    assert client.send_server_warp("E") is True    # no notice when it goes out
    assert seen == ["A", "D"]


def test_serverwarp_session_reset_clears_the_limits():
    client, _rt = online_runtime()
    client.note_server_warp_declined()
    client.server_warp_offers = client.SERVER_WARP_MAX_OFFERS
    client._protocol.connect = lambda: True
    client._protocol.connected = False
    client.connect()
    assert client.server_warp_allowed()


# -- review round: font resolution is bounded ------------------------------

def test_fonttype_lookups_never_touch_the_disk_after_the_index(monkeypatch,
                                                              tmp_path):
    """font2.py: 64 junk names used to make a later real face resolve to
    None; now a lookup is a dict hit whatever came before."""
    from pyreborn import asset_paths
    from pyreborn.game.gs2_gui import profiles
    calls = []
    monkeypatch.setattr(asset_paths, "content_dirs",
                        lambda: calls.append(1) or [tmp_path])
    profiles.reset_font_resolution()
    try:
        profiles.prime_font_roots()
        # any further directory/file probe would go through Path.is_file/
        # iterdir/resolve; make them fail loudly
        def boom(*args, **kwargs):
            raise AssertionError("font lookup touched the disk")
        for attr in ("iterdir", "is_file", "resolve", "stat"):
            monkeypatch.setattr(Path, attr, boom)
        for i in range(500):
            assert profiles.resolve_font_file(f"junk{i}", i % 2 == 0) is None
        bundled = profiles.resolve_font_file("rebornfont", False)
        assert bundled is not None and bundled.endswith("rebornfont.ttf")
        assert len(calls) == 1               # roots built once, not per name
    finally:
        monkeypatch.undo()
        profiles.reset_font_resolution()


def test_fonttype_roots_follow_the_content_dir_environment(monkeypatch, tmp_path):
    from pyreborn.game.gs2_gui import profiles
    (tmp_path / "fonts").mkdir()
    shutil.copy(Path(profiles.__file__).resolve().parents[2]
                / "assets" / "rebornfont.ttf", tmp_path / "fonts" / "extra.ttf")
    profiles.reset_font_resolution()
    try:
        monkeypatch.delenv("PYREBORN_CONTENT_DIR", raising=False)
        assert profiles.resolve_font_file("extra", False) is None
        monkeypatch.setenv("PYREBORN_CONTENT_DIR", str(tmp_path))
        assert profiles.resolve_font_file("extra", False) is not None
    finally:
        profiles.reset_font_resolution()


# -- review round: root add is not quadratic -------------------------------

def test_adding_a_root_fits_only_that_root(monkeypatch):
    from pyreborn.game.gs2_gui import GuiControl
    rt = ClientGS2()
    rt.gui.canvas_size = (640, 480)
    resolved = []
    original = GuiControl.resolve_profile

    def counting(self, *args, **kwargs):
        resolved.append(self)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(GuiControl, "resolve_profile", counting)
    for i in range(60):
        rt.gui.addcontrol(rt.gui.create_control("GuiControl", f"c{i}"))
    # one fit check per add (<= 1 resolve of its own profile), never one per
    # existing root: 60 adds would be ~1800 resolves in the quadratic form
    own = [c for c in resolved if c.name.startswith("c") and c.name[1:].isdigit()]
    assert len(own) <= 60 * 3


def test_root_controls_are_capped_cleanly_and_destroy_frees_capacity():
    from pyreborn.game.gs2_gui import manager
    rt = ClientGS2()
    rt.gui.canvas_size = (320, 200)
    for i in range(manager.MAX_ROOT_CONTROLS):
        rt.gui.addcontrol(rt.gui.create_control("GuiControl", f"r{i}"))
    assert len(rt.gui.roots) == manager.MAX_ROOT_CONTROLS
    extra = rt.gui.create_control("GuiControl", "extra")
    rt.gui.addcontrol(extra, owner_vm=object())
    assert extra not in rt.gui.roots
    # untouched: never woken, no owner stamped, off the construction stack
    assert extra._awake is False and extra._owner_vm is None
    assert extra not in rt.gui._construction_stack
    assert len(rt.gui.roots) == manager.MAX_ROOT_CONTROLS
    rt.gui.destroy(rt.gui.roots[0])            # frees one slot
    assert len(rt.gui.roots) == manager.MAX_ROOT_CONTROLS - 1
    again = rt.gui.create_control("GuiControl", "again")
    rt.gui.addcontrol(again)
    assert again in rt.gui.roots


def test_canvas_resize_still_refits_every_modal_root():
    rt = ClientGS2()
    rt.gui.canvas_size = (320, 200)
    modal = rt.gui.create_control("GuiControlProfile", "ModalP")
    modal.set("modal", 1.0)
    first = rt.gui.create_control("GuiControl", "m1")
    first.profile_obj, first.profile_name = modal, "ModalP"
    rt.gui.addcontrol(first)
    assert (first.width, first.height) == (320.0, 200.0)   # fitted on add
    rt.gui.on_canvas_resize(640, 480)
    assert (first.width, first.height) == (640.0, 480.0)


# -- review round: hideplayer cannot stick ---------------------------------

def test_disconnect_while_hidden_clears_the_bit_and_tells_the_server():
    from reborn_protocol import PLSTATUS
    client, _rt = online_runtime()
    client.player.status = 0
    client.hide_player(5.0)
    assert client.player.status & PLSTATUS.HIDDEN
    client._protocol.disconnect = lambda: None
    client.disconnect()
    assert not client.player.status & PLSTATUS.HIDDEN
    assert client.hide_player_until == 0.0
    last_id, last_payload = client._protocol.sent[-1]
    assert last_id == PacketID.PLI_PLAYERPROPS
    assert last_payload[1] - 32 == 0                 # the clear went out first


def _self_status_packet(status):
    return bytes([18 + 32, status + 32])


def test_login_status_carrying_hidden_is_masked_and_corrected_once():
    from reborn_protocol import PLSTATUS
    client, _rt = online_runtime()
    client.hide_player_until = 0.0
    client._handle_packet(PacketID.PLO_PLAYERPROPS,
                          _self_status_packet(PLSTATUS.HIDDEN))
    assert not client.player.status & PLSTATUS.HIDDEN
    sent = [p for p in client._protocol.sent
            if p[0] == PacketID.PLI_PLAYERPROPS]
    assert len(sent) == 1 and sent[0][1][1] - 32 == 0
    client._handle_packet(PacketID.PLO_PLAYERPROPS, _self_status_packet(0))
    assert len([p for p in client._protocol.sent
                if p[0] == PacketID.PLI_PLAYERPROPS]) == 1


def test_a_pending_hide_keeps_its_status_bit_on_a_self_status_prop():
    from reborn_protocol import PLSTATUS
    client, _rt = online_runtime()
    client.player.status = 0
    client.hide_player(5.0)
    client._handle_packet(PacketID.PLO_PLAYERPROPS,
                          _self_status_packet(PLSTATUS.HIDDEN))
    assert client.player.status & PLSTATUS.HIDDEN


# -- review round: inactive buttons use the not-active colour --------------

def test_inactive_button_ignores_fontcolorhl_and_uses_fontcolorna():
    rt = ClientGS2()
    btn, _prof = _styled_button(rt, fontcolorhl=(0, 0, 255),
                                fontcolorna=(255, 0, 0))
    btn.set("active", 0.0)
    btn.hovered = True
    surf = _render(rt, btn)
    assert _pixels_of(surf, (0, 0, 255)) == 0
    assert _pixels_of(surf, (255, 0, 0)) > 20
    btn.set("active", 1.0)
    assert _pixels_of(_render(rt, btn), (0, 0, 255)) > 20


def test_inactive_button_without_fontcolorna_keeps_its_normal_colour():
    """The reference gives fontcolorna no default (GuiControlProfile.cpp:
    178-221), so a profile that never set it must look as it did before."""
    rt = ClientGS2()
    btn, _prof = _styled_button(rt, fontcolorhl=(0, 0, 255))
    btn.set("active", 0.0)
    btn.hovered = True
    surf = _render(rt, btn)
    assert _pixels_of(surf, (255, 255, 255)) > 20
    assert _pixels_of(surf, (0, 0, 255)) == 0


def test_inactive_bitmap_button_label_is_not_hover_coloured():
    from pyreborn.game.gs2_gui.profiles import _profile_from_fields
    rt = ClientGS2()
    btn = rt.gui.create_control("GuiBitmapButtonCtrl", "bb")
    prof = _profile_from_fields({"fontcolor": (255, 255, 255),
                                 "fontcolorhl": (0, 0, 255),
                                 "fontcolorna": (9, 9, 9)})
    btn.hovered = True
    assert btn.label_color(prof) == (0, 0, 255)
    btn.set("active", 0.0)
    assert btn.label_color(prof) == (9, 9, 9)


# -- variable-held string receivers ----------------------------------------

@needs_compiler
def test_savestring_on_a_variable_receiver_writes_the_file(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    client, rt = online_runtime()
    run(rt, tmp_path, """
function onCreated() {
  temp.s = "abc";
  temp.s.savestring("f.txt", 0);
  temp.s.savestring("f.txt", 1);
}""")
    names = {path.name: path.read_text() for path in _cache_files(cfg)}
    assert names["f.txt"] == "abcabc"


@needs_compiler
def test_unhandled_root_method_on_a_variable_string_fetches_no_weapon(
        tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    client, rt = online_runtime()
    fetched = []
    monkeypatch.setattr(rt, "fetch_weapon",
                        lambda name: fetched.append(name) or None)
    run(rt, tmp_path, """
function onCreated() {
  temp.s = "SomeWeapon";
  temp.s.loadstring("f.txt");
  temp.s.savestring("g.txt", 0);
}""")
    assert fetched == []
    assert [p.name for p in _cache_files(tmp_path / "cfg")] == ["g.txt"]
