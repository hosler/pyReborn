"""The ordered overlay stack of the pygame client.

Every modal or screen-space UI that sits over the world is one entry of
`GameClient.overlays`, in input priority order (topmost first):

  input walks the list forwards and stops at the first entry whose
  `handle_event` returns True; whatever nobody consumed reaches gameplay
  (InputMixin._handle_events).
  draw walks it backwards, so the entry that gets events first is drawn on
  top (HUD.draw).
  the held-key movement gate asks `captures_keys` of every entry, and the
  F-key mutual close and the server-warp prompt close entries by name
  (InputMixin._close_overlays).

The entries are thin adapters over the existing UIs: each UI keeps its own
state, layout and key handling (several are plain booleans on the game, such
as `show_player_list` or `typing`), and the adapter reads that state at call
time. So a game whose UIs are created lazily, or a test harness that sets only
the attributes it needs, can use the stack at any time.

Entry fields:

  name            stable identifier (`close_overlays` and tests use it)
  visible         True while the UI is open
  captures_keys   True while held keys must not drive gameplay (movement,
                  sword, GS1 keydown mirror). False for the non-modal level
                  editor and for passive layers; for the GS2 GUI only while a
                  text edit holds keyboard focus.
  hud_layer       drawn as part of the play HUD, which the death overlay
                  replaces: skipped while the death presentation is up.
  handle_event()  True = consumed.
  draw(surface)   paints the entry's current state (nothing while closed,
                  except the chat entry, which always paints the chat log).
  close()         closes the UI the way its own Escape path does.
"""

from typing import List, Optional

import pygame
from pygame.locals import (
    KEYDOWN, MOUSEBUTTONDOWN, K_DOWN, K_PAGEDOWN, K_PAGEUP, K_UP,
)

from . import keymap


class Overlay:
    """Base entry: a passive layer that is never open and takes no input."""

    name = ""
    hud_layer = True

    def __init__(self, game, hud=None):
        self.game = game
        self._hud = hud

    @property
    def visible(self) -> bool:
        return False

    @property
    def captures_keys(self) -> bool:
        return self.visible

    def handle_event(self, event) -> bool:
        return False

    def draw(self, surface) -> None:
        pass

    def close(self) -> None:
        pass

    # helpers for the adapters
    @property
    def hud(self):
        return self._hud or getattr(self.game, 'hud', None)

    def _hud_shown(self) -> bool:
        """The parts of the HUD a full stop (`client.input_frozen`) hides."""
        return not getattr(self.game.client, 'input_frozen', False)

    def __repr__(self) -> str:
        return f"<overlay {self.name} visible={self.visible}>"


class _KeyPanel(Overlay):
    """A modal UI that takes every KEYDOWN while it is open and no other
    event, through one handler."""

    def handle_event(self, event) -> bool:
        if event.type != KEYDOWN or not self.visible:
            return False
        self.handle_key(event)
        return True

    def handle_key(self, event) -> None:
        raise NotImplementedError


class ServerWarpPrompt(Overlay):
    """PLO_SERVERWARP consent prompt. It outranks everything, the GS2 GUI
    included: a script must not be able to answer or dismiss it. It takes
    every key and swallows mouse clicks; other mouse events pass."""

    name = "server_warp"

    @property
    def visible(self) -> bool:
        return getattr(self.game, 'server_warp_prompt', None) is not None

    def handle_event(self, event) -> bool:
        if not self.visible or event.type not in (KEYDOWN, MOUSEBUTTONDOWN):
            return False
        if event.type == KEYDOWN:
            self.game._handle_server_warp_key(event)
        return True

    def draw(self, surface) -> None:
        if self.visible:
            self.hud._draw_server_warp_prompt(surface)

    def close(self) -> None:
        # The prompt's default answer is No.
        if self.visible:
            self.game._decline_server_warp()


