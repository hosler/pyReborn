"""Passive public-server probing and schema-versioned catalog support."""

from __future__ import annotations

import json
import math
import re
import socket
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from pyreborn.client import Client
from pyreborn.listserver import ListServerClient, ServerEntry
from pyreborn.prefs import Prefs
from pyreborn.tiletypes import get_tile_type, type_is_blocking
from pyreborn.protocol import VERSIONS


SCHEMA_VERSION = 3
DEFAULT_CATALOG = Path(__file__).with_name("server_catalog.json")
CATEGORY_NAMES = {"P": "gold", "H": "bronze", "U": "hidden", "3": "3d"}
PASSIVE_TESTS = {"connection_stability", "level_data", "npc_visibility"}
ACTIVE_TESTS = {
    "movement_all_directions", "collision_detection", "swimming_detection",
    "walk_to_target", "chat_roundtrip", "sword_attack", "item_detection",
    "file_download", "chest_interaction", "level_parsing",
}


def _redact(text: str, username: str, password: str) -> str:
    for secret in (password, username):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def parse_server_name(display_name: str) -> tuple[str, str]:
    """Return the clean display name and the public-list category."""
    if len(display_name) >= 2 and display_name[1] == " " and display_name[0] in CATEGORY_NAMES:
        return display_name[2:], CATEGORY_NAMES[display_name[0]]
    return display_name, "classic"


def is_owned_server(host: str, name: str = "") -> bool:
    normalized = host.strip().lower()
    return normalized in {"localhost", "127.0.0.1", "::1", "10.0.0.61"} and (
        normalized != "10.0.0.61" or "funtimes" in name.lower()
    )


def capabilities_to_tests(capabilities: dict[str, Any], active_ok: bool = False) -> list[str]:
    tests: list[str] = []
    if capabilities.get("login") == "accepted":
        tests.append("connection_stability")
    if capabilities.get("board_received"):
        tests.extend(("level_data", "npc_visibility"))
    if active_ok and capabilities.get("login") == "accepted":
        tests.extend(sorted(ACTIVE_TESTS))
    return list(dict.fromkeys(tests))


def empty_catalog() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "servers": {}}


def _merge_crawl_defaults(crawl: dict[str, Any]) -> None:
    """Add fields introduced by newer catalog minors without losing history."""
    from game_tester.server_crawl import empty_crawl_record
    defaults = empty_crawl_record()
    for key, value in defaults.items():
        if key not in crawl:
            crawl[key] = value
        elif isinstance(value, dict) and isinstance(crawl[key], dict):
            for child_key, child_value in value.items():
                crawl[key].setdefault(child_key, child_value)
    for level in crawl.get("levels_visited", []):
        if isinstance(level, dict):
            level.setdefault("frames_rendered", 0)
            level.setdefault("soak_exceptions", [])
    crawl.get("gs1_exec", {}).pop("unknown_commands", None)
    crawl.get("gs2", {}).pop("unknown_host_calls", None)


def _merge_record_timestamps(record: dict[str, Any]) -> None:
    """Backfill section timestamps for catalogs written before section merges."""
    timestamp = record.get("last_probed")
    if not timestamp:
        return
    updated = record.setdefault("last_updated", {})
    updated.setdefault("base", timestamp)
    if "versions" in record:
        updated.setdefault("versions", timestamp)
    if "crawl" in record:
        updated.setdefault("crawl", timestamp)


def load_catalog(path: Path | str = DEFAULT_CATALOG) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") not in (1, 2, SCHEMA_VERSION) or not isinstance(data.get("servers"), dict):
        raise ValueError("unsupported or malformed server catalog")
    if data.get("schema_version") in (1, 2):
        data["schema_version"] = SCHEMA_VERSION
    from game_tester.server_crawl import empty_crawl_record
    for record in data["servers"].values():
        record.setdefault("crawl", empty_crawl_record())
        _merge_crawl_defaults(record["crawl"])
        _merge_record_timestamps(record)
    return data


