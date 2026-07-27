"""gs1_client_conformance - CLIENT-side GS1 engine conformance suite.

The server-side twin (gs1_conformance.py) diffs pygserver's GS1 host against
the gs2emu oracle. THIS suite pins the CLIENT engine — pyreborn/gs1_client.py
running inside the real stack (Client + GameClient + NPCHandler, SDL dummy
video like render_smoke) — against the decompiled reference client:
Preagonal/FourPlay/quattroplay/src (the official interpreter, our top
oracle). Until now every client-GS1 semantic lived
only in hand-read decompile citations inside gs1_client.py; each CASE row here
is an executable transcription of one such citation, so an engine change that
breaks a row is contradicting a cited reference line, not a guess.

Architecture (one live session, one throwaway server, ~35 warps):

  * A throwaway pygserver on a free port provides the REAL wire session:
    login, boards, PLO_LEVELSIGN, NPC entities via PLO_NPCPROPS, weapon-text
    grants (PLO_NPCWEAPONADD), and the sink for the PLI packets the engine
    emits (captured via a send_packet spy).
  * The client under test is a real GameClient over a real Client, headless
    (SDL dummy) — the exact wiring the pygame shell ships: gs1 callbacks,
    npc_handler touch dispatch, board patching, HUD state.
  * Each case owns one generated fixture level qa_c_<name>.nw. Script
    delivery is per-channel:
      - 'weapon': shipped THROUGH the server. The body (one line, see below)
        is wrapped in a #L level gate, written as a GRAWP001 weapon file into
        the server's weapons dir, and pre-granted via the account fixture, so
        login streams it as PLO_NPCWEAPONADD text and the reload machinery
        fires its playerenters on the case level. ONE LINE because pygserver's
        build_npc_weapon_add (protocol/builders/world.py:167-176) does not
        apply the GS1 wire's newline->0xa7 mangling, so a multi-line script
        truncates at its first newline (pinned by the weapon_multiline_
        truncation divergence row below; the client side accepts 0xa7 fine,
        reborn_protocol/gs1/lexer.py:146).
      - 'npc': the fixture NPC arrives over the wire (image/x/y props), but
        pygserver never puts NPCPROP_SCRIPT(1) on the wire — it runs level-NPC
        GS1 server-side only (npc.py build_props_packet has no SCRIPT entry;
        NPCManager.attach_gs1 is the whole path). So the harness injects the
        script at the exact seam a streamed script lands in
        (client.npcs[id]['script']) and lets game._load_new_npcs() — the real
        streamed-NPC load path — parse it and fire created/playerenters.
        The delivery is simulated; everything the case ASSERTS runs in the
        real engine.

CLI:
    python -m game_tester --gs1-client

CI-safe: skips wholesale (non-failing, clear message) when the pygserver
checkout or a login can't be brought up. The whole suite targets < 60s.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .reporter import TestResult

# SDL dummy before any pygame import (render_smoke pattern).
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_HERE = Path(__file__).resolve().parent                 # pyReborn/game_tester
_PYREBORN = _HERE.parent                                # pyReborn
_REPO = _PYREBORN.parent                                # the checkout root
_FIXTURES = _HERE / "fixtures" / "gs1_client"
_PYGSERVER_DIR = Path(os.environ.get("PYGSERVER_DIR", _REPO / "pygserver"))

# Reference roots, abbreviated in per-case cites:
#   FP  = Preagonal/FourPlay/quattroplay/src   (decompiled official client)
#   GSV = GServer-v2/server                    (C++ reimplementation)
# FP is the oracle of record; GSV appears only where the semantic is a wire
# convention FP does not spell (the '#c#' marker literal).

NPC_X, NPC_Y = 30, 30          # fixture NPC anchor (image rect [30,32)^2)
PLAYER_X, PLAYER_Y = 40, 40    # warp-in point, clear of every footprint

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


# ---------------------------------------------------------------------------
# Case table
# ---------------------------------------------------------------------------
@dataclass
class ClientCase:
    name: str
    family: str
    cite: str                      # grep-verified oracle file:line(s)
    check: Callable                # (env) -> None; raises AssertionError
    channel: str = "npc"           # 'npc' | 'weapon' | 'none'
    script: str = ""               # NPC body (multi-line ok) / ONE-LINE weapon body
    npc_image: str = "-"           # NPC image field written into the .nw
    signs: Tuple = ()              # ((x, y, "text"), ...)
    board: Dict = field(default_factory=dict)   # {(x, y): tile_id}
    settle: int = 8                # pump frames after script delivery
    divergence: str = ""           # non-empty = pinned-divergence row


class CaseEnv:
    """Live handles + per-case capture the check callables read."""

    def __init__(self, game, client):
        self.game = game
        self.client = client
        self.gs1 = game.gs1
        self.handler = game.npc_handler
        self.level = ""            # qa_c_<name>.nw of the running case
        self.npc_id = None         # the fixture NPC (npc channel)
        self.wire: List[Tuple[int, bytes]] = []      # PLI sends since case start
        self.board_mods: List[dict] = []             # on_board_modify infos

    # -- helpers used by checks --------------------------------------------
    def npc(self) -> dict:
        return self.client.npcs.get(self.npc_id) or {}

    def npc_this(self) -> dict:
        """The fixture NPC script's `this` scope (engine state, e.g. this.n)."""
        entry = self.gs1._progs.get(f"npc_{self.npc_id}")
        return entry["scopes"]["this"] if entry else {}

    def wire_ids(self):
        return [pid for pid, _ in self.wire]

    def pump(self, n=8, dt=0.05):
        _pump(self.game, n, dt)

    def touch_probe(self, px: float, py: float, direction: int):
        """Move the player's touch cursor like the input path does: same
        process_movement entry the default-movement code calls per step."""
        self.handler.touched_npcs = set()
        self.handler.process_movement(px, py, direction)


