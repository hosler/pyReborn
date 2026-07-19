"""game/settings_ui.py (F9 settings overlay) + hud.py's chat-scrollback math.

Two things are testable headlessly without a real GameClient/network Client:
1. SettingsOverlay's adjust/toggle logic against a small fake `game` stub
   (real SoundManager + Camera2D, since neither needs a live pygame display),
   including that every change round-trips through prefs.json.
2. hud.chat_window's pure scroll-window arithmetic (PageUp/PageDown).

SDL_VIDEODRIVER/SDL_AUDIODRIVER are forced to "dummy" (matches the rest of
tests/unit/) so this runs in CI/headless without a display or audio device.
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

import pygame.locals as pgl
import pytest

from pyreborn.game.camera import Camera2D
from pyreborn.game.hud import chat_window
from pyreborn.game.settings_ui import SettingsOverlay
from pyreborn.prefs import Prefs
from pyreborn.sounds import SoundManager


class _Key:
    """Minimal stand-in for a pygame KEYDOWN event -- handle_key only reads
    `.key`."""

    def __init__(self, key):
        self.key = key


class _FakeGame:
    """Just enough of GameClient's surface for SettingsOverlay to drive:
    a real SoundManager (its volume/music_enabled setters don't touch the
    mixer unless it's been initialize()'d) and a real Camera2D (zoom clamps
    identically to the live client)."""

    def __init__(self):
        self.sound_mgr = SoundManager()
        self.camera = Camera2D(640, 480)
        self.minimap_visible = True
        self._day_night_enabled = True


@pytest.fixture
def prefs_home(tmp_path, monkeypatch):
    """Point prefs.json at a throwaway directory so these tests never touch
    the user's real ~/.config/pyreborn/prefs.json."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def overlay(prefs_home):
    return SettingsOverlay(_FakeGame())


# -- Prefs round-trip for the new fields -------------------------------------

def test_prefs_defaults_match_pre_overlay_hardcoded_values():
    """Defaults must match what GameClient/SoundManager/Camera2D used before
    the overlay existed, so a first launch (no prefs.json yet) behaves
    exactly as it did before this feature."""
    p = Prefs()
    assert p.sound_volume == 1.0
    assert p.music_enabled is True
    assert p.minimap_visible is True
    assert p.zoom == 1.0
    assert p.day_night is True


def test_prefs_new_fields_round_trip(prefs_home):
    p = Prefs()
    p.sound_volume = 0.4
    p.music_enabled = False
    p.minimap_visible = False
    p.zoom = 2.0
    p.save()

    loaded = Prefs.load()
    assert loaded.sound_volume == 0.4
    assert loaded.music_enabled is False
    assert loaded.minimap_visible is False
    assert loaded.zoom == 2.0


# -- SettingsOverlay: adjust/toggle + live apply + persistence --------------

def test_volume_adjust_clamps_and_persists(overlay, prefs_home):
    row = [s for s in overlay._settings if s.label == "Sound Volume"][0]
    for _ in range(20):   # far more than needed to hit the 0.0 floor
        row.left()
    assert overlay.game.sound_mgr.volume == 0.0
    assert Prefs.load().sound_volume == 0.0

    for _ in range(20):   # ... and the 1.0 ceiling
        row.right()
    assert overlay.game.sound_mgr.volume == 1.0
    assert Prefs.load().sound_volume == 1.0


def test_music_toggle_live_and_persisted(overlay):
    row = [s for s in overlay._settings if s.label == "Music"][0]
    assert overlay.game.sound_mgr.music_enabled is True
    row.enter()
    assert overlay.game.sound_mgr.music_enabled is False
    assert Prefs.load().music_enabled is False
    row.enter()
    assert overlay.game.sound_mgr.music_enabled is True
    assert Prefs.load().music_enabled is True


def test_minimap_toggle_live_and_persisted(overlay):
    row = [s for s in overlay._settings if s.label == "Minimap"][0]
    row.left()   # left == right == toggle for boolean rows
    assert overlay.game.minimap_visible is False
    assert Prefs.load().minimap_visible is False


def test_day_night_toggle_live_and_persisted(overlay):
    row = [s for s in overlay._settings if s.label == "Day/Night Tint"][0]
    row.right()
    assert overlay.game._day_night_enabled is False
    assert Prefs.load().day_night is False