def save_catalog(catalog: dict[str, Any], path: Path | str = DEFAULT_CATALOG) -> None:
    from game_tester.server_crawl import empty_crawl_record
    catalog["schema_version"] = SCHEMA_VERSION
    for record in catalog.get("servers", {}).values():
        record.setdefault("crawl", empty_crawl_record())
        _merge_crawl_defaults(record["crawl"])
        _merge_record_timestamps(record)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def merge_probe_record(existing: dict[str, Any] | None,
                       fresh: dict[str, Any], *, ran_versions: bool,
                       ran_deep: bool) -> dict[str, Any]:
    """Merge independently collected probe sections without erasing history."""
    existing = existing or {}
    updated = dict(existing)
    updated.update({key: value for key, value in fresh.items()
                    if key not in {"versions", "crawl", "last_updated"}})
    timestamps = dict(existing.get("last_updated", {}))
    timestamp = fresh.get("last_probed", datetime.now(timezone.utc).isoformat())
    timestamps["base"] = timestamp
    if ran_versions:
        updated["versions"] = fresh.get("versions", {})
        timestamps["versions"] = timestamp
    if ran_deep:
        updated["crawl"] = fresh.get("crawl", {})
        timestamps["crawl"] = timestamp
    updated["last_updated"] = timestamps
    return updated


def _initial_version(entry: ServerEntry) -> str:
    match = re.search(r"\b(1\.411|2\.17|2\.21|2\.22|6\.037)\b", entry.version or "")
    return match.group(1) if match else "6.037"


def _client_snapshot(client: Any, auto_retry: bool, version: str) -> dict[str, Any]:
    stats = getattr(client, "packet_stats", {})
    received = {str(pid): int(values.get("received", 0)) for pid, values in stats.items()}
    handled_ids = getattr(client, "_handled_plo_ids", set())
    unknown = sorted(int(pid) for pid, values in stats.items()
                     if values.get("received", 0) and pid not in handled_ids)
    handler_errors = [values.get("last_traceback") or values.get("last_error")
                      for values in stats.values() if values.get("errors")]
    tiles = getattr(client, "tiles", [])
    diagnostics = getattr(client, "prop_parse_diagnostics", {})
    player = getattr(client, "player", None)
    player_x = getattr(player, "x", None)
    player_y = getattr(player, "y", None)
    in_gmap_segment = bool(getattr(client, "in_gmap_segment", False))
    max_x = max(1, int(getattr(client, "gmap_width", 0))) * 64 if in_gmap_segment else 64
    max_y = max(1, int(getattr(client, "gmap_height", 0))) * 64 if in_gmap_segment else 64
    position_sane = (
        bool(getattr(client, "authenticated", False))
        and isinstance(player_x, (int, float))
        and isinstance(player_y, (int, float))
        and math.isfinite(player_x) and math.isfinite(player_y)
        and 0 <= player_x < max_x and 0 <= player_y < max_y
    )
    authenticated = bool(getattr(client, "authenticated", False))
    protocol = getattr(client, "_protocol", None)
    handshake_gen = getattr(protocol, "last_handshake_gen", None)
    result = {
        "reachable": True,
        "login": "accepted" if authenticated else "rejected",
        "negotiated_version": version if authenticated else None,
        "encryption_gen": handshake_gen,
        "auto_retry": auto_retry,
        "packet_counts": received,
        "unknown_plo_ids": unknown,
        "unhandled_plo_ids": unknown,
        "level_name": getattr(client, "_current_level_name", "") or getattr(getattr(client, "player", None), "level", ""),
        "board_received": authenticated and bool(tiles),
        "tiles_ok": authenticated and len(tiles) == 4096 and all(isinstance(tile, int) for tile in tiles),
        "gmap_detected": bool(getattr(client, "is_gmap", False)),
        "npc_count": len(getattr(client, "npcs", {})),
        "weapon_count": len(getattr(client, "weapons", {})),
        "baddy_count": len(getattr(client, "baddies", {})),
        "other_players_seen": max(len(getattr(client, "players", {})),
                                  len(getattr(client, "player_list", {}))),
        "files_auto_downloaded_ok": bool(getattr(client, "_received_files", {})) and not bool(getattr(client, "_failed_files", set())),
        "has_npc_server": bool(getattr(client, "has_npc_server", False)),
        "handler_errors": [error for error in handler_errors if error],
        "disconnect_reason": getattr(client, "disconnect_reason", ""),
        "prop_parse_warnings": int(diagnostics.get("warnings", 0)),
        "prop_parse_errors": int(diagnostics.get("errors", 0)),
        "prop_width_fallbacks": int(diagnostics.get("width_fallbacks", 0)),
        "player_position_sane": position_sane,
    }
    if handshake_gen is not None:
        result["gen_source"] = "handshake"
    return result


def parse_versions(value: str | None) -> list[str]:
    """Parse and validate a comma-separated version matrix."""
    if not value:
        return []
    versions = list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    invalid = [version for version in versions if version not in VERSIONS]
    if invalid:
        raise ValueError(f"unsupported client version(s): {', '.join(invalid)}")
    return versions


