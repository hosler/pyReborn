"""NPC blocking/touch footprints + timeout-cancel, vs the reference client.

Rule derived from the FourPlay decompile (Preagonal/FourPlay/quattroplay/src):
the level wall test asks its NPCs before the board (TServerLevel::isOnWall,
TServerLevel.cpp:2642-2654) and player movement runs through exactly that test
(TPlayer::movementAction, TPlayer.cpp:7515-7519). Per NPC (TServerNPC::isOnNPC,
TServerNPC.cpp:2093-2226):

- invisible (or zoom-0) NPCs neither block nor touch;
- the not-blocking flag (dontblock/dontblocklocal set, blockagain* clear —
  TServerNPCProperties.cpp:358-371, 436-446) exempts from WALL tests only;
  touch ignores it;
- character NPCs block/touch a 2x2 box at +(0.5, 1.0) (also GServer-v2
  NPC.h:544-551);
- setshape publishes cells; a setshape2 array cell walls at type >= 20;
- otherwise a visible image NPC's footprint is its setimgpart rect, else the
  image's full (uncapped) size, refined per-pixel by transparency;
- `timeout = 0` / settimer(0) CANCELS the pending timer (TScriptSpace::
  setTimeout, TScriptSpace.cpp:121-129: any value <= 0.0001 deactivates).
"""

import os
import sys
import types

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn.gs1_client import ClientGS1
from pyreborn.npc_handler import NPCHandler


def _client(npcs=None):
    return types.SimpleNamespace(
        npcs=npcs or {}, x=30.0, y=30.0, tiles=[0] * 4096,
        _current_level_name='level1.nw',
        player=types.SimpleNamespace(direction=0, x=30.0, y=30.0, hearts=3),
        global_flags={})


def _gs1(npcs=None, image_size=None):
    client = _client(npcs)
    gs1 = ClientGS1(client)
    if image_size is not None:
        gs1.image_size_source = lambda name: image_size
    return client, gs1


# -- image footprint blocking ------------------------------------------------

def test_image_npc_blocks_its_image_footprint():
    _c, gs1 = _gs1({5: {'x': 10.0, 'y': 10.0, 'image': 'trunk.png'}},
                   image_size=(32, 48))    # 2x3 tiles
    assert gs1.npc_blocks_at(10.5, 12.9) is True
    assert gs1.npc_blocks_at(11.9, 10.0) is True
    assert gs1.npc_blocks_at(12.1, 10.5) is False   # right of the rect
    assert gs1.npc_blocks_at(10.5, 13.0) is False   # exclusive far edge
    assert gs1.npc_blocks_at(9.9, 10.5) is False


def test_setimgpart_rect_is_the_footprint():
    # setimgpart sizes the NPC (TServerNPC::pixelsize: shape > imgpart >
    # texture size): a 32x32 part of a big sheet is a 2x2-tile footprint,
    # not the sheet's.
    _c, gs1 = _gs1({5: {'x': 10.0, 'y': 10.0, 'image': 'pics1.png',
                        'imagepart': (176, 128, 32, 32)}},
                   image_size=(2048, 512))
    assert gs1.npc_blocks_at(11.9, 11.9) is True
    assert gs1.npc_blocks_at(12.1, 10.5) is False
    assert gs1.npc_blocks_at(10.5, 12.1) is False


def test_unknown_image_size_defaults_to_2x2():
    # No size hook (headless) -> the engine's unsized-texture default of
    # 32x32 px (TParticleData::pixelsize).
    _c, gs1 = _gs1({5: {'x': 10.0, 'y': 10.0, 'image': 'door.png'}})
    assert gs1.npc_blocks_at(11.5, 11.5) is True
    assert gs1.npc_blocks_at(12.5, 11.5) is False


def test_imageless_npc_has_no_footprint():
    _c, gs1 = _gs1({5: {'x': 10.0, 'y': 10.0}})
    assert gs1.npc_blocks_at(10.5, 10.5) is False


def test_transparent_pixels_do_not_block():
    # The reference footprint resolves to !isPixelTransparent inside the
    # rect; art left half transparent -> walkable there.
    _c, gs1 = _gs1({5: {'x': 10.0, 'y': 10.0, 'image': 'glow.png'}},
                   image_size=(32, 32))
    gs1.image_opaque_source = lambda name, px, py: px >= 16
    assert gs1.npc_blocks_at(10.5, 11.0) is False   # px 8: transparent half
    assert gs1.npc_blocks_at(11.5, 11.0) is True    # px 24: opaque half


def test_hidden_npc_neither_blocks_nor_touches():
    npcs = {5: {'x': 10.0, 'y': 10.0, 'image': 'door.png', 'visible': False}}
    client, gs1 = _gs1(npcs)
    assert gs1.npc_blocks_at(10.5, 10.5) is False
    handler = NPCHandler(client)
    handler.gs1 = gs1
    handler.update_npcs()
    assert handler.npc_shapes == {}


