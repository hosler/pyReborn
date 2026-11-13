"""The ``TYPE_CHECKING`` method stubs in game/host.py match the real methods.

``GameHost`` carries a stub for every method or property that one mixin calls
on another, so mypy can check those calls. Nothing under ``TYPE_CHECKING``
runs, so only this test can notice a stub that drifted from the method it
copies. Each stub is compiled here (outside the class, in the globals of the
real method's module, so default expressions resolve to the same objects) and
its ``inspect.signature`` must equal the real one: parameter names, kinds,
defaults and annotations.

A new cross-mixin call needs a stub (mypy reports it as ``attr-defined``); a
stub whose method is gone or renamed fails ``test_every_stub_names_a_real_method``.
"""

import __future__
import ast
import inspect
from pathlib import Path

import pytest

from pyreborn.game.host import GameHost
from pyreborn.pygame_game import GameClient

HOST = Path(inspect.getsourcefile(GameHost))


def _stub_defs():
    """The FunctionDef nodes of the ``if TYPE_CHECKING:`` block in GameHost."""
    tree = ast.parse(HOST.read_text())
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "GameHost")
    blocks = [n for n in cls.body
              if isinstance(n, ast.If)
              and ast.unparse(n.test) == "TYPE_CHECKING"]
    assert blocks, "GameHost has no `if TYPE_CHECKING:` stub section"
    return [n for b in blocks for n in b.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


STUBS = _stub_defs()


def _real(name):
    """The method as defined on the first MRO class that has it."""
    for cls in GameClient.__mro__:
        if cls is GameHost:
            break
        if name in vars(cls):
            attr = vars(cls)[name]
            if isinstance(attr, property):
                return attr.fget
            if isinstance(attr, (staticmethod, classmethod)):
                return attr.__func__
            return attr
    return None


def _compile_stub(node, real):
    """The stub as a function object, built in the real method's globals."""
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    glob = dict(real.__globals__)
    future = glob.get("annotations") is __future__.annotations
    code = compile(module, str(HOST), "exec",
                   flags=__future__.annotations.compiler_flag if future else 0,
                   dont_inherit=True)
    exec(code, glob)
    obj = glob[node.name]
    if isinstance(obj, property):
        return obj.fget
    if isinstance(obj, (staticmethod, classmethod)):
        return obj.__func__
    return obj


def test_there_are_stubs():
    assert len(STUBS) > 50


def test_stubs_are_not_runtime_attributes():
    """Nothing under TYPE_CHECKING executes: no stub is a GameHost attribute."""
    leaked = sorted(s.name for s in STUBS if s.name in vars(GameHost))
    assert not leaked, leaked


def test_stub_names_are_unique():
    names = [s.name for s in STUBS]
    assert len(names) == len(set(names))


def test_every_stub_names_a_real_method():
    gone = sorted(s.name for s in STUBS if _real(s.name) is None)
    assert not gone, (
        "stub with no method of that name on any GameClient mixin (the "
        "method was renamed or deleted: update or delete the stub): %s" % gone)


@pytest.mark.parametrize("node", STUBS, ids=lambda n: n.name)
def test_stub_signature_equals_the_real_method(node):
    real = _real(node.name)
    assert real is not None, "%s: no such method" % node.name
    stub = _compile_stub(node, real)
    got, want = inspect.signature(stub), inspect.signature(real)
    assert got == want, (
        "stub %s%s differs from the real method %s%s (defined in %s)"
        % (node.name, got, node.name, want, real.__qualname__))


@pytest.mark.parametrize("node", STUBS, ids=lambda n: n.name)
def test_stub_kind_equals_the_real_kind(node):
    """A property stays a property, a staticmethod a staticmethod."""
    for cls in GameClient.__mro__:
        if node.name in vars(cls):
            attr = vars(cls)[node.name]
            break
    else:
        pytest.fail("%s: no such method" % node.name)
    want = type(attr).__name__ if isinstance(
        attr, (property, staticmethod, classmethod)) else "function"
    decos = [ast.unparse(d) for d in node.decorator_list]
    got = decos[0] if decos else "function"
    assert got == want, "stub is %r, real method is %r" % (got, want)
