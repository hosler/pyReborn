"""Gani canvas anchoring: frame offsets are relative to the entity's world
(x, y) with NO centring adjustment.

Real-client convention (classic-client-mechanics-truth): an entity's (x, y)
is the ORIGIN of the gani's logical canvas and per-sprite frame offsets are
applied as-is.  Server content encodes placement in those offsets:

* itsasign2.gani places its 32x32 sign sprite at frame offset (0, 0) and the
  Bomber v6 lobby pairs it with ``setshape 1,32,32`` at the same NPC (x, y)
  -- the sprite's top-left IS the NPC position.
* sen_piano.gani encodes its own placement as negative offsets (-3, -30).

Regression: a blanket ``base_offset_x = -(48 - 32)//2 = -8`` inside
_render_animated_entity (added 07-06 for player ganis, later cancelled at the
player call sites only) shifted every NPC/horse gani half a tile left --
hosler's "sign npcs are ~.5 tiles to the left" Bomber v6 report.

Also locked here: the bomb/explosion effect-gani path centres its ganis on a
drop POINT and was tuned with the old -8 baked in; its call-site offset now
carries that 8px itself, so effect placement must be unchanged.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame

from pyreborn.gani import GaniParser, AnimationState
from pyreborn.game.constants import TILE_SIZE
from pyreborn.game.render_entities import EntityRenderMixin
from pyreborn.game.render_effects import EffectsRenderMixin

pygame.init()

# Verbatim structure of the real Bomber v6 lobby sign gani (sprite table +
# single frame placing sprite 20 at offset 0,0).
ITSASIGN2 = """GANI0001
SPRITE    0         SPRITES    0    0   24   16 shadow
SPRITE   20       sign1.gif    0    0   32   32 sprite

CONTINUOUS
SINGLEDIRECTION
DEFAULTHEAD head19.png
DEFAULTBODY body.png

ANI
  20   0   0
ANIEND
"""

# sen_piano-style: placement encoded as negative frame offsets, plus a
# shadow (sprite 0 from the SPRITES keyword sheet) placed in the frame.
NEGATIVE_OFFSETS = """GANI0001
SPRITE    0         SPRITES    0    0   24   12 shadow
SPRITE   20       piano.png    0    0   71   77 Piano
SPRITE   21       piano.png   71    0   28   20 Stool

SINGLEDIRECTION

ANI
   0  12  36,  20  -3 -30,   21  18  36
ANIEND
"""


class _RecordingScreen:
    """Stands in for the pygame display; records blit destinations."""

    def __init__(self):
        self.blits = []

    def blit(self, surface, dest):
        self.blits.append((surface, dest))


class _StubSpriteManager:
    """Returns a fresh surface for any sprite crop request."""

    def get_sprite(self, image, x, y, w, h):
        return pygame.Surface((w, h))

    def get_sprite_recolored(self, image, colors, x, y, w, h):
        return pygame.Surface((w, h))


class _Harness(EntityRenderMixin, EffectsRenderMixin):
    def __init__(self):
        self.screen = _RecordingScreen()
        self.sprite_mgr = _StubSpriteManager()
        self.gani_parser = GaniParser()
        self.shadow_sprite = pygame.Surface((24, 16))
        self.requested = []
        for name, content in (("itsasign2", ITSASIGN2),
                              ("negoffs", NEGATIVE_OFFSETS)):
            self.gani_parser.put_cache(
                name, self.gani_parser.parse_content(content, name))

    def _request_asset(self, filename):  # never hit the network in tests
        self.requested.append(filename)


def _anim(harness, name, direction=2):
    anim = AnimationState(harness.gani_parser)
    anim.set_animation(name, direction)
    assert anim.gani is not None
    return anim


def test_sign_gani_anchors_sprite_exactly_at_entity_xy():
    h = _Harness()
    h._render_animated_entity(400.0, 300.0, _anim(h, "itsasign2"), {})
    # [0] is the shadow (also at its literal frame offset); [1] the sign.
    sign_blits = [(s, d) for s, d in h.screen.blits if s is not h.shadow_sprite]
    assert len(sign_blits) == 1
    sprite, dest = sign_blits[0]
    assert sprite.get_size() == (32, 32)
    assert dest == (400.0, 300.0), (
        "itsasign2's frame offset is (0,0): the 32x32 sign sprite's top-left "
        "must land exactly on the NPC's world position (setshape 1,32,32 "
        "there on the server), with no canvas-centring shift")


def test_shadow_layer_uses_same_anchor():
    h = _Harness()
    h._render_animated_entity(400.0, 300.0, _anim(h, "negoffs"), {})
    shadow_blits = [d for s, d in h.screen.blits if s is h.shadow_sprite]
    assert shadow_blits == [(400.0 + 12, 300.0 + 36)]


def test_negative_frame_offsets_apply_verbatim():
    """sen_piano-style ganis carry their placement in the offsets."""
    h = _Harness()
    h._render_animated_entity(240.0, 640.0, _anim(h, "negoffs"), {})
    dests = [d for _, d in h.screen.blits]
    assert (240.0 - 3, 640.0 - 30) in dests   # piano body
    assert (240.0 + 18, 640.0 + 36) in dests  # stool


def test_effect_gani_frame_stays_centred_on_drop_point():
    """Bomb/explosion ganis centre on an impact POINT; the call-site offset
    absorbed the old -8 canvas shift, so net placement is unchanged: a 32px
    sprite at frame offset 0 spans point +/- 16."""
    h = _Harness()
    gani = h.gani_parser.parse("itsasign2")
    h._render_effect_gani_frame(gani, 100.0, 100.0, 2, 0.0)
    sign_blits = [(s, d) for s, d in h.screen.blits if s is not h.shadow_sprite]
    assert len(sign_blits) == 1
    sprite, (dx, dy) = sign_blits[0]
    assert dx == 100.0 - TILE_SIZE  # 32px sprite: spans 84..116, centred on 100
    assert dy == 100.0 - TILE_SIZE / 2
