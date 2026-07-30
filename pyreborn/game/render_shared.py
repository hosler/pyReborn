"""Shared entity-rendering definitions."""

from __future__ import annotations

from typing import Any, NamedTuple

import pygame


class _Entity(NamedTuple):
    """One drawable collected by an entity pass, before depth sorting.

    `depth` is the image's bottom edge in world tiles (_depth_sort_key), so a
    single stable sort across every kind reproduces the old per-kind draw
    order for ties. `key` is the collection's id -- player id, npc id, baddy
    id, horse key -- and is None for the local player, which has no entry."""

    kind: str
    depth: float
    x: float
    y: float
    data: Any
    key: Any = None


def _c255(v: float) -> int:
    """Clamp a 0..1 GS1 colour/alpha multiplier to a 0..255 byte."""
    return max(0, min(255, int(float(v) * 255)))


# findimg(i).red/.green/.blue/.alpha — the GS2 way of tinting a scripted
# layer. GS1's changeimgcolors packs all four into rec['colors'] at once;
# GS2 scripts instead assign the channels one at a time on the image object
# (gs2_client._LayerImage passes unknown property names straight through to
# the same record), so the values land as separate keys that no renderer
# read. Zelda's -Player/Movement puts up its hurt-flash quad that way:
#
#     showpoly(2000, {0,0,screenwidth,0,screenwidth,screenheight,0,screenheight});
#     findimg(2000).red = 1; findimg(2000).blue = findimg(2000).green = 0;
#     findimg(2000).alpha = 0;                    // invisible until hurt
#
# (Preagonal/graal-lttp weapons/weapon-Player_Movement.txt:155-160, and it
# ramps .alpha up in onTimeout when the player takes damage).
# With the channels ignored the quad fell back to opaque white and filled the canvas.
_LAYER_COLOR_KEYS = ("red", "green", "blue", "alpha")


def _layer_colors(rec: dict):
    """(r, g, b, a) 0..1 multipliers for a scripted layer, or None if the
    script never coloured it.

    changeimgcolors' packed rec['colors'] wins when present; otherwise any
    per-channel findimg() assignment is honoured, with the engine's default
    of 1.0 for the channels the script left alone."""
    colors = rec.get('colors')
    if colors:
        return colors
    if not any(k in rec for k in _LAYER_COLOR_KEYS):
        return None
    out = []
    for k in _LAYER_COLOR_KEYS:
        try:
            out.append(float(rec.get(k, 1.0)))
        except (TypeError, ValueError):
            out.append(1.0)
    return tuple(out)


# Perceptual attenuation for changeimgmode-2 (subtractive) showimg layers.
# 1.0 = arithmetically faithful subtraction, which black-clamps the scene
# under opaque near-white smoke textures (the bomber lobby's
# eye_bomb_blackhole* 5x5 grid subtracts ~(163,222,213) from a ~129-lum
# scene, clamping ~half the smoke region to 0). 0.4 keeps the level dim but
# readable; taste band is 0.3 (brighter) .. 0.5 (moodier).
SUBTRACT_SMOKE_SCALE = 0.4


# Type -> default sprite sheet (GServer-v2 BaddyType), used when the server
# doesn't send an explicit BDPROP_POWERIMAGE image name. Ships in
# assets/baddies/ (see game/setup.py _setup_asset_paths); a server-downloaded
# copy of the same filename still wins if the server streams one (SpriteManager
# caches by filename regardless of which search path it came from).
_BADDY_IMAGES = {
    0: "baddygray.png",     # graysoldier
    1: "baddyblue.png",     # bluesoldier
    2: "baddyred.png",      # redsoldier
    3: "baddyblue.png",     # shootingsoldier
    4: "baddygray.png",     # swampsoldier
    5: "baddyhare.png",     # frog / hare
    6: "baddyoctopus.png",  # octopus
    7: "baddygold.png",     # goldenwarrior
    8: "baddylizardon.png", # lizardon
    9: "baddydragon.png",   # dragon
}
_BADDY_DEFAULT_IMAGE = "baddygray.png"


