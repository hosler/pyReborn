"""game/editor — the in-game level editor for staff.

`LevelEditor` is the entry point: `game/input.py` offers it every event while
edit mode is on, and `game/hud.py` draws its overlay and palette last.

    state.py    tools, brush geometry, undo/redo, selection (pure, testable)
    editor.py   the wire: board edits, object commands, save/reload, input
    palette.py  the tileset picker
    overlay.py  grid, brush cursor, object markers, toolbar
"""

from .editor import LevelEditor
from .overlay import EditorOverlay
from .palette import TilePalette
from .state import (
    OBJECT, OBJECT_KINDS, PAINT, PICKER, RECT, SELECT, TOOLS, BoardEdit,
    EditorState,
)

__all__ = [
    "LevelEditor",
    "EditorOverlay",
    "TilePalette",
    "EditorState",
    "BoardEdit",
    "TOOLS",
    "OBJECT_KINDS",
    "PAINT",
    "RECT",
    "PICKER",
    "SELECT",
    "OBJECT",
]
