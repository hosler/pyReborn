"""Per-level tilestype selection and tile-type-table routing.

Oracle: ``TTiles::GetLevelTiles`` (Preagonal/FourPlay/quattroplay/src/
TTiles.cpp:568-631) resets tilestype to 0 on level change and takes the type
of the longest-prefix-matching tiledef, skipping defs with type >= 3 unless
the type is 5. ``TServerLevel::getTileType`` (src/TServerLevel.cpp:688-708)
then reads the classic table for tilestype 0, the new-world table for 1/2,
and reports type 0 for everything under tilestype 5.

``tiletypesnw.dat`` was extracted from the official v6.0.3.7 Linux client
(0x541740, directly after the classic table which byte-matches
tiletypes1.dat). On real era_ levels the classic table calls 96% of board
tiles blocking while the new-world table gives a plausible 57%.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn import tiletypes as tt
from pyreborn.tiletypes import TileType, get_tile_type, select_tilestype


@pytest.fixture(autouse=True)
def _clean_registry():
    tt.reset_tiledefs()
    tt.set_current_level("")
    yield
    tt.reset_tiledefs()
    tt.set_current_level("")


# --- the selection rule (pure) --------------------------------------------

def test_no_defs_selects_classic():
    assert select_tilestype([], "zlttp_overworld.nw") == 0


def test_longest_matching_prefix_wins():
    defs = [("", 1), ("era_", 2)]
    assert select_tilestype(defs, "era_mainstreet.nw") == 2
    assert select_tilestype(defs, "somewhere.nw") == 1


def test_registration_order_breaks_prefix_ties():
    # GetLevelTiles only replaces on a STRICTLY longer prefix
    # (TTiles.cpp:617), so the first-registered def keeps a tie.
    assert select_tilestype([("era_", 1), ("era_", 2)], "era_x.nw") == 1


def test_types_3_and_4_are_skipped_but_5_is_not():
    # addtiledef2 registers type 4 in the real client; it must never flip
    # the table. 5 ("no tiles") is the one high value that participates.
    assert select_tilestype([("era_", 4)], "era_x.nw") == 0
    assert select_tilestype([("era_", 3)], "era_x.nw") == 0
    assert select_tilestype([("era_", 5)], "era_x.nw") == 5
    # A longer skipped def must not shadow a shorter live one.
    assert select_tilestype([("era_", 1), ("era_main", 4)],
                            "era_mainstreet.nw") == 1


def test_corpus_lines_select_expected_tables():
    # Real registrations: LTTP is tilestype 0, era is tilestype 1. The
    # 4-arg mistake "addtiledef era_orangetiles.gif, era_, 1792, 64" parses
    # a huge type, which the skip rule discards.
    defs = [("zlttp", 0), ("era_", 1), ("era_", 1792)]
    assert select_tilestype(defs, "zlttp_overworld.nw") == 0
    assert select_tilestype(defs, "era_mainstreet.nw") == 1


def test_level_name_is_stripped_and_case_folded():
    defs = [("era_", 1)]
    assert select_tilestype(defs, "levels/ERA_street.nw") == 1
    assert select_tilestype(defs, "world\\Era_street.nw") == 1


# --- table routing ---------------------------------------------------------

def test_nw_table_is_shipped_and_loaded():
    assert tt.TILE_TYPES_NW is not None
    assert len(tt.TILE_TYPES_NW) == 4096
    assert tt.TILE_TYPES_NW != tt.TILE_TYPES


def test_tilestype_routes_between_the_two_tables():
    # Pinned from the extracted tables: tile 4 is a wall in classic (22)
    # and walkable in new-world (0); tile 64 is classic-wall, nw-water.
    assert get_tile_type(4, tilestype=0) == TileType.BLOCKING
    assert get_tile_type(4, tilestype=1) == TileType.NONBLOCK
    assert get_tile_type(64, tilestype=2) == TileType.WATER
    # walltile treats tilestype 2 exactly like 1 (TServerLevel.cpp:741).
    assert get_tile_type(4, tilestype=2) == get_tile_type(4, tilestype=1)


def test_tilestype_5_reports_no_tile_types():
    assert get_tile_type(4, tilestype=5) == TileType.NONBLOCK
    assert get_tile_type(4095, tilestype=5) == TileType.NONBLOCK
    # Off-level stays blocking (walltile: gettile < 0 -> wall).
    assert get_tile_type(-1, tilestype=5) == TileType.BLOCKING


def test_default_routing_follows_the_registered_defs():
    tt.register_tiledef("era_", 1)
    tt.set_current_level("era_mainstreet.nw")
    assert tt.active_tilestype() == 1
    assert get_tile_type(4) == TileType.NONBLOCK
    tt.set_current_level("onlinestartlocal.nw")
    assert tt.active_tilestype() == 0
    assert get_tile_type(4) == TileType.BLOCKING


def test_predicates_follow_the_active_table():
    tt.register_tiledef("era_", 1)
    tt.set_current_level("era_mainstreet.nw")
    assert not tt.is_blocking(4)
    assert tt.is_swimming_water(64)
    tt.set_current_level("plain.nw")
    assert tt.is_blocking(4)
    assert not tt.is_swimming_water(64)


def test_reregistering_a_prefix_replaces_and_remove_clears():
    tt.register_tiledef("era_", 1)
    tt.register_tiledef("era_", 5)
    assert tt.tilestype_for_level("era_x.nw") == 5
    tt.remove_tiledefs("era")
    assert tt.tilestype_for_level("era_x.nw") == 0


def test_missing_nw_table_falls_back_to_classic(monkeypatch, caplog):
    monkeypatch.setattr(tt, "TILE_TYPES_NW", None)
    monkeypatch.setattr(tt, "_warned_nw_missing", False)
    import logging
    with caplog.at_level(logging.WARNING, logger="pyreborn.tiletypes"):
        assert get_tile_type(4, tilestype=1) == TileType.BLOCKING
    assert any("tiletypesnw" in rec.message for rec in caplog.records)


# --- wiring: GS1 addtiledef and the client's level hook --------------------

def test_gs1_addtiledef_registers_types_headless():
    from pyreborn.gs1_client import ClientGS1
    gs1 = ClientGS1(client=None)
    gs1.load_script("w", """
