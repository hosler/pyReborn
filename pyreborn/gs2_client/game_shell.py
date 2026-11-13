"""What the GS2 runtime needs from the game that hosts it.

``ClientGS2.game_shell`` is None for headless users (game_tester bots, the
--gs2 tier) and the graphical GameClient otherwise. Every read of it in this
package goes through a member named here, so the library layer never reaches
into a host's private attributes. Each member is one the GS2 code actually
reads; do not add speculative ones.
"""

from typing import Any, Optional

try:  # Protocol is in typing from 3.8
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore

    def runtime_checkable(cls):  # type: ignore
        return cls


@runtime_checkable
class GameShell(Protocol):
    # -- display and input ---------------------------------------------------
    viewport: Any              # .mouse_pos() -> (x, y) in canvas pixels
    camera: Any                # Camera2D: zoom, center, world_to_screen, ...
    screen: Any                # current canvas surface
    fullscreen: bool
    camera_enabled: bool       # enabledefaultcamera() sets it True

    # -- assets ---------------------------------------------------------------
    sprite_mgr: Any
    sound_mgr: Any

    # -- player-facing state --------------------------------------------------
    inventory_ui: Any          # selected_weapon_idx / cursor_weapon_idx
    dialogue_text: Optional[str]
    dialogue_pager: Any
    player_anim: Any           # AnimationState
    current_anim_name: str
    day_night_enabled: bool

    def selected_weapon_full_index(self) -> int:
        """Equipped weapon's index in the full (hidden-included) weapon list."""

    def mark_script_owned_animation(self, name: str) -> None:
        """Record that a script set the player's gani to ``name``: a gani with
        no SETBACKTO then holds its last frame instead of falling back to
        idle (FourPlay quattroplay/src/TGaniObject.cpp:3224-3230). Both
        engines' setani call this."""

    def dismiss_dialogue(self) -> None:
        """Close the dialogue box."""

    def showtext_font(self, name: str, size: int, bold: bool) -> Any:
        """The font the showtext renderer uses for (name, size, bold)."""
