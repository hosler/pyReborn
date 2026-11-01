import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from game_tester import server_probe
from game_tester.server_probe import (
    _exercise_probe_movement,
    capabilities_to_tests,
    empty_catalog,
    iter_catalog_records,
    load_catalog,
    merge_probe_record,
    parse_listserver,
    parse_server_name,
    parse_versions,
    probe_entry,
    probe_servers,
    probe_status,
    save_catalog,
)
from pyreborn.client import Client, HANDLED_PLO_IDS
from pyreborn.packets import PacketID
from pyreborn.listserver import ListServerClient, PacketReader, ServerEntry
from pyreborn.prefs import Prefs


def _wire_string(raw: bytes) -> bytes:
    return bytes([len(raw) + 32]) + raw


def _entry_packet(name: bytes, ip: bytes = b"127.0.0.1") -> bytes:
    fields = [name, b"English", b"desc", b"url", b"2.22", b"1", ip, b"14900"]
    return bytes([33, 40]) + b"".join(_wire_string(field) for field in fields)


def test_wire_text_uses_windows_1252():
    assert PacketReader(_wire_string(b"Alice\x92s")).read_string() == "Alice’s"


def test_auto_address_uses_configured_list_host():
    client = ListServerClient("list.example.test")
    dollar = client._parse_server_list(_entry_packet(b"H Test", b"$AUTO"))[0]
    plain = client._parse_server_list(_entry_packet(b"Test", b"AUTO"))[0]
    assert dollar.ip == "list.example.test" and dollar.auto_address_substituted
    assert plain.ip == "list.example.test" and plain.auto_address_substituted


@pytest.mark.parametrize("value, expected", [
    ("list.example.test", ("list.example.test", ListServerClient.DEFAULT_PORT)),
    ("list.example.test:1234", ("list.example.test", 1234)),
    ("192.0.2.10", ("192.0.2.10", ListServerClient.DEFAULT_PORT)),
    ("192.0.2.10:1234", ("192.0.2.10", 1234)),
])
def test_probe_parse_listserver(value, expected):
    assert parse_listserver(value) == expected


@pytest.mark.parametrize("value", ["", ":1234", "host:", "host:no", "host:0", "host:65536"])
def test_probe_parse_listserver_rejects_invalid_endpoint(value):
    with pytest.raises(ValueError):
        parse_listserver(value)


@pytest.fixture
def probe_calls(monkeypatch):
    prefs = Prefs(username="saved-account", password="saved-password",
                  listserver_host="saved.example.test", listserver_port=9999)
    calls = SimpleNamespace(prefs=prefs, endpoints=[], logins=[], probes=[], disconnects=[])
    monkeypatch.setattr(Prefs, "load", lambda: prefs)
    monkeypatch.delenv("PYREBORN_PROBE_PASSWORD", raising=False)

    def forbid_save(self):
        pytest.fail("the probe must not save preferences")

    monkeypatch.setattr(Prefs, "save", forbid_save)

    class FakeListServer:
        DEFAULT_PORT = ListServerClient.DEFAULT_PORT

        def __init__(self, host, port):
            calls.endpoints.append((host, port))

        def login(self, account, password, timeout):
            calls.logins.append((account, password, timeout))
            entry = ServerEntry("Example", "", "", "", "", "", 0,
                                "game.example.test", 14900)
            return SimpleNamespace(success=True, servers=[entry])

        def disconnect(self):
            calls.disconnects.append(True)

    def fake_probe(entry, account, password, timeout, **kwargs):
        calls.probes.append((account, password, timeout))
        return {"address": {"host": entry.ip, "port": entry.port},
                "last_probed": "2026-11-01T00:00:00+00:00"}

    monkeypatch.setattr(server_probe, "ListServerClient", FakeListServer)
    monkeypatch.setattr(server_probe, "probe_entry", fake_probe)
    return calls


