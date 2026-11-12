"""Where, what and in which order the offline frame draws things.

The checks themselves are in tests/offline_checks.py (a module, so that
test_offline_render.py's self-check can run them under a deliberate renderer
mutation). Each is a colour at a pixel; see that module and
tests/offline_expect.py.
"""

import pytest

from offline_checks import POSITION_CHECKS


@pytest.mark.parametrize("name", sorted(POSITION_CHECKS))
def test_position(make_game, name):
    POSITION_CHECKS[name](make_game)
