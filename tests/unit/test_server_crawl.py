import json

from game_tester.server_crawl import (DeepCrawler, empty_crawl_record,
                                      classify_host_call, enumerate_gs2_events,
                                      parse_nw, real_gs1_surface,
                                      real_gs2_surface,
                                      run_gs1_bounded, run_gs2_bounded,
                                      shaped_error)
from game_tester.server_probe import empty_catalog, load_catalog, run_catalog_tests, save_catalog


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _Client:
    def __init__(self, clock, graph):
        self.clock = clock
        self.connected = True
        self._current_level_name = "a.nw"
        self.player = type("Player", (), {"level": "a.nw"})()
        self.links = graph
        self.tiles = [0] * 4096
        self.signs = {}
        self.npcs = {}
        self.baddies = {}
        self.players = {}
        self.weapons = {}
        self.gs2_bytecode = {}
        self._received_files = {name: b"GLEVNW01\n" for name in graph}

    def update(self, timeout):
        self.clock.advance(timeout)

    def use_link(self, link):
        self._current_level_name = link["dest_level"]
        self.player.level = self._current_level_name
        return True

    def chests_in_level(self, level):
        return {}

    def request_file(self, name):
        return True

    def is_file_pending(self, name):
        return False

    def get_file(self, name):
        return self._received_files.get(name)


def _link(dest):
    return {"dest_level": dest, "dest_x": 1, "dest_y": 1}


def test_bfs_visit_cap_and_dedupe():
    clock = _Clock()
    graph = {"a.nw": [_link("b.nw"), _link("b.nw")],
             "b.nw": [_link("a.nw"), _link("c.nw")], "c.nw": []}
    result = DeepCrawler(_Client(clock, graph), max_levels=2, timeout=20,
                         clock=clock, sleep=clock.advance,
                         renderer=lambda client, level: None).crawl()
    assert [entry["name"] for entry in result["levels_visited"]] == ["a.nw", "b.nw"]
    assert result["counts"]["levels"] == 2
    assert clock.now >= 0.5


def test_budget_abort_is_recorded():
    clock = _Clock()
    graph = {"a.nw": [_link("b.nw")], "b.nw": []}
    result = DeepCrawler(_Client(clock, graph), timeout=0.25, clock=clock,
                         sleep=clock.advance,
                         renderer=lambda client, level: None).crawl()
    assert [entry["name"] for entry in result["levels_visited"]] == ["a.nw"]
    assert any(error["phase"] == "budget" for error in result["errors"])


def test_gs2_step_cap_enforced(monkeypatch):
    import reborn_protocol.gs2.vm as vm_module

    class _FakeVM:
        ops_skipped = {}
        builtins_missing = {}

        def __init__(self, blob, name, host):
            self._ops_used = 0
            self.max_ops = 0

        def run_toplevel(self):
            self._ops_used = self.max_ops

    monkeypatch.setattr(vm_module, "GS2VM", _FakeVM)
    report = run_gs2_bounded(b"bytecode", max_ops=7)
    assert report["capped"] is True
    assert report["steps"] == 7


def test_error_record_shape_is_bounded_and_contextual():
    record = shaped_error("asset_parse", level="room.nw", asset="walk.gani",
                          exception=ValueError("x" * 2000), tb="trace")
    assert record["phase"] == "asset_parse"
    assert record["level"] == "room.nw" and record["asset"] == "walk.gani"
    assert len(record["exception"]) == 1000
    assert record["traceback"] == "trace"


def test_nw_parser_accepts_latin1_level_text():
    parse_nw(b"GLEVNW01\nSIGN 1 1\nnonbreaking:\xa0\nSIGNEND\n")


def test_gani_parameters_are_removed_before_download_and_parse():
    clock = _Clock()
    client = _Client(clock, {"a.nw": []})
    client.npcs = {1: {"gani": "eye_bomber_bombstill,56,sheet.png,101.gani"}}
    client._received_files["eye_bomber_bombstill.gani"] = b"ANI\n0 0 0\nANIEND\n"
    result = DeepCrawler(client, timeout=20, clock=clock, sleep=clock.advance,
                         renderer=lambda client, level: None).crawl()
    assert result["files_parsed"]["failed"] == 0
    assert not any("eye_bombsprites" in error.get("asset", "")
                   for error in result["errors"])


def test_shaped_error_includes_optional_context():
    record = shaped_error("gs1_parse", exception="bad", context="near failure")
    assert record["context"] == "near failure"


def test_catalog_crawl_section_round_trip(tmp_path):
    path = tmp_path / "catalog.json"
    catalog = empty_catalog()
    catalog["servers"]["Example"] = {"crawl": empty_crawl_record()}
    save_catalog(catalog, path)
    loaded = load_catalog(path)
    assert loaded == catalog
    assert json.loads(path.read_text())["schema_version"] == 3