@pytest.mark.parametrize("endpoint, expected", [
    (None, ("saved.example.test", 9999)),
    ("custom.example.test", ("custom.example.test", ListServerClient.DEFAULT_PORT)),
    ("custom.example.test:1234", ("custom.example.test", 1234)),
])
def test_probe_servers_uses_copied_prefs_for_fetch_entries(
        tmp_path, monkeypatch, probe_calls, endpoint, expected):
    before = asdict(probe_calls.prefs)
    fetch_entries = server_probe.fetch_entries
    fetched_prefs = []

    def capture_fetch(prefs, timeout):
        fetched_prefs.append(prefs)
        return fetch_entries(prefs, timeout)

    monkeypatch.setattr(server_probe, "fetch_entries", capture_fetch)
    path = tmp_path / "catalog.json"
    catalog = probe_servers(listserver=endpoint, account="override-account",
                            password="override-password", timeout=0.5, catalog_path=path)
    assert fetched_prefs[0] is not probe_calls.prefs
    assert asdict(probe_calls.prefs) == before
    assert probe_calls.endpoints == [expected]
    assert probe_calls.logins == probe_calls.probes == [("override-account", "override-password", 0.5)]
    assert probe_calls.disconnects == [True]
    assert catalog["servers"]["Example"]["listserver"] == {"host": expected[0], "port": expected[1]}
    assert load_catalog(path) == catalog
    assert "override-password" not in path.read_text()


@pytest.mark.parametrize("explicit, env, expected", [
    (None, None, "saved-password"),
    (None, "env-password", "env-password"),
    ("explicit-password", "env-password", "explicit-password"),
    ("", "env-password", ""),
])
def test_probe_password_precedence(tmp_path, monkeypatch, probe_calls, explicit, env, expected):
    if env is not None:
        monkeypatch.setenv("PYREBORN_PROBE_PASSWORD", env)
    probe_servers(password=explicit, catalog_path=tmp_path / "catalog.json")
    assert probe_calls.logins == probe_calls.probes == [("saved-account", expected, 20.0)]
    assert probe_calls.prefs.password == "saved-password"


def test_probe_catalog_separates_communities_and_preserves_unknown_legacy_source(tmp_path, probe_calls):
    path = tmp_path / "catalog.json"
    catalog = empty_catalog()
    catalog["servers"]["Example"] = {"versions": {"2.22": {"marker": "legacy"}}}
    save_catalog(catalog, path)
    for endpoint in ("first.example.test:1234", "second.example.test", "first.example.test:1234"):
        catalog = probe_servers(listserver=endpoint, catalog_path=path)
    assert len(catalog["servers"]) == 3
    assert catalog["servers"]["Example"]["versions"]["2.22"]["marker"] == "legacy"
    assert "listserver" not in catalog["servers"]["Example"]
    for endpoint in ("first.example.test:1234", "second.example.test:14922"):
        record = catalog["servers"][f"Example [{endpoint}]"]
        host, port = parse_listserver(endpoint)
        assert record["listserver"] == {"host": host, "port": port}
        assert "versions" not in record
    assert len(list(iter_catalog_records(catalog, "Example"))) == 3
    assert len(list(iter_catalog_records(catalog, "Example [first.example.test:1234]"))) == 1


@pytest.mark.parametrize('use_default', [True, False])
def test_probe_legacy_record_uses_default_listserver_provenance(
        tmp_path, probe_calls, use_default):
    path = tmp_path / 'catalog.json'
    catalog = empty_catalog()
    history = {'2.22': {'marker': 'legacy'}}
    catalog['servers']['Example'] = {'versions': history}
    save_catalog(catalog, path)
    defaults = Prefs()
    endpoint = (f'{defaults.listserver_host}:{defaults.listserver_port}'
                if use_default else 'other.example.test:1234')

    catalog = probe_servers(listserver=endpoint, catalog_path=path)

    host, port = parse_listserver(endpoint)
    key = 'Example' if use_default else f'Example [{endpoint}]'
    assert catalog['servers'][key]['listserver'] == {'host': host, 'port': port}
    assert catalog['servers'][key]['name'] == 'Example'
    assert catalog['servers']['Example']['versions'] == history
    assert len(catalog['servers']) == (1 if use_default else 2)
    if not use_default:
        assert 'listserver' not in catalog['servers']['Example']


