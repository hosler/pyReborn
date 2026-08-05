from types import SimpleNamespace

import pygame

from reborn_protocol.gs2 import GS2Object
from pyreborn.game.camera import Camera2D
from pyreborn.gs2_client import ClientGS2


def call(rt, name, args=()):
    return rt.host.call_builtin(None, name, list(args))


def test_mouse_transform_uses_live_camera_and_viewport(monkeypatch):
    rt = ClientGS2(SimpleNamespace(player=SimpleNamespace(x=0, y=0)))
    camera = Camera2D(640, 480)
    camera.set_center(20, 10)
    viewport = SimpleNamespace(mouse_pos=lambda: (320, 240), _scale_x=1.5)
    rt.game_shell = SimpleNamespace(camera=camera, viewport=viewport)
    assert rt.host.get_object("mousex") == 20
    assert rt.host.get_object("mousey") == 10
    assert rt.host.get_object("mousescreenx") == 320
    assert rt.host.get_object("screenpixelscale") == 1.5


def test_shot_attribution_is_scoped_to_wasshot_callback(monkeypatch):
    rt = ClientGS2()
    observed = []
    monkeypatch.setattr(rt, "trigger_npc_event", lambda *args: observed.append(
        (rt.host.get_object("wasshooted"), rt.host.get_object("shotbyplayer"))) or True)
    rt._executing_vm = object()
    assert rt.trigger_npc_wasshot(1, True)
    assert observed == [(True, True)]
    assert rt._shot_attribution is None


def test_reference_key_table_and_format2_edges():
    rt = ClientGS2()
    assert call(rt, "getkeycode", ["Left"]) == 37
    assert call(rt, "keyname2", [37]) == "Left"
    assert call(rt, "keyname2", [65]) == "A"
    assert call(rt, "format2", ["%2$s:%+04d:%.3s:%%", [2.2, "abcdef"]]) == "abcdef:  +2:abc:%"


def test_image_pixel_and_transparency_use_sprite_surface():
    surface = pygame.Surface((2, 2), pygame.SRCALPHA)
    surface.fill((0, 0, 0, 0))
    surface.set_at((1, 0), (255, 128, 0, 255))
    manager = SimpleNamespace(load_sheet=lambda name: surface)
    rt = ClientGS2()
    rt.game_shell = SimpleNamespace(sprite_mgr=manager)
    assert call(rt, "getimgpixel", ["probe.png", 1, 0]) == [1.0, 128 / 255, 0.0]
    assert call(rt, "isimgpixeltransparent", ["probe.png", 0, 0]) == 1.0
    assert call(rt, "isimgrectangletransparent", ["probe.png", 0, 0, 2, 1]) == 0.0


def test_findnpc_and_findlevel_return_persistent_wrappers():
    client = SimpleNamespace(npcs={7: {}}, _current_level_name="Room.nw")
    rt = ClientGS2(client)
    wrapper = GS2Object(name="npc7")
    rt.vms["npc"][7] = SimpleNamespace(this=wrapper)
    assert call(rt, "findnpcbyid", [7]) is wrapper
    assert call(rt, "findlevel", ["room.NW"]) is rt.level_object


def test_gravity_is_writable_engine_state():
    rt = ClientGS2()
    assert rt.host.get_object("gravity") == 2.0
    rt.globals_store["gravity"] = 3.25
    assert rt.host.get_object("gravity") == 3.25
