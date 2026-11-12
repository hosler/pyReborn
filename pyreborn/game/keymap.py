"""The pygame client's gameplay keys, in one table.

Each `KeyAction` names an action, its default key(s), the row it shows in the
H help overlay (if any) and the GS1 `keydown(i)` control-function index it
feeds (if any). The help overlay, the key-press dispatch, held-key gameplay,
the GS1 key mirror and revive-on-input all read this table; nothing else in
the game spells a gameplay key.

The overlays' own navigation keys (list Up/Down, the RC panel's tab keys, the
editor's tool keys, ...) are the overlays' business and are not here.

GS1 indices follow the control-function table in scripting-gs1-functions.md:
0=up 1=left 2=down 3=right 4=weapon(D) 5=sword(S/Space) 6=grab(A) 7=map(M)
8=chat(Tab) 9=inventory(Q). Index 10 (pause) has no bound key here: P pauses
the player, but scripts never saw it as keydown(10) and still do not.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from pygame.locals import (
    K_0, K_DOWN, K_ESCAPE, K_F1, K_F2, K_F7, K_F8, K_F9, K_F10, K_F11, K_F12,
    K_LEFT, K_PAGEDOWN, K_PAGEUP, K_RETURN, K_RIGHT, K_SPACE, K_TAB, K_UP,
    K_a, K_d, K_h, K_m, K_n, K_p, K_q, K_s,
)


@dataclass(frozen=True)
class KeyAction:
    name: str
    keys: Tuple[int, ...]
    #: (key label, description) row in the help overlay, in table order.
    help: Optional[Tuple[str, str]] = None
    #: GS1 keydown(i) index this action's keys hold down, or None.
    gs1_index: Optional[int] = None


KEYMAP: Tuple[KeyAction, ...] = (
    KeyAction("move_up", (K_UP,), ("Arrow Keys", "Move"), gs1_index=0),
    KeyAction("move_left", (K_LEFT,), gs1_index=1),
    KeyAction("move_down", (K_DOWN,), gs1_index=2),
    KeyAction("move_right", (K_RIGHT,), gs1_index=3),
    KeyAction("grab", (K_a,), ("A", "Grab / Pick up / Throw"), gs1_index=6),
    KeyAction("sword", (K_s, K_SPACE), ("S or Space", "Swing sword"),
              gs1_index=5),
    KeyAction("weapon", (K_d,), ("D", "Use weapon"), gs1_index=4),
    KeyAction("inventory", (K_q,), ("Q", "Inventory"), gs1_index=9),
    KeyAction("zoom_reset", (K_0,), ("Wheel / 0", "Zoom / reset")),
    KeyAction("map", (K_m,), ("M", "Open map"), gs1_index=7),
    KeyAction("noclip", (K_n,), ("N", "Noclip (walk through walls)")),
    KeyAction("chat", (K_RETURN,), ("Enter", "Chat")),
    KeyAction("debug", (K_F1,), ("F1", "Debug / tile editor")),
    KeyAction("unstick", (K_F2,), ("F2", "Unstick: warp to (30,30)")),
    KeyAction("player_list", (K_F7,), ("F7", "Player list / PM")),
    KeyAction("server_list", (K_F8,), ("F8", "Server list")),
    KeyAction("settings", (K_F9,), ("F9", "Settings")),
    KeyAction("rc_tools", (K_F10,), ("F10", "RC tools (staff)")),
    KeyAction("level_editor", (K_F11,), ("F11", "Level edit mode (staff)")),
    KeyAction("dev_tools", (K_F12,), ("F12", "Dev playground (staff)")),
    KeyAction("chat_scroll_back", (K_PAGEUP,),
              ("PageUp/Down", "Scroll chat log")),
    KeyAction("chat_scroll_forward", (K_PAGEDOWN,)),
    KeyAction("help", (K_h,), ("H", "Close this help")),
    KeyAction("pause", (K_p,)),
    KeyAction("back", (K_ESCAPE,)),
    # S held is also a modifier: with D it cycles weapons, with A it selects
    # an item to give away (TPlayer.cpp:2272-2297). Space swings the sword
    # but is not the modifier.
    KeyAction("item_combo", (K_s,)),
    # The scripts' chat control (keydown(8)); typed chat opens on Enter.
    KeyAction("script_chat", (K_TAB,), gs1_index=8),
)

ACTIONS: Dict[str, KeyAction] = {action.name: action for action in KEYMAP}
assert len(ACTIONS) == len(KEYMAP), "duplicate action name in KEYMAP"

#: The four walking directions in the order the movement loop applies them,
#: with their (dx, dy).
MOVE_ACTIONS: Tuple[Tuple[str, Tuple[int, int]], ...] = (
    ("move_up", (0, -1)), ("move_left", (-1, 0)),
    ("move_down", (0, 1)), ("move_right", (1, 0)),
)
MOVE_NAMES: Tuple[str, ...] = tuple(name for name, _ in MOVE_ACTIONS)

#: Gameplay input that revives a dead player once the death animation has
#: played (FourPlay TPlayer.cpp:2164).
REVIVE_ACTIONS: Tuple[str, ...] = MOVE_NAMES + ("grab", "sword", "weapon")

#: The actions a single key press triggers in gameplay
#: (InputMixin._handle_key_press). Their keys must not overlap.
PRESS_ACTIONS: Tuple[str, ...] = (
    "pause", "back", "chat", "inventory", "zoom_reset", "debug", "unstick",
    "player_list", "server_list", "settings", "rc_tools", "level_editor",
    "dev_tools", "chat_scroll_back", "chat_scroll_forward", "help", "map",
    "noclip",
)

#: The press actions an open dialogue box lets through (its own keys are
#: advance and scroll; everything else is swallowed).
DIALOGUE_PASSTHROUGH: Tuple[str, ...] = (
    "debug", "unstick", "player_list", "server_list", "settings", "rc_tools",
    "level_editor", "dev_tools",
)


def keys_for(*names: str) -> Tuple[int, ...]:
    """Every key bound to any of the named actions, in table order."""
    return tuple(key for name in names for key in ACTIONS[name].keys)


def held(pressed, *names: str) -> bool:
    """True when a key of any named action is down in `pressed` (the
    pygame.key.get_pressed() sequence, or any key-indexed mapping)."""
    return any(pressed[key] for key in keys_for(*names))


def pressed_now(just_pressed: Mapping[int, bool], *names: str) -> bool:
    """True when a key of any named action went down this frame."""
    return any(just_pressed.get(key, False) for key in keys_for(*names))


def _press_table() -> Dict[int, str]:
    table: Dict[int, str] = {}
    for name in PRESS_ACTIONS:
        for key in ACTIONS[name].keys:
            assert key not in table, f"key {key} bound to two press actions"
            table[key] = name
    return table


_PRESS_BY_KEY = _press_table()


def press_action(key: int) -> Optional[str]:
    """The gameplay press action bound to `key`, or None."""
    return _PRESS_BY_KEY.get(key)


#: (keydown index, keys) for the GS1 key mirror.
GS1_KEYDOWN: Tuple[Tuple[int, Tuple[int, ...]], ...] = tuple(
    (action.gs1_index, action.keys) for action in KEYMAP
    if action.gs1_index is not None)


def gs1_keydown_indices(pressed) -> set:
    """The GS1 keydown(i) indices the held keys hold down."""
    return {index for index, keys in GS1_KEYDOWN
            if any(pressed[key] for key in keys)}


def help_lines(actions: Iterable[KeyAction] = KEYMAP) -> List[Tuple[str, str]]:
    """The help overlay's (key label, description) rows, in table order."""
    return [action.help for action in actions if action.help is not None]
