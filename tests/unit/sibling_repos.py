"""Where the sibling repos and local-only worlds are, wherever they are checked out.

Locally the three repos sit side by side in one workspace. In CI they are
installed editable from deps/ inside the pyReborn checkout, so "../reborn-protocol"
means nothing there. Locate them through the packages the suite already imports,
and skip (with the reason) what only exists on a developer machine.
"""

from pathlib import Path

import pytest
import reborn_protocol

PROTOCOL_ROOT = Path(reborn_protocol.__file__).resolve().parents[1]
PROTOCOL_FIXTURES = PROTOCOL_ROOT / "tests" / "fixtures"

# Developer workspace: sibling dirs of the pyReborn checkout. Absent in CI.
WORKSPACE = Path(__file__).resolve().parents[3]


def pygserver_root() -> Path:
    import pygserver
    return Path(pygserver.__file__).resolve().parents[1]


def require_workspace_dir(name: str) -> Path:
    """Return WORKSPACE/name, or skip the calling module when it is not there.

    For data that lives only in a developer's workspace (the funtimes-pygserver
    world, a third-party checkout): CI does not have it, so a test that needs
    it cannot run there.
    """
    path = WORKSPACE / name
    if not path.is_dir():
        pytest.skip(f"{name}/ is not checked out next to pyReborn "
                    f"(developer-workspace data; absent in CI)",
                    allow_module_level=True)
    return path