def _expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


# -- check implementations (one per row; rows reference these) --------------

def _chk_block_image_default(env):
    g = env.gs1
    _expect(g.npc_blocks_at(31.0, 31.0), "2x2 default footprint should wall (31,31)")
    _expect(g.is_wall(31, 31), "is_wall must consult NPC footprints before the board")
    _expect(not g.npc_blocks_at(32.5, 31.0), "outside the [30,32) rect must be free")


def _chk_block_imgpart(env):
    g = env.gs1
    _expect(g.npc_blocks_at(32.5, 30.5), "setimgpart 48x16px = 3x1 tiles should wall (32.5,30.5)")
    _expect(not g.npc_blocks_at(30.5, 31.5), "below the 1-tile-high rect must be free")


def _chk_block_setshape(env):
    g = env.gs1
    _expect(g.npc_blocks_at(31.5, 32.5), "setshape 1,32,48 px = 2x3 tiles should wall (31.5,32.5)")
    _expect(not g.npc_blocks_at(32.5, 30.5), "outside the 2-tile-wide box must be free")


def _chk_block_setshape2(env):
    g = env.gs1
    _expect(g.npc_blocks_at(30.5, 30.5), "setshape2 cell type 22 should wall")
    _expect(not g.npc_blocks_at(31.5, 31.5), "cell type 3 (chair) is a walkable overlay")
    _expect(g.npc_tile_type(31, 31) == 3, "the chair cell must still publish tile type 3")
    _expect(g.npc_tile_type(30, 31) == 0, "the 0 cell publishes nothing")


def _chk_dontblock(env):
    g = env.gs1
    _expect(not g.npc_blocks_at(31.0, 31.0), "dontblock exempts from WALL tests")
    env.touch_probe(29.5, 31.0, 0)   # probes (30.55,31.5)/(31.45,31.5): in rect
    env.pump(2)
    _expect(env.npc().get("message") == "touched_dontblock",
            "touch must still fire on a dontblock'ed NPC "
            f"(got message={env.npc().get('message')!r})")


def _chk_blockagain(env):
    _expect(env.gs1.npc_blocks_at(31.0, 31.0),
            "blockagain must restore blocking with the footprint intact")


def _chk_hidden(env):
    g = env.gs1
    _expect(env.npc().get("visible") is False, "hidelocal should clear visible")
    _expect(not g.npc_blocks_at(31.0, 31.0), "an invisible NPC never blocks")
    env.touch_probe(29.5, 31.0, 0)
    env.pump(2)
    _expect(env.npc().get("message") != "ghost",
            "an invisible NPC must not fire playertouchsme")


def _chk_character_marker(env):
    rect = env.gs1.npc_image_rect(env.npc())
    _expect(rect == (NPC_X + 0.5, NPC_Y + 1.0, 2.0, 2.0),
            f"image '#c#' => 2x2 character box at +(0.5,1.0), got {rect}")
    _expect(env.gs1.npc_blocks_at(31.5, 32.0), "inside the character box should wall")
    _expect(not env.gs1.npc_blocks_at(30.2, 31.5), "left of the +0.5 shift must be free")


def _chk_showcharacter(env):
    _expect(env.npc().get("is_character") is True, "showcharacter should mark the NPC")
    rect = env.gs1.npc_image_rect(env.npc())
    _expect(rect == (NPC_X + 0.5, NPC_Y + 1.0, 2.0, 2.0),
            f"showcharacter => same implicit 2x2 box, got {rect}")


def _chk_script_only(env):
    _expect(env.npc_this().get("armed") == 1.0, "fixture script should have run")
    _expect(env.gs1.npc_image_rect(env.npc()) is None,
            "an NPC with no image has no footprint at all")
    _expect(not env.gs1.npc_blocks_at(31.0, 31.0), "and therefore never blocks")


def _chk_touch_up(env):
    env.touch_probe(29.5, 31.0, 0)
    env.pump(2)
    _expect(env.npc().get("message") == "touched_up",
            f"facing-up probe should land in the rect (got {env.npc().get('message')!r})")


def _chk_touch_reach(env):
    env.touch_probe(29.5, 31.6, 0)   # probe y = 32.1, past the [30,32) rect
    env.pump(2)
    _expect(env.npc().get("message") != "touched_up",
            "half-a-tile reach must not stretch to 0.6 below the box")


def _chk_touch_facing(env):
    env.touch_probe(29.5, 31.0, 2)   # same spot as the hit case, facing DOWN
    env.pump(2)
    _expect(env.npc().get("message") != "touched_up",
            "an NPC you are not facing is never probed")


def _chk_timeout_once(env):
    env.pump(12)                     # ~0.6s of engine time vs the 0.15s timer
    _expect(env.npc().get("message") == "timeout_fired", "timeout event should fire")
    _expect(env.npc_this().get("n") == 1.0,
            f"a fired timeout must not re-arm itself (fired {env.npc_this().get('n')}x)")


def _chk_timeout_cancel(env):
    env.pump(12)
    _expect(env.npc().get("message") != "boom", "timeout = 0 must CANCEL the pending event")
    _expect(env.npc().get("_timeout") is None, "the countdown slot must be disarmed")


def _chk_setani(env):
    _expect(env.client.player.animation == "spin",
            f"setani targets the PLAYER (player ani={env.client.player.animation!r})")
    _expect(env.game.current_anim_name == "spin", "the shell mirror must follow")
    _expect(not env.npc().get("gani"), "the NPC's own gani must be untouched")


