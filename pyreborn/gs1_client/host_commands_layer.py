from __future__ import annotations

import logging

from reborn_protocol.gs1.values import to_num, to_str

from .registry import _FALL_THROUGH, _GS1_LAYER_COMMANDS, _gs1_command



logger = logging.getLogger(__name__)


class LayerCommandsMixin:
    # -- _GS1_LAYER_COMMANDS (gate: the script has a layer store) -----------

    @_gs1_command(_GS1_LAYER_COMMANDS, "showimg", "showimg2")
    def _cmd_showimg_layer(self, name, args, ctx, imgs):
        if len(args) < 2:
            return _FALL_THROUGH
        idx = int(to_num(args[0]))
        rec = imgs.setdefault(idx, {})
        src = to_str(args[1])
        if src.startswith("@"):
            # Classic text form: showimg idx,@font@text,x,y (font may
            # be empty). GTA's splashscreen menu is drawn entirely
            # this way (@b@Start / @Wingdings@è); treating it as an
            # image filename rendered nothing.
            parts = src.split("@", 2)
            rec.pop("image", None)
            rec["font"] = parts[1] if len(parts) > 1 else ""
            rec["style"] = ""
            rec["text"] = parts[2] if len(parts) > 2 else ""
            rec["text_is"] = True
        else:
            rec["image"] = src
            rec.pop("text", None)
            rec.pop("text_is", None)
        if len(args) >= 4:
            rec["x"], rec["y"] = to_num(args[2]), to_num(args[3])
        if name == "showimg2" and len(args) >= 5:
            # showimg2's one extra arg is a Z coordinate, like showani2's:
            # scriptfun_servernpc_showimg2 ("isddd") does setz(*z) where
            # showimg copies the owner NPC's z (TServerNPCProperties.cpp:
            # 816-834; scripting-gs1-commands.md:2707 "showimg2
            # index,filename,x,y,z"). Bomber's room walls draw with it
            # (`showimg2 1000+i,eye_wall...,i%64,int(i/64)-7.25,-.25`).
            rec["z"] = to_num(args[4])
        rec["screen"] = (name == "showimg2")
        rec.setdefault("vis", 4)

    @_gs1_command(_GS1_LAYER_COMMANDS, "showani", "showani2")
    def _cmd_showani(self, name, args, ctx, imgs):
        # showani index,x,y,dir,gani,param1,... / showani2
        # index,x,y,z,dir,gani,param1,... (reference lexer: EEEDS vs
        # EEEEDS — showani2 only ADDS a z coordinate; BOTH are
        # level-tile draws, unlike showimg2/showtext2 which are the
        # screen-space variants. Bomber's PetSys pet and the emotes
        # bubble are showani2-at-player-coords: flagging them
        # screen-space painted them at pixel (playerx,playery), i.e.
        # the screen's top-left corner, instead of on the player).
        # Record gani + position so the renderer can animate
        # furniture/effects. Pull the first string arg after the
        # coords as the gani name (best-effort), then keep everything
        # after it as params: the classic GANI "PARAMn" frame-token
        # substitution (Bomber Arena's DrawBomb() picks the bomb's
        # body/decal sprite and decal image this way, see
        # _render_animated_entity).
        if len(args) < 3:
            return _FALL_THROUGH
        idx = int(to_num(args[0]))
        rec = imgs.setdefault(idx, {})
        rec["x"], rec["y"] = to_num(args[1]), to_num(args[2])
        if name == "showani2" and len(args) >= 4:
            rec["z"] = to_num(args[3])
        name_idx = next((i for i in range(3, len(args))
                          if isinstance(args[i], str) and args[i]), None)
        if name_idx is not None:
            # The lexer delivers the trailing S arg as ONE comma-joined
            # string ("eye_bomber_expl,2,7"): the first token is the
            # gani, the rest are its PARAMn values. Keeping only the
            # name and dropping the tail left params empty — and the
            # scripted-gani explosion fallback keys on params[0], so
            # explosions drew nothing.
            _parts = [p.strip() for p in to_str(args[name_idx]).split(",")]
            gani = _parts[0]
            # Classic `ani[frame]` notation: the bracket picks a frame
            # of that gani, it is NOT part of the filename. PetSys
            # hand-animates the squirrel/kitty walk this way
            # (pet-eye-squirrelwalk1[0..1] each 0.05s tick); keeping
            # the bracket in the name made the file unresolvable, so
            # the pet only drew via its plain idle ani — i.e. it was
            # invisible while following and "teleported" on stop.
            # Strip to the base name (the renderer then simply PLAYS
            # the gani, which cycles the same frames) and record the
            # requested frame for renderers that want exactness.
            if gani.endswith("]") and "[" in gani:
                base, _, fidx = gani[:-1].partition("[")
                gani = base
                try:
                    rec["gani_frame"] = int(float(fidx))
                except (TypeError, ValueError):
                    rec.pop("gani_frame", None)
            else:
                rec.pop("gani_frame", None)
            if gani != rec.get("gani"):
                rec["gani"] = gani
                rec.pop("_anim", None)   # gani changed -> rebuild animation
            rec["params"] = _parts[1:] + list(args[name_idx + 1:])
            rec.pop("_fx_t", None)   # a re-shown effect restarts its burst clock
            # The arg just before the gani name is the direction
            # (present in both forms once enough args are given).
            if name_idx >= 4:
                try:
                    rec["dir"] = int(to_num(args[name_idx - 1])) & 3
                except (TypeError, ValueError):
                    pass
        rec["screen"] = False
        rec.setdefault("vis", 4)

    @_gs1_command(_GS1_LAYER_COMMANDS, "changeimgpart")
    def _cmd_changeimgpart(self, name, args, ctx, imgs):
        if len(args) < 5:
            return _FALL_THROUGH
        rec = imgs.get(int(to_num(args[0])))
        if rec is not None:
            rec["part"] = (int(to_num(args[1])), int(to_num(args[2])),
                           int(to_num(args[3])), int(to_num(args[4])))

    @_gs1_command(_GS1_LAYER_COMMANDS, "changeimgcolors")
    def _cmd_changeimgcolors(self, name, args, ctx, imgs):
        # too few args: ignore (do NOT fall through -- the flat chain had a
        # second, bodyless `changeimgcolors` arm for exactly this)
        if len(args) >= 5:
            rec = imgs.get(int(to_num(args[0])))
            if rec is not None:
                rec["colors"] = tuple(to_num(a) for a in args[1:5])

    @_gs1_command(_GS1_LAYER_COMMANDS, "changeimgzoom")
    def _cmd_changeimgzoom(self, name, args, ctx, imgs):
        if len(args) < 2:
            return _FALL_THROUGH
        rec = imgs.get(int(to_num(args[0])))
        if rec is not None:
            rec["zoom"] = to_num(args[1])

    @_gs1_command(_GS1_LAYER_COMMANDS, "changeimgvis")
    def _cmd_changeimgvis(self, name, args, ctx, imgs):
        if len(args) < 2:
            return _FALL_THROUGH
        rec = imgs.get(int(to_num(args[0])))
        if rec is not None:
            rec["vis"] = int(to_num(args[1]))
            # An EXPLICIT vis matters to the renderer: scripts that set
            # vis>=4 opt the layer into the GUI band (screen-pixel
            # coords, drawn above the seteffect tint — the classic
            # layer table: 0 under players, 1 with players, 2-3 over
            # players, 4+ GUI). Layers that never call changeimgvis
            # keep the default band AND world-tile coords.
            rec["vis_set"] = True

    @_gs1_command(_GS1_LAYER_COMMANDS, "changeimgmode")
    def _cmd_changeimgmode(self, name, args, ctx, imgs):
        if len(args) < 2:
            return _FALL_THROUGH
        rec = imgs.get(int(to_num(args[0])))
        if rec is not None:
            rec["mode"] = int(to_num(args[1]))

    @_gs1_command(_GS1_LAYER_COMMANDS, "showtext")
    def _cmd_showtext(self, name, args, ctx, imgs):
        if len(args) < 6:
            return _FALL_THROUGH
        imgs[int(to_num(args[0]))] = {
            "x": to_num(args[1]), "y": to_num(args[2]),
            "font": to_str(args[3]), "style": to_str(args[4]),
            "text": to_str(args[5]), "text_is": True, "vis": 4,
            "screen": False,
        }

    @_gs1_command(_GS1_LAYER_COMMANDS, "showtext2")
    def _cmd_showtext2(self, name, args, ctx, imgs):
        # showtext2 index,x,y,z,font,style,text (lexer 'EEEESSS' — one more
        # arg than showtext's 'EEESSS'). The extra number is a Z COORDINATE,
        # not a zoom: scriptfun_servernpc_showtext2 ("idddsss") does setz(*z)
        # where showtext copies the owner's z (TServerNPCProperties.cpp:
        # 852-870), and the docs spell "showtext2 index,x,y,z,font,style,text"
        # (scripting-gs1-commands.md:2849). Zoom has its own channel
        # (changeimgzoom). Storing this arg as "zoom" scaled the text by its
        # DEPTH — bomber's player name labels (`showtext2 400+t,...,
        # (t==4),arial,bc,[...]` + `changeimgzoom 400+t,0.75`) drew their 8
        # outline copies at z=0 => font floor instead of the 0.75 zoom.
        if len(args) < 7:
            return _FALL_THROUGH
        imgs[int(to_num(args[0]))] = {
            "x": to_num(args[1]), "y": to_num(args[2]),
            "z": to_num(args[3]),
            "font": to_str(args[4]), "style": to_str(args[5]),
            "text": to_str(args[6]), "text_is": True, "vis": 4,
            "screen": True,
        }

    @_gs1_command(_GS1_LAYER_COMMANDS, "hideimg", "hidetext")
    def _cmd_hideimg_layer(self, name, args, ctx, imgs):
        if not args:
            return _FALL_THROUGH
        imgs.pop(int(to_num(args[0])), None)

    @_gs1_command(_GS1_LAYER_COMMANDS, "hideimgs")
    def _cmd_hideimgs(self, name, args, ctx, imgs):
        # hideimgs start,end — clear layers in [start, end] (the bomber
        # uses this form, e.g. `hideimgs 300,304`). hideimgs start — from
        # start onward. hideimgs — all.
        start = int(to_num(args[0])) if args else None
        end = int(to_num(args[1])) if len(args) >= 2 else None
        for k in [k for k in imgs
                  if (start is None or k >= start)
                  and (end is None or k <= end)]:
            imgs.pop(k, None)

    @_gs1_command(_GS1_LAYER_COMMANDS, "showpoly", "showpoly2")
    def _cmd_showpoly(self, name, args, ctx, imgs):
        # showpoly index,{x1,y1,x2,y2,...} (2D) / showpoly2
        # index,{x1,y1,z1,x2,y2,z2,...} (3D — a height/z per vertex,
        # e.g. eye_furniture_*.gani's pupil poly). The second arg is a
        # GS1 array literal, which the interpreter already evaluates to
        # a flat Python list — a prior version stored `args[1:]` (the
        # *tuple of remaining args*, i.e. a 1-element list wrapping
        # that list) which silently failed to render since it isn't a
        # flat number list. Stored as a regular layer record (like
        # showimg/showani/showtext) so changeimgvis/changeimgcolors and
        # the vis>=2 over-player ordering apply to it the same way.
        if len(args) < 2:
            return _FALL_THROUGH
        rec = imgs.setdefault(int(to_num(args[0])), {})
        rec["poly"] = [float(to_num(v)) for v in args[1]]
        rec["poly_dim"] = 3 if name == "showpoly2" else 2
        rec.setdefault("vis", 4)

