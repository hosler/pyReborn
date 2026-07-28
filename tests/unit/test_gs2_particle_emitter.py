"""The findimg(i).emitter particle surface (pyreborn/particles.py).

Shaped from the reference client (FourPlay quattroplay/src/TShowImg.cpp,
TParticleEmitter.cpp, TParticleModifier.cpp, TParticleData.cpp,
TParticleEmitterProperties.cpp, TInitStatics.cpp:4744-4746) against the three
corpus acceptance references:

- Preagonal/graal-gta/world/ganis/global_aura.gani (aura: template tinting,
  once/movex spread, removeparticles/removemodifiers),
- GServer-v2/bin/servers/eradev2/scripts/particle_smoke.txt (era new-GS1
  with-blocks, particles[0..1] via particletypes),
- GServer-v2/bin/servers/eradev2/world/levels/world/staff/era_hachitest.nw
  (`with (addlocalmodifier(...)) { addmod(...) }`) and era_partyhouse.nw:25
  (empty-modtype reject path).
"""
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import math

from reborn_protocol.gs2 import GS2_NULL, GS2Object

from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2, GS2ClientHost, _LayerImage
from pyreborn.particles import (
    EMITTER_METHOD_NAMES, ParticleEmitter, ParticleModifier, ParticleTemplate,
)


def call(rt, name, args=(), obj=None, vm=None):
    return rt.host.call_builtin(vm, name, list(args), obj=obj)


def _client(**over):
    base = dict(
        player=SimpleNamespace(x=30.0, y=30.0, account="me", nickname="Me",
                               id=1, direction=2, gani="idle",
                               colors=[1, 2, 3, 4, 5], gattribs={}),
        players={}, x=30.0, y=30.0, npcs={}, weapons={}, server_name="probe",
        connected=False, _current_level_name="a.nw", tiles=[0] * 4096)
    base.update(over)
    return SimpleNamespace(**base)


def _rt(**over):
    client = _client(**over)
    return ClientGS2(client, ClientGS1(client))


#: TParticleEmitterProperties::propDefs[0x1c] (:5-256), minus the four
#: object-typed / two counter entries asserted separately below.
WRITABLE_PROPS = (
    "attachposition", "autorotation", "checkbelowterrain", "clippingbox",
    "cliptoscreen", "continueafterdestroy", "delaymax", "delaymin",
    "emissionoffset", "emitatterrainheight", "emitautomatically",
    "firstinfront", "forceaboveterrain", "isfrozen", "maxparticles",
    "movementfactor", "noclipping", "nrofparticles", "particletypes",
    "showonground", "showontop", "switchyandzaxis", "wraptoclippingbox",
)


def test_findimg_emitter_is_lazy_and_identity_stable():
    """TShowImg::getParticleEmitter allocates on first read and caches
    (TShowImg.cpp:180-185); findimg(i) itself must materialize the layer --
    era_partyhouse.nw:495 runs `hideimg(200); with (findimg(200)) {...}`."""
    rt = _rt()
    image = call(rt, "findimg", [200])
    assert isinstance(image, _LayerImage)
    assert call(rt, "findimg", [200]) is image
    emitter = image.get("emitter")
    assert isinstance(emitter, ParticleEmitter)
    assert image.get("emitter") is emitter
    # read-only prop: the write is ignored (TShowImgProperties.cpp:495-498)
    image.set("emitter", 5)
    assert image.get("emitter") is emitter


