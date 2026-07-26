"""Head image and ATTRn ("hat") layer resolution.

Two separate wire facts, both live on Bomber classic (2026-07-25):

* PLPROP_HEADGIF is a preset id below 100, else a filename. The reference
  client turns a preset id N into ``head{N}.png``
  (Preagonal/FourPlay/quattroplay/src/TServerPlayer.cpp:1659-1666); pyReborn
  used to keep only the filename form and silently ignore the id, leaving the
  avatar on whatever head it already had.
* An ATTRn sprite layer draws the WEARER's gani attribute n
  (PLPROP_GATTRIB1.., ``#P1..`` in script), not a setani argument and not the
  gani file's own text. The reference client resolves ``Attr`` from the
  object's attribute table and ``Param`` from the setani list as two distinct
  cases (Preagonal/FourPlay/quattroplay/src/TGaniObject.cpp:1974-1994), and
  its gani parser has no DEFAULTATTRn directive at all (TGraalAni.cpp:425-495).
  pyReborn fell back to DEFAULTATTRn unconditionally, so Bomber's
  ``DEFAULTATTR1 hat0.png`` put a hat on every character that no other client
  drew -- and Bomber's real #P1 holds room-editor data, not an image.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pathlib import Path

import pygame

from pyreborn.gani import GaniParser, AnimationState
from pyreborn.game.render_entities import EntityRenderMixin
from pyreborn.packets import parse_other_player, parse_player_props
from pyreborn.player import Player

pygame.init()

BOMBER_IDLE = (Path(__file__).resolve().parents[2]
               / "cache" / "bomber_arena" / "eye_bomber_idle0.gani")


def _headgif_packet(payload: bytes) -> bytes:
    """PLO_OTHERPLPROPS body: gshort id, HEADGIF, then CURLEVEL.

    The trailing prop is what proves the stream stayed aligned: a preset id
    read as a length-prefixed string would eat CURLEVEL's id byte. It has to
    sort ABOVE HEADGIF -- the parser stops at the first descending id."""
    return (bytes([32, 32 + 7])                       # player id 7
            + bytes([11 + 32]) + payload
            + bytes([20 + 32, 5 + 32]) + b"aa.nw")


def test_preset_head_id_becomes_a_filename():
    props = parse_other_player(_headgif_packet(bytes([19 + 32])))
    assert props["head_image"] == "head19.png"
    assert props["level"] == "aa.nw"


def test_custom_head_filename_survives():
    name = b"head1167.png"
    props = parse_other_player(_headgif_packet(
        bytes([100 + len(name) + 32]) + name))
    assert props["head_image"] == "head1167.png"
    assert props["level"] == "aa.nw"


def test_preset_head_id_on_our_own_props():
    props = parse_player_props(bytes([11 + 32, 48 + 32]))
    assert props["head_image"] == "head48.png"


def test_gattribs_land_on_the_player():
    player = Player()
    player.update_from_props({"gattrib1": "hat3.png", "gattrib2": "10.8125,9"})
    assert player.gattribs[1] == "hat3.png"
    assert player.gattribs[2] == "10.8125,9"


# --- ATTR layer resolution ---------------------------------------------------

def _attr_images(equipment):
    """Which images _resolve_gani_layers picks for Bomber's idle gani."""
    parser = GaniParser()
    gani = parser.parse_file(BOMBER_IDLE)
    assert gani is not None and gani.defaults.get("ATTR1") == "hat0.png"

    anim = AnimationState(parser)
    anim.gani = gani
    anim.direction = 2
    anim.frame = 0
    frame = anim.get_frame()

    mixin = EntityRenderMixin.__new__(EntityRenderMixin)
    resolved = EntityRenderMixin._resolve_gani_layers(mixin, anim, frame,
                                                      dict(equipment))
    return [entry[1] for entry in resolved
            if entry[0] != "shadow" and entry[2].layer == "ATTR1"] or []


def test_unset_attribute_draws_no_hat():
    """A player whose #P1 is empty wears nothing -- NOT the gani's
    DEFAULTATTR1."""
    equip = EntityRenderMixin._attr_equipment({})
    assert equip["attr1_image"] == ""
    assert _attr_images(equip) == []


def test_attribute_image_is_drawn():
    equip = EntityRenderMixin._attr_equipment({1: "hat7.png"})
    assert _attr_images(equip) == ["hat7.png"]


def test_non_image_attribute_is_not_replaced_by_the_gani_default():
    """Bomber stores room-editor data in #P1; it names no file."""
    equip = EntityRenderMixin._attr_equipment({1: '"hosler"'})
    # Used verbatim; it names no file, so nothing loads and (having no '.')
    # nothing is requested from the server either -- same as the real client.
    assert _attr_images(equip) == ['"hosler"']


def test_caller_without_attr_keys_still_gets_the_gani_default():
    """NPC/movie gani objects that never learn an attribute table keep the
    old DEFAULTATTRn behaviour."""
    assert _attr_images({}) == ["hat0.png"]
