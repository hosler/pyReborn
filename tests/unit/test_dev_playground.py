"""game/dev_ui.py — the F12 dev playground panel.

Pins the rules that protect a builder's work and other people's servers:

  * an unsaved script is never dropped silently: selecting something else
    asks first;
  * a script only reaches the server on an explicit save;
  * a fetch that arrives while the buffer is dirty does NOT overwrite what
    the builder is typing;
  * deletes confirm;
  * with no NC session, nothing is sent and the panel says why.

Headless, no server: the NC link is a mock and the game is a stub.
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pygame.locals as pgl

from pyreborn.game.dev_ui import TABS, DevOverlay
from pyreborn.nc_link import READY, NCLink, NCSnapshot


class _Key:
    def __init__(self, key, unicode="", mod=0):
        self.key = key
        self.unicode = unicode
        self.mod = mod


def _panel(snapshot=None, npcs=None):
    client = SimpleNamespace(
        host="localhost", port=14900, version="6.037",
        npcs=npcs or {},
        x=10.0, y=12.0,
        player=SimpleNamespace(account="builder"),
        get_current_level_from_position=lambda: "onlinestartlocal.nw",
    )
    game = SimpleNamespace(client=client, rc_password="pw", rc_ui=None,
                           screen_w=800, screen_h=600)
    panel = DevOverlay(game)
    link = Mock(spec=NCLink)
    link.snapshot = snapshot or NCSnapshot(state=READY, status="NC session active")
    link.available = link.snapshot.state == READY
    link.started = True
    link.state = link.snapshot.state
    panel.nc_link = link
    panel.visible = True
    return panel, link


def _tab(panel, name):
    panel.tab = TABS.index(name)


def test_selecting_a_weapon_fetches_its_script():
    panel, link = _panel(NCSnapshot(state=READY, weapons=("sword", "bow")))
    _tab(panel, "Weapons")
    panel.selected[panel.tab] = 1
    panel.load_selected()
    link.get_weapon.assert_called_once_with("bow")
    assert panel.loaded == ("weapon", "bow")


def test_a_fetched_script_lands_in_the_buffer():
    snap = NCSnapshot(state=READY, weapons=("bow",),
                      last_weapon={'name': 'bow', 'script': 'say hello;'})
    panel, _ = _panel(snap)
    _tab(panel, "Weapons")
    panel.loaded = ("weapon", "bow")
    panel.poll_fetch()
    assert panel.editor.buffer.text == "say hello;"


def test_a_late_fetch_never_clobbers_unsaved_typing():
    snap = NCSnapshot(state=READY, weapons=("bow",),
                      last_weapon={'name': 'bow', 'script': 'from the server'})
    panel, _ = _panel(snap)
    _tab(panel, "Weapons")
    panel.loaded = ("weapon", "bow")
    panel.editor.buffer.load("")
    panel.editor.buffer.insert("my unsaved work")
    panel.poll_fetch()
    assert panel.editor.buffer.text == "my unsaved work"


def test_switching_entries_with_unsaved_changes_asks_first():
    panel, link = _panel(NCSnapshot(state=READY, weapons=("sword", "bow")))
    _tab(panel, "Weapons")
    panel.editor.buffer.insert("edited")
    panel.load_selected()
    link.get_weapon.assert_not_called()
    assert panel.confirm is not None

    panel.handle_key(_Key(ord('y'), 'y'))
    link.get_weapon.assert_called_once()


def test_editing_alone_sends_nothing_until_save():
    panel, link = _panel(NCSnapshot(state=READY, weapons=("bow",),
                                    last_weapon={'name': 'bow', 'image': 'b.png',
                                                 'script': 'old'}))
    _tab(panel, "Weapons")
    panel.loaded = ("weapon", "bow")
    panel.editor.buffer.load("old")
    panel.focus_editor = True
    for ch in "new":
        panel.handle_key(_Key(ord(ch), ch))
    link.add_weapon.assert_not_called()

    # load() parks the cursor at the top of the script, as opening a file
    # does, so the typing lands before the loaded text.
    panel.handle_key(_Key(pgl.K_s, 's', mod=pgl.KMOD_CTRL))
    link.add_weapon.assert_called_once_with("bow", "b.png", "newold")
    assert not panel.editor.buffer.dirty, "saving must clear the dirty flag"


def test_npc_script_saves_by_id():
    npcs = {7: {'x': 5.0, 'y': 6.0, 'image': 'npc.png',
                '_level': 'onlinestartlocal.nw'}}
    panel, link = _panel(NCSnapshot(state=READY), npcs=npcs)
    _tab(panel, "NPCs")
    panel.load_selected()
    link.get_npc_script.assert_called_once_with(7)

    panel.editor.buffer.load("if (created) hide;")
    panel.save_script()
    link.set_npc_script.assert_called_once_with(7, "if (created) hide;")


def test_delete_confirms_before_it_fires():
    panel, link = _panel(NCSnapshot(state=READY, weapons=("bow",)))
    _tab(panel, "Weapons")
    panel.handle_key(_Key(ord('d'), 'd'))
    link.delete_weapon.assert_not_called()
    panel.handle_key(_Key(ord('n'), 'n'))
    link.delete_weapon.assert_not_called()

    panel.handle_key(_Key(ord('d'), 'd'))
    panel.handle_key(_Key(ord('y'), 'y'))
    link.delete_weapon.assert_called_once_with("bow")


def test_typing_in_the_editor_does_not_trigger_panel_shortcuts():
    panel, link = _panel(NCSnapshot(state=READY, weapons=("bow",)))
    _tab(panel, "Weapons")
    panel.focus_editor = True
    for ch in "drop":            # contains 'd' (delete) and 'r' (refresh)
        panel.handle_key(_Key(ord(ch), ch))
    link.delete_weapon.assert_not_called()
    assert panel.editor.buffer.text == "drop"


def test_escape_leaves_the_text_area_before_it_closes_the_panel():
    panel, _ = _panel()
    panel.focus_editor = True
    panel.handle_key(_Key(pgl.K_ESCAPE))
    assert panel.visible and not panel.focus_editor
    panel.handle_key(_Key(pgl.K_ESCAPE))
    assert not panel.visible


def test_console_needs_the_rc_link_and_reports_when_it_is_missing():
    panel, _ = _panel()
    _tab(panel, "Console")
    panel.console.buffer.load("sendtorc hi;")
    panel.run_console()
    assert "no RC session" in panel.message


def test_console_sends_the_eval_command_the_server_parses():
    panel, _ = _panel()
    rc = Mock()
    rc.available = True
    rc.snapshot = SimpleNamespace(messages=())
    panel.game.rc_ui = SimpleNamespace(link=rc)
    _tab(panel, "Console")
    panel.console.buffer.load("sendtorc hi;")
    panel.run_console()
    rc.say.assert_called_once_with("/eval onlinestartlocal.nw sendtorc hi;")


def test_console_mangles_multiline_code_for_the_wire():
    panel, _ = _panel()
    rc = Mock()
    rc.available = True
    rc.snapshot = SimpleNamespace(messages=())
    panel.game.rc_ui = SimpleNamespace(link=rc)
    panel.console.buffer.load("first;\nsecond;\nthird;")
    panel.run_console()
    command = rc.say.call_args.args[0]
    assert '\n' not in command
    assert command.count('\xa7') == 2


def test_existing_fixed_weapon_name_requires_overwrite_confirmation():
    panel, link = _panel(NCSnapshot(state=READY,
                                    weapons=("dev_builder",)))
    panel._new_weapon()
    link.add_weapon.assert_not_called()
    assert panel.confirm is not None
    panel.handle_key(_Key(ord('y'), 'y'))
    link.add_weapon.assert_called_once_with("dev_builder", "",
                                            "// new weapon\n")


def test_existing_fixed_class_name_requires_overwrite_confirmation():
    panel, link = _panel(NCSnapshot(state=READY,
                                    classes=("dev_builder",)))
    panel._new_class()
    link.add_class.assert_not_called()
    assert panel.confirm is not None
    panel.handle_key(_Key(ord('y'), 'y'))
    link.add_class.assert_called_once_with("dev_builder", "// new class\n")


def test_new_fixed_names_are_created_without_confirmation():
    panel, link = _panel()
    panel._new_weapon()
    link.add_weapon.assert_called_once()
    assert panel.confirm is None


def test_nothing_is_sent_without_a_live_nc_session():
    panel, link = _panel(NCSnapshot(state="denied", status="no NC access"))
    link.available = False
    _tab(panel, "Weapons")
    panel.load_selected()
    link.get_weapon.assert_not_called()
    assert "no NC session" in panel.message


def test_panel_draws_on_every_tab():
    pygame.init()
    pygame.display.set_mode((320, 240))
    surface = pygame.Surface((800, 600))
    npcs = {3: {'x': 1.0, 'y': 2.0, 'image': 'a.png',
                '_level': 'onlinestartlocal.nw'}}
    panel, _ = _panel(NCSnapshot(state=READY, weapons=("bow",),
                                 classes=("gui",), levels=("a.nw",)), npcs=npcs)
    panel.game.font = pygame.font.Font(None, 18)
    panel.game.font_small = pygame.font.Font(None, 14)
    from pyreborn.game.assets import FontManager
    panel.game.fonts = FontManager()
    for index in range(len(TABS)):
        panel.tab = index
        panel.draw(surface)          # must not raise on any tab
    pygame.quit()