@pytest.fixture
def catalog_run(tmp_path, monkeypatch, probe_calls):
    path = tmp_path / 'catalog.json'
    record = {
        'name': 'Example',
        'listserver': {'host': 'custom.example.test', 'port': 1234},
        'address': {'host': 'game.example.test', 'port': 14900},
        'capabilities': {'login': 'accepted'},
        'testable_tests': ['connection_stability'],
    }
    catalog = empty_catalog()
    catalog['servers']['Example [custom.example.test:1234]'] = record
    save_catalog(catalog, path)
    calls = SimpleNamespace(bots=[], scenarios=[], captures=[], checks=[], disconnects=[])
    baselines = {'servers': {'Example': {'seconds': 0.25}}}

    class FakeBot:
        def __init__(self, account, host, port, password):
            calls.bots.append((account, host, port, password))
            self.client = SimpleNamespace(connected=True)

        def connect(self, timeout):
            return True

        def disconnect(self):
            calls.disconnects.append(self.client)

    def scenario(bot):
        calls.scenarios.append(bot.client)
        return SimpleNamespace(passed=True, name='connection_stability', details='ok')

    def capture(client, seconds, **kwargs):
        calls.captures.append((client, seconds, kwargs))
        return {'observed': True}

    def check(name, observed, baseline):
        calls.checks.append((name, observed, baseline))
        return True

    monkeypatch.setattr('game_tester.game_bot.GameBot', FakeBot)
    monkeypatch.setattr('game_tester.test_scenarios.TestScenarios.test_connection', scenario)
    monkeypatch.setattr('game_tester.behaviour_fingerprint.load_baselines', lambda: baselines)
    monkeypatch.setattr('game_tester.behaviour_fingerprint.capture_from_client', capture)
    monkeypatch.setattr('game_tester.behaviour_fingerprint.check_fingerprint', check)
    return SimpleNamespace(path=path, catalog=catalog, record=record, calls=calls,
                           baselines=baselines)


@pytest.mark.parametrize('stored_name', [True, False])
def test_catalog_fingerprint_uses_plain_name_for_suffixed_record(catalog_run, stored_name):
    if not stored_name:
        del catalog_run.record['name']
        save_catalog(catalog_run.catalog, catalog_run.path)
    assert server_probe.run_catalog_tests('Example', catalog_path=catalog_run.path)
    calls = catalog_run.calls
    assert calls.checks == [('Example', {'observed': True}, catalog_run.baselines)]
    assert calls.captures == [(calls.scenarios[0], 0.25, {'replay_bytecode': True})]
    assert calls.disconnects == calls.scenarios


def test_catalog_suffixed_record_fails_when_fingerprint_fails(catalog_run, monkeypatch):
    monkeypatch.setattr('game_tester.behaviour_fingerprint.check_fingerprint',
                        lambda name, observed, baselines: False)
    assert not server_probe.run_catalog_tests(catalog_path=catalog_run.path)
    assert catalog_run.calls.captures


@pytest.mark.parametrize('fingerprint', [True, False])
def test_catalog_warns_when_fingerprint_baseline_missing(catalog_run, caplog, fingerprint):
    catalog_run.baselines['servers'].clear()
    assert server_probe.run_catalog_tests(catalog_path=catalog_run.path,
                                          fingerprint=fingerprint)
    warnings = [record for record in caplog.records if record.levelname == 'WARNING']
    assert len(warnings) == int(fingerprint)
    if fingerprint:
        assert 'baseline' in warnings[0].message
        assert 'Example' in warnings[0].message
    assert not catalog_run.calls.captures


@pytest.mark.parametrize('explicit, env, expected', [
    (None, None, 'saved-password'),
    (None, 'env-password', 'env-password'),
    ('explicit-password', 'env-password', 'explicit-password'),
    ('', 'env-password', ''),
])
def test_catalog_tests_resolve_temporary_overrides(
        catalog_run, probe_calls, monkeypatch, explicit, env, expected):
    before = asdict(probe_calls.prefs)
    if env is not None:
        monkeypatch.setenv('PYREBORN_PROBE_PASSWORD', env)
    assert server_probe.run_catalog_tests(
        catalog_path=catalog_run.path, listserver='custom.example.test:1234',
        account='override-account', password=explicit)
    assert catalog_run.calls.bots == [
        ('override-account', 'game.example.test', 14900, expected)]
    assert asdict(probe_calls.prefs) == before