def _chk_setcharani(env):
    # npc['gani'] keeps the comma-joined "ani,params" form (the same shape a
    # wire NPCPROP_GANI carries); the renderer splits it per frame
    # (render_entities._split_npc_gani). The conformance observable is the
    # resolved animation name.
    gani = (env.npc().get("gani") or "").split(",")[0]
    _expect(gani == "sleep",
            f"setcharani targets the NPC (npc gani={env.npc().get('gani')!r})")
    _expect(env.client.player.animation != "sleep", "the player must be untouched")


def _chk_say_sign0(env):
    _expect(env.game.dialogue_text and "first sign" in env.game.dialogue_text,
            f"say 0 shows LEVEL SIGN 0 in the sign dialogue (got {env.game.dialogue_text!r})")


def _chk_say_sign1(env):
    _expect(env.game.dialogue_text and "second sign" in env.game.dialogue_text,
            f"say 1 indexes signs in arrival order (got {env.game.dialogue_text!r})")


def _chk_say_range(env):
    _expect(env.game.dialogue_text is None,
            f"say past m_signs shows nothing (got {env.game.dialogue_text!r})")
    _expect(not env.npc().get("message"),
            "and must not fall back to a chat bubble for a numeric index")


def _chk_say2(env):
    _expect(env.game.dialogue_text and "hello_say2" in env.game.dialogue_text,
            f"say2 shows its literal text as a sign dialogue (got {env.game.dialogue_text!r})")


def _chk_message(env):
    _expect(env.npc().get("message") == "bubble_test", "message sets the NPC chat bubble")
    _expect(env.npc_id in env.game.npc_chat_texts
            and env.game.npc_chat_texts[env.npc_id][0] == "bubble_test",
            "the shell bubble store must follow")
    _expect(env.game.dialogue_text is None, "message must NOT open the sign dialogue")


def _chk_sign_stacked(env):
    got = env.client.sign_lists.get(env.level) or []
    # Divergence row: the client keeps stacked same-(x,y) signs as separate
    # ordered entries (live GTA abermose7.nw: five signs at 0,0), but
    # pygserver's level parser collapses them into one dict slot before they
    # ever reach the wire, so exactly one arrives. If BOTH arrive, pygserver
    # was fixed - retire this row into a plain say-ordering assertion.
    _expect(len(got) == 1,
            f"pinned: pygserver collapses stacked signs to 1 (got {len(got)}: {got!r})")
    _expect(env.game.dialogue_text is None, "so say 1 has no sign to show")


def _chk_tiles_read(env):
    _expect(env.client.player.nickname == "tiles_ok",
            f"tiles[10,10] should read the planted 427 (nickname={env.client.player.nickname!r})")


def _chk_tiles_write(env):
    got = env.gs1.tile_at(12, 12)
    _expect(got == 171, f"tiles[12,12]=171 must hit the real board (tile_at={got!r})")
    from reborn_protocol.coords import level_index
    board = env.client.levels.get(env.level)
    _expect(board is not None and board[level_index(12, 12)] == 171,
            "the level cache copy must be patched too (renderer + collision source)")


def _chk_updateboard(env):
    # The 4x4 rect is the discriminator: the tiles[] write's own patch
    # callback is 1x1, so only board_update_region can produce a 4x4 mod.
    hits = [m for m in env.board_mods
            if m.get("width") == 4 and m.get("height") == 4
            and m.get("x") == 10 and m.get("y") == 10]
    _expect(hits, f"updateboard 10,10,4,4 must publish that exact region redraw; "
                  f"captured {env.board_mods!r}")
    _expect(hits[0]["tiles"][2 * 4 + 2] == 171,
            "the republished region must carry the freshly written tile")


def _chk_hurt(env):
    _expect(env.client.player.hearts == 2.5,
            f"hurt 1 = ONE HALF-heart: 3 - 0.5 = 2.5 (got {env.client.player.hearts})")


def _chk_hurt_heal(env):
    _expect(env.client.player.hearts == 2.0,
            f"hurt -2 heals a full heart: 1 + 1 = 2 (got {env.client.player.hearts})")


def _chk_hurt_cap(env):
    maxh = float(env.client.player.max_hearts or 3)
    _expect(env.client.player.hearts == maxh,
            f"healing clamps at max_hearts={maxh} (got {env.client.player.hearts})")


def _chk_putbomb(env):
    from reborn_protocol.constants import PLI
    _expect(PLI.BOMBADD in env.wire_ids(),
            f"putbomb must send PLI_BOMBADD (wire={env.wire_ids()!r})")
    spots = [(b.get("x"), b.get("y")) for b in env.game.active_bombs]
    _expect((40.0, 40.0) in spots,
            f"and spawn the local bomb at (40,40) (active={spots!r})")
    _expect(env.npc_this().get("bombs_before") == float(env.client.player.bombs),
            "a scripted bomb must NOT spend the player's bag")


def _chk_putexplosion(env):
    from reborn_protocol.constants import PLI
    _expect(PLI.EXPLOSION in env.wire_ids(),
            f"putexplosion must send PLI_EXPLOSION (wire={env.wire_ids()!r})")
    spots = [(e.get("x"), e.get("y")) for e in env.client.active_explosions]
    _expect((50.0, 50.0) in spots, f"and record the local effect (active={spots!r})")
    _expect(env.client.player.hearts == 3.0,
            "an explosion 16 tiles away must not damage the player")


def _chk_hideimg(env):
    imgs = env.npc().get("imgs") or {}
    _expect(sorted(imgs) == [0, 2],
            f"hideimg 1 removes exactly layer 1 (left: {sorted(imgs)})")


def _chk_hideimgs(env):
    imgs = env.npc().get("imgs") or {}
    _expect(sorted(imgs) == [300],
            f"hideimgs 200,202 clears the INCLUSIVE range (left: {sorted(imgs)})")


