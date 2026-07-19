"""game/settings_ui.py — the F9 in-game settings overlay.

The client previously had no settings UI at all; prefs.py was a config-file-
only affair (login/window prefill, read once at startup). This gives the
player a modal overlay to tune the handful of live-adjustable settings that
exist: sound volume, background music on/off, the day/night ambient tint
(prefs.day_night), the minimap, and zoom.

Follows the same modal-overlay shape as the F7 player list / F8 server list
(see game/input.py's KEYDOWN dispatch chain and game/hud.py's
`_draw_list_overlay`) but owns its own `.visible`/`.selected` state instead
of a `game.show_x` flag -- the same pattern InventoryUI already uses -- since
GameClient.__init__ (pygame_game.py) isn't a file this module wires into.
`game/input.py` lazily constructs one instance per GameClient on first touch
(`_ensure_settings_ui`) and applies the saved prefs into live state at that
point, since there's no earlier hook available here.

Each row is a value (not a pick-to-open-a-submenu entry): Up/Down selects a
row, Left/Right/Enter adjusts or toggles it in place. Every change applies
live immediately (volume/toggle/zoom take effect the same frame) and is
persisted to prefs.json via Prefs.save() so it survives the next launch.
"""

from typing import Callable, List, Optional

from pygame.locals import K_ESCAPE, K_F9, K_UP, K_DOWN, K_LEFT, K_RIGHT, K_RETURN

from ..prefs import Prefs

VOLUME_STEP = 0.1          # per Left/Right keypress
ZOOM_KEY_STEP = 1.25       # multiplicative, per Left/Right keypress (mouse
                           # wheel in input.py uses a finer 1.1 per notch)


class _Setting:
    """One adjustable settings row.

    `text_fn` renders the current value for display; `left`/`right` mutate
    live state (and persist it) in either direction. `enter` is a separate
    hook because Enter's natural meaning differs by row: for a toggle it's
    "flip it" (same as either arrow), for a numeric value it's "advance it"
    (same as Right) -- both are covered by defaulting `enter` to `right`.
    """

    def __init__(self, label: str, text_fn: Callable[[], str],
                 left: Callable[[], None], right: Callable[[], None],
                 enter: Optional[Callable[[], None]] = None):
        self.label = label
        self.text_fn = text_fn
        self.left = left
        self.right = right
        self.enter = enter or right


class SettingsOverlay:
    """Owns the F9 overlay's state: open/closed, selected row, and the list
    of adjustable settings. One instance per GameClient (lazily created --
    see game/input.py's `_ensure_settings_ui`)."""

    def __init__(self, game):
        self.game = game
        self.visible = False
        self.selected = 0
        # Loaded once and kept around (rather than Prefs.load() per edit) so
        # unrelated fields (username/password/last_server/...) aren't
        # clobbered by a stale re-read between edits, and so every save
        # writes through the same object.
        self._prefs = Prefs.load()
        self._settings: List[_Setting] = self._build_settings()

    # -- lifecycle ----------------------------------------------------------
    def apply_saved_prefs(self) -> None:
        """Push prefs.json's saved values into live state. Called once, the
        first time the overlay is touched -- there's no earlier hook in this
        module for a true "at GameClient construction" apply, so this runs
        on the game loop's very first `_handle_events()` call instead
        (before the first frame is drawn)."""
        p = self._prefs
        g = self.game
        g.sound_mgr.set_volume(p.sound_volume)
        g.sound_mgr.set_music_enabled(p.music_enabled)
        g.minimap_visible = p.minimap_visible
        g.camera.zoom = p.zoom
        # Mirrors render_effects.py's own lazy `_day_night_enabled` cache
        # (see _render_screen_tint) -- setting it here means that lazy
        # Prefs.load() never has to fire since it's already populated.
        g._day_night_enabled = p.day_night

    def toggle(self) -> None:
        self.visible = not self.visible
        if self.visible:
            self.selected = min(self.selected, len(self._settings) - 1)

    def close(self) -> None:
        self.visible = False

    # -- persistence ----------------------------------------------------------
    def _save(self, **fields) -> None:
        for name, value in fields.items():
            setattr(self._prefs, name, value)
        self._prefs.save()

    # -- row definitions ------------------------------------------------------
    def _build_settings(self) -> List[_Setting]:
        g = self.game

        def volume_text():
            return f"{round(g.sound_mgr.volume * 100)}%"

        def volume_by(delta):
            def _adjust():
                v = round(max(0.0, min(1.0, g.sound_mgr.volume + delta)), 2)
                g.sound_mgr.set_volume(v)
                self._save(sound_volume=v)
            return _adjust

        def music_text():
            return "On" if g.sound_mgr.music_enabled else "Off"

        def music_toggle():
            v = not g.sound_mgr.music_enabled
            g.sound_mgr.set_music_enabled(v)
            self._save(music_enabled=v)

        def day_night_text():
            return "On" if getattr(g, '_day_night_enabled', True) else "Off"

        def day_night_toggle():
            v = not getattr(g, '_day_night_enabled', True)
            g._day_night_enabled = v
            self._save(day_night=v)

        def minimap_text():
            return "On" if g.minimap_visible else "Off"

        def minimap_toggle():
            g.minimap_visible = not g.minimap_visible
            self._save(minimap_visible=g.minimap_visible)

        def zoom_text():
            return f"{round(g.camera.zoom * 100)}%"

        def zoom_by(factor):
            def _adjust():
                g.camera.zoom_by(factor)   # Camera2D clamps to MIN/MAX_ZOOM
                self._save(zoom=g.camera.zoom)
            return _adjust

        return [
            _Setting("Sound Volume", volume_text,
                     volume_by(-VOLUME_STEP), volume_by(VOLUME_STEP)),
            _Setting("Music", music_text, music_toggle, music_toggle),
            _Setting("Day/Night Tint", day_night_text,
                     day_night_toggle, day_night_toggle),
            _Setting("Minimap", minimap_text, minimap_toggle, minimap_toggle),
            _Setting("Zoom", zoom_text,
                     zoom_by(1.0 / ZOOM_KEY_STEP), zoom_by(ZOOM_KEY_STEP)),
        ]

    # -- input ----------------------------------------------------------------
    def handle_key(self, event) -> None:
        # F9 closes as well as opens, matching the F7/F8 overlays (their key
        # handlers re-check their own toggle key, since the dispatch chain
        # never falls through to the opener while the overlay is visible).
        if event.key in (K_ESCAPE, K_F9):
            self.close()
        elif event.key == K_UP:
            self.selected = max(0, self.selected - 1)
        elif event.key == K_DOWN:
            self.selected = min(len(self._settings) - 1, self.selected + 1)
        elif event.key == K_LEFT:
            self._settings[self.selected].left()
        elif event.key == K_RIGHT:
            self._settings[self.selected].right()
        elif event.key == K_RETURN:
            self._settings[self.selected].enter()

    # -- rendering --------------------------------------------------------------
    def rows(self) -> List[str]:
        """Label/value" lines for hud.py's `_draw_list_overlay` (same
        shared renderer the F7 player list uses)."""
        return [f"{s.label}: {s.text_fn()}" for s in self._settings]