def test_catalog_listserver_override_filters_other_communities(catalog_run):
    other = dict(catalog_run.record, listserver={'host': 'other.example.test', 'port': 1234})
    catalog_run.catalog['servers']['Example [other.example.test:1234]'] = other
    save_catalog(catalog_run.catalog, catalog_run.path)
    assert server_probe.run_catalog_tests(
        'Example', catalog_path=catalog_run.path, listserver='custom.example.test:1234')
    assert len(catalog_run.calls.bots) == 1


def test_catalog_cli_threads_overrides(catalog_run, probe_calls, capsys):
    before = asdict(probe_calls.prefs)
    server_probe.main([
        '--catalog-tests', '--server', 'Example', '--catalog', str(catalog_run.path),
        '--listserver', 'custom.example.test:1234',
        '--account', 'cli-account', '--password', 'cli-password'])
    assert catalog_run.calls.bots == [
        ('cli-account', 'game.example.test', 14900, 'cli-password')]
    assert asdict(probe_calls.prefs) == before
    assert catalog_run.calls.checks
    output = capsys.readouterr()
    assert 'cli-password' not in output.out + output.err + catalog_run.path.read_text()


def test_catalog_cli_returns_failure_when_fingerprint_fails(catalog_run, monkeypatch):
    monkeypatch.setattr('game_tester.behaviour_fingerprint.check_fingerprint',
                        lambda name, observed, baselines: False)
    with pytest.raises(SystemExit) as error:
        server_probe.main(['--catalog-tests', '--catalog', str(catalog_run.path)])
    assert error.value.code == 1


@pytest.mark.parametrize("version", [1, 2, 3])
def test_probe_catalog_accepts_legacy_records_without_listserver(tmp_path, version):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"schema_version": version, "servers": {"Example": {}}}))
    catalog = load_catalog(path)
    assert catalog["schema_version"] == 3
    assert "listserver" not in catalog["servers"]["Example"]
    save_catalog(catalog, path)
    assert load_catalog(path) == catalog


def test_probe_cli_threads_overrides(tmp_path, monkeypatch, probe_calls, capsys):
    path = tmp_path / "catalog.json"
    server_probe.main(["--listserver", "custom.example.test:1234",
                       "--account", "cli-account", "--password", "cli-password",
                       "--server", "Example", "--catalog", str(path)])
    assert probe_calls.endpoints == [("custom.example.test", 1234)]
    assert probe_calls.logins == probe_calls.probes == [("cli-account", "cli-password", 20.0)]
    captured = capsys.readouterr()
    assert "cli-password" not in captured.out + captured.err + path.read_text()


def test_probe_cli_error_does_not_print_password(monkeypatch, capsys):
    def fail(**kwargs):
        raise RuntimeError("remote error contains cli-password")

    monkeypatch.setattr(server_probe, "probe_servers", fail)
    with pytest.raises(SystemExit) as error:
        server_probe.main(["--password", "cli-password"])
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert "cli-password" not in captured.out + captured.err


def test_prefix_parsing():
    assert parse_server_name("P Golden Place") == ("Golden Place", "gold")
    assert parse_server_name("H Bronze Place") == ("Bronze Place", "bronze")
    assert parse_server_name("U Quiet Place") == ("Quiet Place", "hidden")
    assert parse_server_name("Ordinary Place") == ("Ordinary Place", "classic")


def test_capability_mapping_respects_active_gate():
    capabilities = {"login": "accepted", "board_received": True}
    passive = capabilities_to_tests(capabilities)
    active = capabilities_to_tests(capabilities, active_ok=True)
    assert passive == ["connection_stability", "level_data", "npc_visibility"]
    assert "movement_all_directions" not in passive
    assert "movement_all_directions" in active


def test_catalog_round_trip(tmp_path):
    path = tmp_path / "catalog.json"
    catalog = empty_catalog()
    catalog["servers"]["Example"] = {"active_ok": False, "errors": []}
    save_catalog(catalog, path)
    assert load_catalog(path) == catalog
    assert json.loads(path.read_text())["schema_version"] == 3


