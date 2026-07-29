import json
import os

import pytest

from pyreborn.asset_paths import (
    content_dirs,
    expand_content_root,
    looks_like_client_install,
)
from pyreborn.prefs import Prefs, prefs_path


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("PYREBORN_CONTENT_DIR", raising=False)
    return tmp_path


def make_install(path):
    path.mkdir()
    (path / "pics1.png").touch()
    (path / "sprites.png").touch()
    (path / "sounds").mkdir()
    (path / "sounds" / "hit.wav").touch()
    levels = path / "levels"
    for name in (
        "ganis",
        "heads",
        "bodies",
        "baddies",
        "shields",
        "swords",
        "horses",
        "backpals",
        "images",
        "npcs",
        "bomys",
    ):
        (levels / name).mkdir(parents=True, exist_ok=True)
    (levels / "ganis" / "idle.gani").touch()
    (levels / "images" / "object.png").touch()
    return path


def test_detects_install_root(isolated_config):
    install = make_install(isolated_config / "client")

    assert looks_like_client_install(install)


def test_expands_install_root_to_root_and_levels(isolated_config):
    install = make_install(isolated_config / "client")

    assert expand_content_root(install) == [install, install / "levels"]


def test_expands_levels_path_to_root_and_levels(isolated_config):
    install = make_install(isolated_config / "client")

    assert looks_like_client_install(install / "levels")
    assert expand_content_root(install / "levels") == [install, install / "levels"]


def test_env_accepts_several_pathsep_entries(isolated_config, monkeypatch):
    first = make_install(isolated_config / "first")
    second = make_install(isolated_config / "second")
    monkeypatch.setenv(
        "PYREBORN_CONTENT_DIR", os.pathsep.join((str(first), str(second)))
    )

    assert content_dirs() == [
        first,
        first / "levels",
        second,
        second / "levels",
    ]


def test_prefs_content_dirs_round_trip_and_old_file_loads(isolated_config):
    prefs = Prefs(content_dirs=["/one", "/two"])
    prefs.save()

    assert Prefs.load().content_dirs == ["/one", "/two"]

    old_payload = {"username": "returning-user"}
    prefs_path().write_text(json.dumps(old_payload))
    loaded = Prefs.load()
    assert loaded.username == "returning-user"
    assert loaded.content_dirs == []


def test_nonexistent_entries_are_dropped(isolated_config, monkeypatch):
    missing = isolated_config / "missing"
    monkeypatch.setenv("PYREBORN_CONTENT_DIR", str(missing))

    assert content_dirs() == []


def test_content_roots_are_deduplicated(isolated_config, monkeypatch):
    install = make_install(isolated_config / "client")
    monkeypatch.setenv(
        "PYREBORN_CONTENT_DIR",
        os.pathsep.join((str(install), str(install / "levels"), str(install))),
    )
    prefs = Prefs(content_dirs=[str(install)])
    prefs.save()

    assert content_dirs() == [install, install / "levels"]
