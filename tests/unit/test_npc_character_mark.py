"""One rule for "this NPC is a character" (the nameplate gate).

The server marks a character with the image "#c#" (GServer-v2 NPC.h:501;
`showcharacter` sends it, GS1Commands.cpp:3192). The client `showcharacter`
and a server "#c#" image set the mark; the client `setimg` / `setimgpart` and
any other non-empty server image clear it; an empty image changes nothing.
`npc_handler.mark_npc_character` is the one place the client's mark changes;
the GS1 commands and the PLO_NPCPROPS handler call it. Packets are written
by hand, not through the codec.
"""

import offline_game as og
from offline_checks import floor_tile, settle
from offline_game import NAMED_NPC
from pyreborn.packets import PacketID


def _gchar(value):
    return bytes((value + 32,))


def _image_prop(npc_id, image):
    # npc id (GINT3), prop 0 (image), one length byte, the name
    return (bytes(((npc_id >> 14) + 32, ((npc_id >> 7) & 0x7F) + 32,
                   (npc_id & 0x7F) + 32))
            + _gchar(0) + _gchar(len(image)) + image.encode())


def _scene(make_game, nickname):
    npc = dict(NAMED_NPC)
    if nickname is None:
        npc.pop("nickname")
    return make_game(tiles=floor_tile, player_xy=(30.0, 30.0), npcs=[npc])


def _run(game, script):
    game.gs1.load_script("npc_103", script, npc_id=103, x=28, y=34)
    game.gs1.trigger_npc_event(103, "created")


def _plate_drawn(make_game, act):
    """True when the named NPC's frame differs from its unnamed twin's."""
    named, plain = _scene(make_game, "x"), _scene(make_game, None)
    for game in (named, plain):
        act(game)
        game.frames(4)
    return og.changed_pixels(named, plain) > 0


def test_a_character_npc_has_a_plate(make_game):
    # Mutation: skip the plate in _render_npc -> this baseline goes False.
    assert _plate_drawn(make_game, lambda game: None)


def test_setimg_clears_the_mark_and_the_plate(make_game):
    # Mutation: drop mark_npc_character(npc, False) from _cmd_setimg -> the
    # plate stays, `is_character` stays True.
    def act(game):
        _run(game, "if (created) { showcharacter; setimg pics1.png; }")
        assert not game.client.npcs[103].get("is_character")
    assert not _plate_drawn(make_game, act)


def test_setimgpart_clears_the_mark(make_game):
    # Mutation: drop mark_npc_character(npc, False) from _cmd_setimgpart.
    game = _scene(make_game, "x")
    game.client.npcs[103]["is_character"] = True
    _run(game, "if (created) { setimgpart pics1.png,0,0,32,32; }")
    assert "is_character" not in game.client.npcs[103]


def test_showcharacter_marks_an_image_npc(make_game):
    # Mutation: make the showcharacter command a no-op -> the flag stays unset.
    game = _scene(make_game, "x")
    npc = game.client.npcs[103]
    game.feed(PacketID.PLO_NPCPROPS, _image_prop(103, "pics1.png"))
    assert "is_character" not in npc
    _run(game, "if (created) { showcharacter; }")
    assert npc["is_character"] is True


def test_server_image_prop_clears_the_mark(make_game):
    # Mutation: leave `is_character` alone in the PLO_NPCPROPS handler.
    game = _scene(make_game, "x")
    game.client.npcs[103]["is_character"] = True
    game.feed(PacketID.PLO_NPCPROPS, _image_prop(103, "pics1.png"))
    assert "is_character" not in game.client.npcs[103]
    assert game.client.npcs[103]["image"] == "pics1.png"


def test_server_character_marker_image_sets_the_mark(make_game):
    # A "#c#" image arriving on an image NPC marks it a character.
    # Mutation: pass False instead of `image == CHARACTER_IMAGE` in the
    # PLO_NPCPROPS handler -> the is_character assertion fails.
    game = _scene(make_game, "x")
    npc = game.client.npcs[103]
    game.feed(PacketID.PLO_NPCPROPS, _image_prop(103, "pics1.png"))
    assert "is_character" not in npc
    game.feed(PacketID.PLO_NPCPROPS, _image_prop(103, "#c#"))
    assert npc["is_character"] is True
    assert npc["image"] == "#c#"


def test_real_image_on_a_marker_npc_clears_the_mark(make_game):
    # A real image arriving on a "#c#" NPC clears the mark, so the renderer's
    # image test and the flag agree (it is an image NPC again).
    # Mutation: pass True instead of `image == CHARACTER_IMAGE` in the
    # handler -> the first assertion fails.
    game = _scene(make_game, "x")
    npc = game.client.npcs[103]
    game.feed(PacketID.PLO_NPCPROPS, _image_prop(103, "#c#"))
    assert npc["is_character"] is True
    game.feed(PacketID.PLO_NPCPROPS, _image_prop(103, "pics1.png"))
    assert "is_character" not in npc
    assert npc["image"] == "pics1.png"


def test_empty_server_image_changes_nothing(make_game):
    # An empty image prop neither sets nor clears the mark (the server forces
    # the image prop into every NPC send; an image-less NPC is no character).
    # Mutation: call mark_npc_character on an empty image in the handler ->
    # the "set" assertion fails.
    game = _scene(make_game, "x")
    npc = game.client.npcs[103]
    game.feed(PacketID.PLO_NPCPROPS, _image_prop(103, "pics1.png"))
    game.feed(PacketID.PLO_NPCPROPS, _image_prop(103, ""))
    assert "is_character" not in npc
    npc["is_character"] = True
    game.feed(PacketID.PLO_NPCPROPS, _image_prop(103, ""))
    assert npc["is_character"] is True


def test_deleting_an_npc_drops_its_per_npc_stores(make_game):
    # Mutation: remove `self.npc_visual` from the cache tuple in
    # SetupMixin._on_npc_del (or any one of the other three) -> that store
    # still holds 103.
    game = _scene(make_game, "x")
    game.frames(6)
    stores = {"npc_anims": game.npc_anims, "npc_effects": game.npc_effects,
              "npc_chat_texts": game.npc_chat_texts,
              "npc_visual": game.npc_visual}
    game.npc_chat_texts[103] = "hello"
    game.npc_anims[103] = object()
    game.npc_effects[103] = {}
    game.npc_visual[103] = (1.0, 2.0)
    for name, store in stores.items():
        assert 103 in store, f"{name} never filled"
    game.feed(PacketID.PLO_NPCDEL, bytes((32, 32, 103 + 32)))
    assert 103 not in game.client.npcs
    for name, store in stores.items():
        assert 103 not in store, f"{name} kept the deleted NPC"
