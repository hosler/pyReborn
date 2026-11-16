"""Locate optional captures without reading data or skipping during import.

PYREBORN_TEST_FIXTURES_DIR overrides the root containing the capture directories
so tests can exercise their absence without changing local files.
"""

import os
from pathlib import Path

import pytest


CAPTURE_NAMES = ('bomber_room0', 'bomber_lobby_shop', 'bomber_lobby_tailor')


def fixtures_root() -> Path:
    return Path(os.environ.get('PYREBORN_TEST_FIXTURES_DIR',
                               Path(__file__).resolve().parents[1] / 'fixtures'))


def missing_capture_reason(name: str) -> str:
    return (f'{name} fixture data not present (uncommitted:'
            ' third-party server scripts)')


def require_capture(name: str) -> Path:
    path = fixtures_root() / name
    if not path.is_dir():
        pytest.skip(missing_capture_reason(name))
    return path
