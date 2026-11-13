"""Log a deliberately swallowed exception once per site.

``except Exception:`` blocks that fall back to a default are kept, but the
failure must not vanish. ``log_swallowed(logger)`` is called first inside such
a block. It logs the active exception (with traceback) the first time that
handler sees that exception type, and stays silent for repeats, so a
per-frame or per-packet path cannot flood the log. The frame pipeline uses the
same once-per-site rule (``GameClient._contain_frame_error``).

The site is the handler that swallowed, not the line that raised: two handlers
that fail through one shared callee are two sites. A repeat costs a frame
lookup and a set test, with no traceback extraction.

``level`` is WARNING for a failure that hides a real defect. A site where the
exception is ordinary control flow (a socket already closed on teardown, a
headless pygame probe, a malformed packet, a bad downloaded file, a font
fallback) passes ``level=logging.DEBUG``, so default logging stays quiet.

The message names the site (``module.function``) and not the exception text,
so a log filter or a log-capturing harness sees one stable kind per site."""

import logging
import sys
from typing import Set, Tuple

_SEEN: Set[Tuple[str, int, type]] = set()


def log_swallowed(logger: logging.Logger, note: str = "",
                  level: int = logging.WARNING) -> bool:
    """Log the exception being handled, once per (handler line, type).

    Call it from inside the ``except`` block. Returns True when this call
    logged, False for a repeat, when no exception is active, or when
    ``logger`` does not log at ``level``. Never raises."""
    exc_type, exc, tb = sys.exc_info()
    if exc is None:
        return False
    try:
        caller = sys._getframe(1)
        key = (caller.f_code.co_filename, caller.f_lineno, exc_type)
        if key in _SEEN:
            return False
        if not logger.isEnabledFor(level):
            # Not marked seen: enabling the level later still reports it.
            return False
        _SEEN.add(key)
        where = f"{caller.f_globals.get('__name__', '?')}.{caller.f_code.co_name}"
        message = f"Swallowed {exc_type.__name__} in {where}"
        if note:
            message += f" ({note})"
        logger.log(level, message, exc_info=(exc_type, exc, tb))
        return True
    except Exception:
        return False


def reset_swallowed() -> None:
    """Forget the logged sites (tests, one fingerprint target to the next)."""
    _SEEN.clear()
