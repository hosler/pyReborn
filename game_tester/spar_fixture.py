"""Deterministic spar arena, installed before pygserver registers level NPCs."""

from pathlib import Path

from .fixtures import FixtureFile

SPAR_LEVEL = "qa_sparzone.nw"


def spar_level_text() -> str:
    # Tile 0 is open floor; all combat happens around (30, 30).
    rows = [f"BOARD 0 {y} 64 0 {'AA' * 64}" for y in range(64)]
    return "\n".join(["GLEVNW01", *rows,
                       "NPC - 2 2", "//#CLIENTSIDE", "sparringzone", "NPCEND", ""])


def spar_fixture(world_dir) -> FixtureFile:
    """The arena as a removable fixture (see game_tester.fixtures)."""
    return FixtureFile(world_dir, SPAR_LEVEL, spar_level_text().encode())


def spar_fixture_ready(world_dir) -> bool:
    """True when the arena is already in `world_dir` with the right content."""
    path = Path(world_dir) / SPAR_LEVEL
    try:
        return path.is_file() and path.read_text() == spar_level_text()
    except OSError:
        return False


def write_spar_fixture(world_dir) -> bool:
    """Write only when necessary; return whether startup/reload is needed.

    Leaves the file behind: callers that provision for a bounded run use
    spar_fixture() and release it (qa_server records it for `stop`)."""
    directory = Path(world_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SPAR_LEVEL
    text = spar_level_text()
    if path.is_file() and path.read_text() == text:
        return False
    path.write_text(text)
    return True
