"""Locate the native GS2 compiler (gs2test) for tests that compile real scripts.

The binary is a gitignored build product of reborn-protocol
(tests/tools/build_gs2test.sh). A checkout, CI included, may not have it, so a
module that compiles at import time calls `require_compiler()` first and skips
as a whole, with the reason, instead of erroring at collection.
Lookup is reborn_protocol's own: GS2TEST_BIN, the installed checkout's
tests/tools/gs2test, then PATH. Nothing here guesses a sibling directory.
"""

import pytest
from reborn_protocol.gs2.compiler import find_compiler


def require_compiler() -> str:
    """Return the gs2test path, or skip the calling module when it is absent."""
    binary = find_compiler()
    if binary is None:
        pytest.skip(
            "gs2test compiler not built (run reborn-protocol/tests/tools/"
            "build_gs2test.sh or set GS2TEST_BIN)",
            allow_module_level=True)
    return binary
