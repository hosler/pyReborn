"""Guard: gmap grid lookups and the NPC wire-frame heuristic have one home.

The level-name -> grid cell reverse scan was copied 17 times and the
`raw >= LEVEL_SIZE or raw < 0` wire heuristic 6 times, and the copies drifted
(first vs last cell for a duplicated name). Both now live in
pyreborn/gmap_coords.py. This test fails when a new copy appears anywhere else
in pyreborn/ or game_tester/. Call grid_of / grid_index / level_origin /
world_from_local / local_from_world / world_from_wire instead.

Flagged shapes:
* a loop or comprehension over ``<...>gmap_grid.items()`` (or over a local
  that was assigned from one) that compares the level-name variable with
  ``==``, or that builds a ``{name: cell}`` reverse dict;
* a conditional expression whose test is ``v >= LEVEL_SIZE|64 or v < 0``.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / "pyreborn" / "gmap_coords.py"


def _sources():
    for package in ("pyreborn", "game_tester"):
        for path in sorted((ROOT / package).rglob("*.py")):
            if path != HOME:
                yield path


def _mentions_gmap_grid(node):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr == "gmap_grid":
            return True
        if isinstance(sub, ast.Name) and sub.id == "gmap_grid":
            return True
        if isinstance(sub, ast.Constant) and sub.value == "gmap_grid":
            return True
    return False


def _grid_names(tree):
    """Local names assigned from an expression that reads gmap_grid."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _mentions_gmap_grid(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _items_of_grid(iter_node, grid_names):
    if not (isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Attribute)
            and iter_node.func.attr == "items"):
        return False
    owner = iter_node.func.value
    return (_mentions_gmap_grid(owner)
            or (isinstance(owner, ast.Name) and owner.id in grid_names))


def _value_names(target):
    """Names bound to the VALUE (level name) of a ``cell, name`` target."""
    if isinstance(target, ast.Tuple) and len(target.elts) == 2:
        value = target.elts[1]
        if isinstance(value, ast.Name):
            return {value.id}
    return set()


def _compares_eq(nodes, names):
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Compare) and any(isinstance(op, ast.Eq) for op in sub.ops):
                operands = [sub.left, *sub.comparators]
                if any(isinstance(n, ast.Name) and n.id in names
                       for o in operands for n in ast.walk(o)):
                    return True
    return False


def _is_level_size(node):
    return ((isinstance(node, ast.Name) and node.id == "LEVEL_SIZE")
            or (isinstance(node, ast.Constant) and node.value == 64))


def _is_wire_heuristic(test):
    if not (isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or)):
        return False
    upper = lower = False
    for value in test.values:
        if isinstance(value, ast.Compare) and len(value.ops) == 1:
            op, right = value.ops[0], value.comparators[0]
            if isinstance(op, ast.GtE) and _is_level_size(right):
                upper = True
            if isinstance(op, ast.Lt) and isinstance(right, ast.Constant) and right.value == 0:
                lower = True
    return upper and lower


def _violations(path, source=None):
    if source is None:
        source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    grid_names = _grid_names(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and _items_of_grid(node.iter, grid_names):
            if _compares_eq(node.body, _value_names(node.target)):
                found.append((node.lineno, "reverse scan loop over gmap_grid"))
        elif isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)):
            for generator in node.generators:
                if not _items_of_grid(generator.iter, grid_names):
                    continue
                names = _value_names(generator.target)
                if _compares_eq(generator.ifs, names):
                    found.append((node.lineno, "reverse scan over gmap_grid"))
                if (isinstance(node, ast.DictComp) and isinstance(node.key, ast.Name)
                        and node.key.id in names):
                    found.append((node.lineno, "name -> cell reverse dict"))
                if (isinstance(node, ast.DictComp) and isinstance(node.key, ast.Call)
                        and any(isinstance(a, ast.Name) and a.id in names
                                for a in ast.walk(node.key))):
                    found.append((node.lineno, "name -> cell reverse dict"))
        elif isinstance(node, ast.IfExp) and _is_wire_heuristic(node.test):
            found.append((node.lineno, "raw >= LEVEL_SIZE wire heuristic"))
    return [f"{path}:{line}: {what}" for line, what in found]


def test_no_gmap_lookup_copies_outside_the_helper_module():
    violations = [v for path in _sources() for v in _violations(path)]
    assert not violations, (
        "use pyreborn.gmap_coords instead of a local copy:\n  "
        + "\n  ".join(violations))


def test_guard_catches_each_known_shape():
    samples = {
        "next((c for c, n in client.gmap_grid.items() if n == level), None)": 1,
        "{n: c for c, n in client.gmap_grid.items()}": 1,
        "next((c for c, n in getattr(x, 'gmap_grid', {}).items()"
        " if str(n).casefold() == lv), None)": 1,
        "for (gx, gy), name in gmap_grid.items():\n    if name == lvl:\n        pass": 1,
        "{n.casefold(): c for c, n in c.gmap_grid.items()}": 1,
        "g = c.gmap_grid\n{n: c for c, n in g.items()}": 1,
        "for (gx, gy), name in self.gmap_grid.items():\n    if name == lvl:\n        pass": 1,
        "w = raw if (raw >= LEVEL_SIZE or raw < 0) else raw + o": 1,
        "w = x if (x >= 64 or x < 0) else x + gx * 64": 1,
        # Not copies: forward lookups, origin listings, bounds checks.
        "client.gmap_grid.get((1, 2))": 0,
        "[(n, gx) for (gx, gy), n in self.gmap_grid.items()]": 0,
        "if tx < 0 or tx >= 64:\n    pass": 0,
    }
    for source, expected in samples.items():
        found = _violations(Path("<sample>"), source)
        assert len(found) == expected, (source, found)
