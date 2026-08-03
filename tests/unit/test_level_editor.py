"""game/editor — brush geometry, stroke-to-undo collapsing, and the wire.

The rules worth pinning are the ones whose failure a builder would only
notice after losing work, or after painting somebody else's level:

  * one stroke is ONE undo step, and undo restores what was under the FIRST
    brush stamp, not what a later stamp of the same stroke saw;
  * an edit's rectangle is exactly what PLI_BOARDMODIFY carries, so undo
    replays as one packet and untouched tiles inside the bounding box keep
    their value;
  * a paste clipped by the level edge reads its source with the COPIED
    stride, not the clipped one (otherwise it shears);
  * the editor never sends anything while edit mode is off, and object
    commands are refused (not queued) with no control connection.

Headless: no display, no server. SDL_VIDEODRIVER is forced to dummy like the
rest of tests/unit/.
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest

from pyreborn.game.editor import LevelEditor
from pyreborn.game.editor.overlay import EditorOverlay
from pyreborn.game.editor.palette import tile_id_at
from pyreborn.game.editor.state import (
    LEVEL_SIZE, OBJECT, PAINT, RECT, BoardEdit, EditorState,
)


class _Board:
    """A 64x64 board with the same indexing the client uses."""

    def __init__(self, fill=1):
        self.tiles = [fill] * (LEVEL_SIZE * LEVEL_SIZE)

    def read(self, x, y):
        return self.tiles[y * LEVEL_SIZE + x]

    def write(self, x, y, value):
        self.tiles[y * LEVEL_SIZE + x] = value


def _editor(board: _Board):
    """A LevelEditor over a fake game whose client writes into `board`."""
    client = SimpleNamespace(
        tiles=board.tiles,
        npcs={},
        player=SimpleNamespace(account="builder", x=10.0, y=10.0),
        x=10.0, y=10.0,
        in_gmap_segment=False,
        get_current_level_from_position=lambda: "onlinestartlocal.nw",
    )

    def modify_board(x, y, w, h, tiles):
        for row in range(h):
            for col in range(w):
                board.write(x + col, y + row, tiles[row * w + col])
        return True

    client.modify_board = Mock(side_effect=modify_board)
    game = SimpleNamespace(client=client, world_surface=object(),
                           _world_to_level_local=lambda x, y: (int(x), int(y)),
                           rc_ui=None, dev_ui=None)
    editor = LevelEditor(game)
    editor.state.enabled = True
    return editor, client


# -- brush geometry ----------------------------------------------------------

def test_brush_covers_the_tile_under_the_cursor_and_clips_at_the_edge():
    state = EditorState(brush=2)
    assert (10, 10) in state.brush_tiles(10, 10)
    assert len(state.brush_tiles(10, 10)) == 4

    corner = state.brush_tiles(0, 0)
    assert all(0 <= x < LEVEL_SIZE and 0 <= y < LEVEL_SIZE for x, y in corner)

    state.brush = 3
    assert len(state.brush_tiles(30, 30)) == 9


# -- strokes and undo --------------------------------------------------------

def test_a_stroke_is_one_undo_step_that_restores_the_original_tiles():
    board = _Board(fill=7)
    editor, client = _editor(board)
    editor.state.tile = 42

    editor.mouse_down(3, 3, 1)
    editor.mouse_drag(4, 3)
    editor.mouse_drag(5, 3)
    editor.mouse_up(5, 3, 1)

    assert [board.read(x, 3) for x in (3, 4, 5)] == [42, 42, 42]
    assert len(editor.state.undo_stack) == 1

    editor.undo()
    assert [board.read(x, 3) for x in (3, 4, 5)] == [7, 7, 7]

    editor.redo()
    assert [board.read(x, 3) for x in (3, 4, 5)] == [42, 42, 42]


def test_repainting_a_tile_mid_stroke_still_undoes_to_the_original():
    board = _Board(fill=5)
    editor, _ = _editor(board)
    editor.state.tile = 9

    editor.mouse_down(2, 2, 1)
    editor.mouse_drag(2, 2)          # same tile again
    editor.mouse_drag(3, 2)
    editor.mouse_up(3, 2, 1)
    editor.undo()

    assert board.read(2, 2) == 5, "undo restored a mid-stroke value, not the original"


def test_untouched_tiles_inside_the_stroke_bounding_box_are_preserved():
    """A diagonal stroke's rectangle covers tiles it never painted."""
    board = _Board(fill=3)
    editor, _ = _editor(board)
    editor.state.tile = 8

    editor.mouse_down(10, 10, 1)
    editor.mouse_drag(11, 11)
    editor.mouse_up(11, 11, 1)

    edit = editor.state.undo_stack[-1]
    assert (edit.x, edit.y, edit.w, edit.h) == (10, 10, 2, 2)
    assert board.read(11, 10) == 3            # never painted
    editor.undo()
    assert board.read(11, 10) == 3            # and undo leaves it alone
    assert board.read(10, 10) == 3