def _chk_hidelocal_wire(env):
    from reborn_protocol.constants import PLI
    _expect(env.npc().get("visible") is False, "hidelocal hides the NPC locally")
    npc_ops = {PLI.NPCPROPS, PLI.NPCDEL, PLI.PUTNPC}
    sent = set(env.wire_ids()) & npc_ops
    _expect(not sent, f"hidelocal is LOCAL: no NPC wire op may leave ({sent!r})")


def _chk_showlocal(env):
    _expect(env.npc().get("visible") is True,
            "showlocal restores visibility after hidelocal")
    _expect(env.gs1.npc_blocks_at(31.0, 31.0), "and the footprint walls again")


def _chk_selectedweapon(env):
    want = f"w{env.game.selected_weapon_full_index()}"
    got = env.client.player.nickname
    _expect(got == want,
            f"selectedweapon must read the full-array equip index ({got!r} != {want!r})")


def _chk_weapon_truncation(env):
    w = env.client.weapons.get("-qa_c_ml") or {}
    script = w.get("script") or ""
    _expect("this.line2" in script,
            "multi-line weapon text must survive the wire: the server joins "
            "script lines with 0xa7 (fixed in pygserver "
            "protocol/builders/world.py build_npc_weapon_add 2026-07-27) and "
            f"the client lexer normalizes it back. ({script!r})")


