from __future__ import annotations

import logging

from reborn_protocol.gs1.values import to_num, to_str

from .. import npc_flags
from .objects import _carry_code_for_name
from .registry import _CHARPROP_NPC, _FALL_THROUGH, _GS1_NPC_COMMANDS, _GS1_NPC_TAIL_COMMANDS, _gs1_command



logger = logging.getLogger(__name__)


class NpcCommandsMixin:
    # -- _GS1_NPC_COMMANDS (gate: the script has an NPC dict) ---------------

    @_gs1_command(_GS1_NPC_COMMANDS, "setzoomeffect")
    def _cmd_setzoomeffect(self, name, args, ctx, imgs):
        if not args:
            return _FALL_THROUGH
        ctx.this_obj["zoom_effect"] = to_num(args[0])

    @_gs1_command(_GS1_NPC_COMMANDS, "seteffectmode")
    def _cmd_seteffectmode(self, name, args, ctx, imgs):
        if not args:
            return _FALL_THROUGH
        ctx.this_obj["effect_mode"] = int(to_num(args[0]))

    @_gs1_command(_GS1_NPC_COMMANDS, "setcoloreffect")
    def _cmd_setcoloreffect(self, name, args, ctx, imgs):
        if len(args) < 4:
            return _FALL_THROUGH
        ctx.this_obj["coloreffect"] = tuple(to_num(v) for v in args[:4])

    @_gs1_command(_GS1_NPC_COMMANDS, "showcharacter")
    def _cmd_showcharacter(self, name, args, ctx, imgs):
        ctx.this_obj["is_character"] = True

    @_gs1_command(_GS1_NPC_COMMANDS, "setcharprop")
    def _cmd_setcharprop_npc(self, name, args, ctx, imgs):
        # a non-#P code: mirror a Reborn player's appearance slots
        # (_CHARPROP_NPC) onto the NPC so showcharacter composites it
        if len(args) < 2:
            return _FALL_THROUGH
        key = _CHARPROP_NPC.get(to_str(args[0]))
        if key is not None:
            ctx.this_obj[key] = to_str(args[1])

    @_gs1_command(_GS1_NPC_COMMANDS, "drawoverplayer", "drawunderplayer")
    def _cmd_draw_layer(self, name, args, ctx, imgs):
        ctx.this_obj["draw_layer"] = ("over" if name == "drawoverplayer"
                                      else "under")

    @_gs1_command(_GS1_NPC_COMMANDS, "dontblock", "dontblocklocal")
    def _cmd_dontblock(self, name, args, ctx, imgs):
        # dontblocklocal differs only in wire sync (scriptfun_servernpc_
        # dontblocklocal, TServerNPCProperties.cpp:443 — same blocking field
        # as dontblock :436); identical client-side.
        #
        # Sets ONLY the not-blocking flag. The reference command writes one
        # boolean (TServerNPCProperties.cpp:436-446) and leaves the shape
        # geometry alone, so `blockagain` restores blocking with the shape
        # intact, and the shape stays available to TOUCH tests (which ignore
        # the blocking flag — see npc_blocks_at's rule derivation). The old
        # code here popped rt.shapes and the published cells, which made
        # blockagain a no-op and killed touch on any dontblock'ed NPC.
        ctx.this_obj["dontblock"] = True

    @_gs1_command(_GS1_NPC_COMMANDS, "blockagain", "blockagainlocal")
    def _cmd_blockagain(self, name, args, ctx, imgs):
        # inverse of dontblock: clears the same flag
        # (scriptfun_servernpc_blockagain/blockagainlocal,
        # TServerNPCProperties.cpp:358-371). Blocking queries read the flag
        # live, so the NPC's footprint (shape cells or image rect) resumes
        # blocking immediately — GTA's doors re-arm this way on timeout.
        ctx.this_obj["dontblock"] = False
        # The command also restores the default drawing layer; otherwise an
        # earlier under/over command would survive after blocking resumes.
        # Preagonal/FourPlay/quattroplay/src/TServerNPCProperties.cpp:358-371
        ctx.this_obj.pop("draw_layer", None)

    @_gs1_command(_GS1_NPC_COMMANDS, "destroy")
    def _cmd_destroy_npc(self, name, args, ctx, imgs):
        ctx.this_obj["visible"] = False
        ctx.this_obj.pop("imgs", None)
        entry = self.rt._progs.get(getattr(ctx, "_prog_key", None))
        if entry is not None:
            entry["inactive"] = True
        npc_id = getattr(ctx, "_npc_id", 0)
        if npc_id > 0 and self.rt.client is not None:
            self.rt.client.delete_npc(npc_id)


    # canbe*/cannotbe*: one bit each of the NPC's BLOCKFLAGS byte
    # (TServerNPCProperties.cpp:373-378; bit layout in npc_flags.py).
    _BLOCKFLAG_COMMANDS = {
        "canbecarried": (npc_flags.CAN_BE_CARRIED, True),
        "cannotbecarried": (npc_flags.CAN_BE_CARRIED, False),
        "canbepushed": (npc_flags.CAN_BE_PUSHED, True),
        "cannotbepushed": (npc_flags.CAN_BE_PUSHED, False),
        "canbepulled": (npc_flags.CAN_BE_PULLED, True),
        "cannotbepulled": (npc_flags.CAN_BE_PULLED, False),
    }

    @_gs1_command(_GS1_NPC_COMMANDS, *sorted(_BLOCKFLAG_COMMANDS))
    def _cmd_blockflag(self, name, args, ctx, imgs):
        bit, on = self._BLOCKFLAG_COMMANDS[name]
        npc_flags.set_flag(ctx.this_obj, bit, on)

    # The ganis a carrying character plays: curanis[10..13] = lift,
    # carrystill, hiddenstill, carry (TInitStatics.cpp:1468-1474).
    _CARRY_GANIS = frozenset({"lift", "carrystill", "hiddenstill", "carry"})

    @staticmethod
    def _npc_is_character(npc):
        from ..npc_handler import _is_character_npc
        return _is_character_npc(npc)

    @_gs1_command(_GS1_NPC_COMMANDS, "carryobject")
    def _cmd_carryobject(self, name, args, ctx, imgs):
        # carryobject <name>: a CHARACTER NPC picks up a classic carry object
        # (TServerNPCProperties.cpp:380-393). An unknown name or a plain image
        # NPC does nothing; a known one sets the carry sprite and starts the
        # carrystill gani.
        npc = ctx.this_obj
        if not args or not self._npc_is_character(npc):
            return None
        found, code = _carry_code_for_name(to_str(args[0]))
        if not found:
            return None
        npc["carry_sprite"] = code
        npc["gani"] = "carrystill,"
        return None

    @_gs1_command(_GS1_NPC_COMMANDS, "throwcarry")
    def _cmd_throwcarry(self, name, args, ctx, imgs):
        # throwcarry: a character NPC in a lift/carry gani throws what it
        # carries (TServerNPCProperties.cpp:977-1018). The thrown object is
        # launched by the shell (on_throwcarry); the NPC drops to idle.
        npc = ctx.this_obj
        if not self._npc_is_character(npc):
            return None
        if str(npc.get("gani") or "").split(",")[0].strip().lower() not in self._CARRY_GANIS:
            return None
        code = npc.get("carry_sprite", -1)
        if code is None or code == -1:
            # TServerPlayer::throwObject only launches when a sprite is held
            return None
        npc["carry_sprite"] = -1
        npc["gani"] = "idle,"
        cb = self.rt.on_throwcarry
        if cb:
            cb(npc, code)
        return None

    @_gs1_command(_GS1_NPC_COMMANDS, "timershow")
    def _cmd_timershow(self, name, args, ctx, imgs):
        # timershow: draw the NPC's remaining `timeout` above its head. Cleared
        # by message, by timeout <= 0.0001 and when the timeout fires
        # (setShowTimer on the script variable, TScriptSpace.cpp:121-126,1042-1046).
        ctx.this_obj["timershow"] = True

    # shootfireblast / shootnuke: a flying object (arrow family) fired from the
    # NPC, power 2 / 3 (TServerNPCProperties.cpp:747-755 ->
    # servernpc_shoot_flying_object, :112-150).
    _FLYING_POWER = {"shootfireblast": 2, "shootnuke": 3}

    @_gs1_command(_GS1_NPC_COMMANDS, *sorted(_FLYING_POWER))
    def _cmd_shoot_flying(self, name, args, ctx, imgs):
        rt = self.rt
        if not args or not rt.on_flying:
            return _FALL_THROUGH
        text = to_str(args[0]).strip().lower()
        direction = {"up": 0, "left": 1, "down": 2, "right": 3}.get(text)
        if direction is None:
            direction = int(to_num(text))
            if direction < 0:
                direction = 4 - (-direction & 3)
            direction &= 3
        npc = ctx.this_obj
        x = to_num(npc.get("world_x", npc.get("x", 0)))
        y = to_num(npc.get("world_y", npc.get("y", 0)))
        if direction in (1, 3):
            x, y = x - 0.9375, y - 0.3125
        else:
            x, y = x - 0.3125, y - 0.9375
        rect = rt.npc_image_rect(npc)
        width, height = (rect[2], rect[3]) if rect else (0.0, 0.0)
        if direction == 2:
            x, y = x + width * 0.5, y + height
        else:
            if direction == 3:
                x += width
            elif direction != 1:
                x += width * 0.5
            y += height * 0.5
        rt.on_flying(x, y, direction, self._FLYING_POWER[name])

    @_gs1_command(_GS1_NPC_COMMANDS, "take")
    def _cmd_take(self, name, args, ctx, imgs):
        # take <item>: the NPC absorbs one matching ground item within reach
        # (TServerNPCProperties.cpp:872-910). Reach = 10 tiles + half the
        # diagonal of the NPC's size, measured from the NPC's centre.
        if not args:
            return None
        self.rt.npc_take_item(ctx.this_obj, to_str(args[0]))
        return None

    # -- _GS1_NPC_TAIL_COMMANDS (gate: an NPC dict; last stage) -------------

    @_gs1_command(_GS1_NPC_TAIL_COMMANDS, "hide", "show",
                  "hidelocal", "showlocal")
    def _cmd_visible(self, name, args, ctx, imgs):
        # The *local forms only differ on the wire (visibility change not
        # synced to other players — scriptfun_servernpc_hidelocal/showlocal,
        # TServerNPCProperties.cpp:460/:778 vs hide/show :453/:757); for a
        # client-side renderer they are the same toggle. Live GTA uses
        # hidelocal 67 times across its weapon scripts.
        ctx.this_obj["visible"] = name in ("show", "showlocal")

    @_gs1_command(_GS1_NPC_TAIL_COMMANDS, "move")
    def _cmd_move(self, name, args, ctx, imgs):
        npc = ctx.this_obj
        if len(args) >= 2:
            npc["x"] = to_num(npc.get("x", 0)) + to_num(args[0])
            npc["y"] = to_num(npc.get("y", 0)) + to_num(args[1])