def test_catalog_load_backfills_status_for_older_records(tmp_path):
    path = tmp_path / "catalog.json"
    catalog = empty_catalog()
    catalog["servers"]["Staff Only"] = {
        "capabilities": {"reachable": True, "login": "rejected",
                         "login_reject_reason": "restricted to staff only"},
        "versions": {"2.22": {"login": "rejected"}}}
    save_catalog(catalog, path)
    loaded = load_catalog(path)
    record = loaded["servers"]["Staff Only"]
    assert record["capabilities"]["status"] == "rejected"
    assert record["versions"]["2.22"]["status"] == "rejected"


def _probe_section_record(marker):
    return {"last_probed": f"2026-07-20T00:00:0{marker}+00:00",
            "capabilities": {"marker": marker},
            "versions": {"6.037": {"marker": marker}},
            "crawl": {"marker": marker}}


def test_deep_then_matrix_preserves_crawl():
    deep = merge_probe_record(None, _probe_section_record(1),
                              ran_versions=False, ran_deep=True)
    matrix = merge_probe_record(deep, _probe_section_record(2),
                                ran_versions=True, ran_deep=False)
    assert matrix["crawl"] == {"marker": 1}
    assert matrix["versions"] == {"6.037": {"marker": 2}}
    assert matrix["last_updated"]["crawl"].endswith("01+00:00")
    assert matrix["last_updated"]["versions"].endswith("02+00:00")


def test_matrix_then_deep_preserves_versions():
    matrix = merge_probe_record(None, _probe_section_record(1),
                                ran_versions=True, ran_deep=False)
    deep = merge_probe_record(matrix, _probe_section_record(2),
                              ran_versions=False, ran_deep=True)
    assert deep["versions"] == {"6.037": {"marker": 1}}
    assert deep["crawl"] == {"marker": 2}
    assert deep["last_updated"]["versions"].endswith("01+00:00")
    assert deep["last_updated"]["crawl"].endswith("02+00:00")


class _ExplodingClient:
    def __init__(self, host, port, version):
        self.connected = True
        self.authenticated = True
        self.disconnect_reason = ""
        self.packet_stats = {}

    def connect(self):
        return True

    def login(self, username, password, timeout):
        return True

    def update(self, timeout):
        raise ValueError("deliberate parser failure")

    def disconnect(self):
        self.connected = False


def test_probe_captures_client_exception_without_socket():
    entry = ServerEntry("Example", "", "", "", "", "", 0, "example.test", 14900)
    record = probe_entry(
        entry, "account", "secret", timeout=0.01,
        client_factory=_ExplodingClient,
        resolver=lambda *args, **kwargs: [(None, None, None, None, None)],
    )
    assert record["errors"]
    assert "ValueError: deliberate parser failure" in record["errors"][0]
    assert "secret" not in json.dumps(record)


class _RejectingClient:
    def __init__(self, host, port, version):
        self.version = version
        self.connected = True
        self.authenticated = False
        self.disconnect_reason = "Account is not permitted"
        self.packet_stats = {}
        self.tiles = []
        self._protocol = type("Protocol", (), {"gen": 3, "connect_timeout": 0.0})()

    def connect(self):
        return True

    def login(self, username, password, timeout):
        self._protocol.last_handshake_gen = self._protocol.gen
        self.connected = False
        return False

    def disconnect(self):
        self.connected = False


def test_rejected_login_keeps_reason_version_and_generation():
    entry = ServerEntry("Example", "", "", "", "", "2.22", 0,
                        "example.test", 14900)
    record = probe_entry(
        entry, "account", "secret", timeout=0.01,
        client_factory=_RejectingClient,
        resolver=lambda *args, **kwargs: [(None, None, None, None, None)],
    )
    capabilities = record["capabilities"]
    assert capabilities["login"] == "rejected"
    assert capabilities["login_reject_reason"] == "Account is not permitted"
    assert capabilities["negotiated_version"] is None
    assert capabilities["encryption_gen"] == 3
    assert capabilities["gen_source"] == "handshake"


def test_status_taxonomy_separates_refusal_from_failure():
    assert probe_status({"reachable": True, "login": "accepted"}) == "ok"
    # Staff-only listings and version gates: reachable, but not ours to test.
    assert probe_status({"reachable": True, "login": "rejected"}) == "rejected"
    assert probe_status({"reachable": True, "login": "timeout"}) == "timeout"
    assert probe_status({"reachable": False, "login": "not_attempted"}) == "unreachable"
    assert probe_status({"reachable": False}) == "unreachable"
    # Only an exception before any verdict counts as our failure.
    assert probe_status({"reachable": False, "login": "timeout"}) == "error"
    # Per-version records carry no reachability flag of their own.
    assert probe_status({"login": "rejected"}) == "rejected"


