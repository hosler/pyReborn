"""Per-run scratch directory for the live visual scripts' screenshots.

Those scripts used to write fixed names into bare /tmp, where nothing removed
them. They now write under one `tempfile.mkdtemp` that is deleted at interpreter
exit. Set PYREBORN_QA_KEEP_SCRATCH=1 to keep it (the path is printed) when a
person wants to look at the images.
"""
import atexit
import os
import shutil
import tempfile

_DIR = None


def scratch_path(name: str) -> str:
    global _DIR
    if _DIR is None:
        _DIR = tempfile.mkdtemp(prefix="pyreborn_qa_")
        if os.environ.get("PYREBORN_QA_KEEP_SCRATCH"):
            print(f"[scratch] keeping {_DIR}")
        else:
            atexit.register(shutil.rmtree, _DIR, ignore_errors=True)
    return os.path.join(_DIR, name)
