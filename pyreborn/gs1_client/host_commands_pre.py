from __future__ import annotations

import logging

from reborn_protocol.gs1.values import to_num, to_str

from ..tiletypes import register_tiledef, remove_tiledefs
from .board import board_update_region
from .objects import _pcode
from .registry import _FALL_THROUGH, _GS1_PRE_COMMANDS, _NOOP, _NPC_WRITE, _gs1_command



logger = logging.getLogger(__name__)


class PreCommandsMixin:
    # -- _GS1_PRE_COMMANDS: before the layer store is resolved --------------

    @_gs1_command(_GS1_PRE_COMMANDS, *_NOOP)
    def _cmd_noop(self, name, args, ctx, imgs):
        # Commands that just toggle/ignore for client rendering (input/feature
        # state we don't model, or world side-effects irrelevant to drawing the
        # lobby). Swallowed silently so a script full of them still runs its
        # visible commands. Membership is the _NOOP set, which other modules
        # read.
        return None

    @_gs1_command(_GS1_PRE_COMMANDS, "join")
    def _cmd_join(self, name, args, ctx, imgs):
        if args:
            self.rt.join_class(ctx, to_str(args[0]))

    @_gs1_command(_GS1_PRE_COMMANDS, "showstats")
    def _cmd_showstats(self, name, args, ctx, imgs):
        # showstats bitflag — select which default-HUD elements the client
        # draws (1 ASD, 2 icons, 4 gralats, 8 bombs, 16 arrows, 32 hearts,
        # 64 AP, 128 MP, 256 minimap, 512 inventory, 1024 players; allstats
        # = 2047). Scripted HUDs call showstats(allstats - <bits>) to hide
        # the built-in HUD before drawing their own. game/hud.py reads
        # rt.stats_mask each frame; None = never called = show everything.
        # State persists across level changes like the real client (levels
        # that care re-issue it on playerenters).
        self.rt.stats_mask = int(to_num(args[0])) if args else None

    @_gs1_command(_GS1_PRE_COMMANDS, "disabledefmovement", "enabledefmovement")
    def _cmd_defmovement(self, name, args, ctx, imgs):
        # disable/enable the engine's built-in WASD/arrow movement. The arena
        # weapons (arenaSYS) disable it and move the player themselves via
        # keydown()+playerx; the input layer checks rt.default_movement.
        self.rt.default_movement = name == "enabledefmovement"

    @_gs1_command(_GS1_PRE_COMMANDS, "enableweapons", "disableweapons")
    def _cmd_weapons_enabled(self, name, args, ctx, imgs):
        # real client-side state (backs the `weaponsenabled` flag), not just a
        # swallowed no-op
        self.rt.weapons_enabled = name == "enableweapons"

    @_gs1_command(_GS1_PRE_COMMANDS, "updateboard", "updateboard2")
    def _cmd_updateboard(self, name, args, ctx, imgs):
        # updateboard x,y,width,height — region redraw from board data (see
        # board_update_region for the oracle citation). GS2 scripts reach
        # this through the shared GS1-command surface (gs2_client routes any
        # reborn_protocol.gs1 COMMANDS name here), which is how LTTP's
        # -Player/Movement publishes its CheckTiles bush edits.
        if len(args) >= 4:
            board_update_region(self.rt.client,
                                to_num(args[0]), to_num(args[1]),
                                to_num(args[2]), to_num(args[3]))

    @_gs1_command(_GS1_PRE_COMMANDS, "addtiledef2")
    def _cmd_addtiledef2(self, name, args, ctx, imgs):
        # addtiledef2 <image>, <level>, <xoffset>, <yoffset> — paste an image
        # onto the active tileset sheet at the given pixel offset.
        rt = self.rt
        if len(args) >= 3 and rt.on_tiledef:
            image = to_str(args[0])
            levelstart = to_str(args[1]) if len(args) >= 2 else ""
            x = int(to_num(args[2]))
            y = int(to_num(args[3])) if len(args) >= 4 else 0
            rt.on_tiledef("paste", image, levelstart, x, y)

    @_gs1_command(_GS1_PRE_COMMANDS, "addtiledef")
    def _cmd_addtiledef(self, name, args, ctx, imgs):
        # addtiledef <image>[, <levelstart>[, <type>]] — replace the WHOLE
        # tileset (the image is a full 2048x512 sheet; Bomber v6's
        # bmb_pics1.png). The type selects the tile-TYPE table for matching
        # levels (0 classic, 1/2 new-world, 5 none — tiletypes.py); it is
        # registered even headless, where on_tiledef is unwired but script
        # probes (onwall/onwater/tiletype) still read the tables.
        rt = self.rt
        if not args:
            return
        image = to_str(args[0])
        levelstart = to_str(args[1]) if len(args) >= 2 else ""
        try:
            tile_type = int(to_num(args[2])) if len(args) >= 3 else 0
        except (TypeError, ValueError):
            tile_type = 0
        register_tiledef(levelstart, tile_type)
        if rt.on_tiledef:
            rt.on_tiledef("full", image, levelstart, tile_type)

    @_gs1_command(_GS1_PRE_COMMANDS, "removetiledefs")
    def _cmd_removetiledefs(self, name, args, ctx, imgs):
        # revert to the default tileset
        prefix = to_str(args[0]).lower() if args else ""
        remove_tiledefs(prefix)
        if self.rt.on_tiledef:
            self.rt.on_tiledef(None, prefix)

    @_gs1_command(_GS1_PRE_COMMANDS, "seteffect")
    def _cmd_seteffect(self, name, args, ctx, imgs):
        # seteffect r,g,b,a — fullscreen colour tint (Tier 3d). 0..1 floats.
        rt = self.rt
        if not (rt.on_seteffect and len(args) >= 4):
            return _FALL_THROUGH
        rt.on_seteffect(to_num(args[0]), to_num(args[1]),
                        to_num(args[2]), to_num(args[3]))

    @_gs1_command(_GS1_PRE_COMMANDS, "setcharprop", "setplayerprop")
    def _cmd_player_gattrib(self, name, args, ctx, imgs):
        # #P1..#P30 player gattribs (room slot lists). setcharprop/setplayerprop
        # on a #P code targets the PLAYER, not the NPC — store it so the script
        # can read it back via #P1(-1) etc. Any other code falls through to the
        # NPC-dict setcharprop / the on_setplayerprop callback below.
        rt = self.rt
        if len(args) < 2:
            return _FALL_THROUGH
        pk = _pcode(to_str(args[0]))
        if pk is None:
            return _FALL_THROUGH
        val = to_str(args[1])
        rt._player_props[pk] = val
        # sync our gattrib to the server so other players see it (the
        # bomber room queue shares slot lists this way)
        try:
            if rt.client is not None:
                rt.client.set_gattrib(int(pk[1:]), val)
        except Exception:
            pass

    @_gs1_command(_GS1_PRE_COMMANDS, "replaceani")
    def _cmd_replaceani(self, name, args, ctx, imgs):
        # replaceani orig,new — swap a default player ani for a level-supplied
        # one (visuals via the game client's resolver AND #m, which scripts
        # test — e.g. the bomber stairs NPC's walk check). One arg restores
        # the default.
        rt = self.rt
        if not args:
            return _FALL_THROUGH
        orig = to_str(args[0])
        if len(args) >= 2 and to_str(args[1]):
            new = to_str(args[1])
            rt.ani_replacements[orig] = new
            # The replacement gani only reaches the parser cache via a
            # server download (setup.py on_file) — fetch it once, or the
            # player's anim silently keeps the old gani.
            if new not in rt._requested_anis:
                rt._requested_anis.add(new)
                try:
                    rt.client.request_file(new + ".gani")
                except Exception:
                    pass
        else:
            rt.ani_replacements.pop(orig, None)

    @_gs1_command(_GS1_PRE_COMMANDS, *_NPC_WRITE)
    def _cmd_npc_write(self, name, args, ctx, imgs):
        # command -> NPC dict key it writes, so the renderer reflects the
        # change (the _NPC_WRITE table).
        if not args:
            return _FALL_THROUGH
        npc = ctx.this_obj
        if isinstance(npc, dict):
            npc[_NPC_WRITE[name]] = to_str(args[0])

    # -- player / game commands (work for weapon scripts too, where there
    # is no NPC object) -----------------------------------------------------

    @_gs1_command(_GS1_PRE_COMMANDS, "setani")
    def _cmd_setani(self, name, args, ctx, imgs):
        # setani ALWAYS drives the LOCAL PLAYER's gani, even from an NPC
        # script — setcharani is the NPC-targeting form (GServer-v2
        # GS1Commands.cpp resolves setani to the player, setcharani to the
        # npc; the GS2 host's _bi_setani splits the same way). Aliasing both
        # onto the NPC made bomber-classic's piano vanish on seating: doPlay's
        # `setani sen_piano_idle,;` replaced the piano NPC's own gani, and
        # the seated player never showed the playing pose.
        rt = self.rt
        if not args:
            return _FALL_THROUGH
        joined = ",".join(to_str(a) for a in args).rstrip(",")
        base = joined.split(",")[0].strip()
        if not base:
            return None
        # Wire prop (other clients + #m); set_animation applies replaceani.
        send = getattr(rt.client, "set_animation", None)
        if send is not None:
            try:
                send(base)
            except Exception:
                pass
        # Local mirror: the renderer draws the local player from
        # player_anim/current_anim_name, which only the built-in input path
        # updates — the pygame shell wires on_setani (game/setup.py) to
        # reflect the scripted gani (params ride along: a gani's PLAYSOUND
        # is routinely a PARAMn token).
        if rt.on_setani:
            rt.on_setani(joined)
        return None

    @_gs1_command(_GS1_PRE_COMMANDS, "setlevel2", "setlevel")
    def _cmd_setlevel(self, name, args, ctx, imgs):
        rt = self.rt
        if not (rt.on_warp and args):
            return _FALL_THROUGH
        x = to_num(args[1]) if len(args) > 1 else None
        y = to_num(args[2]) if len(args) > 2 else None
        rt.on_warp(to_str(args[0]), x, y)

    @_gs1_command(_GS1_PRE_COMMANDS, "freezeplayer", "unfreezeplayer")
    def _cmd_freezeplayer(self, name, args, ctx, imgs):
        rt = self.rt
        # unfreezeplayer cancels a running freeze early (GTA's magic system
        # pairs `freezeplayer <cast time>` with it); freezeplayer 0 through
        # the same path clears both the rt deadline and the game shell's.
        secs = 0.0 if name == "unfreezeplayer" else (
            to_num(args[0]) if args else 0.5)
        if rt.on_freezeplayer:
            rt.on_freezeplayer(secs)
        import time as _t
        rt._freeze_until = _t.monotonic() + max(0.0, secs)

    @_gs1_command(_GS1_PRE_COMMANDS, "hitobjects")
    def _cmd_hitobjects(self, name, args, ctx, imgs):
        # hitobjects power,x,y — client-side sword-hit emulation (see
        # npcserver.md "Emulating sword hits"): fire `washit` on NPCs and hurt
        # baddies at that (level-local) point, same effects as a real sword
        # swing (client.py _sword_hit_npcs/_sword_hit_baddies). The reference
        # ALSO reports the probe to the server (FourPlay's hitobjects calls
        # sendWeaponHit alongside the local weaponHits, TInitStatics.cpp:
        # 3409-3423) so serverside-scripted NPCs get their washit too —
        # mirrored here with the same PLI_HITOBJECTS the sword swing sends.
        if len(args) < 3:
            return _FALL_THROUGH
        power, x, y = to_num(args[0]), to_num(args[1]), to_num(args[2])
        self.rt.hit_objects_at(x, y, power)
        cl = self.rt.client
        if cl is not None:
            try:
                cl.send_hit_objects(power, x, y)
            except Exception:
                pass

    @_gs1_command(_GS1_PRE_COMMANDS, "setminimap")
    def _cmd_setminimap(self, name, args, ctx, imgs):
        if not self.rt.on_setminimap:
            return _FALL_THROUGH
        self.rt.on_setminimap([to_str(a) for a in args])

    @_gs1_command(_GS1_PRE_COMMANDS, "setfocus")
    def _cmd_setfocus(self, name, args, ctx, imgs):
        # setfocus x,y — camera looks at a level position instead of the
        # player (GTA's splashscreen/cutscenes); resetfocus returns it.
        if not (self.rt.on_setfocus and len(args) >= 2):
            return _FALL_THROUGH
        self.rt.on_setfocus(to_num(args[0]), to_num(args[1]))

    @_gs1_command(_GS1_PRE_COMMANDS, "resetfocus")
    def _cmd_resetfocus(self, name, args, ctx, imgs):
        if self.rt.on_setfocus:
            self.rt.on_setfocus(None, None)

    @_gs1_command(_GS1_PRE_COMMANDS, "setbackpal")
    def _cmd_setbackpal(self, name, args, ctx, imgs):
        # setbackpal filename -- swap the tileset's 256-color palette for the
        # one carried by `filename` (scripting-gs1-commands.md:1715). GTA's
        # underwater/dusk/moon levels re-issue it on playerenters and the
        # *Clock weapon flips grayscale/seasonal palettes globally; the pal
        # files are tiny indexed PNGs whose PALETTE is the payload
        # (underwaterpal.png is 32x32 with a full 256-entry palette).
        # Client-local render state, persisting across levels until the next
        # call -- `setbackpal pics1.png` restores stock because that file
        # carries the stock palette. Applied by TilesetManager.set_backpal
        # via the shell callback.
        rt = self.rt
        if not (args and rt.on_setbackpal):
            return _FALL_THROUGH
        fname = to_str(args[0]).strip()
        if fname:
            rt.on_setbackpal(fname)

    @_gs1_command(_GS1_PRE_COMMANDS, "toweapons")
    def _cmd_toweapons(self, name, args, ctx, imgs):
        rt, npc = self.rt, ctx.this_obj
        if not (rt.on_toweapons and args):
            return _FALL_THROUGH
        weapon_name = to_str(args[0])
        if getattr(ctx, "_is_weapon", False):
            rt.on_toweapons(weapon_name)
            return
        script = npc.get("script", "") if isinstance(npc, dict) else ""
        image = npc.get("image", "") if isinstance(npc, dict) else ""
        if isinstance(script, bytes):
            script = script.decode("latin-1")
        try:
            rt.on_toweapons(weapon_name, getattr(ctx, "_npc_id", 0), script, image)
        except TypeError:
            # Some headless integrations still expose the original callback.
            rt.on_toweapons(weapon_name)

