"""pyreborn.prefs -- local UI preferences persisted to disk.

Stores whatever the login/server-select screens need to pre-fill next launch
(account, last server, listserver host, window size) so the user doesn't
retype everything every time.

Location: `$XDG_CONFIG_HOME/pyreborn/prefs.json`, falling back to
`~/.config/pyreborn/prefs.json` when XDG_CONFIG_HOME is unset (the XDG
default). The directory is created on first save.

PLAINTEXT PASSWORD: `password` is stored unencrypted in prefs.json. That's a
deliberate, user-accepted tradeoff for a single-player convenience feature in
a game client -- it is NOT a security boundary. The file is chmod'd 0600
(owner read/write only) on every save so at least other local accounts on the
same machine can't read it, but treat it like a browser's saved password:
don't reuse it anywhere that matters.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


def config_dir() -> Path:
    """Directory prefs.json lives in (XDG_CONFIG_HOME-aware)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "pyreborn"


def prefs_path() -> Path:
    return config_dir() / "prefs.json"


@dataclass
class ServerPref:
    """Enough to identify + reconnect to the last-used server."""
    name: str = ""
    ip: str = ""
    port: int = 0
    version: str = ""

    def matches(self, server) -> bool:
        """Whether a listserver ServerEntry is "the same server" as this pref."""
        return self.name == getattr(server, "name", None) and \
            self.ip == getattr(server, "ip", None) and \
            self.port == getattr(server, "port", None)


@dataclass
class Prefs:
    username: str = ""
    password: str = ""                     # plaintext -- see module docstring
    use_listserver: bool = True
    listserver_host: str = "listserver.example.com"
    listserver_port: int = 14922
    host: str = "localhost"                # direct-connect host
    port: int = 14900                      # direct-connect port
    last_server: Optional[ServerPref] = field(default=None)
    window_w: int = 1024
    window_h: int = 720
    day_night: bool = False

    # -- in-game settings overlay (F9, game/settings_ui.py) ----------------
    # Live-tunable gameplay settings, applied to game/sound state and
    # persisted here so they survive to the next launch. Defaults match the
    # hardcoded values GameClient/SoundManager/Camera2D used before the
    # overlay existed.
    sound_volume: float = 1.0
    music_enabled: bool = True
    low_hearts_warning: bool = True
    minimap_visible: bool = True
    zoom: float = 1.0

    # -- persistence ------------------------------------------------------

    @classmethod
    def load(cls) -> "Prefs":
        """Read prefs.json, or return defaults if missing/corrupt."""
        try:
            raw = prefs_path().read_text()
            data = json.loads(raw)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return cls()

        prefs = cls()
        for f in prefs.__dataclass_fields__:
            if f == "last_server":
                continue
            if f in data:
                setattr(prefs, f, data[f])
        server = data.get("last_server")
        if isinstance(server, dict):
            prefs.last_server = ServerPref(
                name=server.get("name", ""),
                ip=server.get("ip", ""),
                port=server.get("port", 0),
                version=server.get("version", ""),
            )
        return prefs

    def save(self) -> None:
        """Write prefs.json, creating the config dir and locking permissions."""
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = prefs_path()

        payload = asdict(self)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.chmod(0o600)
        tmp.replace(path)   # atomic on same filesystem
        try:
            path.chmod(0o600)
        except OSError:
            pass

    # -- convenience --------------------------------------------------------

    def remember_login(self, username: str, password: str, use_listserver: bool, *,
                        host: Optional[str] = None, port: Optional[int] = None,
                        listserver_host: Optional[str] = None) -> None:
        """Persist a successful login. Only touches the fields relevant to the
        mode actually used, so e.g. a listserver login doesn't clobber the
        saved direct-connect host/port (and vice versa)."""
        self.username = username
        self.password = password
        self.use_listserver = use_listserver
        if use_listserver:
            if listserver_host:
                self.listserver_host = listserver_host
        else:
            if host:
                self.host = host
            if port:
                self.port = port
        self.save()

    def remember_server(self, server) -> None:
        self.last_server = ServerPref(
            name=getattr(server, "name", ""),
            ip=getattr(server, "ip", ""),
            port=getattr(server, "port", 0),
            version=getattr(server, "version", ""),
        )
        self.save()

    def remember_window_size(self, w: int, h: int) -> None:
        self.window_w = int(w)
        self.window_h = int(h)
        self.save()
