"""SetupMixin — Asset paths, client callbacks, GS1 callbacks, NPC script bootstrap.

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
from ..gs1_interpreter import GS1Interpreter
from ..player import Player
from ..tiletypes import TileType, get_tile_type
from .constants import (
    PACKAGE_DIR, TILE_CORRECTIONS_FILE, TILE_SIZE, SCREEN_WIDTH, SCREEN_HEIGHT,
    TILESET_COLS, TILESET_ROWS, MOVE_STEP, parse_npc_visual_effects,
)


class SetupMixin:
    """Mixin providing the above methods for GameClient."""

    def _setup_asset_paths(self) -> List[Path]:
        """Setup asset search paths."""
        base_path = PACKAGE_DIR  # pyreborn/ — independent of this module's location
        paths = [
            base_path / "assets",
            base_path.parent / "cache",
            base_path.parent / "cache" / "levels" / f"{self.client.host}_{self.client.port}",
            base_path.parent / "examples" / "games" / "reborn_modern" / "assets" / "levels",
            base_path.parent / "examples" / "games" / "reborn_modern" / "assets",
        ]
        # Add subdirectories for ganis and sounds
        extra_paths = []
        for p in paths:
            extra_paths.append(p / "ganis")
            extra_paths.append(p / "sounds")
            extra_paths.append(p / "bodies")
            extra_paths.append(p / "heads")
            extra_paths.append(p / "swords")
            extra_paths.append(p / "shields")
        return paths + extra_paths
    def _setup_callbacks(self):
        """Setup client callbacks."""
        def on_chat(player_id, message):
            self.chat_messages.append(f"[{player_id}] {message}")
            if len(self.chat_messages) > 10:
                self.chat_messages.pop(0)

        def on_hurt(attacker_id, damage, damage_type, source_x, source_y):
            # Spawn floating damage number at player position
            self.damage_numbers.append({
                'x': self.visual_x,
                'y': self.visual_y - 16,
                'damage': damage,
                'time': time.time(),
                'duration': 1.0,
            })
            # Trigger hurt flash
            self.hurt_flash_time = time.time()

            # Check for death (hearts already reduced by client.respond_to_hurt)
            if self.client.player.hearts <= 0:
                # Play death sound
                self.sound_mgr.play("dead.wav")
                # Set death animation
                self.player_anim.set_animation("dead", self.client.player.direction)

        def on_minimap(data: bytes):
            """Handle minimap data from server."""
            self.minimap_data = data
            self._build_minimap_surface()

        def on_ghost_mode(enabled: bool):
            """Handle ghost mode toggle."""
            self.ghost_mode = enabled

        self.client.on_chat = on_chat
        self.client.on_hurt = on_hurt
        self.client.on_minimap = on_minimap
        self.client.on_ghost_mode = on_ghost_mode
    def _setup_gs1_callbacks(self):
        """Setup GS1 interpreter callbacks for visual/audio feedback."""
        # Play sound callback
        def on_play(sound_name):
            self.sound_mgr.play(sound_name)

        # Say/chat callback - sets NPC speech bubble
        def on_say(npc_id, message):
            self.npc_chat_texts[npc_id] = (message, time.time())

        # Show message callback (dialogue box)
        def on_message(text):
            self._show_dialogue(text)

        # Set effect callback
        def on_seteffect(r, g, b, a):
            # Could apply screen tint effect here
            pass

        self.gs1.on_play = on_play
        self.gs1.on_say = on_say
        self.gs1.on_message = on_message
    def _load_npc_scripts(self):
        """Load NPC scripts into the GS1 interpreter."""
        for npc_id, npc in self.client.npcs.items():
            script = npc.get('script', '')
            if script:
                x, y = npc.get('x', 0), npc.get('y', 0)
                self.gs1.load_script(f"npc_{npc_id}", script, npc_id=npc_id, x=x, y=y)
    def _trigger_playerenters(self):
        """Trigger playerenters event on all loaded NPC scripts."""
        for name, code in self.gs1.scripts.items():
            if 'playerenters' in code.lower():
                try:
                    self.gs1.trigger_event('playerenters')
                except Exception:
                    pass  # Silently ignore errors during event execution
