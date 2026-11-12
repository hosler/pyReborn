"""gs2_client.registry.gui_layer() under a concurrent first use.

The resolved flag used to be set BEFORE the GUI package import ran, so a
second thread constructing ClientGS2() during that import got a layer whose
members were still None (manager=None). The import here is a stand-in module
whose body blocks until the test releases it, so the window is held open.
"""

import importlib.abc
import importlib.util
import sys
import threading
import time

from pyreborn.gs2_client import registry

_FAKE_MODULE = "pyreborn_test_slow_gui_layer"


class _SlowGuiLayer(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.imports = 0

    def find_spec(self, name, path, target=None):
        if name != _FAKE_MODULE:
            return None
        return importlib.util.spec_from_loader(name, self)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        self.imports += 1
        self.started.set()
        assert self.release.wait(10), "test never released the import"
        registry.register_gui_layer("manager", "control", "popup",
                                    "method_names", "reset_fonts")


def test_second_thread_waits_for_the_import(monkeypatch):
    finder = _SlowGuiLayer()
    monkeypatch.setattr(registry, "_gui_layer", registry._GuiLayer())
    monkeypatch.setattr(registry, "_GUI_LAYER_MODULE", _FAKE_MODULE)
    sys.meta_path.insert(0, finder)
    seen = {}

    def first():
        seen["first"] = registry.gui_layer().manager

    def second():
        seen["second"] = registry.gui_layer().manager

    try:
        a = threading.Thread(target=first)
        a.start()
        assert finder.started.wait(10)
        b = threading.Thread(target=second)
        b.start()
        # Give the second thread time to reach gui_layer() while the import
        # is still blocked. With the old flag order it returned here.
        time.sleep(0.2)
        finder.release.set()
        a.join(10)
        b.join(10)
    finally:
        finder.release.set()
        sys.meta_path.remove(finder)
        sys.modules.pop(_FAKE_MODULE, None)

    assert seen == {"first": "manager", "second": "manager"}
    assert finder.imports == 1
    assert registry._gui_layer.resolved


def test_failed_import_still_resolves(monkeypatch):
    monkeypatch.setattr(registry, "_gui_layer", registry._GuiLayer())
    monkeypatch.setattr(registry, "_GUI_LAYER_MODULE",
                        "pyreborn_test_missing_gui_layer")
    layer = registry.gui_layer()
    assert layer.manager is None
    assert layer.resolved