def test_with_block_resolution_reaches_emitter_via_real_vm():
    """The GS2 VM's with-stack resolution is has()-gated (GS2VM._lookup /
    _assign_name): a computed property get() answers but has() does not
    claim is INVISIBLE inside `with (...) {}` -- a bare `emitter` read
    inside `with (findimg(i))` answered None and
    `with (<emitter>) { nrofparticles = 50; }` wrote a VM global, so the
    emitter never emitted.  Drives the real VM resolution path."""
    from reborn_protocol.gs2 import GS2VM
    from reborn_protocol.gs2.container import GS2Container
    from reborn_protocol.gs2.vm import _Frame

    rt = _rt()
    image = call(rt, "findimg", [200])
    vm = GS2VM(GS2Container())
    frame = _Frame(0, [])

    # with (findimg(200)) { ... }: bare `emitter` resolves to the layer's
    # emitter, bare `x = ...` writes the layer record (not a VM global)
    frame.with_stack.append(image)
    emitter = vm._lookup("emitter", frame)
    assert isinstance(emitter, ParticleEmitter)
    assert emitter is image.get("emitter")
    vm._assign_name("x", 12.0, frame)
    assert image._rec["x"] == 12.0
    assert "x" not in vm.globals

    # with (<emitter>) { nrofparticles = 50; }: the write lands on the
    # emitter (clamped setter), not on VM globals, and actually emits
    frame.with_stack.append(emitter)
    vm._assign_name("nrofparticles", 50, frame)
    assert "nrofparticles" not in vm.globals
    assert emitter.get("nrofparticles") == 50.0
    assert vm._lookup("nrofparticles", frame) == 50.0
    assert vm._lookup("particles", frame) is emitter.get("particles")
    emitter.emit_now()
    assert len(emitter.particles) == 50

    # with (emitter.particle) { image = ...; }: template computed names too
    frame.with_stack.append(emitter.get("particle"))
    vm._assign_name("image", "smoke3.png", frame)
    assert emitter.get("particle").get("image") == "smoke3.png"
    assert "image" not in vm.globals
    assert vm._lookup("movementvector", frame) == [1.0, 0.0, 0.0]


def test_every_property_in_the_oracle_table_is_claimed():
    """Existence-gating: an unclaimed name makes construction writes vanish
    and reads answer 0.0 -- every propDefs name must round-trip."""
    emitter = ParticleEmitter({})
    for name in WRITABLE_PROPS:
        assert emitter.get(name) is not None, name
    emitter.set("delaymin", 0.1)
    emitter.set("delaymax", 0.3)
    emitter.set("nrofparticles", 2)
    emitter.set("emissionoffset", [-2.5, -2.5, 0])
    emitter.set("attachposition", 1)
    assert emitter.get("delaymin") == 0.1
    assert emitter.get("delaymax") == 0.3
    assert emitter.get("nrofparticles") == 2.0
    assert emitter.get("emissionoffset") == [-2.5, -2.5, 0.0]
    assert emitter.get("attachposition") == 1.0
    # constructor defaults (TParticleEmitter.cpp:37-110)
    assert emitter.get("emitautomatically") == 1.0
    assert emitter.get("firstinfront") == 1.0
    assert emitter.get("maxparticles") == 100000.0
    # counters read back, writes ignored (nullptr setters)
    assert emitter.get("currentparticlecount") == 0.0
    assert emitter.get("emittedparticles") == 0.0
    emitter.set("currentparticlecount", 99)
    assert emitter.get("currentparticlecount") == 0.0
    # setter clamps (TParticleEmitter.cpp:122-138)
    emitter.set("nrofparticles", 5000)
    assert emitter.get("nrofparticles") == 1000.0
    emitter.set("maxparticles", -1)
    assert emitter.get("maxparticles") == 0.0


def test_particle_template_and_particles_array():
    """`particle` is particles[0]; `particletypes` resizes the template array
    copying template 0 (TParticleEmitter.cpp:79-90, :149-225).  Unwritten
    string props answer STRINGS (the strtofloat mis-branch hazard)."""
    emitter = ParticleEmitter({})
    particle = emitter.get("particle")
    assert isinstance(particle, ParticleTemplate)
    assert emitter.get("particles")[0] is particle
    assert particle.get("image") == ""          # unwritten string reads ""
    assert particle.get("zoom") == 1.0
    assert particle.get("alpha") == 1.0
    particle.set("image", "smoke3.png")
    particle.set("lifetime", 4)
    particle.set("zoom", 2)
    emitter.set("particletypes", 2)
    templates = emitter.get("particles")
    assert len(templates) == 2 and emitter.get("particletypes") == 2.0
    # the grown slot copies template 0 (particle_smoke then overrides image)
    assert templates[1].get("image") == "smoke3.png"
    templates[1].set("image", "smoke4.png")
    assert templates[0].get("image") == "smoke3.png"
    emitter.set("particletypes", 0)             # clamps to 1
    assert len(emitter.get("particles")) == 1


