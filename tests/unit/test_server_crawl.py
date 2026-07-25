import json

from game_tester.server_crawl import (CrawlSession, DeepCrawler,
                                      RecordingHost, empty_crawl_record,
                                      classify_host_call, enumerate_gs2_events,
                                      other_gs2_functions, parse_nw,
                                      real_gs1_surface, real_gs2_surface,
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
            self._errors = 0
            self.max_ops = 0

        def run_toplevel(self):
            self._ops_used = self.max_ops

    monkeypatch.setattr(vm_module, "GS2VM", _FakeVM)
    report = run_gs2_bounded(b"bytecode", max_ops=7)
    assert report["capped"] is True
    assert report["steps"] == 7


def test_cooperative_main_loop_is_bounded_by_yields_not_reported_as_capped(monkeypatch):
    """A `while (true) { ...; sleep(); }` entry point is not a runaway script.

    Zelda's piano NPC (npc:10003 doplay) used to burn the whole 200k op
    budget here because a plain vm.call() makes sleep() inert; driven as the
    coroutine the client runs, it settles at a few ops per iteration.
    """
    import reborn_protocol.gs2.vm as vm_module

    class _LoopVM:
        ops_skipped = {}
        builtins_missing = {}
        functions = {"oncreated": 0, "doplay": 1}

        def __init__(self, blob, name, host):
            self._ops_used = 0
            self._errors = 0
            self.max_ops = 0

        def run_toplevel(self):
            self._ops_used = 1

        def iter_call(self, entry):
            def generator():
                self._ops_used = 0
                if entry == "doplay":
                    while True:
                        self._ops_used += 10
                        yield 0.05
                self._ops_used = 2
                return
                yield  # pragma: no cover - makes this a generator

            return generator()

    monkeypatch.setattr(vm_module, "GS2VM", _LoopVM)
    report = run_gs2_bounded(b"bytecode", max_ops=1000, max_yields=8)
    assert report["cooperative"] == ["doplay"]
    assert report["capped"] is False
    assert report["steps"] == 1 + 2 + 8 * 10


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
                              "segments_visited": 3, "segments_skipped": []}


def test_gmap_grid_aborts_on_foreign_warp():
    clock = _Clock()
    result = DeepCrawler(_GmapClient(clock, foreign_warp=True), max_levels=3,
                         timeout=20, clock=clock, sleep=clock.advance,
                         renderer=lambda client, level: None).crawl()
    assert len(result["levels_visited"]) == 1
    assert any(error["phase"] == "gmap_warp" for error in result["errors"])


class _GridGmapClient(_Client):
    """2x2 gmap. A seam listed in `walls` accepts the movement packet but
    never hands the segment over -- what a live server does at a blocked
    seam, and what used to end the whole grid BFS with no error recorded."""

    LEVELS = {(0, 0): "a.nw", (1, 0): "b.nw", (0, 1): "c.nw", (1, 1): "d.nw"}

    def __init__(self, clock, walls=()):
        super().__init__(clock, {name: [] for name in self.LEVELS.values()})
        self.gmap_grid = dict(self.LEVELS)
        self.gmap_width = self.gmap_height = 2
        self.gmap_name = "world.gmap"
        self.in_gmap_segment = True
        self.walls = set(walls)
        self.x = self.player.x = 32.0
        self.y = self.player.y = 32.0
        self._received_files["world.gmap"] = (
            b"WIDTH 2\nHEIGHT 2\nLEVELNAMES\na.nw,b.nw\nc.nw,d.nw\nLEVELNAMESEND\n")

    def _cell(self):
        return next(pos for pos, name in self.gmap_grid.items()
                    if name == self._current_level_name)

    def move(self, dx, dy, step=0.5):
        cell = self._cell()
        target = (cell[0] + dx, cell[1] + dy)
        if target not in self.gmap_grid or (cell, target) in self.walls:
            return True                      # accepted, but nothing moves
        local_x, local_y = self.x % 64, self.y % 64
        self.x = self.player.x = target[0] * 64 + (
            0.25 if dx > 0 else 63.75 if dx < 0 else local_x)
        self.y = self.player.y = target[1] * 64 + (
            0.25 if dy > 0 else 63.75 if dy < 0 else local_y)
        self._current_level_name = self.player.level = self.gmap_grid[target]
        return True


