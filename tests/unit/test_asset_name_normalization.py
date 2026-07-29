import io

import pygame

from pyreborn.asset_paths import user_content_dir
from pyreborn.gani import GaniParser
from pyreborn.sounds import SoundManager
from pyreborn.sprites import SpriteManager


def _png_bytes(color=(20, 40, 60, 255)):
    surface = pygame.Surface((2, 2), pygame.SRCALPHA)
    surface.fill(color)
    stream = io.BytesIO()
    pygame.image.save(surface, stream, "asset.png")
    return stream.getvalue()


def test_lowercase_sheet_resolves_for_mixed_case_request(tmp_path):
    (tmp_path / "body.png").write_bytes(_png_bytes())
    manager = SpriteManager([tmp_path])

    assert manager.load_sheet("Body.PNG") is not None
    assert list(manager.sheet_cache) == ["body.png"]


def test_prefixed_names_resolve_to_the_bare_file(tmp_path):
    (tmp_path / "body.png").write_bytes(_png_bytes())
    manager = SpriteManager([tmp_path])

    first = manager.load_sheet("levels/images/body.png")
    second = manager.load_sheet(r"levels\images\BODY.PNG")

    assert first is second
    assert list(manager.sheet_cache) == ["body.png"]


def test_two_casings_share_one_cache_entry_and_request():
    requests = []

    def request(name):
        requests.append(name)
        return None

    manager = SpriteManager([], fetch_bytes=request)

    assert manager.load_sheet("Body.PNG") is None
    assert manager.load_sheet("body.png") is None
    assert requests == ["body.png"]
    assert manager._missing_sheets == {"body.png"}


def test_user_content_fallback_finds_mixed_case_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PYREBORN_CONTENT_DIR", str(tmp_path))
    (tmp_path / "BoDy.PnG").write_bytes(_png_bytes())
    manager = SpriteManager([user_content_dir()])

    assert manager.load_sheet("body.png") is not None
    assert list(manager.sheet_cache) == ["body.png"]


def test_arriving_bytes_supersede_negative_cache():
    manager = SpriteManager([])

    assert manager.load_sheet("images/Body.PNG") is None
    assert manager._missing_sheets == {"body.png"}

    loaded = manager.load_bytes(r"downloads\BODY.png", _png_bytes())

    assert loaded is not None
    assert manager._missing_sheets == set()
    assert manager.load_sheet("Body.PNG") is loaded
    assert list(manager.sheet_cache) == ["body.png"]


def test_gani_casings_share_one_negative_entry_and_request():
    requests = []
    manager = GaniParser([], fetch_bytes=lambda name: requests.append(name))

    assert manager.parse(r"ganis\IDLE.GANI") is None
    assert manager.parse("idle") is None
    assert requests == ["idle.gani"]
    assert manager.cache == {"idle": None}


def test_sound_casings_share_failure_and_request(monkeypatch):
    requests = []
    manager = SoundManager([])
    manager.file_requester = requests.append
    monkeypatch.setattr(manager, "initialize", lambda: None)

    assert manager.load(r"sounds\SWORD.WAV") is None
    assert manager.load("sword.wav") is None
    assert requests == ["sword.wav"]
    assert manager._sound_failed == {"sword.wav"}
