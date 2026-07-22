import json

from game_tester.server_probe import (
    _exercise_probe_movement,
    capabilities_to_tests,
    empty_catalog,
    load_catalog,
    merge_probe_record,
    parse_server_name,
    parse_versions,
    probe_entry,
    save_catalog,
)
from pyreborn.client import Client, HANDLED_PLO_IDS
from pyreborn.packets import PacketID
from pyreborn.listserver import ListServerClient, PacketReader, ServerEntry


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
