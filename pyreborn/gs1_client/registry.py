from __future__ import annotations

import logging
import os
import sys
import traceback

from reborn_protocol.gs1.host_shared import A_CLASS_NPC_ATTR, A_CLASS_PLAYER_ATTR



logger = logging.getLogger(__name__)


logger = logging.getLogger(__name__)

# Surface GS1 script errors (they're otherwise swallowed) so problems are
# visible. Deduped so a per-frame failure doesn't spam. Set GS1_DEBUG=1 for a
# full traceback on each unique error.
_GS1_ERR_SEEN: set = set()
_GS1_DEBUG = os.environ.get("GS1_DEBUG")

# The measured playerenters stall spent 430 ms in 8.1 million Python calls,
# or about 18,800 calls/ms.  Four ms is therefore roughly 75,000 calls across
# all 11 weapon handlers started that frame: 200 statements apiece leaves room
# for about 34 calls per statement (75,000 / 11 / 200), including the profiled
# name resolution and builtins, before one frame escapes the few-ms range.
_GS1_STATEMENTS_PER_SLICE = 200

# A board normally follows its level announce within a few frames.  Five
# seconds at the client's 60-FPS target is long enough to cover a slow stream,
# but finite because suppressing the continuation forever would be a worse
# semantic change than letting its existing GS1NoBoard error path win.
_GS1_PREEMPT_BOARD_WAIT_FRAMES = 300


def _report_gs1_error(where: str, exc: Exception):
    sig = (where, type(exc).__name__, str(exc)[:160])
    if sig in _GS1_ERR_SEEN:
        return
    _GS1_ERR_SEEN.add(sig)
    print(f"[GS1] {where}: {type(exc).__name__}: {exc}", file=sys.stderr)
    if _GS1_DEBUG:
        traceback.print_exc()




# player-prefixed builtin -> attribute on the pyReborn Player
PLAYER_ATTR = {**A_CLASS_PLAYER_ATTR, "playeraccount": "account"}
# unprefixed builtin -> key on the client NPC dict (the NPC running the script)
NPC_ATTR = dict(A_CLASS_NPC_ATTR)
# command -> NPC dict key it writes (so the renderer reflects the change).
# Image commands are handled explicitly in _dispatch (they also manage the
# imagepart sub-rect), so they're not listed here. NB `setani` is NOT here:
# it always targets the LOCAL PLAYER, even from an NPC script (see
# _cmd_setani) — only `setcharani` is the NPC-targeting form.
_NPC_WRITE = {
    "setcharani": "gani", "setnick": "nickname",
}

# setcharprop / setplayerprop message-code target -> NPC dict key. These mirror
# a Reborn player's appearance slots (#2 shield, #3 head, #8 body, colours, ...).
# A character NPC (showcharacter) is then composited like a player.
_CHARPROP_NPC = {
    "#1": "sword_image", "#2": "shield_image", "#3": "head_image",
    "#5": "horse_image", "#7": "gani", "#8": "body_image",
    "#m": "gani", "#n": "nickname", "#c": "message",
    "#C0": "color0", "#C1": "color1", "#C2": "color2",
    "#C3": "color3", "#C4": "color4", "#C5": "color5",
    "#C6": "color6", "#C7": "color7",
}

# The same appearance codes read off the LOCAL PLAYER, for a script with no NPC
# source (a weapon). Colours are not here: they live in Player.colors as
# palette indices, keyed by the code's slot number (see _color_code_slot).
_CHARPROP_PLAYER = {
    "#1": "sword_image", "#2": "shield_image",
    "#3": "head_image", "#8": "body_image",
}

# Commands that just toggle/ignore for client rendering (input/feature state we
# don't model, or world side-effects irrelevant to drawing the lobby). Swallowed
# silently so a script full of them still runs its visible commands.
_NOOP = frozenset({
    "timereverywhere", "enablefeatures",
    "noplayerkilling",
    "setcursor", "sleep",
    "savelog2", "setletters", "timershow",
    "serverwarp",
    "deletestring", "insertstring", "replacestring",
})

# onwall2 rect probes: far-edge sliver overlaps up to this many tiles are NOT
# counted as hits (see the onwall2 comment in call_function for the full
# derivation from -Test/Movement's flush-wall sliding bug). Must exceed the
# worst resting wall penetration a check-then-move script can leave (one
# movement step, 0.3 tiles on Bomber v6) minus the 1/16 the scripts already
# shave off their probe extents: 0.3 - 1/16 = 0.2375.
_ONWALL2_EDGE_TOL = 0.25

# `timeout = v` with v at or below this cancels the pending timeout instead of
# arming it — TScriptSpace::setTimeout deactivates the timer for any value
# <= 0.0001 (Preagonal/FourPlay/quattroplay/src/TScriptSpace.cpp:121-129).
_TIMEOUT_CANCEL = 0.0001

# Default footprint for an image NPC whose texture size is unknown (image not
# loaded / headless host): 32x32 pixels = 2x2 tiles, the reference engine's
# fallback for an unsized texture (TParticleData::pixelsize,
# Preagonal/FourPlay/quattroplay/src/TParticleData.cpp:155-163).
_DEFAULT_IMAGE_PX = 32



_FALL_THROUGH = object()

#: get_builtin stages. Each has a gate; the two shared data tables
#: (PLAYER_ATTR / NPC_ATTR) are consulted right after their stage's handlers.
_GS1_PLAYER_BUILTINS: dict = {}     # gate: a local player exists
_GS1_NPC_BUILTINS: dict = {}        # gate: ctx.this_obj is an NPC dict
_GS1_BUILTINS: dict = {}            # no gate

#: _dispatch stages, in dispatch order.
_GS1_PRE_COMMANDS: dict = {}        # before the layer store is resolved
_GS1_LAYER_COMMANDS: dict = {}      # gate: a layer store exists
_GS1_NPC_COMMANDS: dict = {}        # gate: ctx.this_obj is an NPC dict
_GS1_MAIN_COMMANDS: dict = {}       # no gate
_GS1_NPC_TAIL_COMMANDS: dict = {}   # gate: NPC dict; last stage


def _gs1_builtin(table, *names):
    """Register a get_builtin handler in `table` under each of `names`.
    Handlers take (self, name, indices, ctx) and may return UNSET.

    A name must not also be in the data table that shares the stage's gate
    (PLAYER_ATTR / NPC_ATTR), because those are read AFTER the handlers and the
    duplicate would be unreachable.
    """
    shadowed = {id(_GS1_PLAYER_BUILTINS): PLAYER_ATTR,
                id(_GS1_NPC_BUILTINS): NPC_ATTR}.get(id(table), ())

    def register(fn):
        for entry in names:
            if entry in table or entry in shadowed:
                raise AssertionError(f"duplicate GS1 builtin {entry!r}")
            table[entry] = fn
        return fn
    return register


def _gs1_command(table, *names):
    """Register a _dispatch handler in `table` under each of `names`.
    Handlers take (self, name, args, ctx, imgs) and return None (handled) or
    _FALL_THROUGH."""
    def register(fn):
        for entry in names:
            if entry in table:
                raise AssertionError(f"duplicate GS1 command {entry!r}")
            table[entry] = fn
        return fn
    return register
