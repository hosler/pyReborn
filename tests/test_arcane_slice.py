"""Offline acceptance tests for the funtimes Arcane weapon and dungeon."""

from collections import deque
import asyncio
from pathlib import Path
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Resolve the installed server package before its sibling world/ data directory.
sys.path.insert(0, str(ROOT / "pygserver"))

from pyreborn.gs1_client import ClientGS1
from pyreborn.tiletypes import type_is_blocking
from pygserver.level import Level
from pygserver.tiletypes import get_tile_type


WORLD = ROOT / "funtimes-pygserver"
WEAPON = WORLD / "weapons/weapon-ArcaneBolt.txt"
GENERATOR = WORLD / "tools/gen_dungeon.py"
DUNGEON = WORLD / "world/arcane_dungeon.nw"
KEY = "weapon_ArcaneBolt"


def weapon_source():
    return WEAPON.read_text().split("//#CLIENTSIDE", 1)[1].rsplit("SCRIPTEND", 1)[0]


def runtime(direction=3):
    client = SimpleNamespace(
        player=SimpleNamespace(x=20.0, y=20.0, direction=direction, account="mage",
                               nickname="Mage", id=1),
        x=20.0, y=20.0, players={}, npcs={}, baddies={}, weapons={},
        connected=False, _current_level_name="arcane_dungeon.nw",
        _tiles_level_name="arcane_dungeon.nw", tiles=[0x1FF] * 4096,
    )
    rt = ClientGS1(client)
    actions = []
    rt.on_triggeraction = lambda x, y, action, npc_id: actions.append(
        (x, y, action, npc_id))
    rt.load_weapon("ArcaneBolt", weapon_source())
    assert rt._progs[KEY]["prog"] is not None
    return rt, client, actions


def fire(rt):
    rt.trigger_event("weaponfired", name=KEY)


def layers(rt):
    return rt._weapon_imgs[KEY]


@pytest.mark.parametrize("direction,dx,dy", [(0, 0, -1), (1, -1, 0),
                                            (2, 0, 1), (3, 1, 0)])
def test_bolt_emitter_and_facing(direction, dx, dy):
    rt, _, actions = runtime(direction)
    fire(rt)
    image = layers(rt)[200]
    assert image["image"] == "arcane_bolt.png"
    assert (image["x"], image["y"]) == (20 + dx, 20 + dy)
    emitter = image["emitter"]
    assert emitter.get("nrofparticles") == 3
    assert emitter.get("delaymin") == pytest.approx(0.05)
    assert emitter.get("particle").get("image") == "arcane_spark.png"
    assert emitter.get("particle").get("lifetime") == pytest.approx(0.4)
    assert len(emitter.local_modifiers) == 4
    fire(rt)  # A second fire cannot create another live bolt or reset its trail.
    assert layers(rt)[200]["emitter"] is emitter
    rt.process_timeouts(0.05)
    assert (image["x"], image["y"]) == (20 + 2 * dx, 20 + 2 * dy)
    rt.process_timeouts(0.05)  # First advance starts the emitter's cadence.
    assert emitter.get("currentparticlecount") > 0
    assert not actions


def test_baddy_hit_reports_exact_weapon_carrier_and_hides_image():
    rt, client, actions = runtime()
    client.baddies[42] = {"x": 23.0, "y": 20.0, "power": 2}
    fire(rt)
    rt.process_timeouts(0.05)
    assert actions == [(22.0, 20.0,
                        "serverside,ArcaneBolt,hit,baddy,0,22,20", -1)]
    assert 200 not in layers(rt)
    assert rt._progs[KEY]["scopes"]["this"]["live"] is False
    rt.process_timeouts(0.05)
    assert len(actions) == 1
    fire(rt)
    assert 200 in layers(rt)


def test_npc_hit_uses_level_index_and_skips_invisible_image():
    rt, client, actions = runtime()
    client.npcs[10] = {"x": 22, "y": 20, "image": "body.png", "visible": False}
    client.npcs[20] = {"x": 22, "y": 20, "image": "body.png"}
    fire(rt)
    rt.process_timeouts(0.05)
    assert actions == [(22.0, 20.0,
                        "serverside,ArcaneBolt,hit,npc,1,22,20", -1)]
    assert 200 not in layers(rt)


