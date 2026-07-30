"""Animated-entity rendering mixin."""

from __future__ import annotations

import pygame

from ..gani import AnimationState


class GaniRenderMixin:
    def _resolve_gani_layers(self, anim: AnimationState, frame, equipment: dict) -> list:
        """Resolve frame.sprites -> (image, sprite-rect) per layer, memoized
        per (gani, direction, frame, equipment). This is the expensive part
        of _render_animated_entity (a dict.get/isinstance/startswith/isdigit
        chain per sprite, per entity, per frame - ~80 entities/frame adds up
        fast) but its result only changes when the animation moves to a new
        frame/direction or the equipment dict changes, both far rarer than
        "every frame" - most entities hold the same gani/frame/equipment
        across many consecutive frames, so this cache is normally a hit.

        Returns a list of entries, either:
          ('shadow', ox, oy) - blit self.shadow_sprite there, or
          ('sprite', img, sprite_def, ox, oy, recolor) - recolor is True if
          the caller should draw it through get_sprite_recolored using the
          CALLER's *current* equipment['colors'] (not baked into the cache -
          only the resolved (img, sprite_def) needs memoizing; re-reading
          colors from the live equipment dict at blit time is just as cheap
          as a plain get_sprite lookup and avoids ever holding a stale
          reference to an old colors list).
        """
        cache = getattr(self, '_gani_layer_cache', None)
        if cache is None:
            cache = self._gani_layer_cache = {}

        # A hashable snapshot of the equipment dict - small (a handful of
        # keys), so building this every call is cheap; it's re-walking
        # frame.sprites with it that's expensive, and that's what gets cached.
        equipment_key = tuple(sorted(
            (k, tuple(v) if isinstance(v, (list, tuple)) else v)
            for k, v in equipment.items()
        ))
        # Direction is part of the key even though it's not called out
        # explicitly in the finding, because the same frame index can hold
        # different sprite layouts per direction (facing up vs down) - the
        # important thing being memoized is (gani, direction, frame index).
        key = (id(anim.gani), anim.direction, anim.frame, equipment_key)
        entry = cache.get(key)
        if entry is not None and entry[0] is anim.gani:
            return entry[1]

        resolved = []
        for raw_sprite_id, ox, oy in frame.sprites:
            sprite_id = raw_sprite_id
            if isinstance(sprite_id, str):
                # A "PARAM1".."PARAM5" frame token - the real sprite id is
                # whatever the showani/setani call passed as that positional
                # extra arg (see _showani_param_equip / gani.py's
                # _parse_frame_line), falling back to the gani's own
                # DEFAULTPARAMn (e.g. eye_bomber_bomb.gani's DEFAULTPARAM1 50)
                # when the caller didn't pass one.
                pval = equipment.get(sprite_id.lower())
                if pval is None:
                    pval = anim.gani.defaults.get(sprite_id)
                if pval is None:
                    continue
                try:
                    sprite_id = int(float(pval))
                except (TypeError, ValueError):
                    continue
            sprite_def = anim.gani.sprites.get(sprite_id)
            if not sprite_def:
                continue

            # Determine which image to use
            layer = sprite_def.layer
            if layer == "BODY":
                img = equipment.get('body_image', anim.gani.defaults.get('BODY', 'body.png'))
            elif layer == "HEAD":
                img = equipment.get('head_image', anim.gani.defaults.get('HEAD', 'head0.png'))
            elif layer == "SWORD":
                img = equipment.get('sword_image', anim.gani.defaults.get('SWORD', 'sword1.png'))
            elif layer == "SHIELD":
                img = equipment.get('shield_image', anim.gani.defaults.get('SHIELD', 'shield1.png'))
            elif layer.startswith("ATTR") and layer[4:].isdigit():
                # An ATTRn sprite layer draws the WEARER's gani attribute n
                # (PLPROP_GATTRIB1.. on the wire, #P1.. in script), not the
                # gani's own text. The reference client resolves the two
                # separately - `case Attr` indexes the object's attr table and
                # `case Param` the setani argument list
                # (Preagonal/FourPlay/quattroplay/src/TGaniObject.cpp:1974-1994)
                # - and its gani parser has no DEFAULTATTRn directive at all
                # (same tree, TGraalAni.cpp:425-495: SPRITE / ATTACHSPRITE /
                # ANI / LOOP / SETBACKTO / DEFAULTHEAD / DEFAULTBODY / ZOOM /
                # ACTOR / PARAMn / ATTRn, and nothing else).
                #
                # So a caller that knows the entity's attributes passes them
                # (empty string included) and owns the slot; only a caller
                # that supplies no attrN_image key at all still falls back to
                # DEFAULTATTRn. Falling back unconditionally drew Bomber's
                # `DEFAULTATTR1 hat0.png` (cache/bomber_arena/
                # eye_bomber_idle0.gani) on every player, hat or no hat, while
                # the real client drew none.
                img = equipment.get(f'{layer.lower()}_image')
                if img is None:
                    img = anim.gani.defaults.get(layer, '')
                if not img:
                    continue
            elif layer == "SPRITES":
                # Shadow and effects - use defaults
                # Special case: shadow sprite (id 0) - render our shadow
                if sprite_id == 0:
                    resolved.append(('shadow', ox, oy))
                    continue
                img = anim.gani.defaults.get('SPRITES', 'sprites.png')
            else:
                # A sprite whose source is a literal image filename (e.g.
                # itsasign2's SIGN1.GIF) uses it directly; only keyword layers
                # (no extension) resolve through the gani defaults. Falling back
                # to sprites.png here drew signs/furniture as garbled characters.
                equip_key = f"{layer.lower()}_image"
                if '.' in layer:
                    img = layer.lower()
                elif equip_key in equipment:
                    # Generic equipment-driven layer (e.g. HORSE -> horse_image)
                    # so callers can drive any named gani layer without a
                    # dedicated elif branch here.
                    img = equipment[equip_key]
                else:
                    img = anim.gani.defaults.get(layer, 'sprites.png')

            # BODY goes through the palette-swap path when a colors prop is
            # available (Tier 2a - see sprites.py and PLPROP_COLORS parsing
            # in packets.py/player.py).
            recolor = layer == "BODY" and bool(equipment.get('colors'))
            resolved.append(('sprite', img, sprite_def, ox, oy, recolor))

        if len(cache) > 2000:
            cache.clear()
        cache[key] = (anim.gani, resolved)
        return resolved

    def _render_animated_entity(self, x: float, y: float, anim: AnimationState,
                                  equipment: dict, alpha: int = 255):
        """Render an entity using gani animation.

        The gani offsets position sprites within a bounding box.
        Position (x, y) is the top-left of the entity's tile position.
        """
        frame = anim.get_frame() if anim.gani else None
        requested = getattr(anim, 'requested_name', None)
        if requested and anim.gani is not None and anim.gani.name != requested:
            # A switch to a not-yet-downloaded gani: keep playing the old one
            # (set_animation retries each frame) but get the download going.
            self._request_asset(f"{requested}.gani")

        if not frame:
            # The requested gani isn't downloaded yet: ask for it and draw
            # nothing (real-client behavior), instead of a placeholder box —
            # GTA's cutscene `setani hiddenstill,` drew the player as a
            # magenta rectangle until the file arrived.
            if requested:
                self._request_asset(f"{requested}.gani")
                return
            sprite = self._sprite_with_alpha(self.placeholder_sprite, alpha)
            self.screen.blit(sprite, (x, y))
            return

        # Gani frame offsets are relative to a logical canvas whose ORIGIN is
        # the entity's world (x, y) — the real client applies them as-is with
        # no centring (classic-client spec: the player is a 3x3-tile sprite
        # anchored top-left; idle.gani putting the body at canvas x=8 is
        # exactly why the collision rect starts at x+0.5). Ground truth from
        # server content: itsasign2.gani places its 32x32 sign sprite at
        # frame offset (0,0) and the NPC script pairs it with
        # `setshape 1,32,32` at the same (x, y); sen_piano.gani encodes its
        # own placement as negative offsets (-3,-30). A former blanket
        # -(48-32)//2 = -8px "centre the canvas on a 2-tile box" shift here
        # drew every gani NPC half a tile left (Bomber lobby signs bug);
        # players had it cancelled with a +8 at their call sites — both
        # halves are gone now.
        base_offset_x = 0
        base_offset_y = 0

        # Render each sprite in the frame, from the memoized layer resolution
        for entry in self._resolve_gani_layers(anim, frame, equipment):
            if entry[0] == 'shadow':
                _, ox, oy = entry
                screen_x = x + base_offset_x + ox
                screen_y = y + base_offset_y + oy
                self.screen.blit(self.shadow_sprite, (screen_x, screen_y))
                continue

            _, img, sprite_def, ox, oy, recolor = entry
            if recolor:
                sprite = self.sprite_mgr.get_sprite_recolored(
                    img, equipment['colors'],
                    sprite_def.x, sprite_def.y,
                    sprite_def.width, sprite_def.height
                )
            else:
                sprite = self.sprite_mgr.get_sprite(
                    img,
                    sprite_def.x, sprite_def.y,
                    sprite_def.width, sprite_def.height
                )

            if sprite:
                sprite = self._sprite_with_alpha(sprite, alpha)
                # Calculate screen position: base offset + gani sprite offset
                screen_x = x + base_offset_x + ox
                screen_y = y + base_offset_y + oy
                self.screen.blit(sprite, (screen_x, screen_y))
            elif isinstance(img, str) and '.' in img:
                # The gani parsed fine but its referenced sprite SHEET (e.g.
                # sen_piano.png, sign1.gif) isn't downloaded yet, so get_sprite
                # returned nothing and the NPC drew blank. Ask the server for
                # it — _request_asset dedups, so this is a one-shot per file.
                # (BODY/HEAD/etc. resolve to real filenames upstream; a bare
                # layer name with no extension is skipped by the '.' guard.)
                self._request_asset(img)

    def _sprite_with_alpha(self, sprite: pygame.Surface,
                           alpha: int) -> pygame.Surface:
        """Return a cached alpha copy without mutating a shared sprite.

        The entry pins the source surface (strong ref) and re-checks
        identity on hit: a bare id()-keyed cache serves stale pixels once
        the sprite-manager LRUs evict and CPython reuses the freed
        surface's address for a new same-size sprite."""
        if alpha >= 255:
            return sprite
        cache = getattr(self, '_entity_alpha_cache', None)
        if cache is None:
            cache = self._entity_alpha_cache = {}
        key = (id(sprite), alpha)
        entry = cache.get(key)
        if entry is not None and entry[0] is sprite:
            return entry[1]
        result = sprite.copy()
        result.set_alpha(alpha)
        if len(cache) > 600:
            cache.clear()
        cache[key] = (sprite, result)
        return result
