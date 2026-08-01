"""Scripted-layer rendering mixin."""

from __future__ import annotations

import math
from typing import Optional, Tuple

import pygame

from ..gani import AnimationState
from .constants import TILE_SIZE
from .frame_context import FrameContext
from .render_shared import SUBTRACT_SMOKE_SCALE, _c255, _layer_colors


class LayerRenderMixin:
    @staticmethod
    def _fade_surface_edges(surf: pygame.Surface, frac: float = 0.35):
        """In-place: multiply RGB toward 0 near the surface's edges, so an
        additive glow blit fades out instead of ending in a hard rectangle.
        The ramp is a tiny white-centre bitmap smoothscaled up (bilinear =
        linear edge ramps), multiplied in — no numpy needed. Runs once per
        cached (image, part, zoom) surface."""
        w, h = surf.get_size()
        # 5x5 with a 3x3 white core -> after smoothscale the outer ~1/4 on
        # each side ramps 0..255; close enough to `frac` for a glow fade.
        core = pygame.Surface((5, 5))
        core.fill((0, 0, 0))
        core.fill((255, 255, 255), pygame.Rect(1, 1, 3, 3))
        mask = pygame.transform.smoothscale(core, (w, h))
        surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

    def _render_deferred_lights(self, frame: Optional[FrameContext] = None):
        """Flush this frame's additive light draws (queued by
        _render_light_sprite / additive showimg layers) on top of the
        seteffect/day-night tint — the classic client's effect-mode-2 glows
        brighten the tinted scene rather than punching holes in the tint."""
        draws = (self._frame_context() if frame is None else frame).light_draws
        if not draws:
            return
        for surf, x, y in draws:
            self.screen.blit(surf, (int(x), int(y)),
                             special_flags=pygame.BLEND_ADD)
        draws.clear()

    def _render_gui_layers(self, frame: Optional[FrameContext] = None):
        """Draw every GUI-band layer (explicit vis>=4 / showimg2-family) from
        current-level NPCs and weapon scripts. Called from the render loop
        AFTER _render_screen_tint so scripted menus, captions and countdowns
        stay visible over a seteffect curtain (the arena's `seteffect 0,0,0,1`
        + "Joining..." flow), matching the classic client's GUI stratum.

        This band runs past the point where deferred lights were flushed, so
        it marks the frame: an additive layer drawn here has to blit now
        (FrameContext.defer_light)."""
        frame = self._frame_context() if frame is None else frame
        frame.gui_pass = True
        try:
            self._render_gui_layers_inner()
        finally:
            frame.gui_pass = False

    def _render_gui_layers_inner(self):
        client = getattr(self, 'client', None)
        npcs = getattr(client, 'npcs', {}) if client else {}
        for npc_id in sorted(npcs):
            npc = npcs[npc_id]
            if not isinstance(npc, dict) or npc.get('visible') is False:
                continue
            npc_level = npc.get('_level')
            if (npc_level and not getattr(client, 'in_gmap_segment', False)
                    and npc_level != getattr(client, '_current_level_name', None)):
                continue
            imgs = npc.get('imgs')
            if imgs:
                self._render_npc_layers(imgs, over=True, gui=True)
        wimgs = getattr(getattr(self, 'gs1', None), '_weapon_imgs', None)
        if wimgs:
            for store in list(wimgs.values()):
                self._render_npc_layers(store, over=True, gui=True)

    @staticmethod
    def _layer_is_gui(rec) -> bool:
        """True for layers in the classic GUI band: an EXPLICIT
        changeimgvis >= 4. GUI layers use screen-pixel coordinates (the
        bomber's shop/menus position them from screenwidth/mousescreenx math)
        and draw above the world + seteffect tint — that's how a scripted
        "Joining..." caption stays readable over a black curtain. Layers that
        never called changeimgvis keep world-tile coords even though their
        default band value is 4 (vis_set gates that).

        The "2"-suffixed commands (showimg2/showani2/showtext2) do NOT mean
        screen-space — GServer-v2's own fn_showimg2 says "Displays an image
        ON THE LEVEL at the specified coordinates" (identical wording to
        showimg's); per the docs, "2" only adds a z/zoom parameter, and the
        UI layer is reachable "by using changeimgvis" — nothing to do with
        the command name. gs1_client.py already gets this right for
        showani2 (unconditionally screen=False) but showimg2/showtext2 were
        flagged screen-space by mistake, which sent the bomber lobby's
        room-editor walls/furniture (drawn via showimg2 at vis 1-3, a world
        layer) to raw world-tile numbers read as SCREEN pixels — stuck near
        the canvas's top-left corner instead of following the camera. Rather
        than trust that per-record flag, gate purely on the documented
        vis>=4 signal (this file doesn't own gs1_client.py, but this is the
        only reader of rec['screen'] — see the grep before this fix)."""
        return bool(rec.get('vis_set') and rec.get('vis', 4) >= 4)

    def _layer_pos(self, rec):
        """Screen position of a layer: GUI-band layers (explicit vis>=4) are
        already in screen pixels; otherwise the coords are world tiles."""
        if self._layer_is_gui(rec):
            return rec.get('x', 0.0), rec.get('y', 0.0)
        return self.camera.world_to_screen(rec.get('x', 0.0), rec.get('y', 0.0))

    def _layer_draw_size(self, rec) -> Tuple[float, float]:
        """Approximate on-screen pixel extent of a GS1 layer, for the
        culled-owner on_screen_only pass in _render_npc_layers. Image layers
        use the (cached) sheet or imagepart size scaled the same way
        _render_showimg_rec will draw them; anything without a resolvable
        image (gani/text layers, not-yet-downloaded sheets) falls back to a
        4-tile footprint — the same fallback _npc_draw_size uses."""
        factor = (self.camera.scale / float(TILE_SIZE)) * (rec.get('zoom') or 1.0)
        part = rec.get('part')
        if part and len(part) >= 4 and part[2] > 0 and part[3] > 0:
            return part[2] * factor, part[3] * factor
        image = rec.get('image')
        if image:
            sheet = self.sprite_mgr.load_sheet(image)
            if sheet is not None:
                return sheet.get_width() * factor, sheet.get_height() * factor
        extent = self.camera.scale * 4
        return extent, extent

    def _poly_layer_on_screen(self, rec) -> bool:
        """Visibility test for a world-band showpoly layer: its footprint is
        its vertex bounding box (vertices are level-tile coords — see
        _render_showpoly_rec), not the rec's x/y, which polys never set."""
        pts = rec.get('poly') or ()
        stride = 3 if rec.get('poly_dim') == 3 else 2
        if len(pts) < stride * 3:
            return False
        xs = [pts[i] for i in range(0, len(pts) - stride + 1, stride)]
        ys = [pts[i + 1] for i in range(0, len(pts) - stride + 1, stride)]
        left, top = self.camera.world_to_screen(min(xs), min(ys))
        right, bottom = self.camera.world_to_screen(max(xs), max(ys))
        return self._entity_on_screen(left, top, margin=0,
                                      width=right - left, height=bottom - top)

    def _layer_place_for_sort(self, rec, screen_size=None):
        """Screen position and depth key of one world layer, or None when it
        is off screen. A poly carries no x/y at all -- its footprint is its
        vertex box (see _poly_layer_on_screen), so both come from that box.
        A rotated layer is culled against its expanded box but keeps its
        drawn height in the depth key, which is the bottom edge the reference
        client sorts on."""
        if rec.get('poly'):
            if not self._poly_layer_on_screen(rec):
                return None
            pts = rec.get('poly') or ()
            stride = 3 if rec.get('poly_dim') == 3 else 2
            xs = [pts[i] for i in range(0, len(pts) - stride + 1, stride)]
            ys = [pts[i + 1] for i in range(0, len(pts) - stride + 1, stride)]
            left, top = self.camera.world_to_screen(min(xs), min(ys))
            return max(ys), left, top
        sx, sy = self._layer_pos(rec)
        lw, lh = self._layer_draw_size(rec)
        depth = self._depth_sort_key(rec.get('y', 0.0), lh / self.camera.scale)
        cull_x, cull_y, cull_w, cull_h = sx, sy, lw, lh
        if rec.get('rotation'):
            side = max(lw, lh) * 1.415
            cull_x -= (side - lw) / 2
            cull_y -= (side - lh) / 2
            cull_w = cull_h = side
        if not self._entity_on_screen(cull_x, cull_y, margin=0, width=cull_w,
                                      height=cull_h, screen_size=screen_size):
            return None
        return depth, sx, sy

    def _render_showimg_rec(self, rec: dict):
        image = rec['image']
        part = rec.get('part')
        if part and part[2] > 0 and part[3] > 0:
            sprite = self.sprite_mgr.get_sprite(image, *part)
        else:
            sprite = self.sprite_mgr.load_sheet(image)
        if not sprite:
            self._request_asset(image)
            return
        # Image pixels are 1:1 with the world at base zoom (16 px/tile); the
        # showimg `zoom` arg multiplies on top of the camera scale.
        factor = (self.camera.scale / float(TILE_SIZE)) * (rec.get('zoom') or 1.0)
        if factor <= 0:
            return
        w = max(1, int(sprite.get_width() * factor))
        h = max(1, int(sprite.get_height() * factor))

        colors = _layer_colors(rec)
        # changeimgmode / wire drawMode share one numbering (GServer-v2
        # object/ShowImg.h prop 8): 0 = additive, 1 = replace (normal alpha
        # blend), 2 = subtractive, 3 = daynight. The bomber leans on this:
        # mode 2 draws its dark smoke (eye_bomb_blackhole*) and white-block
        # shadows by SUBTRACTING the image from the scene — treating it as a
        # normal blit painted the raw 400px black/white cloud textures as an
        # opaque player-centred blob with a hard square edge. No explicit
        # mode keeps the legacy light2.png-style additive heuristic.
        mode = rec.get('mode')
        additive = mode == 0 or (mode is None and 'light' in image.lower())
        subtractive = mode == 2
        colors_key = tuple(colors) if colors else None

        # Rescaling every frame (even at factor==1) and recoloring every frame
        # is wasted work for a layer that's usually static between server
        # updates - cache the finished (scaled + recolored) surface keyed by
        # everything that can change its pixels.
        cache = getattr(self, '_showimg_cache', None)
        if cache is None:
            cache = self._showimg_cache = {}
        cache_key = (image, part, w, h, colors_key, additive, subtractive)
        out = cache.get(cache_key)
        if out is None:
            out = sprite if (w, h) == sprite.get_size() else pygame.transform.scale(sprite, (w, h))
            if additive or subtractive:
                # BLEND_ADD/BLEND_RGB_SUB ignore alpha entirely, so both the
                # layer's colour-alpha AND the image's own per-pixel alpha
                # must be folded into RGB first — otherwise a transparent
                # pixel's hidden RGB bleeds into the blend (a fully
                # transparent border would still add/subtract, re-creating
                # the hard square edge these modes exist to avoid).
                out = out.convert_alpha().premul_alpha()
                r, g, b, a = colors if colors else (1.0, 1.0, 1.0, 1.0)
                if subtractive:
                    # Subtractive layers are smoke/shadow, not blackout: a
                    # faithful subtraction of an opaque near-white cloud (the
                    # bomber lobby's eye_bomb_blackhole grid) exceeds the
                    # scene's whole dynamic range and clamps it to black.
                    # Attenuate so the darkness reads as translucent smoke
                    # over a still-legible level. See SUBTRACT_SMOKE_SCALE.
                    a *= SUBTRACT_SMOKE_SCALE
                if colors or subtractive:
                    mult = (_c255(r * a), _c255(g * a), _c255(b * a), 255)
                    out.fill(mult, special_flags=pygame.BLEND_RGB_MULT)
            elif colors:
                r, g, b, a = colors
                out = out.copy()
                out.fill((_c255(r), _c255(g), _c255(b), 255),
                          special_flags=pygame.BLEND_RGB_MULT)
                out.set_alpha(_c255(a))
            if len(cache) > 300:
                cache.clear()
            cache[cache_key] = out

        sx, sy = self._layer_pos(rec)
        rot = rec.get('rotation')
        if rot:
            # findimg(i).rotation is radians, positive = counter-clockwise,
            # pivot = the drawn image's centre (the C# client's Drawing.cs
            # passes origin = centre and negates the angle for MonoGame's
            # clockwise convention; pygame's rotate() is already CCW). The
            # v6 bomber lobby's cogs spin by nudging this every 0.01s, so
            # memoize the rotated surface per rec keyed by (base, angle) and
            # re-anchor the blit so the centre stays put. rotate() pads the
            # corners transparent, so additive/subtractive blends see zero
            # there instead of a hard square.
            try:
                deg = math.degrees(float(rot))
            except (TypeError, ValueError):
                deg = 0.0
            rot_key = (cache_key, round(deg, 1))
            if rec.get('_rot_key') != rot_key:
                rec['_rot_key'] = rot_key
                rec['_rot_surf'] = pygame.transform.rotate(out, deg)
            rotated = rec['_rot_surf']
            sx -= (rotated.get_width() - out.get_width()) / 2.0
            sy -= (rotated.get_height() - out.get_height()) / 2.0
            out = rotated
        if additive:
            # Additive layers are lights: defer them to after the seteffect
            # tint (same treatment as _render_light_sprite) unless we're
            # already in the post-tint GUI pass or outside the frame loop.
            if not self._frame_context().defer_light(out, sx, sy):
                self.screen.blit(out, (int(sx), int(sy)),
                                 special_flags=pygame.BLEND_ADD)
            return
        flags = pygame.BLEND_RGB_SUB if subtractive else 0
        self.screen.blit(out, (int(sx), int(sy)), special_flags=flags)

    def _render_showani_rec(self, rec: dict):
        """Draw a showani layer (an animated gani at a level/screen position) —
        the arena paints bombs, vases and explosions this way. Each layer keeps
        its own AnimationState so it advances independently."""
        gani = rec.get('gani')
        if not gani:
            return
        # gs1_client.py splits the ani name from its trailing params before
        # storing 'gani', but strip defensively in case a caller ever stores
        # the raw comma-joined form.
        gani = gani.split(',')[0].strip()
        anim = rec.get('_anim')
        if anim is None:
            anim = rec['_anim'] = AnimationState(self.gani_parser)
            anim.set_animation(gani, 0)
        else:
            # Face the layer's current direction (pets/emotes update 'dir' as
            # they move) — but only when that direction actually has frames.
            # Forcing a script-set dir onto a gani that only animates in
            # direction 0 (the mini-pet ganis) lands on an empty direction and
            # freezes the sprite, so fall back to the working direction 0.
            want_dir = int(rec.get('dir', 0) or 0)
            if anim.gani is not None and anim.gani.get_frame_count(want_dir) > 0:
                anim.set_direction(want_dir)
        if anim.gani is None and self.gani_parser.cache.get(gani.replace('.gani', '')) is not None:
            # The gani streamed in after this layer's AnimationState was
            # created (arena vases + lobby seat-cushion showani2 layers are
            # drawn ONCE, before their gani downloads on this slow server; the
            # rec and its blank AnimationState persist, and nothing else
            # re-resolves them, so they stay invisible all match). Retry the
            # resolve once the file is in the parser cache — cache-gated so a
            # still-missing gani costs a dict lookup, not a per-frame parse.
            anim.set_animation(gani, int(rec.get('dir', 0) or 0))
        if anim.gani is None:
            self._request_asset(gani + '.gani')
            return

        # An embedded-SCRIPT gani (Bomber Arena's explosion, various light/
        # particle effects) draws its real visual via GS1 showimg calls this
        # engine doesn't execute; its own ANI frames are a near-blank
        # placeholder. Substitute a generic burst so it still reads visually
        # instead of vanishing.
        if anim.gani.has_script:
            self._render_scripted_gani_fallback(rec)
            return

        anim.update(getattr(self, '_frame_dt', 0.05))
        sx, sy = self._layer_pos(rec)
        equip = self._showani_param_equip(rec.get('params'))
        self._render_animated_entity(int(sx), int(sy), anim, equip)

    @staticmethod
    def _showani_param_equip(params) -> dict:
        """Build an equipment dict from a showani call's trailing params, so
        PARAMn frame tokens and PARAMn-layer sprite sources resolve (Bomber
        Arena's bomb gani picks its body/decal this way - see
        _render_animated_entity and gani.py's _parse_frame_line)."""
        equip: dict = {}
        if not params:
            return equip
        for i, p in enumerate(params, start=1):
            equip[f'param{i}'] = p
            if isinstance(p, str):
                equip[f'param{i}_image'] = p
        return equip

    def _render_scripted_gani_fallback(self, rec: dict):
        """Synthesize an expanding/fading burst for a showani whose gani has
        an embedded SCRIPT we don't run. Bomber Arena's eye_bomber_expl.gani
        passes an intensity/trigger as its first param — but the arena only
        issues the showani ONCE with that param frozen at layer creation and
        never hides burnt-out non-wall cells, so the renderer can't watch a
        live countdown. Drive the burst's lifetime from a per-rec clock
        instead, so it expands, fades, and clears itself (a re-shown layer
        restarts because gs1_client pops '_fx_t' on a fresh showani)."""
        params = rec.get('params') or []
        try:
            on = float(params[0]) if params else 0.0
        except (TypeError, ValueError):
            on = 0.0
        if on <= 0:
            return
        t = rec['_fx_t'] = rec.get('_fx_t', 0.0) + getattr(self, '_frame_dt', 0.05)
        LIFE = 0.6  # matches the script's explosion burn timer
        if t >= LIFE:
            return
        progress = t / LIFE
        radius = int(10 + 22 * progress)
        alpha = int(255 * (1.0 - progress))
        if radius <= 0 or alpha <= 0:
            return
        sx, sy = self._layer_pos(rec)
        cx, cy = int(sx) + TILE_SIZE // 2, int(sy) + TILE_SIZE // 2
        surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(surf, (255, 150, 50, alpha), (radius, radius), radius)
        pygame.draw.circle(surf, (255, 220, 120, alpha), (radius, radius), max(1, int(radius * 0.55)))
        self.screen.blit(surf, (cx - radius, cy - radius))

    def _render_showtext_rec(self, rec: dict):
        text = rec.get('text', '')
        if not text:
            return
        style = rec.get('style', '') or ''
        is_gui = self._layer_is_gui(rec)
        if is_gui:
            # GUI-band text lives in raw screen pixels; the C# client's
            # TextDrawing renders it at a fixed 24*zoom px font with NO
            # camera factor. Multiplying by camera.scale here blew the
            # arena's changeimgzoom-5 "Joining..." caption up to ~200px
            # glyphs (5 * scale instead of 24 * 5 = 120px).
            size = max(8, int(24 * (rec.get('zoom') or 1.0)))
        else:
            size = max(8, int(16 * (rec.get('zoom') or 1.0) * (self.camera.scale / float(TILE_SIZE))))
        font = self._showtext_font(rec.get('font', '') or 'Arial', size, 'b' in style)
        colors = _layer_colors(rec)
        col = (_c255(colors[0]), _c255(colors[1]), _c255(colors[2])) if colors else (255, 255, 255)
        # Showtext (NPC name/sign labels) is drawn straight over the level,
        # not on a plate, so it needs the same outline nameplates get.
        surf = self._render_text_outlined_cached(font, text, col)
        if colors and len(colors) > 3:
            # set_alpha mutates the surface in place, so operate on our own
            # copy rather than the shared cached one.
            surf = surf.copy()
            surf.set_alpha(_c255(colors[3]))
        sx, sy = self._layer_pos(rec)
        if 'c' in style:  # horizontally centred on the anchor
            sx -= surf.get_width() / 2.0
            if is_gui:
                # The C# client's centred style centres BOTH axes (its draw
                # origin is the text centre); scripts anchor full-screen
                # captions at screenheight/2 expecting that. World-band
                # labels keep the historical x-only centring (nameplate
                # positions were live-tuned against it).
                sy -= surf.get_height() / 2.0
        self.screen.blit(surf, (int(sx), int(sy)))

    def _showtext_font(self, name: str, size: int, bold: bool):
        cache = getattr(self, '_showtext_fonts', None)
        if cache is None:
            cache = self._showtext_fonts = {}
        key = (name.lower(), size, bold)
        font = cache.get(key)
        if font is None:
            try:
                font = pygame.font.SysFont(name, size, bold=bold)
            except Exception:
                font = pygame.font.Font(None, size)
            cache[key] = font
        return font

    def _render_showpoly_rec(self, rec: dict):
        """Draw a showpoly/showpoly2 layer: `rec['poly']` is a flat
        `[x1,y1,x2,y2,...]` (dim 2) or `[x1,y1,z1,x2,y2,z2,...]` (dim 3, e.g.
        showpoly2's per-vertex height) list of level-tile coordinates. z is
        dropped for our top-down view — the same treatment showani2/showtext2
        give their z/zoom component. Filled with the layer's `colors` (set via
        changeimgcolors on the same index, like any other layer type) or
        opaque white if none was ever set."""
        pts = rec['poly']
        stride = 3 if rec.get('poly_dim') == 3 else 2
        if len(pts) < stride * 3:  # need at least 3 vertices
            return
        if self._layer_is_gui(rec):
            # GUI-band poly (explicit vis>=4): vertices are screen pixels
            # (npc190's full-screen {0,0,screenwidth,0,...} fade quad).
            points = [(int(pts[i]), int(pts[i + 1]))
                      for i in range(0, len(pts) - stride + 1, stride)]
        else:
            points = [self.camera.world_to_screen(pts[i], pts[i + 1])
                      for i in range(0, len(pts) - stride + 1, stride)]
        colors = _layer_colors(rec)
        col = (_c255(colors[0]), _c255(colors[1]), _c255(colors[2]),
               _c255(colors[3]) if len(colors) > 3 else 255) if colors else (255, 255, 255, 255)
        if col[3] == 0:
            # Fully transparent: skip the surface allocation entirely. Scripts
            # park a hurt/fade quad at alpha 0 for the whole session and only
            # ramp it up on damage (see _layer_colors), so this is the common
            # case for a full-screen poly, once per frame.
            return

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x, min_y = min(xs), min(ys)
        w = max(1, max(xs) - min_x)
        h = max(1, max(ys) - min_y)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        local_points = [(px - min_x, py - min_y) for px, py in points]
        pygame.draw.polygon(surf, col, local_points)  # width=0 -> filled
        self.screen.blit(surf, (min_x, min_y))

    # Additive-blitting a light sprite reads as a blown-out white blob rather
    # than a glow. GS1 scripts commonly pass an "on" alpha around 0.99 (see
    # _render_scripted_gani_fallback's arenaGUI note), which looks like it
    # should dim the light almost to nothing... except pygame's BLEND_ADD
    # blit onto a plain (non-SRCALPHA) destination - which self.screen always
    # is here - IGNORES alpha entirely, both the surface-level alpha the
    # original code set via set_alpha() and the sprite's own per-pixel alpha
    # channel (verified empirically: an alpha=0 source still adds its full
    # RGB). So the *actual* additive contribution has always been the
    # sprite's raw, unscaled RGB regardless of coloreffect's alpha - that's
    # the real source of the wash-out, and set_alpha() never touched it.
    # Fixed the same way _render_showimg_rec already handles this exact
    # problem (see its "fold alpha into the colour so additive blending dims
    # it" comment): pre-scale the sprite's RGB via BLEND_RGB_MULT before the
    # additive blit, so the alpha (capped) actually reduces brightness.
    _LIGHT_ADDITIVE_ALPHA_CAP = 140  # out of 255

    def _render_light_sprite(self, sprite: pygame.Surface, x: float, y: float,
                              is_light: bool, coloreffect: Optional[Tuple[float, float, float, float]],
                              frame: Optional[FrameContext] = None):
        """Render a sprite with light effects (additive blending, alpha).

        Args:
            sprite: The sprite surface to render
            x, y: Position (top-left of NPC tile, like other NPC images)
            is_light: If True, use additive blending
            coloreffect: (r, g, b, a) multipliers - r,g,b typically 1.0, a is alpha (0-1)
            frame: the frame whose deferred-light queue an additive glow joins
        """
        # copy()+recolor/set_alpha() every frame per light NPC is wasted work
        # since the same (sprite, mult) pair repeats frame to frame - cache
        # the result.
        cache = getattr(self, '_light_sprite_cache', None)
        if cache is None:
            cache = self._light_sprite_cache = {}

        if is_light:
            # See the class-level comment above: alpha is folded into the RGB
            # via BLEND_RGB_MULT (not set_alpha(), which BLEND_ADD ignores),
            # capped so the additive contribution can't wash the scene out.
            alpha_frac = coloreffect[3] if coloreffect else 1.0
            mult = _c255(min(alpha_frac, self._LIGHT_ADDITIVE_ALPHA_CAP / 255.0))
            key = (id(sprite), mult, True)
            entry = cache.get(key)
            if entry is not None and entry[0] is sprite:
                light_sprite = entry[1]
            else:
                light_sprite = sprite.copy()
                light_sprite.fill((mult, mult, mult, 255), special_flags=pygame.BLEND_RGB_MULT)
                if len(cache) > 300:
                    cache.clear()
                cache[key] = (sprite, light_sprite)
            # Position - place light sprite with top-left at NPC position.
            # User testing confirmed this positioning is correct for light
            # effects. The additive blit is DEFERRED to after the seteffect/
            # day-night tint (render.py's _render_deferred_lights) so the
            # glow brightens the tinted scene the way the classic client's
            # effect-mode-2 lights do — no tint-eraser holes (see
            # FrameContext.light_draws). Direct callers outside the frame loop
            # (render smoke/tests) just blit now.
            ctx = self._frame_context() if frame is None else frame
            if not ctx.defer_light(light_sprite, x, y):
                self.screen.blit(light_sprite, (x, y),
                                 special_flags=pygame.BLEND_ADD)
        else:
            # Non-additive path: a plain blit DOES respect set_alpha(), so
            # this one is unaffected by the BLEND_ADD alpha quirk above.
            alpha = int(coloreffect[3] * 255) if coloreffect else None
            key = (id(sprite), alpha, False)
            entry = cache.get(key)
            if entry is not None and entry[0] is sprite:
                light_sprite = entry[1]
            else:
                light_sprite = sprite.copy()
                if alpha is not None:
                    light_sprite.set_alpha(alpha)
                if len(cache) > 300:
                    cache.clear()
                cache[key] = (sprite, light_sprite)
            self.screen.blit(light_sprite, (x, y))