def test_a_new_edit_drops_the_redo_branch():
    board = _Board()
    editor, _ = _editor(board)
    editor.state.tile = 2
    editor.mouse_down(1, 1, 1)
    editor.mouse_up(1, 1, 1)
    editor.undo()
    assert editor.state.redo_stack

    editor.state.tile = 3
    editor.mouse_down(5, 5, 1)
    editor.mouse_up(5, 5, 1)
    assert not editor.state.redo_stack


def test_undo_and_redo_wait_until_the_editor_returns_to_the_edits_level():
    board = _Board(fill=1)
    editor, client = _editor(board)
    current_level = ["first.nw"]
    client.get_current_level_from_position = lambda: current_level[0]
    edit = BoardEdit("first.nw", 2, 3, 1, 1, [1], [9])
    editor.state.undo_stack.append(edit)

    current_level[0] = "second.nw"
    editor.undo()
    client.modify_board.assert_not_called()
    assert editor.state.undo_stack == [edit]
    assert editor.state.redo_stack == []
    assert "first.nw" in editor.state.status

    current_level[0] = "first.nw"
    editor.undo()
    assert editor.state.undo_stack == []
    assert editor.state.redo_stack == [edit]

    current_level[0] = "second.nw"
    client.modify_board.reset_mock()
    editor.redo()
    client.modify_board.assert_not_called()
    assert editor.state.undo_stack == []
    assert editor.state.redo_stack == [edit]
    assert "first.nw" in editor.state.status


def test_a_noop_edit_is_not_pushed_onto_the_undo_stack():
    board = _Board(fill=4)
    editor, _ = _editor(board)
    editor.state.tile = 4                      # already that tile
    editor.mouse_down(6, 6, 1)
    editor.mouse_up(6, 6, 1)
    assert editor.state.undo_stack == []


# -- rectangle, picking, paste ----------------------------------------------

def test_a_brush_stamp_is_one_packet_not_one_per_tile():
    board = _Board(fill=1)
    editor, client = _editor(board)
    editor.state.brush = 4
    editor.state.tile = 21

    client.modify_board.reset_mock()
    editor.mouse_down(20, 20, 1)
    editor.mouse_up(20, 20, 1)

    assert client.modify_board.call_count == 1
    x, y, w, h, tiles = client.modify_board.call_args[0]
    assert (w, h) == (4, 4) and len(tiles) == 16
    assert board.read(20, 20) == 21


def test_rectangle_fill_sends_one_rectangle():
    board = _Board(fill=1)
    editor, client = _editor(board)
    editor.state.set_tool(RECT)
    editor.state.tile = 12

    client.modify_board.reset_mock()
    editor.mouse_down(2, 2, 1)
    editor.mouse_up(4, 5, 1)

    assert client.modify_board.call_count == 1
    x, y, w, h, tiles = client.modify_board.call_args[0]
    assert (x, y, w, h) == (2, 2, 3, 4)
    assert set(tiles) == {12}


def test_right_click_picks_the_tile_under_the_cursor_with_any_tool():
    board = _Board(fill=1)
    board.write(9, 9, 77)
    editor, _ = _editor(board)
    editor.state.set_tool(PAINT)
    editor.mouse_down(9, 9, 3)
    assert editor.state.tile == 77