def test_template_movement_fields_stay_coupled():
    """speed/angle/zangle/movementvector are one coupled state
    (TParticleData.cpp:91-153): zangle pi/2 sends the whole speed to +z."""
    tpl = ParticleTemplate()
    assert tpl.get("speed") == 1.0              # clear() default vector (1,0,0)
    tpl.set("zangle", 3)                        # clamps to pi/2
    assert abs(tpl.get("zangle") - math.pi / 2) < 1e-6
    tpl.set("speed", 2)
    vx, vy, vz = tpl.get("movementvector")
    assert abs(vz - 2.0) < 1e-6 and abs(vx) < 1e-6 and abs(vy) < 1e-6
    tpl.set("speed", 0)
    assert tpl.get("speed") == 0.0


def test_addlocalmodifier_validates_against_the_three_name_tables():
    """addXmodifier(modtype, t0, t1, var, mode, v0, v1): unknown modtype ->
    null, nothing added; unknown var/mode -> modifier kept, var effect
    silently skipped (TParticleEmitter.cpp:227-240, TParticleModifier
    .cpp:37-59). Lookups are case-insensitive."""
    rt = _rt()
    emitter = call(rt, "findimg", [1]).get("emitter")
    mod = call(rt, "addlocalmodifier", ["once", 0, 0, "movex", "add", -2, 2],
               obj=emitter)
    assert isinstance(mod, ParticleModifier)
    assert len(mod.var_mods) == 1 and len(emitter.local_modifiers) == 1
    assert call(rt, "addlocalmodifier",
                ["ONCE", 0, 0, "MoveY", "Add", -2, 2], obj=emitter
                ) in emitter.local_modifiers
    # unknown modtype: null, list unchanged
    assert call(rt, "addlocalmodifier",
                ["bogus", 0, 0, "movex", "add", -2, 2], obj=emitter) is GS2_NULL
    assert len(emitter.local_modifiers) == 2
    # era_partyhouse.nw:25 -- addglobalmodifier("", 0, 1, "", "", -0.5, 0.5):
    # the EMPTY modtype misses the table too, so nothing is added
    assert call(rt, "addglobalmodifier", ["", 0, 1, "", "", -0.5, 0.5],
                obj=emitter) is GS2_NULL
    assert emitter.global_modifiers == []
    # valid modtype + unknown varname: modifier exists, zero var effects
    empty = call(rt, "addglobalmodifier", ["range", 0, 1, "", "", -0.5, 0.5],
                 obj=emitter)
    assert isinstance(empty, ParticleModifier) and empty.var_mods == []
    # bad mode name, valid varname: same silent skip
    skipped = call(rt, "addemitmodifier",
                   ["impulse", 0, 0, "alpha", "wibble", 0, 1], obj=emitter)
    assert isinstance(skipped, ParticleModifier) and skipped.var_mods == []
    assert emitter.template_modifiers == [skipped]


def test_modifier_addmod_appends_var_effects():
    """era_hachitest.nw:164: `with (emitter.addlocalmodifier("impulse",1,2,
    "spin","add",-20,-30)) { addmod("zangle","add",0.1,0.5); }` -- addmod is
    the modifier object's one funcDef (TParticleModifierProperties.cpp)."""
    rt = _rt()
    emitter = call(rt, "findimg", [1]).get("emitter")
    mod = call(rt, "addlocalmodifier",
               ["impulse", 1, 2, "spin", "add", -20, -30], obj=emitter)
    assert call(rt, "addmod", ["zangle", "add", 0.1, 0.5], obj=mod) == 0.0
    assert len(mod.var_mods) == 2
    assert [v.type_index for v in mod.var_mods] == [10, 7]  # spin, zangle
    call(rt, "addmod", ["nosuchvar", "add", 0, 1], obj=mod)
    assert len(mod.var_mods) == 2                           # silent skip


