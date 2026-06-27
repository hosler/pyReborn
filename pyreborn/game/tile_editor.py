"""TileEditorMixin — F1 tile-type editor: corrections load/save and mouse picking.

Split from pygame_game.py; methods operate on the GameClient instance."""

import time
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame
from pygame.locals import (
    QUIT, KEYDOWN, MOUSEBUTTONDOWN,
    K_ESCAPE, K_RETURN, K_q, K_a, K_s, K_d, K_SPACE, K_m, K_h,
    K_UP, K_DOWN, K_LEFT, K_RIGHT,
    K_F1, K_F2, K_1, K_2, K_3, K_4, K_5, K_6, K_7
)

from .. import Client
from ..gani import GaniParser, AnimationState, direction_from_delta
from ..sprites import SpriteManager, TilesetManager, create_placeholder_sprite, create_shadow_sprite
from ..sounds import SoundManager, preload_common_sounds
from ..inventory_ui import InventoryUI, HeartDisplay
from ..npc_handler import NPCHandler
from ..player import Player
from ..tiletypes import TileType, get_tile_type
from .constants import (
    TILE_CORRECTIONS_FILE, TILE_SIZE, SCREEN_WIDTH, SCREEN_HEIGHT,
    TILESET_COLS, TILESET_ROWS, MOVE_STEP, parse_npc_visual_effects,
)


class TileEditorMixin:
    """Mixin providing the above methods for GameClient."""

    def _load_tile_corrections(self):
        """Load tile type corrections from file."""
        if TILE_CORRECTIONS_FILE.exists():
            try:
                with open(TILE_CORRECTIONS_FILE) as f:
                    data = json.load(f)
                    # Convert string keys back to int
                    self.tile_corrections = {int(k): v for k, v in data.items()}
                    print(f"Loaded {len(self.tile_corrections)} tile corrections")
            except Exception as e:
                print(f"Failed to load tile corrections: {e}")
                self.tile_corrections = {}
    def _save_tile_corrections(self):
        """Save tile type corrections to file."""
        try:
            with open(TILE_CORRECTIONS_FILE, 'w') as f:
                json.dump(self.tile_corrections, f, indent=2)
            print(f"Saved {len(self.tile_corrections)} tile corrections")
        except Exception as e:
            print(f"Failed to save tile corrections: {e}")
    def _handle_tile_click(self, event):
        """Handle mouse click on tile in debug mode."""
        # Window pixel -> virtual canvas -> world tile, all via the shared camera.
        mouse_x, mouse_y = self.viewport.window_to_virtual(*event.pos)
        world_tile_x, world_tile_y = self.camera.screen_to_world(mouse_x, mouse_y)

        # Get tile at this position
        tile_x = int(world_tile_x) % 64
        tile_y = int(world_tile_y) % 64
        tile_id = self._get_tile_at(world_tile_x, world_tile_y)

        if tile_id == 0:
            return  # No tile data

        # Left click applies selected type, right click removes correction
        if event.button == 1:
            new_type = self.debug_selected_type
            type_names = {
                TileType.NONBLOCK: "Walkable",
                TileType.BLOCKING: "Blocking",
                TileType.WATER: "Water",
                TileType.CHAIR: "Chair",
                TileType.BUSH: "Bush",
                TileType.POT: "Pot",
                TileType.ROCK: "Rock",
            }
            type_name = type_names.get(new_type, str(new_type))
        elif event.button == 3:
            # Right click removes correction (restore original)
            if tile_id in self.tile_corrections:
                del self.tile_corrections[tile_id]
                print(f"Tile {tile_id} at ({tile_x},{tile_y}): Restored to original")
                self.world_surface = None
            return
        else:
            return

        # Store correction
        old_type = self._get_corrected_tile_type(tile_id)
        self.tile_corrections[tile_id] = new_type
        print(f"Tile {tile_id} at ({tile_x},{tile_y}): {old_type} -> {new_type} ({type_name})")

        # Invalidate world surface to force redraw
        self.world_surface = None
    def _get_tile_info_at_screen_pos(self, screen_x: int, screen_y: int) -> Optional[Tuple[int, int, int, int]]:
        """Get tile info at screen position. Returns (tile_id, tile_type, tx, ty) or None.

        screen_x/screen_y are virtual-canvas coordinates (already mapped from the
        window by the caller).
        """
        world_tile_x, world_tile_y = self.camera.screen_to_world(screen_x, screen_y)

        tile_x = int(world_tile_x) % 64
        tile_y = int(world_tile_y) % 64
        tile_id = self._get_tile_at(world_tile_x, world_tile_y)

        if tile_id == 0:
            return None

        tile_type = self._get_corrected_tile_type(tile_id)
        return (tile_id, tile_type, tile_x, tile_y)