def _probe_position_clear(client: Any, x: float, y: float) -> bool:
    """Conservatively check the headless client's current 64x64 board."""
    tiles = getattr(client, "tiles", [])
    if len(tiles) != 4096 or getattr(client, "in_gmap_segment", False):
        return True
    for sample_x in (x + 0.5, x + 1.5, x + 2.5 - 1e-3):
        for sample_y in (y + 1.0, y + 2.0, y + 3.0 - 1e-3):
            tile_x, tile_y = math.floor(sample_x), math.floor(sample_y)
            if not (0 <= tile_x < 64 and 0 <= tile_y < 64):
                return False
            if type_is_blocking(get_tile_type(tiles[tile_y * 64 + tile_x])):
                return False
    return True


def _exercise_probe_movement(client: Any, wander: int | None,
                             deadline: float) -> None:
    """Send only gentle movement, stopping on timeout or a level change."""
    starting_level = (getattr(client, "_current_level_name", "") or
                      getattr(getattr(client, "player", None), "level", ""))
    if wander is None:
        if time.monotonic() < deadline and hasattr(client, "move"):
            client.move(1, 0, step=0.25)
        return

    pattern = ((1, 0), (1, 0), (0, 1), (0, 1),
               (-1, 0), (-1, 0), (0, -1), (0, -1))
    for tile_index in range(max(0, wander)):
        dx, dy = pattern[tile_index % len(pattern)]
        for _ in range(4):
            if time.monotonic() >= deadline or not client.connected:
                return
            current_level = (getattr(client, "_current_level_name", "") or
                             getattr(getattr(client, "player", None), "level", ""))
            if starting_level and current_level != starting_level:
                return
            player = client.player
            if not _probe_position_clear(client, player.x + dx * 0.25,
                                         player.y + dy * 0.25):
                break
            if not client.move(dx, dy, step=0.25):
                break
            client.update(timeout=min(0.05, max(0.0, deadline - time.monotonic())))
            current_level = (getattr(client, "_current_level_name", "") or
                             getattr(getattr(client, "player", None), "level", ""))
            if starting_level and current_level != starting_level:
                return


def _probe_entry_once(entry: ServerEntry, username: str, password: str, timeout: float = 20.0,
                client_factory: Callable[..., Any] = Client,
                resolver: Callable[..., Any] = socket.getaddrinfo,
                wander: int | None = None, deep: bool = False,
                max_levels: int = 15, deep_timeout: float = 120.0,
                crawler: Callable[..., dict[str, Any]] | None = None,
                forced_version: str | None = None, pin_version: bool = False,
                retry_sleep: Callable[[float], None] | None = None) -> dict[str, Any]:
    """Probe one entry; all client failures become record data."""
    name, category = parse_server_name(entry.display_name)
    active_ok = is_owned_server(entry.ip, name)
    record: dict[str, Any] = {
        "address": {"host": entry.ip, "port": entry.port},
        "category": category,
        "last_probed": datetime.now(timezone.utc).isoformat(),
        "capabilities": {
            "reachable": False,
            "login": "timeout",
            "server_kind": "login" if "loginserver" in (entry.ip + " " + name).lower() else "game",
            "auto_address_substituted": bool(entry.auto_address_substituted),
        },
        "testable_tests": [], "active_ok": active_ok, "errors": [],
    }
    from game_tester.server_crawl import crawl_client, empty_crawl_record, shaped_error
    record["crawl"] = empty_crawl_record()
    crawler = crawler or crawl_client
    client = None
    started = time.monotonic()
    try:
        resolver(entry.ip, entry.port, type=socket.SOCK_STREAM)
        version = forced_version or _initial_version(entry)
        requested_version = version
        auto_retry = False
        client = client_factory(entry.ip, entry.port, version=version)
        if hasattr(client, "_protocol"):
            client._protocol.connect_timeout = max(0.1, timeout - (time.monotonic() - started))
        if not client.connect():
            record["capabilities"]["login"] = "not_attempted"
            return record
        remaining = max(0.1, timeout - (time.monotonic() - started))
        accepted = client.login(username, password, timeout=remaining)
        reason = getattr(client, "disconnect_reason", "")
        if not pin_version and not accepted and "version" in reason.lower():
            match = re.search(r"(\d+\.\d+\d*)", reason)
            if match and match.group(1) != version and time.monotonic() - started < timeout:
                client.disconnect()
                if retry_sleep is not None:
                    retry_sleep(1.0)
                version, auto_retry = match.group(1), True
                client = client_factory(entry.ip, entry.port, version=version)
                if hasattr(client, "_protocol"):
                    client._protocol.connect_timeout = max(0.1, timeout - (time.monotonic() - started))
                if client.connect():
                    accepted = client.login(username, password,
                                            timeout=max(0.1, timeout - (time.monotonic() - started)))
                    reason = getattr(client, "disconnect_reason", "") or reason
        if accepted:
            _exercise_probe_movement(client, wander, started + timeout)
            while time.monotonic() - started < timeout and client.connected:
                client.update(timeout=min(0.1, max(0.0, timeout - (time.monotonic() - started))))
        capabilities = _client_snapshot(client, auto_retry, version)
        capabilities["requested_version"] = requested_version
        capabilities["version_status"] = (
            "renegotiated" if auto_retry else
            "accepted" if accepted else "rejected"
        )
        capabilities["renegotiated_to"] = version if auto_retry else None
        advertised_match = re.search(r"(\d+\.\d+\d*)", reason)
        capabilities["server_advertised_version"] = (
            advertised_match.group(1) if not accepted and advertised_match else None
        )
        capabilities["server_kind"] = (
            "login" if "loginserver" in (entry.ip + " " + name).lower() else "game"
        )
        capabilities["auto_address_substituted"] = bool(entry.auto_address_substituted)
        if not accepted:
            capabilities["login"] = "rejected" if (
                capabilities.get("disconnect_reason") or reason
            ) else "timeout"
            capabilities["login_reject_reason"] = (
                capabilities.get("disconnect_reason") or reason
            )
        record["capabilities"] = capabilities
        record["errors"].extend(
            _redact(error, username, password) for error in capabilities.pop("handler_errors")
        )
        if deep and accepted and client.connected:
            try:
                record["crawl"] = crawler(
                    client, max_levels=max_levels, timeout=deep_timeout)
            except BaseException as exc:
                record["crawl"]["errors"].append(
                    shaped_error("crawl", exception=exc))
    except BaseException:
        record["errors"].append(_redact(traceback.format_exc(), username, password))
    finally:
        if client is not None:
            try:
                client.disconnect()
            except BaseException:
                record["errors"].append(_redact(traceback.format_exc(), username, password))
        record["testable_tests"] = capabilities_to_tests(record["capabilities"], active_ok)
    return record