CASES: List[ClientCase] = [
    # ---- blocking footprints ---------------------------------------------
    ClientCase(
        "block_image_default", "image footprint: unsized texture = 2x2 tiles",
        "FP TServerLevel.cpp:2642-2654 (isOnWall asks NPCs before the board); "
        "FP TServerNPC.cpp:1993-2014 (pixelsize: shape > imgpart > texture); "
        "FP TParticleData.cpp:155-163 (unsized texture default 0x30=48px... "
        "engine uses the 32px classic default, see gs1_client._DEFAULT_IMAGE_PX)",
        _chk_block_image_default, npc_image="qa_c_missing.png"),
    ClientCase(
        "block_imgpart_rect", "setimgpart w,h overrides the texture footprint",
        "FP TServerNPC.cpp:2000-2001 (pixelsize imgpart branch)",
        _chk_block_imgpart, npc_image="qa_c_missing.png",
        script="if (playerenters) { setimgpart qa_c_missing.png,0,0,48,16; }"),
    ClientCase(
        "block_setshape_pixels", "setshape w/h are PIXELS (16 per tile)",
        "FP TServerNPCProperties.cpp:632-641 (setshape stores raw px into the "
        "pixelsize slots); FP TServerNPC.cpp:1996-1997 (shape wins)",
        _chk_block_setshape,
        script="if (playerenters) { setshape 1,32,48; }"),
    ClientCase(
        "block_setshape2_types", "setshape2 cells: >=20 walls, others are tile TYPES",
        "FP TServerNPC.cpp:2199-2213 (shape-2 wall test is getTileType >= 20); "
        "FP TServerLevel.cpp:688-708 (NPC answers >1 override the board)",
        _chk_block_setshape2,
        script="if (playerenters) { setshape2 2,2,{22,22,0,3}; }"),
    ClientCase(
        "dontblock_wall_only", "dontblock exempts from WALL tests; touch still fires",
        "FP TServerNPCProperties.cpp:436-446 (dontblock[local] sets one flag); "
        "FP TServerNPC.cpp:2288-2313 (isOnWall self-marks not-blocking around "
        "its own probe - only works if wall tests skip flagged NPCs)",
        _chk_dontblock, npc_image="qa_c_missing.png",
        script="if (playerenters) { dontblock; }\n"
               "if (playertouchsme) { message touched_dontblock; }"),
    ClientCase(
        "blockagain_restores", "blockagain clears the flag, footprint intact",
        "FP TServerNPCProperties.cpp:358-371 (blockagain[local] clears the "
        "same flag dontblock set; geometry is untouched)",
        _chk_blockagain, npc_image="qa_c_missing.png",
        script="if (playerenters) { dontblock; blockagain; }"),
    ClientCase(
        "hidden_never_blocks_or_touches", "an invisible NPC has no footprint at all",
        "FP TServerNPC.cpp:2095-2096 (isOnNPC bails on !m_visible before any "
        "geometry); FP TServerNPCProperties.cpp:460-464 (hidelocal)",
        _chk_hidden, npc_image="qa_c_missing.png",
        script="if (playerenters) { hidelocal; }\n"
               "if (playertouchsme) { message ghost; }"),
    ClientCase(
        "character_marker_box", "image '#c#' = character: 2x2 box at +(0.5,1.0)",
        "GSV scripting/gs1/GS1Commands.cpp:3049 (showcharacter writes IMAGE "
        "'#c#' - the wire marker, absent from FP's in-process model); "
        "FP TServerNPC.cpp:2106-2112 (character box +0.5,+1.0, 2x2)",
        _chk_character_marker, npc_image="#c#"),
    ClientCase(
        "showcharacter_command", "showcharacter marks the NPC a character",
        "FP TServerNPCProperties.cpp:766-776 (scriptfun_servernpc_showcharacter); "
        "FP TServerNPC.cpp:2106-2112 (the box it earns)",
        _chk_showcharacter,
        script="if (playerenters) { showcharacter; }"),
    ClientCase(
        "script_only_no_footprint", "no image, no shape -> no footprint",
        "FP TServerNPC.cpp:2128-2129 (isOnNPC: empty image name -> false)",
        _chk_script_only,
        script="if (playerenters) { this.armed = 1; }"),
    # ---- touchtestd touch -------------------------------------------------
    ClientCase(
        "touch_probe_up", "touchtestd: two probes half a tile past the box, facing only",
        "FP TInitStatics.cpp:1492-1501 (touchtestd table, verbatim in "
        "npc_handler.TOUCH_OFFSETS); FP TPlayer.cpp:1792-1831 (touchNPCs "
        "probes touchtestd[dir] and touchtestd[dir+4])",
        _chk_touch_up, npc_image="qa_c_missing.png",
        script="if (playertouchsme) { message touched_up; }"),
    ClientCase(
        "touch_out_of_reach", "the probe reach is half a tile, not more",
        "FP TInitStatics.cpp:1492-1501 (0.5-tile probe offsets)",
        _chk_touch_reach, npc_image="qa_c_missing.png",
        script="if (playertouchsme) { message touched_up; }"),
    ClientCase(
        "touch_requires_facing", "an adjacent NPC you face away from is never probed",
        "FP TPlayer.cpp:1792-1831 (only touchtestd[dir]/[dir+4] are tested)",
        _chk_touch_facing, npc_image="qa_c_missing.png",
        script="if (playertouchsme) { message touched_up; }"),
    # ---- timeout ----------------------------------------------------------
    ClientCase(
        "timeout_fires_once", "timeout = N arms one event; firing does not re-arm",
        "FP TScriptSpace.cpp:120-133 (setTimeout stores the delay; the fire "
        "path deactivates before running the handler)",
        _chk_timeout_once,
        script="if (playerenters) { timeout = 0.15; }\n"
               "if (timeout) { message timeout_fired; this.n = this.n + 1; }"),
    ClientCase(
        "timeout_zero_cancels", "timeout = 0 CANCELS the pending event",
        "FP TScriptSpace.cpp:121-129 (any value <= 0.0001 zeroes and "
        "deactivates the timer)",
        _chk_timeout_cancel,
        script="if (playerenters) { timeout = 0.2; timeout = 0; }\n"
               "if (timeout) { message boom; }"),
    # ---- setani vs setcharani --------------------------------------------
    ClientCase(
        "setani_targets_player", "setani ALWAYS drives the local player's gani",
        "FP TInitStatics.cpp:3622-3631 (scriptfun_gsfunctionsclient_setani -> "
        "actionplayer->startAnimation) + :4257 (registration)",
        _chk_setani,
        script="if (playerenters) { setani spin,; }"),
    ClientCase(
        "setcharani_targets_npc", "setcharani drives the NPC, never the player",
        "FP TServerNPCProperties.cpp:576-586 (scriptfun_servernpc_setcharani "
        "-> npc->startAnimation)",
        _chk_setcharani,
        script="if (playerenters) { setcharani sleep,; }"),
    # ---- say / say2 / message / signs ------------------------------------
    ClientCase(
        "say_shows_sign0", "say N displays LEVEL SIGN N, not a chat bubble",
        "FP TInitStatics.cpp:3805-3821 (say indexes level->m_signs, parses "
        "the sign text into sign mode)",
        _chk_say_sign0, signs=((10, 10, "first sign"), (12, 10, "second sign")),
        script="if (playerenters) { say 1 - 1; }"),
    ClientCase(
        "say_orders_by_arrival", "sign index = arrival (level-file) order",
        "FP TInitStatics.cpp:3810-3814 (m_signs is the level's ordered array)",
        _chk_say_sign1, signs=((10, 10, "first sign"), (12, 10, "second sign")),
        script="if (playerenters) { say 1; }"),
    ClientCase(
        "say_out_of_range", "an index past the sign array shows nothing",
        "FP TInitStatics.cpp:3811-3812 (signIndex >= mArraySize -> return)",
        _chk_say_range, signs=((10, 10, "only sign"),),
        script="if (playerenters) { say 5; }"),
    ClientCase(
        "say2_literal_text", "say2 shows its text in the sign dialogue",
        "FP TInitStatics.cpp:3823-3831 (parseSignImages on the literal text)",
        _chk_say2,
        script="if (playerenters) { say2 hello_say2; }"),
    ClientCase(
        "message_is_a_bubble", "message sets the NPC chat bubble, no dialogue",
        "FP TServerNPCProperties.cpp:552-556 (scriptfun_servernpc_message -> "
        "npc->setChat)",
        _chk_message,
        script="if (playerenters) { message bubble_test; }"),
    ClientCase(
        "sign_stacked_collapse", "stacked same-(x,y) signs survive as ordered entries",
        "FP TInitStatics.cpp:3805-3821 (say indexes the ordered array - live "
        "GTA stacks say-only signs at 0,0); pygserver/pygserver/level.py:228 "
        "collapses them into one (x,y)-keyed dict slot server-side",
        _chk_sign_stacked, signs=((10, 10, "stack one"), (10, 10, "stack two")),
        script="if (playerenters) { say 1; }",
        divergence="pygserver ships only the LAST stacked sign; the client "
                   "engine keeps arrival order (client.sign_lists) and gs2emu "
                   "delivers both. Server-side gap, not a client-engine bug."),
    # ---- tiles[] / updateboard (weapon channel: server-shipped) -----------
    ClientCase(
        "tiles_read", "tiles[x,y] reads the live board (local frame standalone)",
        "FP TServerLevel.cpp:563-588 (gettile: layer-0 tiles[x + (y<<6)], "
        "gmap-aware via getSideLevel)",
        _chk_tiles_read, channel="weapon", board={(10, 10): 427},
        script="if (tiles[10,10] == 427) { setplayerprop #n,tiles_ok; }"),
    ClientCase(
        "tiles_write", "tiles[x,y] = id writes the real board (collision follows)",
        "FP TServerLevel.cpp:590-612 (settile writes layer 0 in place)",
        _chk_tiles_write, channel="weapon",
        script="tiles[12,12] = 171;"),
    ClientCase(
        "updateboard_publishes", "updateboard x,y,w,h re-publishes the region",
        "FP TInitStatics.cpp:3981-3985 (scriptfun_gsfunctionsclient_"
        "updateboard -> updateBoard(0,x,y,w,h)) + :4280 ('iiii' registration)",
        _chk_updateboard, channel="weapon",
        script="tiles[12,12] = 171; updateboard 10,10,4,4;"),
    # ---- hurt: half-hearts, negatives heal --------------------------------
    ClientCase(
        "hurt_halfhearts", "hurt N hits the player for N HALF-hearts",
        "FP TServerNPCProperties.cpp:466-487 (hurtPlayer(damage * 0.5); the "
        "0.5 is DOUBLE_00402410, FP TInitStatics.cpp:1253)",
        _chk_hurt,
        script="if (playerenters) { playerhearts = 3; hurt 1; }"),
    ClientCase(
        "hurt_negative_heals", "negative hurt HEALS (GTA fountains: hurt -3)",
        "FP TServerNPCProperties.cpp:466-487 (no sign clamp on the damage "
        "before hurtPlayer; corpus: GTA fountain/food scripts heal this way)",
        _chk_hurt_heal,
        script="if (playerenters) { playerhearts = 1; hurt -2; }"),
    ClientCase(
        "hurt_heal_caps", "healing clamps at max_hearts",
        "FP TServerNPCProperties.cpp:466-487 + player hearts cap on apply "
        "(hurtPlayer clamps into [0, fullhearts])",
        _chk_hurt_cap,
        script="if (playerenters) { playerhearts = 2; hurt -9; }"),
    # ---- putbomb / putexplosion: wire + local pairs -----------------------
    ClientCase(
        "putbomb_wire_and_local", "putbomb: local spawn + PLI_BOMBADD, no ammo",
        "FP TServerLevelProperties.cpp:137-144 ('putbomb' idd registration); "
        "FP TServerLevel.cpp:1087 (putBomb(..., sendToServer, fromPlayer))",
        _chk_putbomb,
        script="if (playerenters) { this.bombs_before = playerbombs; putbomb 1,40,40; }"),
    ClientCase(
        "putexplosion_wire_and_local", "putexplosion: local effect + PLI_EXPLOSION",
        "FP TServerLevelProperties.cpp:155-162 ('putexplosion' idd); "
        "FP TServerLevel.cpp:1494 (putExplosion)",
        _chk_putexplosion,
        script="if (playerenters) { playerhearts = 3; putexplosion 1,50,50; }"),
    # ---- hideimg / hideimgs -----------------------------------------------
    ClientCase(
        "hideimg_single", "hideimg N removes exactly layer N",
        "FP TServerNPCProperties.cpp:954-962 (getByImgIndex -> destroy that one)",
        _chk_hideimg,
        script="if (playerenters) { showimg 0,a.png,30,28; showimg 1,b.png,31,28; "
               "showimg 2,c.png,32,28; hideimg 1; }"),
    ClientCase(
        "hideimgs_inclusive_range", "hideimgs A,B clears the INCLUSIVE [A,B]",
        "FP TServerNPCProperties.cpp:964-975 (>= startIndex && <= endIndex)",
        _chk_hideimgs,
        script="if (playerenters) { showimg 200,a.png,30,28; showimg 201,b.png,31,28; "
               "showimg 202,c.png,32,28; showimg 300,d.png,33,28; hideimgs 200,202; }"),
    # ---- hidelocal/showlocal: wire vs local -------------------------------
    ClientCase(
        "hidelocal_is_local", "hidelocal hides locally and sends NOTHING",
        "FP TServerNPCProperties.cpp:460-464 (hidelocal) vs :453-458 (hide "
        "syncs to the server; the *local forms differ only in that sync)",
        _chk_hidelocal_wire, npc_image="qa_c_missing.png",
        script="if (playerenters) { hidelocal; }"),
    ClientCase(
        "showlocal_restores", "showlocal undoes hidelocal, footprint returns",
        "FP TServerNPCProperties.cpp:778-784 (showlocal) vs :757-776 (show)",
        _chk_showlocal, npc_image="qa_c_missing.png",
        script="if (playerenters) { hidelocal; showlocal; }"),
    # ---- selectedweapon ---------------------------------------------------
    ClientCase(
        "selectedweapon_full_index", "selectedweapon = equip index in the FULL array",
        "FP TInitStatics.cpp:2657-2660 (activeplayer->selectedWeapon, -1 when "
        "none; GS1 corpus: GTA -System3 'callweapon selectedweapon,...')",
        _chk_selectedweapon, channel="weapon",
        script="setplayerprop #n,w#v(selectedweapon);"),
    # ---- weapon text wire framing ----------------------------------------
    ClientCase(
        "weapon_multiline_truncation", "multi-line weapon text survives the wire",
        "GS1 wire format joins script lines with 0xa7 (client side: "
        "reborn_protocol/gs1/lexer.py:146 normalizes 0xa7 back); pygserver's "
        "build_npc_weapon_add applies the mangling since 2026-07-27 — this "
        "row was a pinned truncation divergence until then",
        _chk_weapon_truncation, channel="none"),
]