def test_template_seeds_spawned_particles_and_once_modifier_applies():
    """global_aura.gani: template rgba/mode/lifetime propagate to every
    emitted particle; the once/movex modifier lands a uniform value in
    [-2, 2] on the movement vector."""
    emitter = ParticleEmitter({"x": 10.0, "y": 12.0})
    emitter.set("delaymin", 0)
    emitter.set("delaymax", 0)
    emitter.set("nrofparticles", 2)
    particle = emitter.get("particle")
    particle.set("lifetime", 1.5)
    particle.set("image", "light2.png")
    particle.set("zoom", 0.2)
    particle.set("alpha", 0.9)
    particle.set("speed", 0)
    particle.set("red", 0.25)
    particle.set("green", 0.5)
    particle.set("blue", 1.0)
    particle.set("mode", 2)
    emitter.add_local_modifier(["once", 0, 0, "movex", "add", -2, 2])
    emitter.advance(0.05)
    emitter.advance(0.05)
    assert len(emitter.particles) == 2
    for p in emitter.particles:
        assert p.image == "light2.png"
        assert p.zoom == 0.2 and p.alpha == 0.9
        assert (p.red, p.green, p.blue) == (0.25, 0.5, 1.0)
        assert p.mode == 2.0
        assert p.lifetime == 1.5
        assert -2.0 <= p.vx <= 2.0      # speed 0 + once movex add [-2, 2]
        assert abs(p.x - 10.0) < 2.5 and abs(p.y - 12.0) < 2.5


def test_lifetime_expiry_and_counters():
    emitter = ParticleEmitter({})
    emitter.set("delaymin", 0)
    emitter.set("delaymax", 0)
    emitter.set("nrofparticles", 3)
    emitter.get("particle").set("lifetime", 0.2)
    emitter.get("particle").set("image", "x.png")
    emitter.advance(0.05)   # arms the clock
    emitter.advance(0.05)   # first emission
    assert emitter.get("currentparticlecount") == 3.0
    assert emitter.get("emittedparticles") == 3.0
    emitter.set("emitautomatically", 0)
    for _ in range(6):
        emitter.advance(0.05)
    assert emitter.get("currentparticlecount") == 0.0   # all expired
    assert emitter.get("emittedparticles") == 3.0       # total is cumulative


def test_removemodifiers_drops_all_three_lists_and_the_particles():
    """TParticleEmitter::removeModifiers (:272-281) deletes template+global+
    local AND calls removeParticles; removeparticles only zeroes the live
    set."""
    rt = _rt()
    emitter = call(rt, "findimg", [1]).get("emitter")
    emitter.set("nrofparticles", 4)
    call(rt, "addlocalmodifier", ["once", 0, 0, "x", "add", 0, 1], obj=emitter)
    call(rt, "addglobalmodifier", ["impulse", 0.2, 0.2, "spin", "multiply",
                                   0.6, 0.6], obj=emitter)
    call(rt, "addemitmodifier", ["range", 0, 1, "alpha", "add", 0, 1],
         obj=emitter)
    call(rt, "emit", [], obj=emitter)
    assert emitter.get("currentparticlecount") == 4.0
    call(rt, "removeparticles", [], obj=emitter)
    assert emitter.get("currentparticlecount") == 0.0
    assert len(emitter.local_modifiers) == 1
    call(rt, "emit", [], obj=emitter)
    call(rt, "removemodifiers", [], obj=emitter)
    assert emitter.local_modifiers == []
    assert emitter.global_modifiers == []
    assert emitter.template_modifiers == []
    assert emitter.get("currentparticlecount") == 0.0


