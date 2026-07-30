from pyreborn.gani import Gani, GaniSprite
from pyreborn.game.render_entities import EntityRenderMixin


class _Harness(EntityRenderMixin):
    def __init__(self):
        self.requested = []

    def _request_asset(self, filename):
        self.requested.append(filename)


def test_prefetch_requests_static_filenames_once_and_skips_params():
    gani = Gani(
        name="prefetch_test",
        defaults={
            "BODY": "body.png",
            "HEAD": "head.gif",
            "ATTR1": "hat.bmp",
            "SPRITES": "sprites.png",
            "PARAM1": "1.5",
            "PARAM2": "sheet.png",
            "SWORD": 17,
        },
        sprites={
            0: GaniSprite(0, "SPRITES", 0, 0, 24, 16),
            1: GaniSprite(1, "SIGN1.GIF", 0, 0, 32, 32),
            2: GaniSprite(2, None, 0, 0, 1, 1),
        },
    )
    harness = _Harness()

    harness._prefetch_gani_assets(gani)

    assert set(harness.requested) == {
        "body.png", "head.gif", "hat.bmp", "sprites.png", "sign1.gif",
    }
    assert "1.5" not in harness.requested
    assert "sheet.png" not in harness.requested

    first_requests = list(harness.requested)
    harness._prefetch_gani_assets(gani)
    assert harness.requested == first_requests