def test_player_hit_skips_self():
    rt, client, actions = runtime()
    client.players[2] = {"x": 23, "y": 20, "account": "other"}
    fire(rt)
    rt.process_timeouts(0.05)
    assert actions == [(22.0, 20.0,
                        "serverside,ArcaneBolt,hit,player,1,23.5,22", -1)]
    assert 200 not in layers(rt)


@pytest.mark.parametrize("wall", [False, True])
def test_range_and_blocking_tiles_stop_the_bolt(wall):
    rt, client, actions = runtime()
    if wall:
        client.tiles[20 * 64 + 22] = 0x278
    fire(rt)
    image = layers(rt)[200]
    for _ in range(1 if wall else 12):
        rt.process_timeouts(0.05)
    assert 200 not in layers(rt)
    assert image["x"] == (22 if wall else 33)
    assert not actions


def assert_dungeon(path):
    rows = [line.split() for line in path.read_text().splitlines()
            if line.startswith("BOARD ")]
    assert len(rows) == 64
    assert {int(row[2]) for row in rows} == set(range(64))
    assert all(row[1] == "0" and row[3:5] == ["64", "0"]
               and len(row[5]) == 128 for row in rows)
    level = Level.load(str(path))
    assert not level._unsupported_features
    assert 6 <= len(level._baddies) <= 10
    assert {baddy["type"] for baddy in level._baddies} == {0, 1, 2}
    assert len(level._links) == 1
    link = level._links[0]
    assert link["dest_level"] == "chicken1.nw"
    assert (float(link["dest_x"]), float(link["dest_y"])) == (29, 23)
    assert len(level._npc_defs) == 1
    assert "Warden" in level._npc_defs[0]["code"]
    assert get_tile_type(level.get_tile(9, 9)) == 0
    assert not type_is_blocking(get_tile_type(level.get_tile(9, 9)))
    assert {level.get_tile(x, y) for y in range(64) for x in range(64)} == {
        0x1FF, 0x278}
    for i in range(64):
        assert level.get_tile(i, 0) == level.get_tile(i, 63) == 0x278
        assert level.get_tile(0, i) == level.get_tile(63, i) == 0x278

    reachable = {(9, 9)}
    queue = deque(reachable)
    while queue:
        x, y = queue.popleft()
        for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            nx, ny = point
            if (0 <= nx < 64 and 0 <= ny < 64 and point not in reachable
                    and not type_is_blocking(get_tile_type(level.get_tile(nx, ny)))):
                reachable.add(point)
                queue.append(point)
    assert (int(link["x"]), int(link["y"])) in reachable
    for entity in level._baddies + level._npc_defs:
        assert (int(entity["x"]), int(entity["y"])) in reachable
    return level


def test_checked_in_dungeon_parses_and_is_connected():
    assert_dungeon(DUNGEON)