def test_paste_clipped_by_the_level_edge_keeps_the_source_stride():
    board = _Board(fill=0)
    editor, _ = _editor(board)
    # A 2x2 stamp pasted so only its left column fits.
    editor.clipboard = (2, 2, [1, 2, 3, 4])
    editor.paste(LEVEL_SIZE - 1, 0)
    assert board.read(LEVEL_SIZE - 1, 0) == 1
    assert board.read(LEVEL_SIZE - 1, 1) == 3, "clipped paste sheared its source"


def test_copy_requires_a_selection():
    board = _Board()
    editor, _ = _editor(board)
    editor.copy()
    assert editor.clipboard is None
    assert "nothing selected" in editor.state.status


# -- gating ------------------------------------------------------------------

def test_nothing_is_sent_while_edit_mode_is_off():
    board = _Board()
    editor, client = _editor(board)
    editor.state.enabled = False
    client.modify_board.reset_mock()

    assert editor.handle_key(SimpleNamespace(key=0, mod=0, unicode="")) is False
    editor.mouse_down(1, 1, 1)     # the input layer would not call this, but
    editor.mouse_up(1, 1, 1)       # the guard must hold anyway
    assert editor.state.enabled is False


def test_object_commands_report_when_there_is_no_control_connection():
    board = _Board()
    editor, _ = _editor(board)
    editor.state.set_tool(OBJECT)

    editor.state.object_kind = "npc"
    editor.place_object(5, 5)
    assert "no NC session" in editor.state.status

    editor.state.object_kind = "sign"
    editor.place_object(5, 5)
    assert "no RC session" in editor.state.status

    editor.save_level()
    assert "no RC session" in editor.state.status


def test_object_commands_use_the_grammar_the_server_parses():
    board = _Board()
    editor, _ = _editor(board)
    rc = Mock()
    rc.available = True
    editor.game.rc_ui = SimpleNamespace(link=rc)

    editor.state.object_kind = "sign"
    editor.place_object(4, 6)
    rc.say.assert_called_with("/sign add onlinestartlocal.nw 4 6 new sign")

    editor.state.object_kind = "chest"
    editor.place_object(4, 6)
    rc.say.assert_called_with("/chest add onlinestartlocal.nw 4 6 greenrupee")

    editor.state.object_kind = "link"
    editor.place_object(4, 6)
    rc.say.assert_called_with(
        "/link add onlinestartlocal.nw 4 6 1 1 onlinestartlocal.nw 30 30")

    editor.delete_object(4, 6)
    rc.say.assert_called_with("/link del onlinestartlocal.nw 4 6")

    editor.save_level()
    rc.say.assert_called_with("/savelevel onlinestartlocal.nw")

    # The REFERENCE spelling of a reload (GServer-v2 Server.cpp:2370), which
    # pygserver accepts as an alias - so one command works on both servers.
    editor.reload_level()
    rc.say.assert_called_with("/updatelevel onlinestartlocal.nw")


# -- the portable export ------------------------------------------------------

def _with_links(editor, level="onlinestartlocal.nw"):
    client = editor.game.client
    client.links = {level: []}
    client.signs = {level: {}}
    client.chest_items = {}
    client.chest_signs = {}
    client.chests_in_level = lambda name: {}
    client.baddies_in_level = lambda name: {}
    return client


def test_export_refuses_until_every_npc_script_has_been_fetched(tmp_path,
                                                                monkeypatch):
    """An NPC's script never arrives on the game connection.

    Serializing without it would upload NPC bodies with EMPTY scripts and
    destroy working content, so the export fetches first and refuses to
    write anything until it has them all.
    """
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    board = _Board(fill=1)
    editor, _ = _editor(board)
    client = _with_links(editor)
    client.npcs = {4: {'x': 1.0, 'y': 2.0, 'image': 'npc.png',
                       '_level': 'onlinestartlocal.nw'}}

    rc = Mock()
    rc.available = True
    rc.snapshot = SimpleNamespace(folder="world")
    editor.game.rc_ui = SimpleNamespace(link=rc)

    nc = Mock()
    nc.available = True
    nc.snapshot = SimpleNamespace(npc_scripts=())     # nothing fetched yet
    editor.game.dev_ui = SimpleNamespace(nc_link=nc)

    editor.export_level()
    rc.files_upload.assert_not_called()
    nc.get_npc_script.assert_called_once_with(4)
    assert "fetching" in editor.state.status

    # Second press, with the script in hand: now it uploads.
    nc.snapshot = SimpleNamespace(npc_scripts=((4, "if (created) hide;"),))
    editor.export_level()
    assert rc.files_upload.call_count == 1
    staged = rc.files_upload.call_args[0][0]
    text = open(staged, encoding="latin-1").read()
    assert text.startswith("GLEVNW01")
    assert "if (created) hide;" in text


