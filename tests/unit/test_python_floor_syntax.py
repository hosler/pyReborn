"""Every first-party source file must parse at the declared Python floor.

CI runs the oldest supported interpreter, but a developer on a newer one can
write syntax the floor rejects (f-string expressions with a backslash, PEP 695
generics) and see nothing locally. `ast.parse(feature_version=...)` catches what
the grammar gates by version. It does not catch a 3.12 tokenizer relaxation, so
the f-string backslash rule is checked on its own. The real proof stays a
run on the floor interpreter (the CI matrix).
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "__pycache__", "pyreborn.egg-info", "build", "dist", ".venv"}


def _floor():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^requires-python\s*=\s*">=(\d+)\.(\d+)', text, re.M)
    assert match, "pyproject.toml has no requires-python lower bound"
    return int(match.group(1)), int(match.group(2))


def _sources():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if SKIP_DIRS.intersection(rel.parts):
            continue
        # CI checks sibling repos out under deps/; they are not ours to gate.
        if rel.parts[0] == "deps":
            continue
        yield path


def _fstring_backslashes(tree, source):
    for node in ast.walk(tree):
        if isinstance(node, ast.FormattedValue):
            segment = ast.get_source_segment(source, node.value) or ""
            if "\\" in segment:
                yield node.lineno


def test_floor_is_declared():
    assert _floor() >= (3, 8)


@pytest.mark.parametrize("path", list(_sources()),
                         ids=lambda p: str(p.relative_to(ROOT)))
def test_parses_at_declared_floor(path):
    source = path.read_text(encoding="utf-8")
    floor = _floor()
    tree = ast.parse(source, filename=str(path), feature_version=floor)
    lines = list(_fstring_backslashes(tree, source))
    assert not lines, (
        f"{path.name}:{lines[0]}: backslash inside an f-string expression "
        f"is a SyntaxError before Python 3.12 (floor is {floor[0]}.{floor[1]})")