def test_dead_address_is_unreachable_not_a_probe_error():
    def refuse(*args, **kwargs):
        raise OSError("Name or service not known")

    entry = ServerEntry("Example", "", "", "", "", "6.037", 0, "gone.test", 14900)
    record = probe_entry(entry, "account", "secret", timeout=0.01,
                         client_factory=_RejectingClient, resolver=refuse)
    assert record["capabilities"]["status"] == "unreachable"
    assert record["capabilities"]["login"] == "not_attempted"
    assert record["errors"] == ["address resolution failed: Name or service not known"]


def test_rejected_probe_records_status_alongside_the_reason():
    entry = ServerEntry("Example", "", "", "", "", "6.037", 0, "example.test", 14900)
    record = probe_entry(
        entry, "account", "secret", timeout=0.01,
        client_factory=_RejectingClient,
        resolver=lambda *args, **kwargs: [(None, None, None, None, None)],
    )
    assert record["capabilities"]["status"] == "rejected"


def test_version_matrix_pins_each_requested_version_and_shapes_records():
    created = []
    sleeps = []

    class MatrixClient(_RejectingClient):
        def __init__(self, host, port, version):
            super().__init__(host, port, version)
            self.disconnect_reason = "Version 6.037 required"
            self._protocol.gen = {"2.22": 5, "6.037": 5}[version]
            # Must not leak into the record; login overwrites this with the
            # generation represented by the fake wire handshake.
            self._protocol.last_handshake_gen = 99
            self.login_timeout = None
            created.append(self)

        def login(self, username, password, timeout):
            self.login_timeout = timeout
            return super().login(username, password, timeout)

    entry = ServerEntry("Example", "", "", "", "", "2.22", 0,
                        "example.test", 14900)
    record = probe_entry(
        entry, "account", "secret", timeout=8.0,
        client_factory=MatrixClient,
        resolver=lambda *args, **kwargs: [(None, None, None, None, None)],
        versions=["2.22", "6.037"], sleep=sleeps.append,
    )

    # The ordinary probe retains auto-negotiation. Both matrix rows, including
    # the catalog/default version, get separate pin-strict connections.
    assert [client.version for client in created] == [
        "2.22", "6.037", "2.22", "6.037",
    ]
    assert sleeps == [1.0, 1.0, 1.0]
    assert set(record["versions"]) == {"2.22", "6.037"}
    modern = record["versions"]["6.037"]
    classic = record["versions"]["2.22"]
    assert classic["version_status"] == "rejected"
    assert classic["server_advertised_version"] == "6.037"
    assert classic["renegotiated_to"] is None
    assert modern["requested_version"] == "6.037"
    assert modern["version_status"] == "rejected"
    assert modern["renegotiated_to"] is None
    assert modern["prop_parse_warnings"] == 0
    assert modern["prop_parse_errors"] == 0
    assert modern["player_position_sane"] is False
    assert modern["encryption_gen"] == 5
    assert modern["gen_source"] == "handshake"
    assert all(client.login_timeout <= 4.0 for client in created)


def test_matrix_records_are_isolated_to_each_fresh_connection():
    created = []

    class IsolatedClient(_RejectingClient):
        def __init__(self, host, port, version):
            super().__init__(host, port, version)
            self.authenticated = version == "6.037"
            self.tiles = list(range(4096))
            self.disconnect_reason = "Version 6.037 required" if version == "2.22" else ""
            created.append(self)

        def login(self, username, password, timeout):
            self._protocol.last_handshake_gen = self._protocol.gen
            self.connected = False
            return self.authenticated

    entry = ServerEntry("Example", "", "", "", "", "2.22", 0,
                        "example.test", 14900)
    record = probe_entry(
        entry, "account", "secret", timeout=1.0,
        client_factory=IsolatedClient,
        resolver=lambda *args, **kwargs: [(None, None, None, None, None)],
        versions=["2.22", "6.037"], sleep=lambda _: None,
    )

    assert len(created) == 4  # default attempt + retry + two fresh matrix pins
    assert record["versions"]["2.22"]["board_received"] is False
    assert record["versions"]["2.22"]["tiles_ok"] is False
    assert record["versions"]["6.037"]["board_received"] is True
    assert record["versions"]["6.037"]["tiles_ok"] is True