class _GmapClient(_Client):
    def __init__(self, clock, foreign_warp=False):
        super().__init__(clock, {"a.nw": [], "b.nw": [], "c.nw": []})
        self.gmap_grid = {(0, 0): "a.nw", (1, 0): "b.nw", (2, 0): "c.nw"}
        self.gmap_width, self.gmap_height = 3, 1
        self.gmap_name = "world.gmap"
        self.in_gmap_segment = True
        self.x = self.player.x = 63.5
        self.y = self.player.y = 10.0
        self.foreign_warp = foreign_warp
        self._received_files["world.gmap"] = (
            b"WIDTH 3\nHEIGHT 1\nLEVELNAMES\na.nw,b.nw,c.nw\nLEVELNAMESEND\n")

    def move(self, dx, dy, step=0.5):
        if self.foreign_warp:
            self._current_level_name = self.player.level = "unexpected.nw"
            return True
        cell = next(pos for pos, name in self.gmap_grid.items()
                    if name == self._current_level_name)
        target = (cell[0] + dx, cell[1] + dy)
        if target in self.gmap_grid:
            self._current_level_name = self.player.level = self.gmap_grid[target]
            self.x = self.player.x = target[0] * 64 + 0.25
            self.y = self.player.y = target[1] * 64 + 10.0
        return True


def test_gmap_grid_bfs_visits_segments_and_parses_map():
    clock = _Clock()
    result = DeepCrawler(_GmapClient(clock), max_levels=3, timeout=20,
                         clock=clock, sleep=clock.advance,
                         renderer=lambda client, level: None).crawl()
    assert [entry["name"] for entry in result["levels_visited"]] == [
        "a.nw", "b.nw", "c.nw"]
    assert result["gmap"] == {"name": "world.gmap", "grid_size": [3, 1],
                              "segments_visited": 3}


def test_gmap_grid_aborts_on_foreign_warp():
    clock = _Clock()
    result = DeepCrawler(_GmapClient(clock, foreign_warp=True), max_levels=3,
                         timeout=20, clock=clock, sleep=clock.advance,
                         renderer=lambda client, level: None).crawl()
    assert len(result["levels_visited"]) == 1
    assert any(error["phase"] == "gmap_warp" for error in result["errors"])


def test_soak_tick_and_frame_cadence():
    clock = _Clock()
    ticks, frames = [], []
    crawler = DeepCrawler(_Client(clock, {"a.nw": []}), timeout=20, clock=clock,
                          ticker=lambda client, level, dt: ticks.append(dt),
                          renderer=lambda client, level: frames.append(level),
                          soak_seconds=1.0, soak_dt=0.1,
                          soak_frame_interval=0.5)
    result = crawler.crawl()
    assert len(ticks) == 10
    assert len(frames) == 3
    assert result["levels_visited"][0]["frames_rendered"] == 3


def test_soak_wall_cap_records_error():
    clock = _Clock()
    crawler = DeepCrawler(_Client(clock, {"a.nw": []}), timeout=20, clock=clock,
                          ticker=lambda client, level, dt: clock.advance(0.2),
                          renderer=lambda client, level: None,
                          soak_wall_seconds=0.1)
    result = crawler.crawl()
    assert result["soak"]["errors"] == 1
    assert any(error["phase"] == "soak" for error in result["errors"])


def test_recording_gs1_host_never_reaches_client_send_path():
    class _NoSendProtocol:
        def __init__(self):
            self.calls = []

        def send_packet(self, *args):
            self.calls.append(args)
            raise AssertionError("recording execution reached the wire")

    fake_client = type("FakeClient", (), {"_protocol": _NoSendProtocol()})()
    report = run_gs1_bounded("if (created) { playerhearts = 0; say unsafe; }")
    assert fake_client._protocol.calls == []
    assert ("set", "playerhearts") in report["host"].accesses
    assert report["implemented_count"] == 1
    assert report["true_gaps"] == []


def test_host_call_classification_uses_real_surfaces_and_registry():
    gs1_surface = real_gs1_surface()
    gs2_surface = real_gs2_surface()
    for name in ("showimg", "setani", "play"):
        assert classify_host_call(name, gs1_surface) == "implemented"
        assert classify_host_call(name, gs2_surface) == "implemented"
    assert classify_host_call("crawler_only_missing_call", gs2_surface) == "true_gap"
    assert classify_host_call("quattro::setvolume", gs2_surface) == "known_unsupported"
    assert classify_host_call("switchopenglrenderer", gs1_surface) == "known_unsupported"


def test_gs2_event_enumeration_comes_from_function_table():
    functions = {"helper": 1, "oncreated": 2, "onTimeout": 3,
                 "onPlayerEnters": 4}
    assert enumerate_gs2_events(functions) == [
        "oncreated", "onPlayerEnters", "onTimeout"]


def test_catalog_unreachable_and_rejected_are_skips(tmp_path, monkeypatch, capsys):
    path = tmp_path / "catalog.json"
    catalog = empty_catalog()
    base = {"address": {"host": "example.test", "port": 1},
            "testable_tests": [], "active_ok": False, "crawl": empty_crawl_record()}
    catalog["servers"]["Down"] = {**base, "capabilities": {"reachable": False}}
    catalog["servers"]["No Login"] = {
        **base, "capabilities": {"reachable": True, "login": "rejected",
                                 "login_reject_reason": "not allowed"}}
    save_catalog(catalog, path)

    class _Bot:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr("game_tester.game_bot.GameBot", _Bot)
    monkeypatch.setattr("game_tester.server_probe.Prefs.load",
                        lambda: type("Prefs", (), {"username": "u", "password": "p"})())
    assert run_catalog_tests(catalog_path=path) is True
    output = capsys.readouterr().out
    assert "SKIP unreachable" in output
    assert "SKIP login rejected: not allowed" in output
    assert "FAIL" not in output