def test_emit_and_emitat_and_advancetime_via_host_dispatch():
    rt = _rt()
    emitter = call(rt, "findimg", [7]).get("emitter")
    emitter.set("emitautomatically", 0)
    emitter.set("nrofparticles", 1)
    emitter.get("particle").set("lifetime", 10)
    call(rt, "emit", [], obj=emitter)
    call(rt, "emitat", [[3, 4, 0]], obj=emitter)
    call(rt, "emitat", ["5,6"], obj=emitter)    # 's' arg: CSV coordinate list
    assert emitter.get("currentparticlecount") == 3.0
    xs = sorted(round(p.x, 3) for p in emitter.particles)
    assert xs == [0.0, 3.0, 5.0]
    call(rt, "advancetime", [0.5], obj=emitter)
    assert emitter.get("currentparticlecount") == 3.0


def test_range_modifier_activates_only_inside_its_window():
    """era_hachitest's `range 0..100000 speed add 3 3`: dt-scaled add inside
    the window (TParticleModifier.cpp:104-142)."""
    emitter = ParticleEmitter({})
    emitter.set("emitautomatically", 0)
    emitter.set("nrofparticles", 1)
    particle = emitter.get("particle")
    particle.set("lifetime", 100)
    particle.set("speed", 1)        # heading +x
    emitter.add_local_modifier(["range", 2, 100000, "speed", "add", 3, 3])
    emitter.emit_now()
    p = emitter.particles[0]
    emitter.advance(1.0)
    assert abs(p.speed - 1.0) < 1e-6            # before the window
    emitter.advance(1.5)                        # now inside [2, ...]
    assert p.speed > 1.0


def test_global_impulse_reschedules_a_shared_timer():
    emitter = ParticleEmitter({})
    emitter.set("emitautomatically", 0)
    emitter.set("nrofparticles", 2)
    particle = emitter.get("particle")
    particle.set("lifetime", 100)
    particle.set("zangle", 0.4)
    mod = emitter.add_global_modifier(
        ["impulse", 0.2, 0.2, "zangle", "multiply", 0.95, 0.95])
    emitter.emit_now()
    zangle0 = emitter.particles[0].zangle
    emitter.advance(0.05)
    assert emitter.particles[0].zangle < zangle0    # fired (timer began at 0)
    assert mod.user_time > 0.0                      # rescheduled ~0.2s out


def test_dropemitter_is_lazily_created_and_manual():
    """TParticleEmitter.cpp:377-393: created on first read, never emits
    automatically; an expiring particle feeds it."""
    emitter = ParticleEmitter({})
    sub = emitter.get("dropemitter")
    assert isinstance(sub, ParticleEmitter) and sub is emitter.get("dropemitter")
    assert sub.get("emitautomatically") == 0.0
    sub.set("nrofparticles", 1)
    sub.get("particle").set("lifetime", 5)
    emitter.set("emitautomatically", 0)
    emitter.set("nrofparticles", 1)
    emitter.get("particle").set("lifetime", 0.1)
    emitter.emit_now()
    for _ in range(4):
        emitter.advance(0.05)
    assert emitter.get("currentparticlecount") == 0.0
    assert sub.get("currentparticlecount") == 1.0


def test_host_surface_reports_the_emitter_and_modifier_methods():
    surface = GS2ClientHost.host_surface()
    for name in sorted(EMITTER_METHOD_NAMES) + ["addmod"]:
        assert name in surface, name


def test_frozen_emitter_does_not_advance():
    emitter = ParticleEmitter({})
    emitter.set("delaymin", 0)
    emitter.set("delaymax", 0)
    emitter.set("nrofparticles", 1)
    emitter.get("particle").set("lifetime", 5)
    emitter.set("isfrozen", 1)
    for _ in range(5):
        emitter.advance(0.05)
    assert emitter.get("currentparticlecount") == 0.0
    emitter.set("isfrozen", 0)
    emitter.advance(0.05)
    emitter.advance(0.05)
    assert emitter.get("currentparticlecount") == 1.0