def test_matrix_record_receives_prop_anomaly_counters_from_its_client():
    class AnomalousClient(_RejectingClient):
        def __init__(self, host, port, version):
            super().__init__(host, port, version)
            self._decoder = Client(version=version)

        def login(self, username, password, timeout):
            self._protocol.last_handshake_gen = self._protocol.gen
            # Short COLORS under the 2.22 five-byte width cannot be decoded.
            self._decoder._handle_packet(
                PacketID.PLO_PLAYERPROPS, bytes([13 + 32, 32, 33]))
            self.prop_parse_diagnostics = self._decoder.prop_parse_diagnostics
            self.connected = False
            return False

    entry = ServerEntry("Example", "", "", "", "", "6.037", 0,
                        "example.test", 14900)
    record = probe_entry(
        entry, "account", "secret", timeout=1.0,
        client_factory=AnomalousClient,
        resolver=lambda *args, **kwargs: [(None, None, None, None, None)],
        versions=["2.22"], sleep=lambda _: None,
    )

    assert record["versions"]["2.22"]["prop_parse_errors"] == 1


def test_parse_versions_validates_and_deduplicates():
    assert parse_versions("2.22, 6.037,2.22") == ["2.22", "6.037"]
    try:
        parse_versions("9.999")
    except ValueError as exc:
        assert "9.999" in str(exc)
    else:
        raise AssertionError("unsupported version accepted")


def test_client_counts_player_prop_width_fallbacks_and_parse_errors():
    client = Client(version="6.037")
    # A classic five-byte COLORS payload followed by X/Y. The v6-preferred
    # width desynchronizes; the classic fallback consumes it cleanly.
    classic_props = bytes([13 + 32, 32, 33, 34, 35, 36,
                           15 + 32, 52, 16 + 32, 54])
    client._handle_packet(PacketID.PLO_PLAYERPROPS, classic_props)
    assert client.prop_parse_diagnostics == {
        "warnings": 1, "errors": 0, "width_fallbacks": 1,
    }
    assert (client.player.x, client.player.y) == (10.0, 11.0)

    client._handle_packet(PacketID.PLO_PLAYERPROPS,
                          bytes([13 + 32, 32, 33]))
    assert client.prop_parse_diagnostics["errors"] == 1


class _SendingProtocol:
    def __init__(self):
        self.calls = []

    def send_packet(self, packet_id, data=b""):
        self.calls.append((packet_id, data))
        return True


def test_listprocesses_replies_with_single_truthful_identity():
    client = Client()
    client._protocol = _SendingProtocol()
    client._handle_packet(PacketID.PLO_LISTPROCESSES, b"")
    assert client._protocol.calls == [(PacketID.PLI_PROCESSLIST, b"pyReborn")]
    assert int(PacketID.PLO_LISTPROCESSES) in HANDLED_PLO_IDS


class _WanderClient:
    def __init__(self, level_change_after=None):
        self.connected = True
        self.authenticated = True
        self._current_level_name = "start.nw"
        self.player = type("Player", (), {"x": 10.0, "y": 10.0, "level": "start.nw"})()
        self.tiles = []
        self.moves = []
        self.level_change_after = level_change_after

    def move(self, dx, dy, step):
        self.moves.append((dx, dy, step))
        self.player.x += dx * step
        self.player.y += dy * step
        return True

    def update(self, timeout):
        if self.level_change_after and len(self.moves) >= self.level_change_after:
            self._current_level_name = "other.nw"


def test_wander_counts_tiles_and_returns_to_start():
    client = _WanderClient()
    _exercise_probe_movement(client, 8, float("inf"))
    assert len(client.moves) == 32
    assert (client.player.x, client.player.y) == (10.0, 10.0)


def test_wander_aborts_when_level_changes():
    client = _WanderClient(level_change_after=3)
    _exercise_probe_movement(client, 8, float("inf"))
    assert len(client.moves) == 3
