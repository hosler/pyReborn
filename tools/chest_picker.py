#!/usr/bin/env python3
"""Interactive tileset tile picker.

Pan/zoom the tileset, click tiles to select them, and tag them as the CLOSED or
OPEN chest graphic. Writes the selection (tile ids + row-major grid) to JSON so
the chest sprite can be wired up from real data instead of guessed tile numbers.

Run:
    python tools/chest_picker.py
    python tools/chest_picker.py path/to/tileset.png

Controls:
    Left click            toggle a tile in the active group
    Tab / 1 / 2           switch active group (1=closed, 2=open)
    Mouse wheel           zoom (around cursor)
    Arrow keys / RMB drag pan
    g                     toggle grid lines
    c                     clear active group
    s                     save selection to JSON (also saved on quit)
    h                     toggle help
    Esc / window close    save + quit
"""

import json
import os
import sys

import pygame

TILE = 16
COLS = 128  # tileset is 128 tiles wide (2048px)

# Groups and output are overridable at runtime (--groups a,b,c / --out path).
GROUPS = ("closed", "open")
PALETTE = [(80, 220, 255), (255, 170, 60), (120, 255, 120), (255, 110, 200),
           (255, 240, 90), (160, 160, 255)]
GROUP_COLOR = {g: PALETTE[i % len(PALETTE)] for i, g in enumerate(GROUPS)}

DEFAULT_TILESET = os.path.join(
    os.path.dirname(__file__), "..", "pyreborn", "assets", "dustynewpics1.png")
OUT_PATH = os.path.join(os.path.dirname(__file__), "tile_pick.json")