class GS2Gui(Overlay):
    """Script-built GS2 GUI windows (showgui/GuiControl). Every event is
    offered to them; a consumed one (a click inside a control, a keystroke
    into a focused text edit, Esc on a window) stops here. Keys are not
    offered while chat or a PM is being typed (see _gs2_gui_event)."""

    name = "gs2_gui"
    hud_layer = False

    @property
    def manager(self):
        gs2 = getattr(self.game, 'gs2', None)
        return getattr(gs2, 'gui', None) if gs2 is not None else None

    @property
    def visible(self) -> bool:
        mgr = self.manager
        return bool(mgr is not None and any(
            getattr(root, 'visible', False) for root in mgr.roots))

    @property
    def captures_keys(self) -> bool:
        mgr = self.manager
        return bool(mgr is not None and mgr.keyboard_captured)

    def handle_event(self, event) -> bool:
        return self.game._gs2_gui_event(event)

    def draw(self, surface) -> None:
        mgr = self.manager
        if mgr is not None:
            mgr.render(surface, self.game.fonts, self.game.sprite_mgr)

    def close(self) -> None:
        # The windows belong to the server's scripts; the client never
        # closes them on its own.
        pass


class DebugReadouts(Overlay):
    """F1 debug mode's screen readouts (level, position, tile under the
    cursor). Passive; the tile tint itself is a world pass."""

    name = "debug_hud"
    hud_layer = False

    @property
    def visible(self) -> bool:
        return bool(getattr(self.game, 'debug_mode', False))

    @property
    def captures_keys(self) -> bool:
        return False

    def draw(self, surface) -> None:
        if self.visible:
            self.game._render_debug_hud()

    def close(self) -> None:
        self.game.debug_mode = False


class HudNotice(Overlay):
    """The one-line notice at the top of the screen (show_hud_notice).
    Passive; it expires on its own."""

    name = "hud_notice"

    @property
    def visible(self) -> bool:
        return getattr(self.game, 'hud_notice', None) is not None

    @property
    def captures_keys(self) -> bool:
        return False

    def draw(self, surface) -> None:
        notice = getattr(self.game, 'hud_notice', None)
        if notice is None:
            return
        if self.game.clock.frame_now() >= notice[1]:
            self.game.hud_notice = None
        else:
            self.hud._draw_hud_notice(surface, notice[0])

    def close(self) -> None:
        self.game.hud_notice = None


class _UIObjectPanel(_KeyPanel):
    """A modal panel object with `.visible`, `.handle_key(event)`,
    `.draw(surf)` and `.close()` (the F10 RC tools, the F12 dev
    playground)."""

    attr = ""

    @property
    def ui(self):
        return getattr(self.game, self.attr, None)

    @property
    def visible(self) -> bool:
        ui = self.ui
        return bool(ui is not None and ui.visible)

    def handle_key(self, event) -> None:
        self.ui.handle_key(event)

    def draw(self, surface) -> None:
        ui = self.ui
        if ui is not None:
            ui.draw(surface)

    def close(self) -> None:
        ui = self.ui
        if ui is not None:
            ui.close()


class RCTools(_UIObjectPanel):
    """F10 RC tools. Above the other panels because it types free text
    (chat, ban reasons, file paths) into its own prompt, so no letter of it
    may fall through to a gameplay action."""

    name = "rc_tools"
    attr = "rc_ui"


class DevTools(_UIObjectPanel):
    """F12 dev playground (scripts + console)."""

    name = "dev_tools"
    attr = "dev_ui"


class LevelEditorKeys(Overlay):
    """F11 edit mode, keyboard side. Not modal: it claims its own tool keys
    and lets everything else through, so a builder still walks around with
    the arrows and chats while the grid is up. Draws the grid, object
    markers, toolbar and palette."""

    name = "level_editor"

    @property
    def editor(self):
        return getattr(self.game, 'level_editor', None)

    @property
    def visible(self) -> bool:
        editor = self.editor
        return bool(editor is not None and editor.state.enabled)

    @property
    def captures_keys(self) -> bool:
        return False

    def handle_event(self, event) -> bool:
        editor = self.editor
        if event.type != KEYDOWN or editor is None:
            return False
        return bool(editor.handle_key(event))

    def draw(self, surface) -> None:
        # Edit mode decorates the WORLD, so it sits under the panels: grid,
        # object markers and toolbar first, then the palette it opens.
        overlay = getattr(self.game, 'editor_overlay', None)
        if overlay is None:
            return
        overlay.draw(surface)
        editor = self.editor
        if editor.state.enabled and editor.state.palette_visible:
            self.game.tile_palette.draw(surface, editor.state.tile)

    def close(self) -> None:
        if self.visible:
            self.editor.toggle()