def _version_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return the stable, per-version portion of a full probe record."""
    capabilities = record.get("capabilities", {})
    keys = (
        "requested_version", "version_status", "renegotiated_to",
        "negotiated_version", "server_advertised_version", "encryption_gen",
        "gen_source", "login", "login_reject_reason",
        "board_received", "tiles_ok", "prop_parse_warnings",
        "prop_parse_errors", "prop_width_fallbacks", "player_position_sane",
        "disconnect_reason",
    )
    result = {key: capabilities.get(key) for key in keys}
    result["errors"] = list(record.get("errors", []))
    return result


def probe_entry(entry: ServerEntry, username: str, password: str, timeout: float = 20.0,
                client_factory: Callable[..., Any] = Client,
                resolver: Callable[..., Any] = socket.getaddrinfo,
                wander: int | None = None, deep: bool = False,
                max_levels: int = 15, deep_timeout: float = 120.0,
                crawler: Callable[..., dict[str, Any]] | None = None,
                versions: Iterable[str] | None = None,
                sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Probe the default version plus optional pinned version-matrix entries."""
    matrix = list(dict.fromkeys(versions or []))
    invalid = [version for version in matrix if version not in VERSIONS]
    if invalid:
        raise ValueError(f"unsupported client version(s): {', '.join(invalid)}")
    default_version = _initial_version(entry)
    connection_versions = list(dict.fromkeys([default_version, *matrix]))
    per_probe_timeout = timeout / len(connection_versions)
    record = _probe_entry_once(
        entry, username, password, per_probe_timeout, client_factory, resolver,
        wander, deep, max_levels, deep_timeout, crawler,
        retry_sleep=sleep if matrix else None)
    if not matrix:
        return record
    record["versions"] = {}
    for version in matrix:
        sleep(1.0)
        version_probe = _probe_entry_once(
            entry, username, password, per_probe_timeout, client_factory,
            resolver, wander, False, max_levels, deep_timeout, crawler,
            forced_version=version, pin_version=True)
        record["versions"][version] = _version_record(version_probe)
    return record


def fetch_entries(prefs: Prefs, timeout: float) -> list[ServerEntry]:
    client = ListServerClient(prefs.listserver_host, prefs.listserver_port)
    try:
        response = client.login(prefs.username, prefs.password, timeout=timeout)
        if not response.success:
            raise RuntimeError(response.error or "public list login failed")
        return response.servers
    finally:
        client.disconnect()