def test_dontblock_clears_blockagain_restores_via_script():
    # GTA's open-door mechanic: `if (playertouchsme) {hidelocal;
    # dontblocklocal;}` then a timeout re-shows and re-blocks.
    script = ("if (playertouchsme) { hidelocal; dontblocklocal; }\n"
              "if (timeout) { showlocal; blockagainlocal; }")
    npcs = {5: {'x': 10.0, 'y': 10.0, 'image': 'door.png', 'script': script}}
    _c, gs1 = _gs1(npcs)
    gs1.load_script("npc_5", script, npc_id=5)

    assert gs1.npc_blocks_at(10.5, 10.5) is True        # shown: blocks
    gs1.trigger_npc_event(5, "playertouchsme")          # open
    assert npcs[5]['dontblock'] is True
    assert npcs[5]['visible'] is False
    assert gs1.npc_blocks_at(10.5, 10.5) is False       # walk through
    gs1.trigger_npc_event(5, "timeout")                 # re-close
    assert npcs[5]['dontblock'] is False
    assert gs1.npc_blocks_at(10.5, 10.5) is True        # blocks again


def test_local_weapon_showimg_layers_do_not_block():
    # Weapon showimg layers/effects are not NPCs (they live in the weapon
    # image stores, not client.npcs) — nothing our own scripts draw may
    # start walling the level.
    _c, gs1 = _gs1({})
    gs1.load_weapon("-fx", "if (created) { showimg 200,huge.png,10,10; }")
    gs1.trigger_event("created", name="weapon_-fx")
    assert gs1._weapon_imgs.get("weapon_-fx")           # the layer exists
    assert gs1.npc_blocks_at(10.5, 10.5) is False       # and doesn't block


# -- setshape / setshape2 interplay ------------------------------------------

def test_setshape_dontblock_keeps_shape_and_blockagain_restores():
    npcs = {7: {'x': 20.0, 'y': 20.0, 'image': 'counter.png'}}
    _c, gs1 = _gs1(npcs)
    gs1.shapes[7] = (2, 2, [22] * 4)
    gs1._update_shape_blocks(7, npcs[7], 2, 2, [22] * 4)
    assert gs1.npc_blocks_at(20.5, 20.5) is True

    npcs[7]['dontblock'] = True
    assert gs1.npc_blocks_at(20.5, 20.5) is False
    # the geometry itself survives (blockagain must restore it, and touch
    # still uses it)
    assert gs1.shapes[7] == (2, 2, [22] * 4)
    assert (20, 20) in gs1._shape_blocks

    npcs[7]['dontblock'] = False
    assert gs1.npc_blocks_at(20.5, 20.5) is True


def test_hidden_shape_npc_does_not_block():
    npcs = {7: {'x': 20.0, 'y': 20.0, 'visible': False}}
    _c, gs1 = _gs1(npcs)
    gs1.shapes[7] = (2, 2, [22] * 4)
    gs1._update_shape_blocks(7, npcs[7], 2, 2, [22] * 4)
    assert gs1.npc_blocks_at(20.5, 20.5) is False


def test_shape2_cells_wall_at_type_20_and_up():
    # isOnNPC's shape-2 wall compare is >= 20 (choc blocks use 22, but 20/21
    # wall too); lower published types (chairs = 3) are walkable overlays.
    npcs = {7: {'x': 20.0, 'y': 20.0}}
    _c, gs1 = _gs1(npcs)
    flags = [22, 21, 20, 3]
    gs1.shapes[7] = (4, 1, flags)
    gs1._update_shape_blocks(7, npcs[7], 4, 1, flags)
    assert gs1.npc_blocks_at(20.5, 20.5) is True
    assert gs1.npc_blocks_at(21.5, 20.5) is True
    assert gs1.npc_blocks_at(22.5, 20.5) is True
    assert gs1.npc_blocks_at(23.5, 20.5) is False


def test_script_shape_overrides_image_footprint():
    # An NPC with a recorded shape never adds its image rect on top
    # (pixelsize precedence): a 1x1 shape on a big image blocks 1x1.
    npcs = {7: {'x': 20.0, 'y': 20.0, 'image': 'big.png'}}
    _c, gs1 = _gs1(npcs)
    gs1.image_size_source = lambda name: (64, 64)
    gs1.shapes[7] = (1, 1, [22])
    gs1._update_shape_blocks(7, npcs[7], 1, 1, [22])
    assert gs1.npc_blocks_at(20.5, 20.5) is True
    assert gs1.npc_blocks_at(22.5, 22.5) is False   # inside image, off shape


# -- touch vs blocking split -------------------------------------------------