class LevelEditorPointer(LevelEditorKeys):
    """F11 edit mode, mouse side: painting, picking, rectangle drags and the
    palette. It ranks below the big map, which swallows the mouse, while the
    editor's keys rank above the panels; hence two entries for one UI. It
    draws nothing (the keyboard entry draws the editor)."""

    name = "level_editor_pointer"

    def handle_event(self, event) -> bool:
        editor = self.editor
        if editor is None or event.type in (KEYDOWN, pygame.VIDEORESIZE):
            return False
        return bool(editor.handle_mouse(event, self.game.tile_palette))

    def draw(self, surface) -> None:
        pass

    def close(self) -> None:
        pass


class PrivateMessage(_KeyPanel):
    """Composing a PM to a player picked in the F7 list. Drawn as that
    list's footer, so the entry itself draws nothing."""

    name = "pm"

    @property
    def visible(self) -> bool:
        return self.game.chat.pm_target_id is not None

    def handle_key(self, event) -> None:
        self.game._handle_pm_input(event)

    def close(self) -> None:
        self.game.chat.pm_target_id = None


class PlayerList(_KeyPanel):
    """F7 player list."""

    name = "player_list"

    @property
    def visible(self) -> bool:
        return bool(getattr(self.game, 'show_player_list', False))

    def handle_key(self, event) -> None:
        self.game._handle_player_list_key(event)

    def draw(self, surface) -> None:
        if self.visible:
            self.hud._draw_player_list(surface)

    def close(self) -> None:
        self.game.show_player_list = False


class ServerList(_KeyPanel):
    """F8 server list."""

    name = "server_list"

    @property
    def visible(self) -> bool:
        return bool(getattr(self.game, 'show_server_list', False))

    def handle_key(self, event) -> None:
        self.game._handle_server_list_key(event)

    def draw(self, surface) -> None:
        if self.visible:
            self.hud._draw_server_list(surface)

    def close(self) -> None:
        self.game.show_server_list = False


class Settings(_UIObjectPanel):
    """F9 settings."""

    name = "settings"
    attr = "settings_ui"

    def draw(self, surface) -> None:
        if self.visible:
            self.hud._draw_settings(surface)


class BigMap(Overlay):
    """M: the large map. Modal: M or Escape close it and every other key is
    swallowed; it swallows mouse input too (but not a window resize), so
    nothing reaches the editor, the inventory, camera zoom or the world."""

    name = "big_map"

    @property
    def visible(self) -> bool:
        return bool(getattr(self.game, 'big_map_visible', False))

    def handle_event(self, event) -> bool:
        if not self.visible or event.type == pygame.VIDEORESIZE:
            return False
        if event.type == KEYDOWN and event.key in keymap.keys_for("map", "back"):
            self.close()
        return True

    def draw(self, surface) -> None:
        if self.visible:
            self.hud._draw_big_map(surface)

    def close(self) -> None:
        self.game.big_map_visible = False


class Help(Overlay):
    """H: the controls overlay. Passive (H toggles it from gameplay); hidden
    while chat is typed, in debug mode and under the inventory."""

    name = "help"

    @property
    def visible(self) -> bool:
        return bool(getattr(self.game, 'show_help', False))

    @property
    def captures_keys(self) -> bool:
        return False

    def draw(self, surface) -> None:
        g = self.game
        if (self._hud_shown() and self.visible
                and not (g.chat.typing or g.debug_mode or g.inventory_ui.visible)):
            self.hud._draw_help_overlay(surface)

    def close(self) -> None:
        self.game.show_help = False