# --- renderer: particles actually blit ---------------------------------------
# (_render_npc_layers wraps layer draws in `except Exception: pass`, so a
# broken emitter renderer would silently draw nothing -- pin the pixels)

import pygame

from pyreborn.game.render_effects import EffectsRenderMixin
from pyreborn.game.render_entities import EntityRenderMixin

pygame.init()

_WHITE = (255, 255, 255, 255)
_BLACK = (0, 0, 0, 255)


class _RenderHarness(EntityRenderMixin, EffectsRenderMixin):
    """Minimal GameClient stand-in exercising the layer + emitter slice."""

    def __init__(self, sheet):
        self.screen = pygame.Surface((200, 200))
        self.screen.fill((0, 0, 0))
        self.camera = SimpleNamespace(
            scale=16.0, world_to_screen=lambda x, y: (x * 16.0, y * 16.0))
        self.sprite_mgr = SimpleNamespace(
            load_sheet=lambda name: sheet,
            get_sprite=lambda name, *part: sheet)
        self.requested = []

    def _request_asset(self, name):
        self.requested.append(name)


def _white_sheet():
    surf = pygame.Surface((8, 8), pygame.SRCALPHA)
    surf.fill(_WHITE)
    return surf


def _emitter_rec(**extra):
    rec = {'x': 50.0, 'y': 50.0, 'vis': 4, 'vis_set': True}
    rec.update(extra)
    emitter = ParticleEmitter(rec)
    emitter.set('emitautomatically', 0)
    emitter.set('nrofparticles', 1)
    emitter.get('particle').set('lifetime', 10)
    emitter.get('particle').set('image', 'dot.png')
    rec['emitter'] = emitter
    return rec, emitter


def test_render_layer_emitter_blits_particles():
    h = _RenderHarness(_white_sheet())
    rec, emitter = _emitter_rec()
    emitter.emit_now()          # one particle at the rec position
    emitter.emit_now(position=(60.0, 60.0, 0.0))
    h._render_npc_layers({1: rec}, over=True, gui=True)
    # GUI band: pixel coords; 8x8 sprites at (50,50) and (60,60)
    assert h.screen.get_at((53, 53)) == _WHITE
    assert h.screen.get_at((63, 63)) == _WHITE
    assert h.screen.get_at((90, 90)) == _BLACK


def test_render_layer_emitter_z_draws_upward_and_alpha_tints():
    h = _RenderHarness(_white_sheet())
    rec, emitter = _emitter_rec()
    emitter.emit_now(position=(50.0, 80.0, 20.0))   # z lifts the draw: y - z
    p = emitter.particles[0]
    p.alpha = 0.5
    h._render_npc_layers({1: rec}, over=True, gui=True)
    px = h.screen.get_at((53, 63))                  # 80 - 20 = 60
    assert px != _BLACK and px[0] < 255             # alpha-attenuated
    assert h.screen.get_at((53, 83)) == _BLACK      # not at raw y


def test_render_layer_emitter_additive_mode():
    h = _RenderHarness(_white_sheet())
    rec, emitter = _emitter_rec()
    emitter.get('particle').set('mode', 2)
    emitter.get('particle').set('red', 1)
    emitter.get('particle').set('green', 0)
    emitter.get('particle').set('blue', 0)
    emitter.emit_now()
    h._render_npc_layers({1: rec}, over=True, gui=True)
    px = h.screen.get_at((53, 53))
    assert px[0] > 128 and px[1] == 0 and px[2] == 0    # red added onto black


def test_render_missing_particle_image_requests_the_asset():
    h = _RenderHarness(None)    # load_sheet answers None
    h.sprite_mgr = SimpleNamespace(load_sheet=lambda name: None,
                                   get_sprite=lambda name, *part: None)
    rec, emitter = _emitter_rec()
    emitter.emit_now()
    h._render_npc_layers({1: rec}, over=True, gui=True)
    assert 'dot.png' in h.requested