class _SettleAwayGmapClient(_GridGmapClient):
    """Hands the segment over and then moves us on again one pump later --
    the post-warp level re-check that used to `return False` without
    recording anything, killing the whole grid BFS."""

    def __init__(self, clock):
        super().__init__(clock)
        self._pumps_in_b = 0

    def update(self, timeout):
        super().update(timeout)
        if self._current_level_name != "b.nw":
            self._pumps_in_b = 0
            return
        self._pumps_in_b += 1
        if self._pumps_in_b >= 2:      # i.e. during the post-arrival settle
            self.x = self.player.x = 64 + 32.0
            self.y = self.player.y = 64 + 32.0
            self._current_level_name = self.player.level = "d.nw"


def _grid_crawl(client, clock, **kwargs):
    return DeepCrawler(client, max_levels=4, timeout=60, clock=clock,
                       sleep=clock.advance,
                       renderer=lambda client, level: None, **kwargs).crawl()


def test_gmap_walled_seam_is_recorded_and_routed_around():
    clock = _Clock()
    result = _grid_crawl(_GridGmapClient(clock, walls={((0, 0), (1, 0))}), clock)
    # the walled seam costs one skip, not the other three segments
    assert sorted(entry["name"] for entry in result["levels_visited"]) == [
        "a.nw", "b.nw", "c.nw", "d.nw"]
    assert result["gmap"]["segments_visited"] == 4
    skipped = result["gmap"]["segments_skipped"]
    assert [item["level"] for item in skipped] == ["b.nw"]
    assert "never changed to b.nw" in skipped[0]["reason"]
    assert any(error["phase"] == "gmap_seam" for error in result["errors"])


def test_gmap_seam_that_settles_elsewhere_is_not_silent():
    clock = _Clock()
    result = _grid_crawl(_SettleAwayGmapClient(clock), clock)
    reasons = [item["reason"] for item in result["gmap"]["segments_skipped"]]
    assert reasons and all("settled in d.nw" in reason for reason in reasons)
    assert any(error["phase"] == "gmap_warp" for error in result["errors"])
    # b.nw is genuinely unreachable, everything else still gets crawled
    assert sorted(entry["name"] for entry in result["levels_visited"]) == [
        "a.nw", "c.nw", "d.nw"]


def test_gmap_traversal_gives_up_after_repeated_seam_failures():
    clock = _Clock()
    walls = {((0, 0), (1, 0)), ((0, 0), (0, 1)), ((1, 0), (0, 0)),
             ((0, 1), (0, 0)), ((1, 1), (1, 0)), ((1, 1), (0, 1))}
    result = _grid_crawl(_GridGmapClient(clock, walls=walls), clock)
    assert result["gmap"]["segments_visited"] == 1
    assert result["gmap"]["segments_skipped"]
    assert any("consecutive unusable seams" in error["exception"] or
               error["phase"] == "gmap_seam" for error in result["errors"])


def test_grid_route_avoids_blocked_seams():
    grid = {cell: "x" for cell in ((0, 0), (1, 0), (0, 1), (1, 1))}
    route = DeepCrawler._grid_route(grid, (0, 0), (1, 0), set())
    assert route == [(0, 0), (1, 0)]
    around = DeepCrawler._grid_route(grid, (0, 0), (1, 0), {((0, 0), (1, 0))})
    assert around == [(0, 0), (0, 1), (1, 1), (1, 0)]
    walled = {((0, 0), (1, 0)), ((0, 0), (0, 1))}
    assert DeepCrawler._grid_route(grid, (0, 0), (1, 1), walled) is None


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


def _session_vm(session, kind, key, functions=()):
    """A registered, empty VM that claims to declare `functions`."""
    from reborn_protocol.gs2.container import GS2Container
    vm = session.vm_for((kind, key), GS2Container())
    for name in functions:
        vm.functions[name.lower()] = 0
    return vm