def probe_servers(server: str | None = None, timeout: float = 20.0,
                  catalog_path: Path | str = DEFAULT_CATALOG,
                  wander: int | None = None, deep: bool = False,
                  max_levels: int = 15, deep_timeout: float = 120.0,
                  versions: Iterable[str] | None = None) -> dict[str, Any]:
    prefs = Prefs.load()
    entries = fetch_entries(prefs, timeout)
    if server:
        entries = [entry for entry in entries if parse_server_name(entry.display_name)[0].casefold() == server.casefold()]
        if not entries:
            raise ValueError(f"server not found: {server}")
    try:
        catalog = load_catalog(catalog_path)
    except FileNotFoundError:
        catalog = empty_catalog()
    for index, entry in enumerate(entries):
        if index:
            time.sleep(1.0)
        name, _ = parse_server_name(entry.display_name)
        fresh = probe_entry(
            entry, prefs.username, prefs.password, timeout, wander=wander,
            deep=deep, max_levels=max_levels, deep_timeout=deep_timeout,
            versions=versions)
        catalog["servers"][name] = merge_probe_record(
            catalog["servers"].get(name), fresh,
            ran_versions=bool(versions), ran_deep=deep)
        save_catalog(catalog, catalog_path)
    return catalog


def iter_catalog_records(catalog: dict[str, Any], selected: str | None = None) -> Iterable[tuple[str, dict[str, Any]]]:
    for name, record in catalog["servers"].items():
        if selected is None or name.casefold() == selected.casefold():
            yield name, record


def run_catalog_tests(selected: str | None = None, catalog_path: Path | str = DEFAULT_CATALOG) -> bool:
    """Run only a catalog record's permitted scenario subset."""
    from game_tester.game_bot import GameBot
    from game_tester.test_scenarios import TestScenarios

    catalog = load_catalog(catalog_path)
    records = list(iter_catalog_records(catalog, selected))
    if selected and not records:
        raise ValueError(f"server not found in catalog: {selected}")
    prefs = Prefs.load()
    scenario_map = {
        "connection_stability": TestScenarios.test_connection,
        "level_data": TestScenarios.test_level_data,
        "npc_visibility": TestScenarios.test_npc_visibility,
        "movement_all_directions": TestScenarios.test_movement_all_directions,
        "collision_detection": TestScenarios.test_collision_detection,
        "swimming_detection": TestScenarios.test_swimming_detection,
        "walk_to_target": TestScenarios.test_walk_to_target,
        "chat_roundtrip": TestScenarios.test_chat_roundtrip,
        "sword_attack": TestScenarios.test_sword_attack,
        "item_detection": TestScenarios.test_item_detection,
        "file_download": TestScenarios.test_file_download,
        "chest_interaction": TestScenarios.test_chest_interaction,
        "level_parsing": TestScenarios.test_level_parsing,
    }
    all_ok = True
    for index, (name, record) in enumerate(records):
        if index:
            time.sleep(1.0)
        address = record["address"]
        bot = GameBot(prefs.username, address["host"], int(address["port"]), prefs.password)
        version = record.get("capabilities", {}).get("negotiated_version")
        if version:
            bot.client = Client(address["host"], int(address["port"]), version=version)
            bot._setup_callbacks()
        print(f"\n[CATALOG SERVER] {name}")
        capabilities = record.get("capabilities", {})
        if not capabilities.get("reachable", False):
            print("  SKIP unreachable during catalog probe")
            continue
        if capabilities.get("login") != "accepted":
            reason = capabilities.get("login_reject_reason") or capabilities.get("disconnect_reason") or capabilities.get("login", "login rejected")
            print(f"  SKIP login rejected: {reason}")
            continue
        if not bot.connect(timeout=20.0):
            print("  FAIL connection")
            all_ok = False
            continue
        try:
            allowed = set(record.get("testable_tests", []))
            if not record.get("active_ok", False):
                allowed &= PASSIVE_TESTS
            for test_name in record.get("testable_tests", []):
                if test_name not in allowed or test_name not in scenario_map:
                    continue
                result = scenario_map[test_name](bot)
                print(f"  {'PASS' if result.passed else 'FAIL'} {result.name}: {result.details}")
                all_ok = all_ok and result.passed
        except BaseException:
            print(traceback.format_exc())
            all_ok = False
        finally:
            bot.disconnect()
    return all_ok