# ---------------------------------------------------------------------------
# Fixture authoring
# ---------------------------------------------------------------------------
def _board_rows(overrides: Dict[Tuple[int, int], int]) -> str:
    rows = []
    for y in range(64):
        row = []
        for x in range(64):
            t = overrides.get((x, y), 0)
            row.append(_B64[(t >> 6) & 63] + _B64[t & 63])
        rows.append(f"BOARD 0 {y} 64 0 {''.join(row)}")
    return "\n".join(rows)


def _level_text(case: ClientCase) -> str:
    parts = ["GLEVNW01", _board_rows(case.board or {})]
    if case.channel == "npc":
        # The NPC ships its image/x/y over the wire; its case script is
        # delivered at the client's streamed-NPC seam instead (see the module
        # docstring). The placeholder line keeps pygserver spawning the NPC
        # even when it has no image (server.py skips image-less, code-less
        # defs).
        parts.append(f"NPC {case.npc_image or '-'} {NPC_X} {NPC_Y}\n"
                     f"this.qa_fixture = 1;\nNPCEND")
    for sx, sy, text in case.signs:
        parts.append(f"SIGN {sx} {sy}\n{text}\nSIGNEND")
    return "\n".join(parts) + "\n"


def _weapon_name(case: ClientCase) -> str:
    return f"-qa_c_{case.name}"