def test_export_gives_up_and_names_the_npcs_that_never_answer(tmp_path,
                                                              monkeypatch):
    """A server with no such NPC answers nothing at all.

    Retrying forever would spin, and writing an empty script would destroy
    content, so the export names the silent ids and refuses.
    """
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    editor, _ = _editor(_Board())
    client = _with_links(editor)
    client.npcs = {77: {'x': 1.0, 'y': 1.0, 'image': 'ghost.png',
                        '_level': 'onlinestartlocal.nw'}}
    rc = Mock()
    rc.available = True
    rc.snapshot = SimpleNamespace(folder="world")
    editor.game.rc_ui = SimpleNamespace(link=rc)
    nc = Mock()
    nc.available = True
    nc.snapshot = SimpleNamespace(npc_scripts=())      # never answers
    editor.game.dev_ui = SimpleNamespace(nc_link=nc)

    for _ in range(4):
        editor.export_level()
    rc.files_upload.assert_not_called()
    assert "never sent a script" in editor.state.status
    assert "77" in editor.state.status

    # The counter resets after it refuses, so a later press starts a fresh
    # attempt rather than staying refused forever.
    editor.export_level()
    assert "fetching" in editor.state.status


def test_export_without_an_nc_session_says_so_and_writes_nothing(tmp_path,
                                                                 monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    editor, _ = _editor(_Board())
    client = _with_links(editor)
    client.npcs = {9: {'x': 0.0, 'y': 0.0, 'image': 'a.png',
                       '_level': 'onlinestartlocal.nw'}}
    rc = Mock()
    rc.available = True
    rc.snapshot = SimpleNamespace(folder="world")
    editor.game.rc_ui = SimpleNamespace(link=rc)
    editor.game.dev_ui = None

    editor.export_level()
    rc.files_upload.assert_not_called()
    assert "no NC session" in editor.state.status
    assert not list(tmp_path.iterdir())


def test_export_of_a_level_without_npcs_needs_no_nc_session(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    editor, _ = _editor(_Board(fill=7))
    client = _with_links(editor)
    client.npcs = {}
    rc = Mock()
    rc.available = True
    rc.snapshot = SimpleNamespace(folder="world")
    editor.game.rc_ui = SimpleNamespace(link=rc)

    editor.export_level()
    rc.files_upload.assert_called_once()
    text = open(rc.files_upload.call_args[0][0], encoding="latin-1").read()
    assert text.startswith("GLEVNW01")


def test_export_carries_the_levels_baddies_and_the_chest_sign_index(tmp_path,
                                                                    monkeypatch):
    """Both were silently dropped, and a live export proved it.

    Exporting qa_testlevel.nw through a real GServer-v2 and diffing the result
    against the server's own copy came back missing the whole BADDY block, and
    with the chest's sign index rewritten from 0 to -1. Everything needed is
    already on the wire: BADDY_PROPS 8-10 carry the verses, and the chest's
    index is the last byte of PLO_LEVELCHEST.
    """
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    editor, _ = _editor(_Board())
    level = "onlinestartlocal.nw"
    client = _with_links(editor)
    client.npcs = {}
    client.chest_items = {level: {(40, 40): "bluerupee"}}
    client.chest_signs = {level: {(40, 40): 0}}
    client.chests_in_level = lambda name: {(40, 40): False}
    client.baddies_in_level = lambda name: {
        1: {'id': 1, 'x': 25.0, 'y': 25.0, 'type': 0, 'verse_sight': 'hello',
            'verse_hurt': 'hurt', 'verse_attack': 'dead'}}
    rc = Mock()
    rc.available = True
    rc.snapshot = SimpleNamespace(folder="world")
    editor.game.rc_ui = SimpleNamespace(link=rc)

    editor.export_level()
    text = open(rc.files_upload.call_args[0][0], encoding="latin-1").read()
    lines = text.splitlines()
    assert "CHEST 40 40 bluerupee 0" in lines
    start = lines.index("BADDY 25 25 0")
    assert lines[start:start + 5] == ["BADDY 25 25 0", "hello", "hurt",
                                      "dead", "BADDYEND"]


def test_export_falls_back_to_no_chest_sign_when_the_wire_never_sent_one():
    """An already-opened chest arrives in the 3-byte form with no index."""
    editor, _ = _editor(_Board())
    client = _with_links(editor)
    client.chest_items = {"onlinestartlocal.nw": {(5, 6): "greenrupee"}}
    client.chests_in_level = lambda name: {(5, 6): True}

    assert editor._chest_records("onlinestartlocal.nw") == [
        (5, 6, "greenrupee", -1)]


# -- the optimistic local patch ---------------------------------------------

def test_modify_board_patches_the_level_the_server_will_apply_it_to():
    """The server applies PLI_BOARDMODIFY to the player's OWN level.

    `_pending_level_name` is stream-routing state: preloading an adjacent
    gmap segment moves it without moving the player. Patching that level
    instead sent the edit to the server correctly but painted the wrong
    cached board, so the painter's own view never changed.
    """
    from pyreborn import Client

    client = Client.__new__(Client)
    patched = {}

    client._apply_board_modify = lambda name, info: patched.update(
        {'level': name, 'info': info})
    client._protocol = SimpleNamespace(connected=True,
                                       send_packet=lambda *a, **k: True)
    client.session = SimpleNamespace(authenticated=True)
    # Minimal state: standing in "here", preloading the neighbour "there".
    client.get_current_level_from_position = lambda: "here.nw"
    client.level_state = SimpleNamespace(current_level_name="here.nw",
                                         pending_level_name="there.nw")

    assert Client.modify_board(client, 5, 5, 1, 1, [42]) is True
    assert patched['level'] == "here.nw", (
        "the edit patched the preloaded neighbour, not the painter's level")


# -- palette -----------------------------------------------------------------

def test_palette_maps_sheet_coordinates_back_to_tile_ids():
    """The inverse of sprites.py's tx/ty layout formula, for every block."""
    for tile_id in (0, 1, 15, 16, 511, 512, 513, 4095):
        tx = (tile_id // 512) * 16 + (tile_id % 16)
        ty = (tile_id // 16) % 32
        assert tile_id_at(tx, ty) == tile_id


# -- gmap: only the standing segment is editable -----------------------------

def _gmap_editor(board: _Board):
    """An editor on the centre segment of a 2x2 gmap, standing in `here.nw`."""
    editor, client = _editor(board)
    client.in_gmap_segment = True
    client.get_current_level_from_position = lambda: "here.nw"
    editor.game._world_to_level_local = lambda x, y: (int(x) % 64, int(y) % 64)
    editor.game._level_tiles_at = lambda x, y: (
        ("here.nw" if (int(x) // 64, int(y) // 64) == (1, 1)
         else "next-door.nw"), board.tiles)
    return editor, client


def test_painting_a_neighbouring_segment_is_refused_not_mirrored():
    """PLI_BOARDMODIFY carries no level.

    The server resolves the tiles against the SENDER's own sub-level origin
    (GServer-v2 PlayerClientPackets.cpp:122), so painting the segment next
    door would silently paint the same local square of your own segment
    instead - a mirrored edit to a level you were not even looking at.
    """
    board = _Board(fill=7)
    editor, client = _gmap_editor(board)
    editor.state.tile = 42

    editor.mouse_down(5, 5, 1)              # world (5,5) = segment (0,0)
    editor.mouse_up(5, 5, 1)

    client.modify_board.assert_not_called()
    assert board.read(5, 5) == 7
    assert "next-door.nw" in editor.state.status

    # The same LOCAL tile of the standing segment is editable.
    editor.mouse_down(64 + 5, 64 + 5, 1)
    editor.mouse_up(64 + 5, 64 + 5, 1)
    assert client.modify_board.call_args[0][:2] == (5, 5)
    assert board.read(5, 5) == 42


def test_a_stroke_stops_at_the_seam_instead_of_wrapping():
    board = _Board(fill=7)
    editor, client = _gmap_editor(board)
    editor.state.tile = 42

    editor.mouse_down(64 + 1, 64 + 1, 1)    # inside the standing segment
    editor.mouse_drag(63, 64 + 1)           # dragged over the seam
    editor.mouse_up(64 + 1, 64 + 1, 1)

    painted = [call[0][:2] for call in client.modify_board.call_args_list]
    assert painted == [(1, 1)], f"the drag leaked across the seam: {painted}"


def test_an_inbound_delta_lands_on_the_level_we_are_standing_in():
    """PLO_BOARDMODIFY carries no level either, and the same trap applies.

    The receiving side used to route it by `_pending_level_name`, which an
    adjacent-segment preload moves without moving the player - so another
    builder's edit was applied to whichever neighbour streamed last and never
    appeared where it was painted.
    """
    from pyreborn.handlers.level import handle_board_modify
    from pyreborn.packets import build_board_modify

    patched = {}
    client = SimpleNamespace(
        get_current_level_from_position=lambda: "here.nw",
        _pending_level_name="there.nw",
        _current_level_name="here.nw",
        on_board_modify=None,
        _apply_board_modify=lambda name, info: patched.update({'level': name}),
    )

    handle_board_modify(client, build_board_modify(5, 5, 1, 1, [42]))

    assert patched['level'] == "here.nw"


def test_pasting_into_a_neighbouring_segment_is_refused_not_mirrored():
    board = _Board(fill=7)
    editor, client = _gmap_editor(board)
    editor.clipboard = (1, 1, [42])

    editor.paste(5, 5)

    client.modify_board.assert_not_called()
    assert board.read(5, 5) == 7
    assert "next-door.nw" in editor.state.status


def test_npc_lookup_ignores_another_levels_npc_at_the_same_coordinates():
    editor, client = _gmap_editor(_Board())
    client.npcs = {
        10: {'x': 69.0, 'y': 70.0, '_level': 'next-door.nw'},
        20: {'x': 69.0, 'y': 70.0, '_level': 'here.nw'},
    }

    assert editor.npc_id_at(5, 6) == 20


def test_object_overlay_draws_only_npcs_from_the_current_level(monkeypatch):
    editor, client = _gmap_editor(_Board())
    client.links = {'here.nw': []}
    client.signs = {'here.nw': {}}
    client.chests_in_level = lambda level: {}
    client.npcs = {
        10: {'x': 69.0, 'y': 70.0, '_level': 'next-door.nw'},
        20: {'x': 71.0, 'y': 72.0, '_level': 'here.nw'},
    }
    overlay = EditorOverlay(editor.game, editor)
    overlay._tile_rect = Mock(return_value=pygame.Rect(0, 0, 1, 1))
    draw_rect = Mock()
    monkeypatch.setattr(pygame.draw, 'rect', draw_rect)

    overlay._draw_objects(Mock())

    overlay._tile_rect.assert_called_once_with(7, 8)
    assert draw_rect.call_count == 1


def test_delete_over_a_neighbouring_segment_is_refused_not_mirrored():
    board = _Board()
    editor, _ = _gmap_editor(board)
    editor.game.camera = SimpleNamespace(screen_to_world=lambda x, y: (5, 6))
    editor.game.viewport = SimpleNamespace(mouse_pos=lambda: (10, 20))
    editor.delete_object = Mock()

    assert editor.handle_key(SimpleNamespace(key=pygame.K_DELETE, mod=0)) is True

    editor.delete_object.assert_not_called()
    assert "next-door.nw" in editor.state.status