def test_shared_session_resolves_cross_script_calls():
    """Zelda's -Player/Movement calls plfunc.modifyclientr(...) and
    ("-Player/Movement").HurtPlayer(...); with one host per script both
    reached the host as unknown builtins and were reported as engine gaps."""
    from reborn_protocol.gs2.vm import GS2ScriptFunction

    session = CrawlSession()
    functions = _session_vm(session, "weapon", "-Player/Functions",
                            ["modifyclientr", "hit"])
    movement = _session_vm(session, "weapon", "-Player/Movement", ["HurtPlayer"])
    # what `plfunc = this` publishes, read back off the FOREIGN this-object
    assert isinstance(functions.this.get("modifyclientr"), GS2ScriptFunction)
    assert functions.this.get("nosuchmember") is None
    # ("-Player/Movement") resolves to that weapon's script object
    assert session.host.get_object("-player/movement") is movement.this
    assert session.host.get_object("nobody") is None
    # ...and both scripts write to ONE globals dict
    movement.globals["plfunc"] = functions.this
    assert functions.globals["plfunc"] is functions.this


def test_isolated_session_keeps_scripts_apart():
    session = CrawlSession()
    _session_vm(session, "weapon", "-Player/Functions", ["modifyclientr"])
    assert RecordingHost().get_object("-Player/Functions") is None


def test_shared_host_call_counts_are_reported_per_script():
    """The shared host's counters are cumulative; each script's report must
    still describe only its own calls."""
    session = CrawlSession()
    _session_vm(session, "weapon", "empty")     # registers the VM; blob unused
    session.host.call_builtin(None, "anotherscriptscall", [])
    report = run_gs2_bounded(b"", "weapon:empty", session=session)
    assert report["true_gaps"] == []
    assert session.host.calls["anotherscriptscall"] == 1


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


def test_resolved_call_filter_hides_only_real_host_names():
    # RecordingHost answers every call NOT_HANDLED (to record it), which
    # makes the VM log "unknown function X()" even for names the live
    # GS2ClientHost implements (sendtext/sort/... misled a whole round).
    # The filter drops exactly those, keeping true-gap warnings visible.
    import logging

    from game_tester.server_crawl import _ResolvedCallFilter

    surface = {item.casefold() for item in real_gs2_surface()}
    assert {"sendtext", "sort", "makefirstresponder", "isobject",
            "findweapon", "echo"} <= surface
    filt = _ResolvedCallFilter(surface)

    def record(msg, *args):
        return logging.LogRecord("reborn_protocol.gs2.vm", logging.WARNING,
                                 __file__, 1, msg, args, None)

    for name in ("sendtext", "findweapon"):
        assert not filt.filter(record("GS2 %s: unknown function %s()",
                                      "weapon:-Serverlist_Chat", name))
    assert not filt.filter(record("GS2 %s: unknown method %s()",
                                  "weapon:-Serverlist_Chat", "sort"))
    assert not filt.filter(record("GS2 x: unknown function %s()",
                                  "quattro::setvolume"))  # known-unsupported
    assert filt.filter(record("GS2 x: unknown function %s()",
                              "crawler_only_missing_call"))
    assert filt.filter(record("GS2 x: unimplemented opcode %s, skipping", 47))


def test_run_gs2_bounded_suppresses_implemented_name_warnings(caplog):
    # weapon:-Rescripted/IRC/Login3 shape: onCreated calls findweapon()/
    # isObject()/echo() -- all implemented on the real client host, so a
    # bounded recording run must not log them as unknown.
    import logging

    import reborn_protocol.gs2.vm as vm_module

    class _FakeVM:
        ops_skipped = {}
        builtins_missing = {}
        functions = {}

        def __init__(self, blob, name, host):
            self._ops_used = 0
            self._errors = 0
            self.max_ops = 0
            self._name = name
            self._host = host

        def run_toplevel(self):
            log = logging.getLogger("reborn_protocol.gs2.vm")
            for name in ("findweapon", "echo", "some_true_gap"):
                self._host.call_builtin(self, name, [])
                log.warning("GS2 %s: unknown function %s()", self._name, name)

    with caplog.at_level(logging.WARNING, logger="reborn_protocol.gs2.vm"):
        import unittest.mock
        with unittest.mock.patch.object(vm_module, "GS2VM", _FakeVM):
            report = run_gs2_bounded(b"bytecode", name="weapon:test")
    messages = [rec.getMessage() for rec in caplog.records]
    assert not any("findweapon" in msg or "echo()" in msg for msg in messages)
    assert any("some_true_gap" in msg for msg in messages)
    assert report["true_gaps"] == ["some_true_gap"]
    assert report["implemented_count"] == 2