# --- era new-GS1 reachability (the same emitter through the GS1 engine) ------

def _gs1_with_client():
    from pyreborn import Client
    client = Client("localhost", 14900)
    gs1 = ClientGS1(client)
    return client, gs1


def test_gs1_with_findimg_reaches_the_shared_emitter():
    """particle_smoke.txt:14-63 shape: `with (findimg(200)) { with (emitter)
    { delaymin = 0.1; ... addlocalmodifier(...); } }` running in the era
    new-GS1 engine must configure the SAME emitter object the GS2 side and
    the renderer see."""
    client, gs1 = _gs1_with_client()
    client.npcs[9] = {"x": 5.0, "y": 5.0}
    script = """function onCreated() {
  with (findimg(200)) {
    layer = 2;
    with (emitter) {
      delaymin = 0.1;
      delaymax = 0.3;
      nrofparticles = 1;
      particletypes = 2;
      continueafterdestroy = 1;
      addlocalmodifier("once", 0, 0, "red", "replace", 0.2, 0.3);
      addlocalmodifier("bogus", 0, 0, "x", "add", 0, 1);
    }
  }
}"""
    gs1.load_script("npc_9", script, npc_id=9, x=5, y=5)
    gs1.trigger_npc_event(9, "created")
    imgs = client.npcs[9].get("imgs")
    assert imgs and 200 in imgs
    rec = imgs[200]
    assert rec.get("vis") == 2
    emitter = rec.get("emitter")
    assert isinstance(emitter, ParticleEmitter)
    assert emitter.get("delaymin") == 0.1
    assert emitter.get("delaymax") == 0.3
    assert emitter.get("nrofparticles") == 1.0
    assert emitter.get("continueafterdestroy") == 1.0
    assert len(emitter.get("particles")) == 2
    assert len(emitter.local_modifiers) == 1        # bogus modtype rejected
    # the GS2 side resolves the SAME record + emitter (find_image and the
    # GS1 findimg share layer_image_get over the one store; a GS2 npc VM
    # reaches this table via _gs1_ctx's this_obj)
    from pyreborn.gs2_client import layer_image_get
    image = layer_image_get(imgs, 200)
    assert image._rec is rec and image.get("emitter") is emitter


def test_gs1_with_particles_index_and_dotted_member_writes():
    client, gs1 = _gs1_with_client()
    client.npcs[3] = {"x": 1.0, "y": 1.0}
    script = """function onCreated() {
  with (findimg(201)) {
    with (emitter) {
      particletypes = 2;
      with (particles[1]) {
        lifetime = 4;
        image = "smoke4.png";
      }
    }
    emitter.particle.image = "smoke3.png";
    emitter.particle.lifetime = 2;
  }
}"""
    gs1.load_script("npc_3", script, npc_id=3, x=1, y=1)
    gs1.trigger_npc_event(3, "created")
    emitter = client.npcs[3]["imgs"][201]["emitter"]
    templates = emitter.get("particles")
    assert templates[1].get("image") == "smoke4.png"
    assert templates[1].get("lifetime") == 4.0
    assert templates[0].get("image") == "smoke3.png"
    assert templates[0].get("lifetime") == 2.0


def test_gs1_advance_layer_emitters_steps_the_simulation():
    client, gs1 = _gs1_with_client()
    client.npcs[4] = {"x": 2.0, "y": 2.0}
    script = """function onCreated() {
  with (findimg(202)) {
    with (emitter) {
      delaymin = 0;
      delaymax = 0;
      nrofparticles = 2;
    }
    emitter.particle.lifetime = 3;
    emitter.particle.image = "light2.png";
  }
}"""
    gs1.load_script("npc_4", script, npc_id=4, x=2, y=2)
    gs1.trigger_npc_event(4, "created")
    for _ in range(3):
        gs1.process_timeouts(0.05)
    emitter = client.npcs[4]["imgs"][202]["emitter"]
    assert emitter.get("currentparticlecount") > 0.0
