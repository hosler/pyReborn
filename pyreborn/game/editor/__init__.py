"""game/editor — the in-game level editor for staff.

`LevelEditor` is the entry point. Its two entries in the overlay stack
(game/overlays.py: `LevelEditorKeys` above the panels, `LevelEditorPointer`
below the big map) offer it keys and mouse events while edit mode is on, and
the keyboard entry draws its overlay and palette under the panels.

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
