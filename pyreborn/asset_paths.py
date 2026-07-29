"""Where assets live on disk, and how asset names are keyed.

Three tiers, deliberately separate:

1. **Bundled** - ``pyreborn/assets/``. Whatever art happens to be installed
   alongside the package. Game art is NOT committed to this repo, so a clone
   has almost nothing here and the client must work with it empty.
2. **User content** - :func:`user_content_dir`. Base art a server assumes the
   client already has, because the original client shipped it built in:
   player ganis, ``sprites.png``, body/head/sword/shield defaults, common
   sounds, ``pics1.png``. A server is under no obligation to serve these, so
   if they are missing and unservable there is nowhere else to get them.
   Populated by the user, once, from their own game install.
3. **Per-server download cache** - :func:`server_cache_dir`. Everything the
   server does send. Written by the client, revalidated by modtime.

The tiers exist because the old arrangement had all three collapsed into one
gitignored ``cache/`` directory inside the checkout that nothing in the code
ever wrote. It was populated out of band, so deleting it silently took the
client's tileset with it, and a fresh clone never had one at all.

Locations follow the XDG base-directory spec, with env overrides for both.
No third-party dependency: the core library has none and this is not worth
adding one for.

Names are keyed through :func:`normalize_asset_name`. Servers are descended
from a Windows client and send whatever casing and path separators they like;
on Linux ``Body.png`` and ``body.png`` are two different files, which without
folding becomes two cache entries, two downloads and two surfaces for one
asset - and splits the "already requested" and "known failed" bookkeeping so
neither dedupe works.
"""

import os
import logging
from pathlib import Path
from typing import List

__all__ = [
    "normalize_asset_name",
    "looks_like_client_install",
    "expand_content_root",
    "content_dirs",
    "user_content_dir",
    "cache_root",
    "server_cache_dir",
    "server_cache_key",
]

_APP = "pyreborn"
logger = logging.getLogger(__name__)


def normalize_asset_name(name: str) -> str:
    """Canonical cache key for an asset name coming off the wire.

    Strips any directory part (servers send bare names, but GS1/GS2 scripts
    and gani SPRITE lines sometimes carry ``levels/images/x.png`` or a
    backslash path) and lowercases the result.

    Returns "" for a falsy name so callers can treat it as "no asset" rather
    than having to guard separately.
    """
    if not name:
        return ""
    return name.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()


def _xdg_dir(env_var: str, fallback: str) -> Path:
    """XDG lookup: $env_var if absolute, else ~/fallback."""
    value = os.environ.get(env_var, "")
    base = Path(value) if os.path.isabs(value) else Path.home() / fallback
    return base / _APP


def user_content_dir() -> Path:
    """Base art the user supplies once (tier 2 above).

    Override with ``PYREBORN_CONTENT_DIR``.
    """
    override = os.environ.get("PYREBORN_CONTENT_DIR", "")
    if override:
        return Path(override).expanduser()
    return _xdg_dir("XDG_DATA_HOME", ".local/share") / "content"


def looks_like_client_install(path: Path) -> bool:
    """Return whether a directory has the expected stock-asset layout."""
    path = Path(path).expanduser()
    if not path.is_dir():
        return False
    if (path / "levels").is_dir():
        return True
    if path.name.lower() == "levels":
        return any((path / name).is_dir() for name in ("ganis", "heads", "bodies"))
    return (path / "pics1.png").is_file()


def expand_content_root(path: Path) -> List[Path]:
    """Expand an install directory or its levels directory into asset roots."""
    path = Path(path).expanduser()
    candidates = [path]
    if path.name.lower() == "levels" and (path.parent / "levels") == path:
        candidates = [path.parent, path]
    elif (path / "levels").is_dir():
        candidates.append(path / "levels")

    roots = []
    seen = set()
    for candidate in candidates:
        try:
            key = candidate.resolve()
        except OSError:
            key = candidate.absolute()
        if candidate.is_dir() and key not in seen:
            seen.add(key)
            roots.append(candidate)
    return roots


def _asset_counts(root: Path) -> str:
    """Summarize common asset groups beneath one resolved root."""
    counts = {}
    for name in ("ganis", "images", "sounds"):
        directories = [root / name, root / "levels" / name]
        counts[name] = sum(
            sum(1 for entry in directory.iterdir() if entry.is_file())
            for directory in directories
            if directory.is_dir()
        )
    return ", ".join(f"{name}={count}" for name, count in counts.items())


def content_dirs() -> List[Path]:
    """Return existing user content roots in search-priority order."""
    configured = os.environ.get("PYREBORN_CONTENT_DIR")
    supplied = []
    if configured:
        supplied.extend(Path(value) for value in configured.split(os.pathsep) if value)

    from .prefs import Prefs
    supplied.extend(Path(value) for value in Prefs.load().content_dirs if value)

    if not configured:
        supplied.append(user_content_dir())

    roots = []
    seen = set()
    for supplied_path in supplied:
        for root in expand_content_root(supplied_path):
            try:
                key = root.resolve()
            except OSError:
                key = root.absolute()
            if key not in seen:
                seen.add(key)
                roots.append(root)

    for root in roots:
        logger.info("Content root %s: %s", root, _asset_counts(root))
    return roots


def cache_root() -> Path:
    """Root of the download cache (tier 3 above).

    Override with ``PYREBORN_CACHE_DIR``.
    """
    override = os.environ.get("PYREBORN_CACHE_DIR", "")
    if override:
        return Path(override).expanduser()
    return _xdg_dir("XDG_CACHE_HOME", ".cache")


def server_cache_key(host: str, port: int) -> str:
    """Filesystem-safe directory name for one server.

    A host can be an IPv6 literal or carry characters that are awkward in a
    path, so anything outside a conservative set is replaced.
    """
    safe = "".join(
        ch if (ch.isalnum() or ch in "-._") else "_" for ch in str(host or "unknown")
    )
    return f"{safe}_{int(port)}"


def server_cache_dir(host: str, port: int) -> Path:
    """Download cache directory for one server. Not created here."""
    return cache_root() / "servers" / server_cache_key(host, port)