def test_touch_uses_the_footprint_and_ignores_dontblock():
    # Touch and wall share the footprint, but only wall reads the blocking
    # flag: a dontblock'ed floor trigger still fires playertouchsme.
    npcs = {5: {'x': 10.0, 'y': 10.0, 'image': 'rug.png',
                'dontblock': True,
                'script': 'if (playertouchsme) { message hi; }'}}
    client, gs1 = _gs1(npcs, image_size=(32, 32))
    assert gs1.npc_blocks_at(10.5, 10.5) is False
    handler = NPCHandler(client)
    handler.gs1 = gs1
    handler.update_npcs()
    assert 5 in handler.npc_shapes
    # player sprite at (8.5, 8.0) facing down: touchtestd down probes land at
    # (10.45, 11.5) / (9.55, 11.5) — inside the rug's 2x2 rect.
    assert handler.check_touch(8.5, 8.0, 2) == [5]


def test_touch_say_sign_talks_from_flush_below():
    # GTA's touch-say signs: image NPC, no setshape — walking up into it
    # must fire playertouchsme. Player flush below a 2x2 sign at (10, 10):
    # sprite y = 10.0 puts the box top (y+1) at the sign's bottom edge; the
    # up probes (y+0.5) land at 10.5, inside the sign.
    npcs = {5: {'x': 10.0, 'y': 10.0, 'image': 'sign.png',
                'script': 'if (playertouchsme) { say2 Hello; }'}}
    client, gs1 = _gs1(npcs, image_size=(32, 32))
    handler = NPCHandler(client)
    handler.gs1 = gs1
    fired = []
    handler.on_playertouchsme = lambda npc_id, npc: fired.append(npc_id)
    handler.process_movement(9.5, 10.0, 0)
    assert fired == [5]
    # facing away (down) from the same spot: no touch
    handler.touched_npcs = set()
    fired.clear()
    handler.process_movement(9.5, 10.0, 2)
    assert fired == []


# -- timeout = 0 cancels (GS1) -----------------------------------------------

def test_gs1_npc_timeout_zero_cancels():
    script = ("if (playerenters) { timeout = 0.05; }\n"
              "if (timeout) { this.fires = this.fires + 1; timeout = 0; }")
    npcs = {5: {'x': 10.0, 'y': 10.0, 'script': script}}
    _c, gs1 = _gs1(npcs)
    gs1.load_script("npc_5", script, npc_id=5)
    gs1.trigger_event("playerenters")
    assert npcs[5]['_timeout'] == pytest.approx(0.05)

    gs1.process_timeouts(0.06)      # fires once, then timeout = 0 cancels
    this = gs1._progs["npc_5"]["scopes"]["this"]
    assert this["fires"] == 1.0
    assert npcs[5]['_timeout'] is None

    for _ in range(5):              # a cancelled timer must never re-fire
        gs1.process_timeouts(1.0)
    assert this["fires"] == 1.0


def test_gs1_npc_negative_timeout_also_cancels():
    npcs = {5: {'x': 10.0, 'y': 10.0, 'script': ''}}
    _c, gs1 = _gs1(npcs)
    script = "if (playerenters) { timeout = -1; }"
    npcs[5]['script'] = script
    gs1.load_script("npc_5", script, npc_id=5)
    npcs[5]['_timeout'] = 3.0       # pending
    gs1.trigger_event("playerenters")
    assert npcs[5]['_timeout'] is None


def test_gs1_weapon_timeout_zero_cancels():
    script = ("if (created) { timeout = 0.05; }\n"
              "if (timeout) { this.fires = this.fires + 1; timeout = 0; }")
    _c, gs1 = _gs1({})
    gs1.load_weapon("-t", script)
    gs1.trigger_event("created", name="weapon_-t")
    assert gs1._weapon_timeouts["weapon_-t"] == pytest.approx(0.05)

    gs1.process_timeouts(0.06)
    this = gs1._progs["weapon_-t"]["scopes"]["this"]
    assert this["fires"] == 1.0
    assert "weapon_-t" not in gs1._weapon_timeouts

    for _ in range(5):
        gs1.process_timeouts(1.0)
    assert this["fires"] == 1.0


# -- timeout = 0 cancels (GS2) -----------------------------------------------

def test_gs2_timeout_zero_cancels():
    from reborn_protocol.gs2 import GS2Container
    from pyreborn.gs2_client import ClientGS2

    rt2 = ClientGS2()
    vm = rt2.load_bytecode("weapon", "w", GS2Container())
    key = rt2._timeout_key(vm)

    vm.this.set("timeout", 0.5)
    assert rt2._timeouts[key] == pytest.approx(0.5)
    vm.this.set("timeout", 0.0)
    assert key not in rt2._timeouts       # cancelled, not armed-at-zero

    # settimer(0) builtin takes the same path
    rt2.host._call_bare_builtin(vm, "settimer", [0.5])
    assert rt2._timeouts[key] == pytest.approx(0.5)
    rt2.host._call_bare_builtin(vm, "settimer", [0.0])
    assert key not in rt2._timeouts


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