def test_gs2_event_enumeration_comes_from_function_table():
    functions = {"helper": 1, "oncreated": 2, "onTimeout": 3,
                 "onPlayerEnters": 4}
    assert enumerate_gs2_events(functions) == [
        "oncreated", "onPlayerEnters", "onTimeout"]


def test_other_gs2_functions_excludes_the_events_already_called():
    functions = {"onCreated": 1, "DoSword": 2, "fps.onSelect": 3, "helper": 4}
    events = enumerate_gs2_events(functions)
    assert other_gs2_functions(functions, events) == ["DoSword", "helper"]


class _ScriptClient(_Client):
    """Client that only serves script bytecode when it is asked for it."""

    def __init__(self, clock):
        super().__init__(clock, {"a.nw": []})
        self.gs2_bytecode = {"weapon": {"Pushed": b"pushed"}, "class": {}}
        self.gs2_script_headers = {
            "Pushed": {"name": "Pushed", "type": "weapon", "bytecode": b"pushed"},
            "door": {"name": "door", "type": "class", "bytecode": b""},
        }
        self.requested = []

    def request_weapon_bytecode(self, name):
        self.requested.append(("weapon", name))
        return True

    def request_class_bytecode(self, name, checksum=0):
        self.requested.append(("class", name))
        if name == "door":
            self.gs2_bytecode["class"]["door"] = b"door-bytecode"
        return True


def _stub_gs2_reports(monkeypatch, reports):
    def fake_run(blob, name="script", *args, **kwargs):
        return reports[name]
    monkeypatch.setattr("game_tester.server_crawl.run_gs2_bounded", fake_run)


def _gs2_report(**overrides):
    report = {"capped": False, "steps": 1, "elapsed": 0.0, "cooperative": [],
              "unknown_opcodes": [],
              "implemented_count": 0, "stubbed": [], "true_gaps": [],
              "known_unsupported": [], "events": [], "event_failures": [],
              "functions": [], "function_failures": [], "vm_errors": 0,
              "warnings": [], "referenced_scripts": {"weapon": [], "class": []}}
    report.update(overrides)
    return report


def test_announced_and_referenced_scripts_are_fetched_and_run(monkeypatch):
    # Zelda announces 11 classes as header-only PLO_LOADSCRIPT records and a
    # weapon names more through findweapon(); neither is ever pushed.
    clock = _Clock()
    client = _ScriptClient(clock)
    _stub_gs2_reports(monkeypatch, {
        "weapon:Pushed": _gs2_report(
            true_gaps=["nosuchcall"], warnings=["unknown function nosuchcall()"],
            referenced_scripts={"weapon": ["-Client/Install"], "class": []}),
        "class:door": _gs2_report(events=["onCreated"], implemented_count=3),
    })
    result = DeepCrawler(client, timeout=20, clock=clock, sleep=clock.advance,
                         renderer=lambda client, level: None).crawl()

    assert sorted(client.requested) == [("class", "door"),
                                        ("weapon", "-Client/Install")]
    assert result["gs2"]["fetched"] == 1
    assert result["gs2"]["fetch_missing"] == ["weapon:-Client/Install"]
    scripts = {f"{item['kind']}:{item['name']}": item for item in result["gs2"]["scripts"]}
    assert scripts["weapon:Pushed"]["source"] == "pushed"
    assert scripts["weapon:Pushed"]["warnings"] == ["unknown function nosuchcall()"]
    assert scripts["class:door"]["source"] == "fetched"
    assert result["gs2"]["true_gaps"] == ["nosuchcall"]


def test_script_fetching_respects_the_crawl_budget(monkeypatch):
    clock = _Clock()
    client = _ScriptClient(clock)
    _stub_gs2_reports(monkeypatch, {"weapon:Pushed": _gs2_report()})
    crawler = DeepCrawler(client, timeout=20, clock=clock, sleep=clock.advance,
                          renderer=lambda client, level: None)
    crawler.deadline = clock() - 1
    crawler._run_bytecodes()
    assert client.requested == []
    assert crawler.result["gs2"]["fetched"] == 0
    assert crawler.result["gs2"]["fetch_missing"] == []


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
