"""Phase 4: a session's end must not leave font files open.

Mutation that fails the assertion: delete the ``attempt("releasing fonts",
self._release_fonts)`` line in GameClient.shutdown (five freesansbold.ttf
descriptors stay open after pygame.quit)."""
import gc
import os


def _open_font_files():
    found = []
    for name in os.listdir("/proc/self/fd"):
        try:
            target = os.readlink(f"/proc/self/fd/{name}")
        except OSError:
            continue
        if target.endswith(".ttf"):
            found.append(target)
    return found


def test_shutdown_leaves_no_font_file_open(make_game):
    gc.collect()
    before = len(_open_font_files())
    game = make_game()
    game.frames(3)
    game.shutdown(remember_window=False)
    gc.collect()
    assert len(_open_font_files()) <= before


def test_inventory_ui_release_fonts_drops_all_three(make_game):
    """Mutation: remove ``self.font_small`` from the assignment in
    InventoryUI.release_fonts; the font_small assertion fails."""
    game = make_game()
    inventory = game.inventory_ui
    assert inventory.font_large and inventory.font_medium and inventory.font_small
    inventory.release_fonts()
    assert inventory.font_large is None
    assert inventory.font_medium is None
    assert inventory.font_small is None
