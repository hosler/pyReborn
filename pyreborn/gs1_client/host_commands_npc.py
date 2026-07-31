from __future__ import annotations

import logging

from reborn_protocol.gs1.values import to_num, to_str

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
