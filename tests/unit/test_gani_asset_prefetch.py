from pyreborn.gani import Gani, GaniFrame, GaniSprite
from pyreborn.game.render_entities import EntityRenderMixin


class _Harness(EntityRenderMixin):
    def __init__(self):
        self.requested = []

    def _request_asset(self, filename):
        self.requested.append(filename)


def _gani(directions):
    return Gani(
        name="prefetch_test",
        defaults={
            "BODY": "body.png",
            "HEAD": "head.gif",
            "ATTR1": "hat.bmp",
            "SPRITES": "sprites.png",
            "CAPE": "cape.png",
            "SWORD": "sword1.png",
            "PARAM1": "3",
            "PARAM2": "4",
            "PARAM3": "1.5",
        },
        sprites={
            0: GaniSprite(0, "SPRITES", 0, 0, 24, 16),
            1: GaniSprite(1, "SIGN1.GIF", 0, 0, 32, 32),
            2: GaniSprite(2, None, 0, 0, 1, 1),
            3: GaniSprite(3, "BODY", 0, 0, 48, 48),
            4: GaniSprite(4, "HEAD", 0, 0, 32, 32),
            5: GaniSprite(5, "CAPE", 0, 0, 32, 32),
            6: GaniSprite(6, "SWORD", 0, 0, 32, 32),
        },
        directions=directions,
    )


def test_prefetch_requests_only_sheets_frames_draw():
    gani = _gani([
        [GaniFrame(sprites=[(0, 0, 0), (1, 0, 0), (2, 0, 0), ("PARAM1", 0, 0)])],
        [GaniFrame(sprites=[("PARAM2", 0, 0), ("PARAM3", 0, 0)])],
    ])
    harness = _Harness()

    harness._prefetch_gani_assets(gani)

    assert set(harness.requested) == {
        "sprites.png", "sign1.gif", "body.png", "head.gif",
    }
    # CAPE/SWORD sprites are defined but never placed by a frame, and ATTR1
    # has no sprite at all -- requesting those is what produced server refusals.
    assert "cape.png" not in harness.requested
    assert "sword1.png" not in harness.requested
    assert "hat.bmp" not in harness.requested
    # PARAM3's default is not a sprite id, and sprite 2 has no layer.
    assert "1.5" not in harness.requested

    first_requests = list(harness.requested)
    harness._prefetch_gani_assets(gani)
    assert harness.requested == first_requests


def test_prefetch_requests_nothing_when_no_frame_places_a_sprite():
    harness = _Harness()

    harness._prefetch_gani_assets(_gani([]))

    assert harness.requested == []