class ChatInput(_KeyPanel):
    """Typed chat (Enter). Draws the chat log as well as the entry line; a
    full stop hides the log but keeps the entry line usable."""

    name = "chat"

    @property
    def visible(self) -> bool:
        return bool(self.game.chat.typing)

    def handle_key(self, event) -> None:
        self.game._handle_chat_input(event)

    def draw(self, surface) -> None:
        if self._hud_shown():
            self.hud._draw_chat(surface)
        elif self.visible:
            self.hud._draw_chat(surface, show_log=False)

    def close(self) -> None:
        self.game.chat.typing = False
        self.game.chat.input = ""


class Dialogue(_KeyPanel):
    """The say2/sign dialogue box. A/S/Space turn its page, the arrows and
    PageUp/PageDown scroll it, the overlay F-keys still work, and every
    other key is swallowed."""

    name = "dialogue"

    @property
    def visible(self) -> bool:
        return getattr(self.game, 'dialogue_text', None) is not None

    def handle_key(self, event) -> None:
        g = self.game
        if event.key in keymap.keys_for("grab", "sword"):
            # This keystroke belongs to the dialog, and a consumed key is
            # never latched for gameplay: dismissing the last page does not
            # re-fire _try_grab and re-open the sign under the player (live
            # on bomber v6 the dialog once wrapped to page 0 forever).
            g._advance_dialogue()
        elif event.key in (K_UP, K_DOWN, K_PAGEUP, K_PAGEDOWN):
            page = g.dialogue_pager.page_size
            g.dialogue_pager.scroll({K_UP: -1, K_DOWN: 1, K_PAGEUP: -page,
                                     K_PAGEDOWN: page}[event.key])
        elif event.key in keymap.keys_for(*keymap.DIALOGUE_PASSTHROUGH):
            g._handle_key_press(event)

    def draw(self, surface) -> None:
        if self._hud_shown():
            self.hud._draw_dialogue(surface)

    def close(self) -> None:
        self.game._dismiss_dialogue()


class Inventory(Overlay):
    """Q: the inventory. Owns its opener while open, plus grid navigation
    and equip keys; nothing reaches gameplay or GS1. Takes mouse motion and
    clicks too."""

    name = "inventory"
    hud_layer = False

    @property
    def ui(self):
        return getattr(self.game, 'inventory_ui', None)

    @property
    def visible(self) -> bool:
        ui = self.ui
        return bool(ui is not None and ui.visible)

    def handle_event(self, event) -> bool:
        if not self.visible:
            return False
        ui = self.ui
        if event.type == KEYDOWN:
            ui.handle_key(event.key, self.game.client.weapons)
            return True
        if event.type == pygame.MOUSEMOTION:
            ui.handle_mouse_motion(event.pos)
            return True
        if event.type == MOUSEBUTTONDOWN:
            if event.button == 1:
                ui.handle_click(event.pos, self.game.client.weapons)
            return True
        return False

    def draw(self, surface) -> None:
        ui = self.ui
        if ui is not None:
            client = self.game.client
            ui.render(client.player, client.weapons)

    def close(self) -> None:
        if self.visible:
            self.ui.hide()


#: The stack, topmost first. This order IS the input priority; draw order is
#: its reverse.
OVERLAY_TYPES = (
    ServerWarpPrompt,
    GS2Gui,
    DebugReadouts,
    HudNotice,
    RCTools,
    DevTools,
    LevelEditorKeys,
    PrivateMessage,
    PlayerList,
    ServerList,
    Settings,
    BigMap,
    LevelEditorPointer,
    Help,
    ChatInput,
    Dialogue,
    Inventory,
)


def build_overlays(game, hud=None) -> List[Overlay]:
    """One entry per OVERLAY_TYPES row, bound to `game` (and to `hud` for
    the HUD-drawn entries, when the game has none of its own)."""
    return [kind(game, hud) for kind in OVERLAY_TYPES]


def find(overlays, name: str) -> Optional[Overlay]:
    for overlay in overlays:
        if overlay.name == name:
            return overlay
    return None