def test_zoom_adjust_clamps_to_camera_bounds_and_persists(overlay):
    row = [s for s in overlay._settings if s.label == "Zoom"][0]
    for _ in range(60):
        row.right()
    assert overlay.game.camera.zoom == Camera2D.MAX_ZOOM
    assert Prefs.load().zoom == Camera2D.MAX_ZOOM

    for _ in range(60):
        row.left()
    assert overlay.game.camera.zoom == Camera2D.MIN_ZOOM
    assert Prefs.load().zoom == Camera2D.MIN_ZOOM


def test_apply_saved_prefs_pushes_prefs_into_live_state(prefs_home):
    p = Prefs()
    p.sound_volume = 0.3
    p.music_enabled = False
    p.minimap_visible = False
    p.zoom = 1.5
    p.day_night = False
    p.save()

    game = _FakeGame()
    su = SettingsOverlay(game)
    su.apply_saved_prefs()

    assert game.sound_mgr.volume == 0.3
    assert game.sound_mgr.music_enabled is False
    assert game.minimap_visible is False
    assert game.camera.zoom == 1.5
    assert game._day_night_enabled is False


# -- keyboard dispatch --------------------------------------------------------

def test_handle_key_navigation_and_close(overlay):
    overlay.visible = True
    overlay.selected = 0
    overlay.handle_key(_Key(pgl.K_DOWN))
    assert overlay.selected == 1
    overlay.handle_key(_Key(pgl.K_UP))
    assert overlay.selected == 0
    # Can't select past either end.
    overlay.handle_key(_Key(pgl.K_UP))
    assert overlay.selected == 0

    overlay.handle_key(_Key(pgl.K_ESCAPE))
    assert overlay.visible is False


def test_toggle_reopens_at_a_valid_row(overlay):
    overlay.selected = len(overlay._settings) - 1
    overlay.toggle()
    assert overlay.visible is True
    assert overlay.selected == len(overlay._settings) - 1


def test_rows_render_label_colon_value(overlay):
    rows = overlay.rows()
    assert len(rows) == len(overlay._settings)
    assert rows[0].startswith("Sound Volume: ")


# -- hud.chat_window: PageUp/PageDown scroll math ----------------------------

def test_chat_window_default_shows_last_five():
    assert chat_window(total=12, scroll=0) == (7, 12)
    assert chat_window(total=3, scroll=0) == (0, 3)
    assert chat_window(total=0, scroll=0) == (0, 0)


def test_chat_window_scrolled_back():
    # 12 messages, scrolled 5 back from the tail -> a window of 5 ending
    # 5 short of the end.
    assert chat_window(total=12, scroll=5) == (2, 7)


def test_chat_window_scroll_past_start_clamps_to_empty_at_front():
    # Scrolling further back than history exists degrades to an empty/short
    # window rather than raising or wrapping negative.
    start, end = chat_window(total=12, scroll=20)
    assert 0 <= start <= end <= 12


def test_chat_window_matches_negative_slice_convention():
    """chat_window(total, 0) must always agree with the old `messages[-5:]`
    slice it replaced, for every history length."""
    for total in range(0, 15):
        messages = list(range(total))
        start, end = chat_window(total, 0)
        assert messages[start:end] == messages[-5:]


def test_f9_closes_settings_overlay(overlay):
    """F9 must close the overlay as well as open it (the dispatch chain never
    reaches the F9 opener while the overlay is visible, so the overlay's own
    key handler has to honor it -- same pattern as the F7/F8 overlays)."""
    overlay.visible = True
    overlay.handle_key(_Key(pgl.K_F9))
    assert overlay.visible is False


def test_chat_seq_counts_appends_past_history_cap():
    """The scroll indicator's "N new" math uses chat_seq, a monotonic append
    counter: unlike len(chat_messages), it keeps advancing once the log sits
    at CHAT_HISTORY_CAP (where every append pops a line)."""
    from pyreborn.game.constants import CHAT_HISTORY_CAP
    from pyreborn.game.setup import SetupMixin

    class _G(SetupMixin):
        chat_seq = 0

        def __init__(self):
            self.chat_messages = []

    g = _G()
    for i in range(CHAT_HISTORY_CAP):
        g._append_chat(f"m{i}")
    assert len(g.chat_messages) == CHAT_HISTORY_CAP

    baseline = g.chat_seq  # PageUp at a full log stores this
    for i in range(10):
        g._append_chat(f"new{i}")

    assert len(g.chat_messages) == CHAT_HISTORY_CAP  # pinned at the cap
    assert g.chat_seq - baseline == 10  # ...but the arrivals still count