if (playerenters) {
  addtiledef zlttp_tiles.png,zlttp,0;
  addtiledef tileset_era01-summer.png,era_,1;
}
""")
    gs1.trigger_event("playerenters")
    assert tt.tilestype_for_level("zlttp_overworld.nw") == 0
    assert tt.tilestype_for_level("era_mainstreet.nw") == 1
    gs1.load_script("w2", "if (playerenters) removetiledefs era_;")
    gs1.trigger_event("playerenters")
    assert tt.tilestype_for_level("era_mainstreet.nw") == 0


def test_level_state_write_updates_the_active_tilestype():
    from pyreborn.client_state import LevelState
    state = LevelState()
    state.tiletypes.register_tiledef("era_", 1)
    state.current_level_name = "era_mainstreet.nw"
    assert state.tiletypes.active_tilestype() == 1
    state.current_level_name = "somewhere.nw"
    assert state.tiletypes.active_tilestype() == 0


@pytest.mark.parametrize("pair,tile_id,expected,xy", [
    ("Z2", 1654, 3, (57, 26)), ("Z4", 1656, 3, (58, 26)),
    ("aG", 1670, 3, (1, 28)), ("aI", 1672, 3, (8, 28)),
    ("Em", 294, 11, (36, 0)), ("A9", 61, 22, (0, 0)),
    ("AC", 2, 20, (5, 7)), ("AD", 3, 20, (6, 7)),
    ("AS", 18, 20, (5, 8)), ("AT", 19, 20, (6, 8)),
])
def test_chicken1_classic_tiles(pair, tile_id, expected, xy):
    # Pinned BOARD character pairs at (x,y) from funtimes/world/chicken1.nw.
    # Inline fixtures keep this test independent of the sibling world checkout.
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    assert (alphabet.index(pair[0]) << 6) | alphabet.index(pair[1]) == tile_id
    assert get_tile_type(tile_id, tilestype=0) == expected


def test_two_clients_and_standalone_selection_are_independent():
    from pyreborn import Client
    from pyreborn.gs1_client import ClientGS1
    a, b = Client(), Client()
    a._current_level_name = b._current_level_name = "same.nw"
    a.tiles = b.tiles = [4] * 4096
    first, second = ClientGS1(a), ClientGS1(b)
    first.load_weapon("tiles", "if (playerenters) addtiledef custom.png,,1;")
    first.trigger_event("playerenters")
    assert first.tile_type_at(0, 0) == 0
    assert second.tile_type_at(0, 0) == 22
    tt.register_tiledef('', 5)
    assert tt.active_tilestype(a) == 1
    assert tt.active_tilestype(b) == 0
    assert tt.active_tilestype() == 5
    assert tt.get_tile_type(4, client=a) == 0
    assert tt.get_tile_type(4, client=b) == 22
    assert tt.get_tile_type(4) == 0
    assert not tt.is_blocking(4, client=a)
    assert tt.is_blocking(4, client=b)
    assert tt.is_water(64, client=a)
    assert tt.is_swimming_water(64, client=a)
    assert not tt.is_water(64, client=b)
    assert not tt.is_swimming_water(64, client=b)
    for client, table in ((a, tt.TILE_TYPES_NW), (b, tt.TILE_TYPES)):
        assert tt.is_damaging(64, client=client) == (table[64] in (2, 9, 12))
    b._current_level_name = "another.nw"
    assert a.level_state.tiletypes.active_tilestype() == 1


def test_game_bot_uses_its_clients_new_world_selection():
    from game_tester.game_bot import GameBot, _validate_warp_dest
    from game_tester.server_probe import _probe_position_clear
    bot = GameBot('tileprobe', 'localhost', 1)
    c = bot.client
    c._current_level_name = 'era_street.nw'
    c.tiles = [4] * 4096  # Classic wall, new-world floor.
    c.levels[c._current_level_name] = c.tiles
    c.level_state.tiletypes.register_tiledef('era_', 1)
    assert tt.get_tile_type(4, client=c) == TileType.NONBLOCK
    assert not bot._is_position_blocked(10, 5)
    assert _probe_position_clear(c, 10, 5)
    assert _validate_warp_dest(c._current_level_name, 10, 5, c.levels.get, c) is None
    # Destination selection must be used even when the current level is classic.
    c._current_level_name = 'classic.nw'
    assert _validate_warp_dest('era_street.nw', 10, 5, c.levels.get, c) is None
    c._current_level_name = 'era_street.nw'
    c.tiles[:] = [64] * 4096  # Classic wall, new-world swimming water.
    assert bot._check_water_at_position(10, 5)


def test_reconnect_resets_only_its_own_tiledefs(monkeypatch):
    from pyreborn import Client
    a, b = Client(), Client()
    for client in (a, b):
        client.level_state.tiletypes.register_tiledef("", 1)
    monkeypatch.setattr(a._protocol, "connect", lambda: True)
    assert a.connect()
    assert a.level_state.tiletypes.active_tilestype() == 0
    assert b.level_state.tiletypes.active_tilestype() == 1