class BaddySheet:
    """Slices a classic baddy PNG (baddygray.png, baddyoctopus.png, ...) into
    per-direction/mode frames.

    Derived empirically (see the contact-sheet recon this task's evidence is
    based on - every 128-wide sheet sliced cleanly into a 4x4 grid of the same
    aspect once GServer-v2's own body.png convention - column = direction, in
    the standard up/left/down/right order - was applied): 4 columns of
    `width/4` px, 4 rows of `height/4` px. baddyhare.png (32x32) is the
    exception: a single frame reused for every mode/direction.

    Row semantics (see the module-level _BADDY_HURT_MODES/_BADDY_DEAD_MODES
    comment): row 0/1 are the two walk frames, row 2 is a hurt/recoil pose,
    row 3 is a final "dead" pose (for baddygray-style sheets this is a
    fully-curled ball; for baddyoctopus it's often blank for the up/down
    columns, since front/back needed no distinct death art - handled by
    _frame_for climbing back down to a populated row).

    The RIGHT direction's sheet column is unreliable across sheets - some
    (baddygray/gold/lizardon) reuse it in rows 1-2 for an unrelated vertical
    blood-decal asset rather than a right-facing pose - so RIGHT is always
    synthesized by horizontally flipping the LEFT column instead of reading
    column 3 (confirmed safe: where column 3 IS genuine right-facing art,
    e.g. baddyoctopus row 0, it's already a mirror of column 1).

    Background pixels: the classic PNGs carry a palette transparency index
    (verified per-file with PIL - each has its own `transparency` index, not
    a fixed RGB) that SpriteManager/pygame already resolves into alpha=0 via
    convert_alpha() in load_sheet()/get_sprite() - no extra colorkey handling
    needed here.
    """

    _DIRECTION_COLS = {0: 0, 1: 1, 2: 2}  # up, left, down -> sheet column
    _BLANK_ALPHA_FRACTION = 0.92  # frame is "no art" if >=92% transparent

    def __init__(self, sprite_mgr, image: str):
        self.sprite_mgr = sprite_mgr
        self.image = image
        self._blank_cache: dict = {}
        self._mirror_cache: dict = {}

    def _sheet_layout(self, sheet):
        """(frame_w, frame_h, single) for the loaded sheet surface."""
        w, h = sheet.get_size()
        if w <= 32 and h <= 32:
            return w, h, True
        return w // 4, h // 4, False

    def _raw_frame(self, row: int, col: int):
        sheet = self.sprite_mgr.load_sheet(self.image)
        if sheet is None:
            return None
        fw, fh, single = self._sheet_layout(sheet)
        if single:
            row = col = 0
        return self.sprite_mgr.get_sprite(self.image, col * fw, row * fh, fw, fh)

    def _is_blank(self, row: int, col: int) -> bool:
        key = (row, col)
        cached = self._blank_cache.get(key)
        if cached is not None:
            return cached
        sprite = self._raw_frame(row, col)
        if sprite is None:
            return True
        w, h = sprite.get_size()
        step = 2 if w * h > 256 else 1
        total = transparent = 0
        for py in range(0, h, step):
            for px in range(0, w, step):
                total += 1
                if sprite.get_at((px, py))[3] == 0:
                    transparent += 1
        blank = total == 0 or (transparent / total) >= self._BLANK_ALPHA_FRACTION
        self._blank_cache[key] = blank
        return blank

    def frame(self, row: int, direction: int):
        """The frame for `row` (0-3) and `direction` (0-3, up/left/down/right),
        falling back to the nearest populated row above it (see class
        docstring) and synthesizing RIGHT by flipping LEFT. None if the sheet
        itself hasn't loaded (caller should request it and stay invisible)."""
        sheet = self.sprite_mgr.load_sheet(self.image)
        if sheet is None:
            return None
        _, _, single = self._sheet_layout(sheet)
        if single:
            return self._raw_frame(0, 0)

        mirror = direction == 3
        col = 1 if mirror else self._DIRECTION_COLS.get(direction, 1)
        r = max(0, min(row, 3))
        while r > 0 and self._is_blank(r, col):
            r -= 1

        if mirror:
            key = (r, col)
            flipped = self._mirror_cache.get(key)
            if flipped is None:
                base = self._raw_frame(r, col)
                if base is None:
                    return None
                flipped = pygame.transform.flip(base, True, False)
                self._mirror_cache[key] = flipped
            return flipped
        return self._raw_frame(r, col)