def _weapon_text(case: ClientCase) -> str:
    body = " ".join(case.script.split("\n")).strip()
    gated = (f"if (playerenters) {{ if (strequals(#L,{_level_name(case)})) "
             f"{{ {body} }} }}")
    return (f"GRAWP001\nREALNAME {_weapon_name(case)}\nIMAGE \n"
            f"SCRIPT\n{gated}\nSCRIPTEND\n")


def _level_name(case: ClientCase) -> str:
    return f"qa_c_{case.name}.nw"


# The 2-line fixture weapon behind the weapon_multiline_truncation pin.
_ML_WEAPON = ("GRAWP001\nREALNAME -qa_c_ml\nIMAGE \nSCRIPT\n"
              "if (playerenters) { this.line1 = 1;\n"
              "this.line2 = 2; }\nSCRIPTEND\n")


def generate_fixtures(dest: Path = _FIXTURES) -> List[str]:
    """(Re)write every case level + weapon into `dest`. Source of truth = CASES.

    Each weapon .txt gets an EMPTY sibling .gs2bc: pygserver's GS2ScriptManager
    prefers an up-to-date bytecode cache over invoking gs2test (gs2.py
    _bytecode_for), and empty bytecode makes announce_weapon take the classic
    TEXT wire path (build_npc_weapon_add). Without this, a gs2test binary in
    the checkout COMPILES these GS1-style bodies as GS2 (the language is
    backward compatible), the client pulls bytecode, and the cases silently
    run in the GS2 VM instead of the GS1 engine under test.
    """
    (dest / "world").mkdir(parents=True, exist_ok=True)
    (dest / "weapons").mkdir(parents=True, exist_ok=True)
    written = []
    for case in CASES:
        if case.channel == "none":
            continue
        fn = _level_name(case)
        (dest / "world" / fn).write_text(_level_text(case))
        written.append(fn)
        if case.channel == "weapon":
            wf = f"qa_c_{case.name}.txt"
            (dest / "weapons" / wf).write_text(_weapon_text(case))
            (dest / "weapons" / f"qa_c_{case.name}.gs2bc").write_bytes(b"")
            written.append(wf)
    (dest / "weapons" / "qa_c_ml.txt").write_text(_ML_WEAPON)
    (dest / "weapons" / "qa_c_ml.gs2bc").write_bytes(b"")
    written.append("qa_c_ml.txt")
    return written


# ---------------------------------------------------------------------------
# Server lifecycle (throwaway pygserver seeded with world + weapons + account)
# ---------------------------------------------------------------------------
def _spawn_server(fixtures: Path):
    """Start pygserver in a temp dir; returns (proc, port, workdir, log) or None."""
    from .gs1_conformance import _free_port, _wait_port   # shared plumbing
    run_server = _PYGSERVER_DIR / "run_server.py"
    if not run_server.exists():
        return None
    workdir = Path(tempfile.mkdtemp(prefix="gs1cliconf_"))
    for sub in ("accounts", "npcs", "world", "config", "weapons"):
        (workdir / sub).mkdir()
    start = _PYGSERVER_DIR / "levels" / "onlinestartlocal.nw"
    if start.exists():
        shutil.copy(start, workdir / "world" / "onlinestartlocal.nw")
    for nw in (fixtures / "world").glob("*.nw"):
        shutil.copy(nw, workdir / "world" / nw.name)
    for wt in (fixtures / "weapons").glob("*.txt"):
        shutil.copy(wt, workdir / "weapons" / wt.name)
    now = time.time()
    for bc in (fixtures / "weapons").glob("*.gs2bc"):
        target = workdir / "weapons" / bc.name
        shutil.copy(bc, target)
        # The empty cache must be at least as new as its .txt or _bytecode_for
        # recompiles (see generate_fixtures docstring).
        os.utime(target, (now + 60, now + 60))
    # Pre-grant every fixture weapon so login streams them all (weapon-channel
    # bodies are #L-gated, so they only ACT on their own case level).
    weapons = [_weapon_name(c) for c in CASES if c.channel == "weapon"]
    weapons.append("-qa_c_ml")
    (workdir / "accounts" / "testbot1.json").write_text(json.dumps({
        "account_name": "testbot1", "weapons": weapons,
    }))
    port = _free_port()
    (workdir / "config" / "serveroptions.txt").write_text(
        f"serverport = {port}\n"
        "noverifylogin = true\n"
        "startlevel = onlinestartlocal.nw\n"
        "startx = 30\nstarty = 30.5\n"
        "staff = testbot1\n")
    log = workdir / "server.log"
    env = dict(os.environ)
    env["PYGSERVER_QA"] = "1"
    with open(log, "wb") as lf:
        proc = subprocess.Popen(
            [sys.executable, str(run_server), str(workdir)],
            cwd=str(_PYGSERVER_DIR), stdout=lf, stderr=subprocess.STDOUT,
            env=env, start_new_session=True)
    if not _wait_port("127.0.0.1", port, proc):
        _stop_server(proc, workdir)
        return None
    return proc, port, workdir, log