def test_generator_is_deterministic_and_reproduces_seed_one(tmp_path):
    outputs = [tmp_path / "first.nw", tmp_path / "second.nw"]
    for output in outputs:
        result = subprocess.run(
            [sys.executable, "-B", str(GENERATOR), "--seed", "1", "--out", str(output)],
            check=True, capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert "rooms=[" in result.stdout
    assert outputs[0].read_bytes() == outputs[1].read_bytes() == DUNGEON.read_bytes()
    assert_dungeon(outputs[0])


def test_portal_entry_matches_the_generated_level():
    town = Level.load(str(WORLD / "world/chicken1.nw"))
    archmage, portal = town._npc_defs[-2:]
    assert (archmage["x"], archmage["y"]) == (30, 26)
    assert (portal["x"], portal["y"]) == (31, 24.5)
    assert "setlevel2 arcane_dungeon.nw,9,9;" in portal["code"]
    assert "Press Q, pick Arcane Bolt, then D to cast." in archmage["code"]
    assert "setshape 1,32,32;" in archmage["code"]
    for npc in (archmage, portal):
        assert get_tile_type(town.get_tile(int(npc["x"]), int(npc["y"]))) == 0
        assert (npc["x"] - 30)**2 + (npc["y"] - 30.5)**2 <= 6.5**2
    # The Archmage's 2x2 footprint fits the grass strip west of the house.
    for x in (30, 31):
        for y in (26, 27):
            assert town.get_tile(x, y) == 0x7FF
    assert town.get_tile(31, 24) == town.get_tile(31, 25) == 0x7FF
    assert not type_is_blocking(get_tile_type(town.get_tile(29, 23)))
    # No automatic portal touch at spawn or after taking the dungeon exit.
    for x, y in ((30, 30.5), (29, 23)):
        assert abs(portal["x"] - x) >= 2 or abs(portal["y"] - y) >= 2


class ServerPlayer(SimpleNamespace):
    def __init__(self, level):
        super().__init__(id=1, x=20.0, y=20.0, direction=3, level=level,
                         hearts=3.0, max_hearts=3.0, flags={}, weapons=[],
                         account_name="mage", nickname="Mage", sent=[], warps=[])

    def add_weapon(self, name):
        if name not in self.weapons:
            self.weapons.append(name)

    async def send_raw(self, packet):
        self.sent.append(packet)

    async def send_props(self, props):
        pass

    async def warp(self, level, x, y):
        self.warps.append((level, x, y))


class OfflineServer:
    """Real script/combat managers, with only transport and world storage faked."""

    def __init__(self, tmp_path):
        from pygserver.baddy import BaddyManager
        from pygserver.combat import CombatManager
        from pygserver.gs2 import GS2ScriptManager, parse_weapon_file
        from pygserver.npc import NPCManager

        self.config = SimpleNamespace(weapons_dir=str(tmp_path / "weapons"))
        self.level = Level("arcane_dungeon.nw")
        self.player = ServerPlayer(self.level)
        self.players = {self.player.id: self.player}
        self.level.add_player(self.player)
        self.server_flags = {}
        self.broadcasts = []
        self.world = SimpleNamespace(get_level=lambda name: self.level,
                                     get_gmap_for_level=lambda name: None)
        self.npc_manager = NPCManager(self)
        self.baddy_manager = BaddyManager(self)
        self.combat_manager = CombatManager(self)
        self.gs2_manager = GS2ScriptManager(self, str(tmp_path))
        name, image, source = parse_weapon_file(WEAPON.read_text())
        self.weapon = self.gs2_manager.upsert_classic_weapon(name, image, source)

    def get_player(self, pid):
        return self.players.get(pid)

    def add_player(self, pid, account, x, y):
        player = ServerPlayer(self.level)
        player.id = pid
        player.account_name = account
        player.x, player.y = x, y
        self.players[pid] = player
        self.level.add_player(player)
        return player

    async def broadcast_to_level(self, level, packet, exclude=None):
        self.broadcasts.append(packet)

    def town_npcs(self):
        town = Level.load(str(WORLD / "world/chicken1.nw"))
        result = []
        for definition in town._npc_defs[-2:]:
            npc = self.npc_manager.create_npc(level=self.level,
                                              x=definition["x"], y=definition["y"])
            self.npc_manager.attach_gs1(npc, definition["code"])
            result.append(npc)
        return result


@pytest.mark.parametrize("kind", ["baddy", "npc", "player"])
def test_server_applies_damage_and_counts_hits_on_the_firing_player(tmp_path, kind):
    from pygserver.baddy import BaddyType
    from pygserver.protocol.packets import build_flag_set
    from pygserver.server import GameServer

    async def check():
        server = OfflineServer(tmp_path)
        player = server.player
        if kind == "baddy":
            target = await server.baddy_manager.add_baddy(
                server.level, 23, 20, BaddyType(0))
            health = target.health
        elif kind == "npc":
            target = server.npc_manager.create_npc(level=server.level, x=22, y=19)
            target.body_image = "body.png"
            target.image = "#c#"  # a character NPC (showcharacter) has the 32x32 box
            health = target.hearts
        else:
            target = server.add_player(2, "target", 22, 19)
            health = target.hearts
        assert await GameServer.handle_trigger_action(
            server, player, 22, 20, f"serverside,ArcaneBolt,hit,{kind},0,22,20")
        await asyncio.sleep(0)
        if kind == "baddy":
            assert target.health == health - 1
        else:
            assert target.hearts == health - (1 if kind == "npc" else 0.5)
        assert player.hearts == 3.0
        assert player.flags["client.arcane.hits"] == "1"
        flag_packet = build_flag_set("client.arcane.hits", "1")
        assert player.sent.count(flag_packet) == 1
        assert flag_packet not in server.broadcasts
        if kind == "player":
            assert flag_packet not in target.sent
        # Unknown verbs and target kinds must do nothing, including to flags.
        for tail in ("miss,baddy,0,22,20", "hit,unknown,0,22,20"):
            await GameServer.handle_trigger_action(
                server, player, 22, 20, "serverside,ArcaneBolt," + tail)
        assert player.flags["client.arcane.hits"] == "1"

    asyncio.run(check())


def test_quest_completion_is_once_per_player_and_portal_checks_flag(tmp_path):
    from pygserver.gs1_host import run_npc_event

    async def check():
        server = OfflineServer(tmp_path)
        archmage, portal = server.town_npcs()
        player = server.player
        run_npc_event(portal, "playertouchsme", server, player)
        await asyncio.sleep(0)
        assert not player.warps
        run_npc_event(archmage, "playertouchsme", server, player)
        assert "ArcaneBolt" in player.weapons
        assert player.flags["client.arcane.quest"] is True
        assert player.flags["client.arcane.hits"] == "0"
        run_npc_event(archmage, "playertouchsme", server, player)
        assert "serverr.arcane.champions" not in server.server_flags
        player.flags["client.arcane.hits"] = "10"
        run_npc_event(archmage, "playertouchsme", server, player)
        assert player.flags["client.arcane.done"] is True
        assert server.server_flags["serverr.arcane.lastchampion"] == "mage"
        assert server.server_flags["serverr.arcane.champions"] == "1"
        run_npc_event(archmage, "playertouchsme", server, player)
        assert server.server_flags["serverr.arcane.champions"] == "1"
        run_npc_event(portal, "playertouchsme", server, player)
        await asyncio.sleep(0)
        assert player.warps == [("arcane_dungeon.nw", 9.0, 9.0)]

    asyncio.run(check())


def test_quest_grant_preserves_the_file_backed_weapon(tmp_path):
    from pygserver.gs1_host import run_npc_event
    from pyreborn.inventory_ui import InventoryUI

    async def check():
        server = OfflineServer(tmp_path)
        archmage, _ = server.town_npcs()
        original = server.weapon.source
        run_npc_event(archmage, "playertouchsme", server, server.player)
        await asyncio.sleep(0)
        weapon = server.gs2_manager.get_weapon("ArcaneBolt")
        assert weapon is server.weapon
        assert weapon.source == original
        assert server.player.weapons == ["ArcaneBolt"]
        assert InventoryUI._visible_weapon_entries(server.player.weapons) == [
            ("ArcaneBolt", {})]
        assert any(b"ArcaneBolt" in packet for packet in server.player.sent)

    asyncio.run(check())


def test_npc_hit_skips_a_hidden_character():
    rt, client, actions = runtime()
    client.npcs[10] = {"x": 21, "y": 19, "image": "body.png",
                       "body_image": "body.png", "visible": False}
    fire(rt)
    rt.process_timeouts(0.05)
    assert not actions


def test_client_player_index_hits_the_same_player_on_the_server(tmp_path):
    from pygserver.server import GameServer

    async def check():
        server = OfflineServer(tmp_path)
        target = server.player  # Joined first on the server.
        target.x, target.y = 22, 19
        target.account_name = "target"
        shooter = server.add_player(2, "mage", 20, 20)
        rt, client, actions = runtime()
        client.player.id = 2
        client.players[1] = {"x": 22, "y": 19, "account": "target"}
        fire(rt)
        rt.process_timeouts(0.05)
        x, y, action, _ = actions[0]
        assert action == "serverside,ArcaneBolt,hit,player,1,23.5,22"
        assert await GameServer.handle_trigger_action(server, shooter, x, y, action)
        await asyncio.sleep(0)
        assert target.hearts == 2.5
        assert shooter.hearts == 3.0
        assert shooter.flags["client.arcane.hits"] == "1"
        assert target.flags == {}

    asyncio.run(check())


@pytest.mark.parametrize("kind", ["player", "npc"])
@pytest.mark.parametrize("target_xy,probe_count", [
    ((29, 29), 1),      # Exact bolt point (30,30).
    ((30, 29), 2),      # Only +0.5 x reaches the rectangle.
    ((27, 29), 3),      # Only -0.5 x reaches the rectangle.
    ((29, 29.5), 4),    # Only +0.5 y reaches the rectangle.
    ((29, 26.5), 5),    # Only -0.5 y reaches the rectangle.
    ((50, 50), 5),      # Every probe misses.
])
def test_server_resolves_collision_rectangles_with_at_most_five_probes(
        tmp_path, monkeypatch, kind, target_xy, probe_count):
    from pygserver.gs1.host import GS1Host
    from pygserver.server import GameServer

    probes = []
    original = GS1Host._test_at

    def record_probe(host, args, ctx, players):
        probes.append(tuple(args))
        return original(host, args, ctx, players)

    monkeypatch.setattr(GS1Host, "_test_at", record_probe)

    async def check():
        server = OfflineServer(tmp_path)
        if kind == "player":
            target = server.add_player(2, "target", *target_xy)
        else:
            target = server.npc_manager.create_npc(
                level=server.level, x=target_xy[0], y=target_xy[1])
            target.body_image = "body.png"
            target.image = "#c#"  # a character NPC (showcharacter) has the 32x32 box
        await GameServer.handle_trigger_action(
            server, server.player, 30, 30,
            f"serverside,ArcaneBolt,hit,{kind},999,30,30")
        await asyncio.sleep(0)
        hit = target_xy != (50, 50)
        assert target.hearts == 3.0 - ((0.5 if kind == "player" else 1) if hit else 0)
        assert server.player.hearts == 3.0
        assert server.player.flags.get("client.arcane.hits") == (
            "1" if hit else None)
        assert probes == [(30, 30), (30.5, 30), (29.5, 30),
                          (30, 30.5), (30, 29.5)][:probe_count]

    asyncio.run(check())


@pytest.mark.parametrize("bolt", [(20, 20), (21.5, 20), (20, 21.5), (20.9, 20.9)])
def test_server_player_self_guard_rejects_before_probing(tmp_path, monkeypatch, bolt):
    from pygserver.gs1.host import GS1Host
    from pygserver.server import GameServer

    def unexpected_probe(*args, **kwargs):
        pytest.fail("Self guard must reject before a player hit test")

    monkeypatch.setattr(GS1Host, "_test_at", unexpected_probe)

    async def check():
        server = OfflineServer(tmp_path)
        # A remote collision rectangle overlaps the bolt; the self guard wins.
        target = server.add_player(2, "target", bolt[0] - 0.5, bolt[1] - 1)
        await GameServer.handle_trigger_action(
            server, server.player, *bolt,
            f"serverside,ArcaneBolt,hit,player,1,{bolt[0]},{bolt[1]}")
        await asyncio.sleep(0)
        assert server.player.hearts == target.hearts == 3.0
        assert not server.player.flags.get("client.arcane.hits")

    asyncio.run(check())


def test_server_resolves_npc_by_position_instead_of_reported_index(tmp_path):
    from pygserver.server import GameServer

    async def check():
        server = OfflineServer(tmp_path)
        decoy = server.npc_manager.create_npc(level=server.level, x=45, y=45)
        target = server.npc_manager.create_npc(level=server.level, x=22, y=19)
        decoy.body_image = target.body_image = "body.png"
        decoy.image = target.image = "#c#"  # character NPCs carry the collision box
        await GameServer.handle_trigger_action(
            server, server.player, 22, 20,
            "serverside,ArcaneBolt,hit,npc,0,22,20")
        await asyncio.sleep(0)
        assert decoy.hearts == 3.0
        assert target.hearts == 2.0
        assert server.player.flags["client.arcane.hits"] == "1"

    asyncio.run(check())


@pytest.mark.parametrize("bolt_x,index,accepted", [
    (36, 0, True), (36.01, 0, False), (22, -1, False), (22, 0.5, False),
])
def test_server_index_fallback_bounds_bolt_distance_and_rejects_invalid_index(
        tmp_path, bolt_x, index, accepted):
    from pygserver.baddy import BaddyType
    from pygserver.server import GameServer

    async def check():
        server = OfflineServer(tmp_path)
        target = await server.baddy_manager.add_baddy(
            server.level, 23, 20, BaddyType(0))
        before = target.health
        await GameServer.handle_trigger_action(
            server, server.player, bolt_x, 20,
            f"serverside,ArcaneBolt,hit,baddy,{index},{bolt_x},20")
        await asyncio.sleep(0)
        after = target.health
        assert after == before - int(accepted)
        assert server.player.flags.get("client.arcane.hits") == (
            "1" if accepted else None)

    asyncio.run(check())