def tile_id(col, row):
    """Reborn tileset tile id from (col, row). Matches sprites.TilesetManager."""
    return (col // 16) * 512 + (col % 16) + (row % 32) * 16


def group_grid(tiles):
    """Build a row-major 2D grid of tile ids over the selection's bounding box.
    Cells not selected become None."""
    if not tiles:
        return [], None
    cols = [c for c, r in tiles]
    rows = [r for c, r in tiles]
    c0, c1, r0, r1 = min(cols), max(cols), min(rows), max(rows)
    grid = []
    for row in range(r0, r1 + 1):
        line = []
        for col in range(c0, c1 + 1):
            line.append(tile_id(col, row) if (col, row) in tiles else None)
        grid.append(line)
    return grid, (c0, r0, c1, r1)


def save(selection):
    out = {}
    for g in GROUPS:
        tiles = sorted(selection[g])
        grid, bbox = group_grid(tiles)
        out[g] = {
            "tiles": [{"col": c, "row": r, "id": tile_id(c, r)} for c, r in tiles],
            "grid": grid,
            "bbox": bbox,
        }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nsaved -> {OUT_PATH}")
    for g in GROUPS:
        print(f"  {g}: grid={out[g]['grid']} bbox={out[g]['bbox']}")
    return out


def main():
    global GROUPS, GROUP_COLOR, OUT_PATH
    args = sys.argv[1:]
    path = DEFAULT_TILESET
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "--groups" and i + 1 < len(args):
            GROUPS = tuple(args[i + 1].split(","))
            i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            OUT_PATH = args[i + 1]
            i += 2
        else:
            rest.append(args[i])
            i += 1
    if rest:
        path = rest[0]
    GROUP_COLOR = {g: PALETTE[k % len(PALETTE)] for k, g in enumerate(GROUPS)}

    pygame.init()
    screen = pygame.display.set_mode((1500, 900), pygame.RESIZABLE)
    pygame.display.set_caption("chest tile picker")
    font = pygame.font.SysFont("monospace", 15)
    bigfont = pygame.font.SysFont("monospace", 17, bold=True)

    sheet = pygame.image.load(path).convert_alpha()
    sheet_w, sheet_h = sheet.get_size()

    zoom = 3.0
    pan = [0.0, 0.0]  # top-left tileset pixel shown at screen origin
    active = GROUPS[0]
    show_grid = True
    show_help = True
    selection = {g: set() for g in GROUPS}

    clock = pygame.time.Clock()
    dragging = False
    running = True

    def screen_to_tile(sx, sy):
        wx = sx / zoom + pan[0]
        wy = sy / zoom + pan[1]
        return int(wx // TILE), int(wy // TILE)

    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                elif e.key == pygame.K_TAB:
                    active = GROUPS[(GROUPS.index(active) + 1) % len(GROUPS)]
                elif pygame.K_1 <= e.key <= pygame.K_9:
                    idx = e.key - pygame.K_1
                    if idx < len(GROUPS):
                        active = GROUPS[idx]
                elif e.key == pygame.K_g:
                    show_grid = not show_grid
                elif e.key == pygame.K_h:
                    show_help = not show_help
                elif e.key == pygame.K_c:
                    selection[active].clear()
                elif e.key == pygame.K_s:
                    save(selection)
                elif e.key == pygame.K_LEFT:
                    pan[0] -= 64 / zoom
                elif e.key == pygame.K_RIGHT:
                    pan[0] += 64 / zoom
                elif e.key == pygame.K_UP:
                    pan[1] -= 64 / zoom
                elif e.key == pygame.K_DOWN:
                    pan[1] += 64 / zoom
            elif e.type == pygame.MOUSEBUTTONDOWN:
                if e.button == 1:
                    col, row = screen_to_tile(*e.pos)
                    if 0 <= col < COLS and 0 <= row < sheet_h // TILE:
                        key = (col, row)
                        s = selection[active]
                        s.discard(key) if key in s else s.add(key)
                elif e.button in (2, 3):
                    dragging = True
                elif e.button == 4:
                    zoom = min(16.0, zoom * 1.15)
                elif e.button == 5:
                    zoom = max(1.0, zoom / 1.15)
            elif e.type == pygame.MOUSEBUTTONUP:
                if e.button in (2, 3):
                    dragging = False
            elif e.type == pygame.MOUSEMOTION and dragging:
                pan[0] -= e.rel[0] / zoom
                pan[1] -= e.rel[1] / zoom

        # ---- draw ----
        screen.fill((25, 25, 30))
        sw, sh = screen.get_size()

        scaled_w = int(sheet_w * zoom)
        scaled_h = int(sheet_h * zoom)
        scaled = pygame.transform.scale(sheet, (scaled_w, scaled_h))
        screen.blit(scaled, (int(-pan[0] * zoom), int(-pan[1] * zoom)))

        if show_grid and zoom >= 2:
            gcol = (255, 255, 255, 40)
            for col in range(COLS + 1):
                x = int((col * TILE - pan[0]) * zoom)
                if 0 <= x <= sw:
                    pygame.draw.line(screen, (70, 70, 80), (x, 0), (x, sh))
            for row in range(sheet_h // TILE + 1):
                y = int((row * TILE - pan[1]) * zoom)
                if 0 <= y <= sh:
                    pygame.draw.line(screen, (70, 70, 80), (0, y), (sw, y))

        # selections
        for g in GROUPS:
            color = GROUP_COLOR[g]
            width = 3 if g == active else 2
            for (col, row) in selection[g]:
                x = int((col * TILE - pan[0]) * zoom)
                y = int((row * TILE - pan[1]) * zoom)
                size = int(TILE * zoom)
                pygame.draw.rect(screen, color, (x, y, size, size), width)

        # hovered tile
        mx, my = pygame.mouse.get_pos()
        hcol, hrow = screen_to_tile(mx, my)
        if 0 <= hcol < COLS and 0 <= hrow < sheet_h // TILE:
            x = int((hcol * TILE - pan[0]) * zoom)
            y = int((hrow * TILE - pan[1]) * zoom)
            size = int(TILE * zoom)
            pygame.draw.rect(screen, (255, 255, 0), (x, y, size, size), 1)
            hud = f"col={hcol} row={hrow} id={tile_id(hcol, hrow)}"
        else:
            hud = "col=- row=- id=-"

        # status bar
        bar = pygame.Surface((sw, 54), pygame.SRCALPHA)
        bar.fill((0, 0, 0, 190))
        screen.blit(bar, (0, sh - 54))
        act_color = GROUP_COLOR[active]
        screen.blit(bigfont.render(f"active: {active.upper()}", True, act_color),
                    (10, sh - 48))
        counts = "   ".join(
            f"{g}={len(selection[g])}" for g in GROUPS)
        screen.blit(font.render(f"{hud}    [{counts}]    zoom={zoom:.1f}",
                                True, (230, 230, 230)), (10, sh - 24))

        if show_help:
            lines = [
                "LMB=toggle tile   Tab/1/2=group   wheel=zoom   arrows/RMB-drag=pan",
                "g=grid  c=clear group  s=save JSON  h=help  Esc=save+quit",
            ]
            for i, ln in enumerate(lines):
                t = font.render(ln, True, (255, 255, 180))
                bg = pygame.Surface((t.get_width() + 8, t.get_height() + 2),
                                    pygame.SRCALPHA)
                bg.fill((0, 0, 0, 150))
                screen.blit(bg, (6, 6 + i * 20))
                screen.blit(t, (10, 7 + i * 20))

        pygame.display.flip()
        clock.tick(60)

    save(selection)
    pygame.quit()


if __name__ == "__main__":
    main()
