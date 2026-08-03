"""game/editor/editor.py — the live level editor, wired to the server.

`EditorState` owns the rules (brush, undo, selection); this owns the IO:

  tiles          PLI_BOARDMODIFY, which the server applies and relays to
                 everyone standing in the level. Ordinary gameplay uses the
                 same packet (bushes, pots, GS1 `updateboard`), so it is NOT
                 staff-gated and painting works the moment the packet lands.
  NPCs           the NC connection (`NCLink`): live add/move/delete/script.
  signs, chests  RC chat commands, applied to the server's in-memory level.
  links          Nothing in this protocol edits these from a client, so
                 pygserver takes them as RC commands and the editor sends
                 those. That is also why they need the explicit save below.

Nothing here writes a level file. Saving is `/savelevel <name>` over RC: the
SERVER serializes what it holds, which is the only copy that knows every NPC
script. A client that serialized its own view would quietly drop the scripts
it never fetched, and overwrite a working level with the loss.

Coordinates: the wire frame for a board edit is level-local (0..63), and on a
gmap PLI_BOARDMODIFY applies to the segment the sender stands in. So the
editor paints inside the CURRENT segment only, and `_local` clamps to it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import pygame
from pygame.locals import (
    K_1, K_2, K_3, K_4, K_5, K_DELETE, K_ESCAPE, K_LEFTBRACKET, K_RIGHTBRACKET,
    K_c, K_g, K_o, K_p, K_r, K_s, K_v, K_y, K_z, KMOD_CTRL, KMOD_SHIFT,
)

from reborn_protocol.coords import in_level_bounds, level_index

from .nw_writer import MissingNpcScriptError, serialize_level
from .state import (
    LEVEL_SIZE, OBJECT, PAINT, PICKER, RECT, SELECT, BoardEdit, EditorState,
)


class LevelEditor:
    """Edit mode for a GameClient: painting, objects, save/reload."""

    def __init__(self, game):
        self.game = game
        self.state = EditorState()
        self.clipboard: Optional[Tuple[int, int, List[int]]] = None
        # Corner of a rectangle/selection drag, in level-local tiles.
        self._anchor: Optional[Tuple[int, int]] = None
        self._painting = False

    # -- links to the two control connections ------------------------------

    @property
    def rc(self):
        """The RC link, if the RC panel has one and it is live."""
        rc_ui = getattr(self.game, 'rc_ui', None)
        link = getattr(rc_ui, 'link', None)
        return link if link is not None and link.available else None

    @property
    def nc(self):
        dev_ui = getattr(self.game, 'dev_ui', None)
        link = getattr(dev_ui, 'nc_link', None)
        return link if link is not None and link.available else None

    @property
    def enabled(self) -> bool:
        return self.state.enabled

    def toggle(self) -> None:
        self.state.enabled = not self.state.enabled
        self.state.status = ("edit mode on" if self.state.enabled
                             else "edit mode off")
        if not self.state.enabled:
            self._anchor = None
            self._painting = False

    # -- board access ------------------------------------------------------

    @property
    def level_name(self) -> str:
        """The level the edits apply to: the segment the player stands in."""
        return self.game.client.get_current_level_from_position()

    def _local(self, world_x: float, world_y: float) -> Tuple[int, int]:
        """World tile -> the level-local frame PLI_BOARDMODIFY speaks."""
        return self.game._world_to_level_local(world_x, world_y)

    def _in_own_segment(self, world_x: float, world_y: float) -> bool:
        """True when (world_x, world_y) is in the segment the player stands in.

        On a gmap the mouse can hover a NEIGHBOURING segment, and its local
        frame is 0-63 as well - so the coordinates look perfectly valid. But
        PLI_BOARDMODIFY carries no level: the server resolves the tiles
        against the sender's OWN sub-level origin (GServer-v2
        PlayerClientPackets.cpp:122). Painting the segment next door
        therefore paints the same local square of your own segment instead,
        which is a silent, mirrored corruption of a level you were not
        looking at. Only the standing segment is editable; walk over.
        """
        if not self.game.client.in_gmap_segment:
            return True
        level, _ = self.game._level_tiles_at(world_x, world_y)
        return not level or level == self.level_name

    def _reject_other_segment(self, world_x: float, world_y: float) -> bool:
        """Refuse an edit outside the standing segment, and say why."""
        if self._in_own_segment(world_x, world_y):
            return False
        level, _ = self.game._level_tiles_at(world_x, world_y)
        self.state.status = (
            f"{level or 'that segment'} is not the level you are standing in "
            f"- walk into it to edit it")
        return True

    def read_tile(self, x: int, y: int) -> int:
        """The current board tile at level-local (x, y), or 0 off-board."""
        if not in_level_bounds(x, y):
            return 0
        tiles = self.game.client.tiles
        idx = level_index(x, y)
        if not tiles or idx >= len(tiles):
            return 0
        return tiles[idx]

    # -- applying edits ----------------------------------------------------

    def apply(self, edit: Optional[BoardEdit], *, undoable: bool = True) -> bool:
        """Send one rectangle to the server (which echoes it to everyone else).

        `Client.modify_board` also patches the local board, so the painter
        sees the change on the next frame without waiting for a round trip.
        """
        if edit is None:
            return False
        ok = self.game.client.modify_board(edit.x, edit.y, edit.w, edit.h,
                                           edit.after)
        if ok and undoable:
            self.state.push_undo(edit)
        self.game.world_surface = None      # force a board redraw
        return ok

    def undo(self) -> None:
        if (self.state.undo_stack
                and self.state.undo_stack[-1].level != self.level_name):
            level = self.state.undo_stack[-1].level
            self.state.status = (
                f"{level} is not the level you are standing in "
                f"- walk into it to undo the edit")
            return
        edit = self.state.undo()
        if edit is None:
            self.state.status = "nothing to undo"
            return
        self.apply(edit, undoable=False)
        self.state.status = "undo"

    def redo(self) -> None:
        if (self.state.redo_stack
                and self.state.redo_stack[-1].level != self.level_name):
            level = self.state.redo_stack[-1].level
            self.state.status = (
                f"{level} is not the level you are standing in "
                f"- walk into it to redo the edit")
            return
        edit = self.state.redo()
        if edit is None:
            self.state.status = "nothing to redo"
            return
        self.apply(edit, undoable=False)
        self.state.status = "redo"

    # -- mouse -------------------------------------------------------------

    def mouse_down(self, world_x: float, world_y: float, button: int) -> None:
        x, y = self._local(world_x, world_y)
        state = self.state

        if button == 1 and self._reject_other_segment(world_x, world_y):
            return
        if button == 3:
            # Right click always picks, whatever the tool: the fastest way to
            # keep painting with what is already on the board.
            state.tile = self.read_tile(x, y)
            state.status = f"picked tile {state.tile}"
            return
        if button != 1:
            return

        if state.tool == PAINT:
            self._painting = True
            state.begin_stroke(self.level_name)
            self._paint_at(x, y)
        elif state.tool in (RECT, SELECT):
            self._anchor = (x, y)
        elif state.tool == PICKER:
            state.tile = self.read_tile(x, y)
            state.status = f"picked tile {state.tile}"
        elif state.tool == OBJECT:
            self.place_object(x, y)

    def mouse_drag(self, world_x: float, world_y: float) -> None:
        if not self._painting:
            return
        # A stroke that wanders across the seam stops at it rather than
        # wrapping onto the same local square of the standing segment.
        if self._reject_other_segment(world_x, world_y):
            return
        x, y = self._local(world_x, world_y)
        self._paint_at(x, y)

    def mouse_up(self, world_x: float, world_y: float, button: int) -> None:
        if button != 1:
            return
        x, y = self._local(world_x, world_y)
        state = self.state

        if self._painting:
            self._painting = False
            edit = state.end_stroke(self.read_tile)
            if edit is not None:
                # The tiles are already on the board and on the wire; the
                # stroke only becomes ONE undo step here.
                state.push_undo(edit)
            return

        if self._anchor is None:
            return
        ax, ay = self._anchor
        self._anchor = None
        if self._reject_other_segment(world_x, world_y):
            return
        if state.tool == RECT:
            self.apply(state.rect_edit(self.level_name, ax, ay, x, y,
                                       self.read_tile))
        elif state.tool == SELECT:
            state.set_selection(ax, ay, x, y)
            sel = state.selection
            state.status = f"selected {sel[2]}x{sel[3]}" if sel else ""

    def _paint_at(self, x: int, y: int) -> None:
        """Paint the brush at one point, as its own small wire rectangle.

        Each brush stamp goes out immediately so other players see the stroke
        as it happens. The whole stroke still collapses into a single undo
        step when the button comes up (see mouse_up).
        """
        state = self.state
        fresh = state.stroke_point(x, y, self.read_tile)
        if not fresh:
            return
        # The brush footprint is contiguous, so the whole stamp goes as ONE
        # rectangle. Sending a packet per tile put 64 of them on the wire for
        # an 8x8 brush, and repainting a tile this stroke already covered is
        # harmless because every tile in the stamp gets the same id.
        covered = state.brush_tiles(x, y)
        x0 = min(tx for tx, _ in covered)
        y0 = min(ty for _, ty in covered)
        w = max(tx for tx, _ in covered) - x0 + 1
        h = max(ty for _, ty in covered) - y0 + 1
        self.game.client.modify_board(x0, y0, w, h, [state.tile] * (w * h))
        self.game.world_surface = None

    # -- clipboard ---------------------------------------------------------

    def copy(self) -> None:
        picked = self.state.selection_tiles(self.read_tile)
        if picked is None:
            self.state.status = "nothing selected"
            return
        self.clipboard = picked
        self.state.status = f"copied {picked[0]}x{picked[1]}"

    def paste(self, world_x: float, world_y: float) -> None:
        if self.clipboard is None:
            self.state.status = "clipboard empty"
            return
        if self._reject_other_segment(world_x, world_y):
            return
        w, h, tiles = self.clipboard
        x, y = self._local(world_x, world_y)
        if self.apply(self.state.paste_edit(self.level_name, x, y, w, h, tiles,
                                            self.read_tile)):
            self.state.status = f"pasted {w}x{h}"

    # -- objects -----------------------------------------------------------

    def place_object(self, x: int, y: int) -> None:
        """Place the selected object kind at level-local (x, y)."""
        kind = self.state.object_kind
        level = self.level_name
        if kind == "npc":
            nc = self.nc
            if nc is None:
                self.state.status = "no NC session: cannot place an NPC"
                return
            # NPCADD carries no script: the NPC is created first, and the
            # script arrives as a separate NPCSCRIPTSET once the server has
            # answered with the new id (the Dev panel's NPC tab does that).
            nc.add_npc("", 0, "", self.game.client.player.account,
                       level, float(x), float(y))
            nc.get_local_npcs(level)
            self.state.status = f"placed an NPC at {x},{y}"
            return

        rc = self.rc
        if rc is None:
            self.state.status = f"no RC session: cannot place a {kind}"
            return
        if kind == "sign":
            rc.say(f"/sign add {level} {x} {y} new sign")
        elif kind == "chest":
            rc.say(f"/chest add {level} {x} {y} greenrupee")
        elif kind == "link":
            rc.say(f"/link add {level} {x} {y} 1 1 {level} 30 30")
        self.state.status = f"placed a {kind} at {x},{y} (server confirms on RC chat)"

    def delete_object(self, x: int, y: int) -> None:
        kind = self.state.object_kind
        level = self.level_name
        rc = self.rc
        if kind == "npc":
            nc = self.nc
            npc_id = self.npc_id_at(x, y)
            if nc is None or npc_id is None:
                self.state.status = "no NPC here"
                return
            nc.delete_npc(npc_id)
            self.state.status = f"deleted NPC {npc_id}"
            return
        if rc is None:
            self.state.status = f"no RC session: cannot delete a {kind}"
            return
        rc.say(f"/{kind} del {level} {x} {y}")
        self.state.status = f"deleted the {kind} at {x},{y}"

    def npc_id_at(self, x: int, y: int) -> Optional[int]:
        """The id of an NPC standing on level-local (x, y), if any.

        `client.npcs` maps id -> a props dict (see handlers/entities.py), and
        its x/y are in the same frame the rest of the level state uses.
        """
        for npc_id, npc in (self.game.client.npcs or {}).items():
            if (not isinstance(npc, dict)
                    or npc.get('_level') != self.level_name):
                continue
            nx, ny = self._local(npc.get('x', -1), npc.get('y', -1))
            if (nx, ny) == (x, y):
                return npc_id
        return None

    # -- level file --------------------------------------------------------

    def save_level(self) -> None:
        """Ask the server to write the level it holds (`/savelevel`).

        The server serializes its own copy. See the module docstring for why
        the client never writes the file itself. Only pygserver understands
        this; `export_level` is the portable route for other servers.
        """
        rc = self.rc
        if rc is None:
            self.state.status = "no RC session: open F10 and connect first"
            return
        rc.say(f"/savelevel {self.level_name}")
        self.state.status = f"save requested for {self.level_name}"

    def reload_level(self) -> None:
        """Reload the level from disk for everyone standing in it.

        Sends `/updatelevel`, which is the REFERENCE spelling (GServer-v2
        Server::processRCChat, Server.cpp:2370). pygserver accepts it as an
        alias of its own `/reloadlevel`, so one command covers both servers
        and the client never has to ask which one it is talking to.
        """
        rc = self.rc
        if rc is None:
            self.state.status = "no RC session: open F10 and connect first"
            return
        rc.say(f"/updatelevel {self.level_name}")
        self.state.status = f"reload requested for {self.level_name}"

    # -- the portable save -------------------------------------------------

    def export_level(self) -> None:
        """Serialize the level here and upload the .nw over the RC file browser.

        This is the route for servers that do NOT have `/savelevel`, and it
        uses nothing but ordinary protocol: the file browser's upload.

        It refuses to write anything until every NPC in the level has had its
        script fetched over NC, because an NPC's script never arrives on the
        game connection. Serializing without them would upload NPC bodies
        with empty scripts and destroy working content. `nw_writer` enforces
        that, and this method does the fetching that satisfies it.
        """
        rc = self.rc
        if rc is None:
            self.state.status = "no RC session: open F10 and connect first"
            return
        # An RC upload lands in the folder the file browser is CURRENTLY in,
        # exactly as it does in a real RC. The client cannot know where a
        # given server keeps its levels, so the builder browses there first
        # and the upload follows them. Opening the browser here instead would
        # reset to the root and drop the level file in the wrong place.
        folder = rc.snapshot.folder
        if not folder:
            self.state.status = ("open the RC panel's Files tab and browse to "
                                 "the levels folder first; the export uploads "
                                 "there")
            return
        level = self.level_name
        scripts = self._npc_scripts_for(level)
        if scripts is None:
            return                      # _npc_scripts_for set the status

        client = self.game.client
        try:
            text = serialize_level(
                level,
                client.tiles,
                client.links.get(level, ()) or (),
                client.signs.get(level, {}) or {},
                self._chest_records(level),
                self._level_npcs(level),
                scripts,
                self._baddy_records(level),
            )
        except MissingNpcScriptError as error:
            self.state.status = f"export refused: {error}"
            return
        except ValueError as error:
            self.state.status = f"export failed: {error}"
            return

        try:
            path = Path(tempfile.gettempdir()) / level
            path.write_text(text, encoding="latin-1")
        except OSError as error:
            self.state.status = f"could not stage {level}: {error}"
            return

        rc.files_upload(str(path))
        self.state.status = (f"uploading {level} ({len(text)} bytes) to "
                             f"/{folder} — the RC panel shows the answer")

    def _npc_scripts_for(self, level: str):
        """Every NPC script for `level`, or None once a fetch was started.

        The first call asks NC for whatever is missing and returns None, so
        the builder presses export again when the replies have arrived. That
        keeps the frame loop free of any waiting.
        """
        npcs = self._level_npcs(level)
        if not npcs:
            return {}
        nc = self.nc
        if nc is None:
            self.state.status = ("no NC session: open F12 first so NPC "
                                 "scripts can be fetched before an export")
            return None
        fetched = dict(nc.snapshot.npc_scripts)
        missing = [npc_id for npc_id in npcs if npc_id not in fetched]
        if not missing:
            self._fetch_rounds = 0
            return fetched

        # A server that has no such NPC answers NOTHING, so an unbounded
        # "ask again" would spin forever on a stale id. After a couple of
        # rounds with no progress, name the ids and refuse: an export that
        # cannot see a script must never write one.
        self._fetch_rounds = getattr(self, '_fetch_rounds', 0) + 1
        if self._fetch_rounds > 3:
            self._fetch_rounds = 0
            ids = ", ".join(str(npc_id) for npc_id in missing[:6])
            self.state.status = (f"export refused: {len(missing)} NPC(s) never "
                                 f"sent a script ({ids}) — reload the level "
                                 f"and try again")
            return None
        for npc_id in missing:
            nc.get_npc_script(npc_id)
        self.state.status = (f"fetching {len(missing)} NPC script(s); "
                             f"press export again when they arrive")
        return None

    def _level_npcs(self, level: str) -> dict:
        """The NPC prop dicts belonging to `level`, keyed by id.

        The attribution key is `_level`, which handlers/entities.py stamps on
        every NPC (entities.py:291). `level` is a PLAYER prop and no NPC
        carries it, so filtering on that name matched everything the client
        had ever seen, including NPCs from other levels - an export then
        waited forever for scripts that were never coming.
        """
        npcs = {}
        for npc_id, npc in (self.game.client.npcs or {}).items():
            if isinstance(npc, dict) and npc.get('_level') == level:
                npcs[npc_id] = npc
        return npcs

    def _chest_records(self, level: str) -> List[tuple]:
        """Chests as (x, y, item, sign_index) rows for the writer.

        The sign index is the last byte of PLO_LEVELCHEST for an unopened
        chest (GServer-v2 Level.cpp:153), so it only has to be remembered, not
        guessed. -1 is the fallback for a chest this session only ever saw
        already-opened, where the server sends the 3-byte form with no index.
        """
        client = self.game.client
        items = getattr(client, 'chest_items', {}) or {}
        level_items = items.get(level, {}) if isinstance(items, dict) else {}
        signs = getattr(client, 'chest_signs', {}) or {}
        level_signs = signs.get(level, {}) if isinstance(signs, dict) else {}
        rows = []
        for (cx, cy) in (client.chests_in_level(level) or {}):
            rows.append((int(cx), int(cy),
                         str(level_items.get((cx, cy), "greenrupee")),
                         int(level_signs.get((cx, cy), -1))))
        return rows

    def _baddy_records(self, level: str) -> List[dict]:
        """Baddies as writer rows, in a stable id order.

        Position, type and all three verses ride PLO_BADDYPROPS (BADDY_PROPS
        8-10), so the client holds everything the level file needs. Leaving
        them out of the export silently DELETED every baddy in the level -
        found by diffing a real export against the reference server's own
        copy of the level.
        """
        client = self.game.client
        baddies = client.baddies_in_level(level) or {}
        return [baddies[key] for key in sorted(baddies)]

    # -- input -------------------------------------------------------------

    def handle_key(self, event) -> bool:
        """Editor keys. True = consumed, so gameplay never sees the key.

        Movement is deliberately NOT consumed: a builder walks around the
        level with the arrow keys while painting with the mouse.
        """
        state = self.state
        if not state.enabled:
            return False

        ctrl = bool(event.mod & KMOD_CTRL)
        key = event.key

        if ctrl:
            if key == K_z:
                self.redo() if event.mod & KMOD_SHIFT else self.undo()
            elif key == K_y:
                self.redo()
            elif key == K_c:
                self.copy()
            elif key == K_v:
                self.paste(*self.game.camera.screen_to_world(
                    *self.game.viewport.mouse_pos()))
            elif key == K_s:
                # Ctrl+Shift+S is the portable route: serialize here and
                # upload, for a server without /savelevel.
                if event.mod & KMOD_SHIFT:
                    self.export_level()
                else:
                    self.save_level()
            elif key == K_r:
                self.reload_level()
            else:
                return False
            return True

        tools = {K_1: PAINT, K_2: RECT, K_3: PICKER, K_4: SELECT, K_5: OBJECT}
        if key in tools:
            state.set_tool(tools[key])
            state.status = f"tool: {state.tool}"
            return True
        if key == K_o:
            state.cycle_object_kind()
            state.status = f"object: {state.object_kind}"
            return True
        if key == K_p:
            state.palette_visible = not state.palette_visible
            return True
        if key == K_g:
            state.grid_visible = not state.grid_visible
            return True
        if key in (K_LEFTBRACKET, K_RIGHTBRACKET):
            state.adjust_brush(1 if key == K_RIGHTBRACKET else -1)
            return True
        if key == K_DELETE:
            world = self.game.camera.screen_to_world(
                *self.game.viewport.mouse_pos())
            if not self._reject_other_segment(*world):
                self.delete_object(*self._local(*world))
            return True
        if key == K_ESCAPE:
            if state.selection is not None:
                state.clear_selection()
            else:
                self.toggle()
            return True
        return False

    def handle_mouse(self, event, palette) -> bool:
        """Mouse in edit mode. True = consumed."""
        if not self.state.enabled:
            return False

        pos = self.game.viewport.window_to_virtual(*event.pos) \
            if hasattr(event, 'pos') else (0, 0)

        if event.type == pygame.MOUSEWHEEL:
            if self.state.palette_visible:
                shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
                step = palette.step * 2
                palette.scroll_by(-event.y * step if shift else 0,
                                  0 if shift else -event.y * step)
                return True
            return False

        # A click inside the palette picks a tile and never reaches the world.
        if (self.state.palette_visible and event.type == pygame.MOUSEBUTTONDOWN
                and hasattr(event, 'pos')):
            picked = palette.tile_at_pos(pos)
            if picked is not None:
                self.state.tile = picked
                self.state.status = f"tile {picked}"
                return True
            if palette.rect().collidepoint(pos):
                return True

        world = self.game.camera.screen_to_world(*pos)
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.mouse_down(*world, event.button)
            return True
        if event.type == pygame.MOUSEBUTTONUP:
            self.mouse_up(*world, event.button)
            return True
        if event.type == pygame.MOUSEMOTION:
            self.mouse_drag(*world)
            return True
        return False