def _stop_server(proc, workdir):
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)
    shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Client pump (render_smoke's loop body: everything but real input events)
# ---------------------------------------------------------------------------
def _pump(game, n=8, dt=0.05):
    for _ in range(n):
        game.client.update(timeout=0.02)
        game._load_new_npcs()
        game._process_pending_warp()
        game._process_self_shoots()
        game.gs1.process_coroutines(dt)
        game.gs1.process_timeouts(dt)
        game.gs1.advance_input_frame()
        game._check_level_change()
        game._update_swimming_state()
        game._update_visual_position(dt)
        game._update_animations(dt)
        game._last_dt = dt
        game._render()


# ---------------------------------------------------------------------------
# Case execution
# ---------------------------------------------------------------------------
def _run_case(env: CaseEnv, case: ClientCase) -> None:
    """Warp, deliver, settle - then hand off to case.check. Raises on failure."""
    game, client = env.game, env.client
    env.level = _level_name(case)
    env.npc_id = None
    env.wire = []
    env.board_mods = []
    game.dialogue_text = None

    # Spies go in BEFORE the warp: a weapon-channel body fires its
    # playerenters during the warp's own settle loop. Checks assert
    # membership, so the warp's routine packets riding along is fine.
    proto = client._protocol
    orig_send = proto.send_packet

    def spy_send(pid, data=b"", *a, **kw):
        env.wire.append((int(pid), bytes(data)))
        return orig_send(pid, data, *a, **kw)

    proto.send_packet = spy_send
    orig_mod = client.on_board_modify

    def spy_mod(info):
        env.board_mods.append(dict(info))
        if orig_mod:
            orig_mod(info)

    client.on_board_modify = spy_mod
    try:
        if case.channel != "none":
            client.warp_to_level(env.level, PLAYER_X, PLAYER_Y)
            deadline = time.time() + 8.0
            while time.time() < deadline:
                _pump(game, 1)
                if (client._current_level_name == env.level
                        and getattr(game, "_gs1_level", None) == env.level):
                    break
            else:
                raise AssertionError(f"never arrived on {env.level} "
                                     f"(at {client._current_level_name!r})")

        if case.channel == "npc":
            # the fixture NPC = the one living on this level nearest the anchor
            candidates = [
                (nid, n) for nid, n in client.npcs.items()
                if isinstance(n, dict) and n.get("_level") == env.level]
            if not candidates:
                raise AssertionError(f"fixture NPC never arrived on {env.level}")
            env.npc_id = min(candidates, key=lambda kv: (
                (kv[1].get("x", 0) - NPC_X) ** 2
                + (kv[1].get("y", 0) - NPC_Y) ** 2))[0]
            if case.script:
                # deliver at the streamed-NPC seam (see module docstring), then
                # let the REAL load path parse + fire created/playerenters.
                client.npcs[env.npc_id]["script"] = case.script
                _pump(game, 2)
        _pump(game, case.settle)
        case.check(env)
    finally:
        proto.send_packet = orig_send
        client.on_board_modify = orig_mod


def run_gs1_client_conformance(host: Optional[str] = None,
                               port: Optional[int] = None) -> List[TestResult]:
    """Entry point for `--gs1-client`. host/port are accepted for symmetry but
    the suite always spawns its own throwaway pygserver (fixtures must be in
    the server's world, so pointing at an arbitrary live server can't work)."""
    generate_fixtures()

    spawned = _spawn_server(_FIXTURES)
    if spawned is None:
        return [TestResult(
            "gs1client_server", True, 0.0,
            "[SKIP] could not start pygserver "
            f"(checkout at {_PYGSERVER_DIR}?) - suite skipped", [])]
    proc, srv_port, workdir, log = spawned

    from .login import login_client, level_ready
    from pyreborn import Client
    from pyreborn.pygame_game import GameClient

    results: List[TestResult] = []
    client = None
    try:
        client = Client("127.0.0.1", srv_port, version="6.037")
        outcome = login_client(client, "testbot1", "testpass",
                               timeout=8.0, settle=False)
        if not (outcome.connected and outcome.accepted):
            return [TestResult(
                "gs1client_login", True, 0.0,
                f"[SKIP] login failed ({outcome}) - suite skipped", [])]
        for _ in range(60):
            client.update(timeout=0.05)
            if level_ready(client):
                break
        else:
            return [TestResult(
                "gs1client_level", True, 0.0,
                "[SKIP] start level never loaded - suite skipped", [])]

        game = GameClient(client)
        game.running = True
        game.visual_x, game.visual_y = client.x, client.y
        game._load_npc_scripts()
        game._trigger_playerenters()
        game.npc_handler.update_npcs()
        game._gs1_level = client._current_level_name
        _pump(game, 10)

        env = CaseEnv(game, client)
        for case in CASES:
            t0 = time.time()
            try:
                _run_case(env, case)
                detail = f"{case.family} [{case.cite}]"
                if case.divergence:
                    detail = f"[PINNED DIVERGENCE] {detail} ({case.divergence})"
                results.append(TestResult(
                    f"gs1client_{case.name}", True, time.time() - t0, detail, []))
            except AssertionError as e:
                results.append(TestResult(
                    f"gs1client_{case.name}", False, time.time() - t0,
                    f"{case.family}: {e} [{case.cite}]", []))
            except Exception as e:  # noqa: BLE001 - one case must not kill the sweep
                results.append(TestResult(
                    f"gs1client_{case.name}", False, time.time() - t0,
                    f"{case.family}: harness error {type(e).__name__}: {e}", []))
        return results
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
        _stop_server(proc, workdir)


if __name__ == "__main__":   # python -m game_tester.gs1_client_conformance
    rs = run_gs1_client_conformance()
    for r in rs:
        print(("[PASS]" if r.passed else "[FAIL]"), r.name, "-", r.details)
    print(f"{sum(r.passed for r in rs)}/{len(rs)} passed")
    sys.exit(0 if all(r.passed for r in rs) else 1)
