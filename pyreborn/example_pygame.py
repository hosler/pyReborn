#!/usr/bin/env python3
"""
pyreborn - Enhanced Pygame Client

A full-featured pygame game client with proper animations, sounds, and inventory.

Usage:
    # Launch with graphical login screen (recommended)
    python -m pyreborn.example_pygame

    # Direct connection to a server (skip login screen)
    python -m pyreborn.example_pygame <username> <password> [host] [port]

    # Via listserver with command line credentials
    python -m pyreborn.example_pygame <username> <password> --listserver [listserver_host]

Examples:
    python -m pyreborn.example_pygame
    python -m pyreborn.example_pygame SpaceManSpiff googlymoogly localhost 14900
    python -m pyreborn.example_pygame SpaceManSpiff googlymoogly --listserver listserver.example.com

Login Screen Controls:
    Tab         - Next field
    Shift+Tab   - Previous field
    F1          - Toggle Listserver/Direct mode
    Enter       - Connect
    Escape      - Quit

Game Controls:
    Arrow Keys  - Move
    A           - Grab/interact
    A + Arrow   - Pickup objects (bushes/pots/rocks based on glove power)
    S or Space  - Swing sword
    D           - Use equipped weapon
    Q           - Toggle inventory
    S + A       - Cycle through weapons
    Enter       - Chat
    Escape      - Quit
"""

import sys
import time
import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import pygame
    from pygame.locals import *
except ImportError:
    print("pygame not installed. Install with: pip install pygame")
    sys.exit(1)

from . import Client
from .listserver import ListServerClient, ServerEntry
from .gani import GaniParser, AnimationState, direction_from_delta, Gani
from .sprites import SpriteManager, TilesetManager, create_placeholder_sprite, create_shadow_sprite
from .sounds import SoundManager, preload_common_sounds
from .inventory_ui import InventoryUI, HeartDisplay
from .player import Player
from .tiletypes import (
    is_blocking, is_water, is_swamp, is_chair, is_liftable,
    get_lift_power_required, get_liftable_type_name,
    TileType, get_tile_type
)

# Tile type corrections file
TILE_CORRECTIONS_FILE = Path(__file__).parent / "tile_corrections.json"

import re


def parse_npc_visual_effects(script: str, image_name: str = '') -> dict:
    """Parse NPC script and image for visual effects like drawaslight and setcoloreffect.

    Note: For client version 6.037+, the server doesn't send GS1 scripts.
    We fall back to image-based detection for light NPCs.

    Returns dict with:
        - drawaslight: bool - render with additive blending
        - coloreffect: tuple (r, g, b, a) - color multiplier
    """
    effects = {
        'drawaslight': False,
        'coloreffect': None,
    }

    # Image-based light detection (for modern clients that don't receive scripts)
    # Light NPCs typically use images like "light2.png", "light.png", "lightblue.png"
    if image_name:
        img_lower = image_name.lower()
        if img_lower.startswith('light') and img_lower.endswith('.png'):
            effects['drawaslight'] = True
            # Default light color effect (semi-transparent for glow)
            effects['coloreffect'] = (1.0, 1.0, 1.0, 0.99)

    # If we have a script, parse it (for older client versions)
    if script:
        # Check for CLIENTSIDE section (the rendering effects are client-side)
        clientside_match = re.search(r'//#CLIENTSIDE(.*)$', script, re.DOTALL | re.IGNORECASE)
        clientside_code = clientside_match.group(1) if clientside_match else script

        # Check for playerenters block
        playerenters_match = re.search(r'if\s*\(\s*playerenters\s*\)\s*\{([^}]*)\}', clientside_code, re.DOTALL)
        if playerenters_match:
            block = playerenters_match.group(1)

            # Check for drawaslight
            if re.search(r'\bdrawaslight\s*;', block, re.IGNORECASE):
                effects['drawaslight'] = True

            # Check for setcoloreffect r,g,b,a
            color_match = re.search(
                r'setcoloreffect\s+([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)',
                block, re.IGNORECASE
            )
            if color_match:
                r, g, b, a = float(color_match.group(1)), float(color_match.group(2)), \
                             float(color_match.group(3)), float(color_match.group(4))
                effects['coloreffect'] = (r, g, b, a)

    return effects


# Constants
TILE_SIZE = 16
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 480
TILESET_COLS = 128
TILESET_ROWS = 32


class GameClient:
    """Enhanced pygame game client with animations and sounds."""

    def __init__(self, client: Client):
        self.client = client
        self.running = True

        # Initialize pygame
        pygame.init()
        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption(f"pyreborn - {client.player.account}")
        self.clock = pygame.time.Clock()

        # Fonts
        self.font = pygame.font.Font(None, 24)
        self.font_small = pygame.font.Font(None, 18)

        # Setup asset paths
        self.asset_paths = self._setup_asset_paths()

        # Initialize managers
        self.sprite_mgr = SpriteManager(self.asset_paths)
        self.tileset_mgr = TilesetManager(self.sprite_mgr)
        self.sound_mgr = SoundManager(self.asset_paths)
        self.gani_parser = GaniParser(self.asset_paths)

        # Preload common sounds
        preload_common_sounds(self.sound_mgr)

        # Load tileset
        self.tileset_mgr.preload_tileset()

        # Animation state for local player
        self.player_anim = AnimationState(self.gani_parser)
        self.player_anim.set_animation("idle", self.client.player.direction)

        # Animation states for other players
        self.other_player_anims: Dict[int, AnimationState] = {}

        # Animation states for NPCs
        self.npc_anims: Dict[int, AnimationState] = {}

        # Visual effects for NPCs (drawaslight, setcoloreffect)
        self.npc_effects: Dict[int, dict] = {}

        # UI components
        self.inventory_ui = InventoryUI(self.screen, self.sprite_mgr)
        self.heart_display = HeartDisplay(10, 30)

        # Input state
        self.typing = False
        self.chat_input = ""
        self.chat_messages: List[str] = []

        # Timing
        self.last_move_time = 0.0
        self.move_delay = 0.1  # 100ms between moves
        self.last_action_time = 0.0
        self.action_delay = 0.3  # 300ms between actions

        # Key state tracking
        self.key_just_pressed: Dict[int, bool] = {}

        # World rendering
        self.world_surface: Optional[pygame.Surface] = None
        self.last_level_count = 0
        self.last_level_name = ""  # Track current level for cache invalidation
        self.known_levels: set = set()  # Track which levels we've seen tiles for

        # Placeholders
        self.placeholder_sprite = create_placeholder_sprite(32, 32, (200, 50, 200))
        self.shadow_sprite = create_shadow_sprite()
        self.npc_placeholder = create_placeholder_sprite(32, 32, (50, 200, 50))

        # Weapon list (will be populated from server)
        self.weapons: List[str] = []

        # Current animation name (for tracking changes)
        self.current_anim_name = "idle"
        self.is_moving = False
        self.is_swimming = False  # Track if player is in water

        # Smooth movement - visual position interpolates toward actual position
        self.visual_x = 0.0
        self.visual_y = 0.0
        self.lerp_speed = 18.0  # Speed of interpolation (higher = snappier)

        # Debug/tile editing mode
        self.debug_mode = False
        self.tile_corrections: Dict[int, int] = {}  # tile_id -> corrected TileType
        self.debug_selected_type = TileType.NONBLOCK  # Currently selected tile type for editing
        self._load_tile_corrections()

        # Removed tiles tracking (for pickup/throw mechanics)
        # Maps (level_name, x, y) -> original_tile_id
        self.removed_tiles: Dict[Tuple[str, int, int], int] = {}

        # Grass/dirt tile ID to replace picked up objects
        self.grass_tile_id = 0  # Will be detected or default to 0

        # Setup callbacks
        self._setup_callbacks()

    def _setup_asset_paths(self) -> List[Path]:
        """Setup asset search paths."""
        base_path = Path(__file__).parent
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

        self.client.on_chat = on_chat

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

    def _get_corrected_tile_type(self, tile_id: int) -> int:
        """Get tile type, using corrections if available."""
        if tile_id in self.tile_corrections:
            return self.tile_corrections[tile_id]
        return get_tile_type(tile_id)

    def _is_tile_blocking(self, tile_id: int) -> bool:
        """Check if tile is blocking, using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        return tile_type == TileType.BLOCKING

    def _is_tile_water(self, tile_id: int) -> bool:
        """Check if tile is water, using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        return tile_type in (TileType.WATER, TileType.NEAR_WATER)

    def _is_tile_chair(self, tile_id: int) -> bool:
        """Check if tile is a chair, using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        return tile_type == TileType.CHAIR

    def _is_tile_liftable(self, tile_id: int) -> bool:
        """Check if tile is liftable (bush/rock/pot), using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        return tile_type in (TileType.BUSH, TileType.ROCK, TileType.POT)

    def _get_tile_lift_power(self, tile_id: int) -> int:
        """Get required glove power to lift tile, using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        if tile_type == TileType.BUSH:
            return 1
        elif tile_type == TileType.POT:
            return 2
        elif tile_type == TileType.ROCK:
            return 3
        return 0

    def _get_liftable_name(self, tile_id: int) -> str:
        """Get the name of a liftable object, using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        if tile_type == TileType.BUSH:
            return "bush"
        elif tile_type == TileType.POT:
            return "pot"
        elif tile_type == TileType.ROCK:
            return "rock"
        return ""

    def run(self):
        """Main game loop."""
        last_time = time.time()
        frame_count = 0

        # Initialize visual position to actual position
        self.visual_x = self.client.x
        self.visual_y = self.client.y

        # Check initial swimming state
        self._update_swimming_state()

        print(f"Starting game loop. running={self.running}, connected={self.client.connected}")

        while self.running and self.client.connected:
            frame_count += 1
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time

            # Handle events
            self._handle_events()

            # Handle held key input
            self._handle_input(current_time)

            # Update client (process packets)
            self.client.update()

            # Update swimming state (in case of server-side warps)
            self._update_swimming_state()

            # Update visual position (smooth interpolation)
            self._update_visual_position(dt)

            # Update animations
            self._update_animations(dt)

            # Render
            self._render()

            # Cap framerate
            self.clock.tick(60)

        # Cleanup
        print(f"Game loop exited after {frame_count} frames. running={self.running}, connected={self.client.connected}")
        self.client.disconnect()
        pygame.quit()

    def _handle_events(self):
        """Handle pygame events."""
        # Reset just-pressed flags
        self.key_just_pressed.clear()

        for event in pygame.event.get():
            if event.type == QUIT:
                self.running = False

            elif event.type == KEYDOWN:
                self.key_just_pressed[event.key] = True

                if self.typing:
                    self._handle_chat_input(event)
                else:
                    self._handle_key_press(event)

            elif event.type == MOUSEBUTTONDOWN and self.debug_mode:
                self._handle_tile_click(event)

    def _handle_chat_input(self, event):
        """Handle chat input mode."""
        if event.key == K_RETURN:
            if self.chat_input:
                self.client.say(self.chat_input)
                self.chat_messages.append(f"[You] {self.chat_input}")
                if len(self.chat_messages) > 10:
                    self.chat_messages.pop(0)
            self.chat_input = ""
            self.typing = False
        elif event.key == K_ESCAPE:
            self.chat_input = ""
            self.typing = False
        elif event.key == K_BACKSPACE:
            self.chat_input = self.chat_input[:-1]
        elif event.unicode and len(self.chat_input) < 100:
            self.chat_input += event.unicode

    def _handle_key_press(self, event):
        """Handle single key press events."""
        if event.key == K_ESCAPE:
            self.running = False

        elif event.key == K_RETURN:
            self.typing = True

        elif event.key == K_q:
            # Toggle inventory
            self.inventory_ui.toggle()

        elif event.key == K_F1:
            # Toggle debug/tile editing mode
            self.debug_mode = not self.debug_mode
            if self.debug_mode:
                print("Debug mode ON - Use 1-7 to select type, click to apply:")
                print("  1=Walkable, 2=Blocking, 3=Water, 4=Chair, 5=Bush, 6=Pot, 7=Rock")
            else:
                self._save_tile_corrections()
                print("Debug mode OFF - Corrections saved")

        elif self.debug_mode and event.key in (K_1, K_2, K_3, K_4, K_5, K_6, K_7):
            # Number keys select tile type in debug mode
            type_map = {
                K_1: (TileType.NONBLOCK, "Walkable"),
                K_2: (TileType.BLOCKING, "Blocking"),
                K_3: (TileType.WATER, "Water"),
                K_4: (TileType.CHAIR, "Chair"),
                K_5: (TileType.BUSH, "Bush"),
                K_6: (TileType.POT, "Pot"),
                K_7: (TileType.ROCK, "Rock"),
            }
            self.debug_selected_type, type_name = type_map[event.key]
            print(f"Selected type: {type_name}")

        elif event.key == K_F2:
            # Emergency warp to (30, 30) on current level
            self.client.warp_to_level(self.client._current_level_name, 30, 30)
            self.visual_x = self.client.x
            self.visual_y = self.client.y
            print(f"Warped to (30, 30) on {self.client._current_level_name}")

    def _handle_tile_click(self, event):
        """Handle mouse click on tile in debug mode."""
        mouse_x, mouse_y = event.pos

        # Calculate camera offset using GMAP-relative visual position
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64

        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE

        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        # Convert screen coords to world tile coords
        world_tile_x = (mouse_x - cam_offset_x) / TILE_SIZE
        world_tile_y = (mouse_y - cam_offset_y) / TILE_SIZE

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

    def _handle_input(self, current_time: float):
        """Handle held key input."""
        if self.typing or self.inventory_ui.visible:
            return

        keys = pygame.key.get_pressed()

        # Check for combined key actions first
        a_held = keys[K_a]
        s_held = keys[K_s]

        # S + A = Cycle weapons
        if s_held and a_held:
            if self.key_just_pressed.get(K_a, False) or self.key_just_pressed.get(K_s, False):
                if current_time - self.last_action_time > self.action_delay:
                    self._cycle_weapon()
                    self.last_action_time = current_time
            return

        # Sword swing (S or Space, but not with A)
        if (s_held or keys[K_SPACE]) and not a_held:
            if self.key_just_pressed.get(K_s, False) or self.key_just_pressed.get(K_SPACE, False):
                if current_time - self.last_action_time > self.action_delay:
                    self._swing_sword()
                    self.last_action_time = current_time
            return

        # Use weapon (D)
        if keys[K_d]:
            if self.key_just_pressed.get(K_d, False):
                if current_time - self.last_action_time > self.action_delay:
                    self._use_weapon()
                    self.last_action_time = current_time
            return

        # Get arrow key directions
        dx, dy = 0, 0
        if keys[K_UP]:
            dy = -1
        elif keys[K_DOWN]:
            dy = 1
        if keys[K_LEFT]:
            dx = -1
        elif keys[K_RIGHT]:
            dx = 1

        # A + Arrow = Pickup
        if a_held and (dx != 0 or dy != 0):
            if current_time - self.last_action_time > self.action_delay:
                self._try_pickup(dx, dy)
                self.last_action_time = current_time
            return

        # A alone = Grab/interact
        if a_held and dx == 0 and dy == 0:
            if self.key_just_pressed.get(K_a, False):
                if current_time - self.last_action_time > self.action_delay:
                    self._try_grab()
                    self.last_action_time = current_time
            return

        # Movement (arrow keys only, no A held)
        if not a_held and (dx != 0 or dy != 0):
            # Stand up automatically if sitting and trying to move
            if self.client.player.is_sitting:
                self.client.player.stand_up()
                self.player_anim.set_animation("idle", self.client.player.direction, force=True)
                self.current_anim_name = "idle"
            if current_time - self.last_move_time > self.move_delay:
                self._move(dx, dy)
                self.last_move_time = current_time
                self.is_moving = True
        else:
            self.is_moving = False

    def _move(self, dx: int, dy: int):
        """Move the player, checking for blocking tiles."""
        # Calculate destination position
        dest_x = self.client.x + dx
        dest_y = self.client.y + dy

        # Check if destination is blocked (pass direction for directional checks)
        if self._is_position_blocked(dest_x, dest_y, dx, dy):
            # Can't move there - still update direction for visual feedback
            direction = direction_from_delta(dx, dy)
            self.player_anim.set_direction(direction)
            return

        # Move is allowed
        self.client.move(dx, dy)

        # Update swimming state after move
        self._update_swimming_state()

        # Update direction
        direction = direction_from_delta(dx, dy)
        self.player_anim.set_direction(direction)

        # Check if we walked onto a chair - auto-sit
        current_tile = self._get_tile_at(self.client.x, self.client.y)
        if self._is_tile_chair(current_tile) and not self.client.player.is_carrying():
            self.client.player.sit_down(direction)
            self.player_anim.set_animation("sit", direction, force=True)
            self.current_anim_name = "sit"
            return

        # Set appropriate animation based on whether we're swimming
        if self.is_swimming:
            if self.current_anim_name != "swim":
                self.player_anim.set_animation("swim", direction)
                self.current_anim_name = "swim"
        else:
            if self.current_anim_name != "walk":
                self.player_anim.set_animation("walk", direction)
                self.current_anim_name = "walk"

    def _swing_sword(self):
        """Swing sword attack."""
        self.client.sword_attack(self.client.player.direction)
        self.player_anim.set_animation("sword", self.client.player.direction, force=True)
        self.current_anim_name = "sword"

    def _try_grab(self):
        """Try to grab/interact with something.

        Priority:
        1. If carrying an object, throw it
        2. If sitting, stand up
        3. If near a chair, sit down
        4. Check for door links
        5. Try to pickup items at current position
        """
        player = self.client.player

        # If carrying something, throw it
        if player.is_carrying():
            self._throw_object()
            return

        # If sitting, stand up
        if player.is_sitting:
            player.stand_up()
            self.player_anim.set_animation("idle", player.direction, force=True)
            self.current_anim_name = "idle"
            return

        # Check for chair in front of player
        chair_tile = self._find_adjacent_chair()
        if chair_tile is not None:
            tx, ty, tile_id = chair_tile
            # Sit down facing direction of chair
            if player.sit_down(player.direction):
                self.player_anim.set_animation("sit", player.direction, force=True)
                self.current_anim_name = "sit"
                return

        # Check for door link
        door_link = self._get_non_edge_door()
        if door_link:
            self.client.use_link(door_link)
            # Update visual position to match new position
            self.visual_x = self.client.x
            self.visual_y = self.client.y
            # Force world surface redraw
            self.world_surface = None
            return

        # Try to pickup item at current position
        self.client.pickup_item()

    def _try_pickup(self, dx: int, dy: int):
        """Try to pickup a liftable 2x2 object (bush/rock/pot) in the given direction.

        Requires appropriate glove power:
        - Bush: glove power 1+
        - Pot: glove power 2+
        - Rock: glove power 3
        """
        player = self.client.player

        # Update direction first
        direction = direction_from_delta(dx, dy)
        self.player_anim.set_direction(direction)
        player.direction = direction

        # If already carrying, throw instead
        if player.is_carrying():
            self._throw_object()
            return

        # If sitting, stand up first
        if player.is_sitting:
            player.stand_up()

        # Calculate target position
        target_x = self.client.x + dx
        target_y = self.client.y + dy

        # Get tile at target position
        tile_id = self._get_tile_at(target_x, target_y)

        # Check if it's a liftable tile
        if self._is_tile_liftable(tile_id):
            required_power = self._get_tile_lift_power(tile_id)
            glove_power = player.glove_power

            if glove_power >= required_power:
                # Find the 2x2 object origin (top-left corner)
                obj_origin = self._find_2x2_object_origin(target_x, target_y)
                if obj_origin:
                    ox, oy = obj_origin
                    # Get all 4 tile IDs
                    tile_ids = self._get_2x2_tiles(ox, oy)
                    object_name = self._get_liftable_name(tile_id)

                    # Store original tiles and replace with grass
                    self._remove_2x2_tiles(ox, oy, tile_ids)

                    # Pick up the object
                    player.pickup_object(object_name, tile_ids, (ox, oy))

                    # Play lift animation then switch to carry
                    self.player_anim.set_animation("lift", direction, force=True)
                    self.current_anim_name = "lift"

                    # Invalidate world surface to show removed tiles
                    self.world_surface = None

                    print(f"Picked up {object_name}!")
            else:
                # Not enough glove power
                object_name = self._get_liftable_name(tile_id)
                print(f"Need glove power {required_power} to lift {object_name} (have {glove_power})")
        else:
            # No liftable object - try regular item pickup
            self.client.pickup_item(target_x, target_y)

            # Play lift animation anyway for visual feedback
            self.player_anim.set_animation("lift", direction, force=True)
            self.current_anim_name = "lift"

    def _find_2x2_object_origin(self, x: float, y: float) -> Optional[Tuple[int, int]]:
        """Find the top-left corner of a 2x2 liftable object.

        Checks if the clicked tile is part of a 2x2 group of the same type.
        Returns (origin_x, origin_y) or None if not found.
        """
        tx, ty = int(x), int(y)
        tile_id = self._get_tile_at(tx, ty)
        if not self._is_tile_liftable(tile_id):
            return None

        tile_type = self._get_corrected_tile_type(tile_id)

        # Check all 4 possible positions this tile could be in a 2x2 grid
        # and find which arrangement has all matching tiles
        possible_origins = [
            (tx, ty),      # This is top-left
            (tx - 1, ty),  # This is top-right
            (tx, ty - 1),  # This is bottom-left
            (tx - 1, ty - 1),  # This is bottom-right
        ]

        for ox, oy in possible_origins:
            # Check if all 4 tiles in this 2x2 are the same type
            all_match = True
            for dy in range(2):
                for dx in range(2):
                    check_tile = self._get_tile_at(ox + dx, oy + dy)
                    check_type = self._get_corrected_tile_type(check_tile)
                    if check_type != tile_type:
                        all_match = False
                        break
                if not all_match:
                    break

            if all_match:
                return (ox, oy)

        # Fallback: just use this tile as origin (for single-tile objects)
        return (tx, ty)

    def _get_2x2_tiles(self, ox: int, oy: int) -> Tuple[int, int, int, int]:
        """Get the 4 tile IDs of a 2x2 object starting at origin."""
        tl = self._get_tile_at(ox, oy)
        tr = self._get_tile_at(ox + 1, oy)
        bl = self._get_tile_at(ox, oy + 1)
        br = self._get_tile_at(ox + 1, oy + 1)
        return (tl, tr, bl, br)

    def _remove_2x2_tiles(self, ox: int, oy: int, tile_ids: Tuple[int, int, int, int]):
        """Remove 2x2 tiles from the level and replace with grass."""
        level_name = self.client._current_level_name
        if not level_name or level_name not in self.client.levels:
            return

        tiles = self.client.levels[level_name]
        local_ox = ox % 64
        local_oy = oy % 64

        # Store original tiles and replace with grass
        positions = [(0, 0), (1, 0), (0, 1), (1, 1)]
        for i, (dx, dy) in enumerate(positions):
            lx, ly = local_ox + dx, local_oy + dy
            if 0 <= lx < 64 and 0 <= ly < 64:
                idx = ly * 64 + lx
                self.removed_tiles[(level_name, lx, ly)] = tile_ids[i]
                tiles[idx] = self.grass_tile_id

    def _restore_2x2_tiles(self, ox: int, oy: int, tile_ids: Tuple[int, int, int, int]):
        """Restore 2x2 tiles to the level (when throwing object back)."""
        level_name = self.client._current_level_name
        if not level_name or level_name not in self.client.levels:
            return

        tiles = self.client.levels[level_name]
        local_ox = ox % 64
        local_oy = oy % 64

        # Restore original tiles
        positions = [(0, 0), (1, 0), (0, 1), (1, 1)]
        for i, (dx, dy) in enumerate(positions):
            lx, ly = local_ox + dx, local_oy + dy
            if 0 <= lx < 64 and 0 <= ly < 64:
                idx = ly * 64 + lx
                tiles[idx] = tile_ids[i]
                # Remove from tracking
                key = (level_name, lx, ly)
                if key in self.removed_tiles:
                    del self.removed_tiles[key]

    def _throw_object(self):
        """Throw the currently carried object."""
        player = self.client.player
        if not player.is_carrying():
            return

        thrown_type, thrown_tiles, thrown_pos = player.throw_object()
        direction = player.direction

        # Play throw animation
        self.player_anim.set_animation("throw", direction, force=True)
        self.current_anim_name = "throw"

        # Calculate throw destination (2 tiles in front of player)
        dx, dy = 0, 0
        if direction == 0:  # up
            dy = -2
        elif direction == 1:  # left
            dx = -2
        elif direction == 2:  # down
            dy = 2
        elif direction == 3:  # right
            dx = 2

        # Calculate where the object lands
        land_x = int(player.x + dx)
        land_y = int(player.y + dy)

        # Restore the tiles at the landing position (or original position if blocked)
        # For now, just restore at original position
        # TODO: Check if landing spot is clear and restore there instead
        if thrown_tiles and thrown_pos:
            ox, oy = thrown_pos
            self._restore_2x2_tiles(ox, oy, thrown_tiles)
            self.world_surface = None  # Force redraw

        print(f"Threw {thrown_type} in direction {direction}!")

    def _find_adjacent_chair(self) -> Optional[Tuple[int, int, int]]:
        """Find a chair tile adjacent to the player in the direction they're facing.

        Returns (tile_x, tile_y, tile_id) if chair found, None otherwise.
        """
        player = self.client.player
        direction = player.direction

        # Calculate offset based on direction
        dx, dy = 0, 0
        if direction == 0:  # up
            dy = -1
        elif direction == 1:  # left
            dx = -1
        elif direction == 2:  # down
            dy = 1
        elif direction == 3:  # right
            dx = 1

        # Check tile in front of player
        target_x = player.x + dx
        target_y = player.y + dy
        tile_id = self._get_tile_at(target_x, target_y)

        if self._is_tile_chair(tile_id):
            return (int(target_x), int(target_y), tile_id)

        return None

    def _use_weapon(self):
        """Use the currently equipped weapon."""
        # Get selected weapon from inventory
        weapon = self.inventory_ui.get_selected_weapon(self.weapons)
        if weapon:
            # Use weapon-specific action
            if "bow" in weapon.lower():
                self.client.shoot(self.client.player.direction)
            elif "bomb" in weapon.lower():
                self.client.drop_bomb(self.client.player.bomb_power)
            else:
                # Default to sword attack
                self.client.sword_attack(self.client.player.direction)

    def _cycle_weapon(self):
        """Cycle through available weapons."""
        self.inventory_ui.cycle_weapon(self.weapons)

    def _get_non_edge_door(self) -> Optional[dict]:
        """Get door link at current position, ignoring edge links in GMAP mode."""
        link = self.client.check_link_collision()
        if not link:
            return None

        # In GMAP mode, ignore edge links
        if self.client.is_gmap:
            if self._is_edge_link(link):
                return None

        return link

    def _is_edge_link(self, link: dict) -> bool:
        """Check if a link is an edge warp."""
        x = link.get('x', 0)
        y = link.get('y', 0)
        w = link.get('width', 1)
        h = link.get('height', 1)

        # Edge links are at level boundaries
        return x <= 1 or x + w >= 63 or y <= 1 or y + h >= 63

    def _update_animations(self, dt: float):
        """Update all animation states."""
        # Update local player animation
        sounds = self.player_anim.update(dt)
        for sound in sounds:
            self.sound_mgr.play_from_gani(sound)

        # Check if animation finished and needs setback
        if self.player_anim.is_finished():
            setback = self.player_anim.get_setback()
            if setback:
                self.player_anim.set_animation(setback, self.client.player.direction)
                self.current_anim_name = setback
            elif self.client.player.is_carrying():
                # Switch to carry animation after lift finishes
                self.player_anim.set_animation("carry", self.client.player.direction)
                self.current_anim_name = "carry"
            elif self.client.player.is_sitting:
                # Stay in sit animation
                self.player_anim.set_animation("sit", self.client.player.direction)
                self.current_anim_name = "sit"
            elif self.current_anim_name != "idle":
                self.player_anim.set_animation("idle", self.client.player.direction)
                self.current_anim_name = "idle"

        # If carrying and not in a transition animation, use carry
        if self.client.player.is_carrying():
            if self.current_anim_name not in ("lift", "throw", "carry"):
                self.player_anim.set_animation("carry", self.client.player.direction)
                self.current_anim_name = "carry"

        # If sitting and not already in sit animation
        if self.client.player.is_sitting:
            if self.current_anim_name != "sit":
                self.player_anim.set_animation("sit", self.client.player.direction)
                self.current_anim_name = "sit"

        # If not moving, switch to appropriate idle animation
        if not self.is_moving and self.current_anim_name in ("walk", "swim"):
            if self.is_swimming:
                # Use swim idle animation (or swim if no swim_idle exists)
                self.player_anim.set_animation("swim", self.client.player.direction)
                self.current_anim_name = "swim"
            elif self.client.player.is_carrying():
                self.player_anim.set_animation("carry", self.client.player.direction)
                self.current_anim_name = "carry"
            else:
                self.player_anim.set_animation("idle", self.client.player.direction)
                self.current_anim_name = "idle"

        # Update other player animations
        for pid, anim in list(self.other_player_anims.items()):
            if pid not in self.client.players:
                del self.other_player_anims[pid]
                continue
            anim.update(dt)

        # Update NPC animations
        for npc_id, anim in list(self.npc_anims.items()):
            if npc_id not in self.client.npcs:
                del self.npc_anims[npc_id]
                continue
            anim.update(dt)

    def _update_visual_position(self, dt: float):
        """Smoothly interpolate visual position toward actual position."""
        target_x = self.client.x
        target_y = self.client.y

        # Calculate distance to target
        dx = target_x - self.visual_x
        dy = target_y - self.visual_y

        # If not moving, snap to position immediately (no sliding)
        if not self.is_moving:
            self.visual_x = target_x
            self.visual_y = target_y
            return

        # If very close, snap to target
        if abs(dx) < 0.05 and abs(dy) < 0.05:
            self.visual_x = target_x
            self.visual_y = target_y
            return

        # Lerp toward target (exponential smoothing)
        lerp_factor = min(1.0, self.lerp_speed * dt)
        self.visual_x += dx * lerp_factor
        self.visual_y += dy * lerp_factor

    def _get_tile_at(self, x: float, y: float) -> int:
        """Get the tile ID at a given position (in tile coordinates)."""
        # Get the current level's tiles
        if self.client.is_gmap:
            # In GMAP mode, need to find the correct level for this position
            level_name = self.client._current_level_name
            tiles = self.client.levels.get(level_name, self.client.tiles)
        else:
            tiles = self.client.tiles

        if not tiles:
            return 0  # Default to walkable

        # Convert to tile indices
        tx = int(x) % 64
        ty = int(y) % 64

        # Bounds check
        if tx < 0 or tx >= 64 or ty < 0 or ty >= 64:
            return 0

        tile_idx = ty * 64 + tx
        if tile_idx < 0 or tile_idx >= len(tiles):
            return 0

        return tiles[tile_idx]

    def _is_position_blocked(self, x: float, y: float, dx: int = 0, dy: int = 0) -> bool:
        """Check if a position is blocked by tiles.

        Uses corrected tile types from user edits.
        Direction (dx, dy) is used for directional collision adjustments.

        The destination (x, y) is 1 tile in the movement direction.
        We check offsets from this destination to determine if movement is blocked.
        Negative offsets check "behind" the destination (closer to current pos).
        """
        check_offsets = []

        # Add directional checks based on movement direction
        if dx < 0:  # Moving left
            # Check left edge of destination, above feet level
            check_offsets.append((-0.4, -0.25))
            check_offsets.append((-0.4, -0.5))  # Upper-left body
        elif dx > 0:  # Moving right
            # Check right edge of destination, above feet level
            check_offsets.append((0.4, -0.25))
            check_offsets.append((0.4, -0.5))  # Upper-right body

        if dy < 0:  # Moving up
            # Check above the destination (body/head area going into wall)
            check_offsets.append((0.0, -0.5))
            check_offsets.append((-0.3, -0.5))
            check_offsets.append((0.3, -0.5))
        elif dy > 0:  # Moving down
            # Check halfway between current and destination
            check_offsets.append((0.0, -0.5))
            check_offsets.append((-0.3, -0.5))
            check_offsets.append((0.3, -0.5))

        # If no direction, just check center (standing still)
        if not check_offsets:
            check_offsets = [(0.0, 0.0)]

        for ox, oy in check_offsets:
            check_x = x + ox
            check_y = y + oy
            tile_id = self._get_tile_at(check_x, check_y)
            if self._is_tile_blocking(tile_id):
                return True

        return False

    def _check_water_at_position(self, x: float, y: float) -> bool:
        """Check if the position is in water."""
        tile_id = self._get_tile_at(x, y)
        return self._is_tile_water(tile_id)

    def _get_tile_info_at_screen_pos(self, screen_x: int, screen_y: int) -> Optional[Tuple[int, int, int, int]]:
        """Get tile info at screen position. Returns (tile_id, tile_type, tx, ty) or None."""
        # Calculate camera offset using GMAP-relative visual position
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64

        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE

        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        # Convert screen coords to world tile coords
        world_tile_x = (screen_x - cam_offset_x) / TILE_SIZE
        world_tile_y = (screen_y - cam_offset_y) / TILE_SIZE

        tile_x = int(world_tile_x) % 64
        tile_y = int(world_tile_y) % 64
        tile_id = self._get_tile_at(world_tile_x, world_tile_y)

        if tile_id == 0:
            return None

        tile_type = self._get_corrected_tile_type(tile_id)
        return (tile_id, tile_type, tile_x, tile_y)

    def _update_swimming_state(self):
        """Update swimming state based on current position."""
        was_swimming = self.is_swimming
        self.is_swimming = self._check_water_at_position(self.client.x, self.client.y)

        # If swimming state changed, update animation
        if self.is_swimming != was_swimming:
            if self.is_swimming:
                # Just entered water - could play splash sound
                pass
            else:
                # Just left water
                pass

    def _render(self):
        """Render the game."""
        # Clear screen
        self.screen.fill((34, 139, 34))

        # Render world
        self._render_world()

        # Render debug overlay if enabled
        if self.debug_mode:
            self._render_debug_overlay()

        # Render entities (sorted by Y for depth)
        self._render_entities()

        # Render UI
        self._render_ui()

        # Flip display
        pygame.display.flip()

    def _render_debug_overlay(self):
        """Render colored overlay showing tile types."""
        # Get camera offset using GMAP-relative visual position
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64

        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE

        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        # Calculate visible tile range
        start_tile_x = int(-cam_offset_x / TILE_SIZE) - 1
        start_tile_y = int(-cam_offset_y / TILE_SIZE) - 1
        end_tile_x = start_tile_x + (SCREEN_WIDTH // TILE_SIZE) + 3
        end_tile_y = start_tile_y + (SCREEN_HEIGHT // TILE_SIZE) + 3

        # Create semi-transparent surfaces for each tile type
        blocking_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        blocking_color.fill((255, 0, 0, 100))  # Red for blocking

        water_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        water_color.fill((0, 100, 255, 100))  # Blue for water

        walkable_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        walkable_color.fill((0, 255, 0, 50))  # Green for walkable (subtle)

        chair_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        chair_color.fill((255, 200, 0, 120))  # Yellow/orange for chairs

        bush_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        bush_color.fill((0, 180, 0, 120))  # Dark green for bushes

        pot_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        pot_color.fill((180, 100, 50, 120))  # Brown for pots

        rock_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        rock_color.fill((128, 128, 128, 120))  # Gray for rocks

        # Draw overlay for each visible tile
        for ty in range(start_tile_y, end_tile_y):
            for tx in range(start_tile_x, end_tile_x):
                # Get tile at this world position
                tile_id = self._get_tile_at(tx, ty)
                if tile_id == 0:
                    continue

                tile_type = self._get_corrected_tile_type(tile_id)

                # Calculate screen position
                screen_x = tx * TILE_SIZE + cam_offset_x
                screen_y = ty * TILE_SIZE + cam_offset_y

                # Skip if off screen
                if screen_x < -TILE_SIZE or screen_x > SCREEN_WIDTH:
                    continue
                if screen_y < -TILE_SIZE or screen_y > SCREEN_HEIGHT:
                    continue

                # Draw overlay based on tile type
                if tile_type == TileType.BLOCKING:
                    self.screen.blit(blocking_color, (screen_x, screen_y))
                elif tile_type in (TileType.WATER, TileType.NEAR_WATER):
                    self.screen.blit(water_color, (screen_x, screen_y))
                elif tile_type == TileType.CHAIR:
                    self.screen.blit(chair_color, (screen_x, screen_y))
                elif tile_type == TileType.BUSH:
                    self.screen.blit(bush_color, (screen_x, screen_y))
                elif tile_type == TileType.POT:
                    self.screen.blit(pot_color, (screen_x, screen_y))
                elif tile_type == TileType.ROCK:
                    self.screen.blit(rock_color, (screen_x, screen_y))
                else:
                    self.screen.blit(walkable_color, (screen_x, screen_y))

    def _render_world(self):
        """Render the tile world."""
        world_surf = self._get_world_surface()
        if not world_surf:
            return

        # Calculate camera offset using visual position in GMAP coordinate space
        # Convert world coords to GMAP-relative coords by subtracting offset
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64

        # World pixel position (using GMAP-relative visual position)
        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE

        offset_x = SCREEN_WIDTH // 2 - world_px
        offset_y = SCREEN_HEIGHT // 2 - world_py

        self.screen.blit(world_surf, (offset_x, offset_y))

    def _get_world_surface(self) -> Optional[pygame.Surface]:
        """Get or create the world surface."""
        if not self.client.levels and not self.client.tiles:
            return None

        # Check if we need to invalidate cache
        current_count = len(self.client.levels) + (1 if self.client.tiles else 0)
        current_level = self.client._current_level_name
        current_level_keys = set(self.client.levels.keys())

        # Invalidate if: count changed, level changed, or new levels appeared
        needs_redraw = (
            current_count != self.last_level_count or
            current_level != self.last_level_name or
            not current_level_keys.issubset(self.known_levels)
        )

        if not needs_redraw and self.world_surface:
            return self.world_surface

        # Update tracking
        self.last_level_count = current_count
        self.last_level_name = current_level
        self.known_levels.update(current_level_keys)

        # Check if current level is in GMAP
        in_gmap = self.client._current_level_name in self.client.gmap_grid.values()

        if in_gmap and self.client.gmap_grid:
            world_w = max(1, self.client.gmap_width) * 64 * TILE_SIZE
            world_h = max(1, self.client.gmap_height) * 64 * TILE_SIZE
        else:
            world_w = 64 * TILE_SIZE
            world_h = 64 * TILE_SIZE

        self.world_surface = pygame.Surface((world_w, world_h))
        self.world_surface.fill((34, 139, 34))

        # Render tiles
        if not in_gmap or not self.client.gmap_grid:
            self._render_single_level(self.world_surface, self.client.tiles, 0, 0)
        else:
            for (gx, gy), level_name in self.client.gmap_grid.items():
                if level_name in self.client.levels:
                    level_tiles = self.client.levels[level_name]
                    offset_x = gx * 64 * TILE_SIZE
                    offset_y = gy * 64 * TILE_SIZE
                    self._render_single_level(self.world_surface, level_tiles, offset_x, offset_y)

        return self.world_surface

    def _render_single_level(self, surface: pygame.Surface, tiles: List[int],
                              offset_x: int, offset_y: int):
        """Render a single level's tiles."""
        if not tiles:
            return

        for ty in range(64):
            for tx in range(64):
                tile_id = tiles[ty * 64 + tx]
                dest_x = offset_x + tx * TILE_SIZE
                dest_y = offset_y + ty * TILE_SIZE

                tile = self.tileset_mgr.get_tile_or_color(tile_id)
                surface.blit(tile, (dest_x, dest_y))

    def _render_entities(self):
        """Render all entities (players, NPCs) sorted by Y position."""
        entities = []

        # Calculate camera offset using GMAP-relative visual position
        # This avoids jumps when _current_level_name changes during interpolation
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64

        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE
        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        # Add local player - screen center (camera follows player)
        player = self.client.player
        local_y = self.visual_y % 64
        px = SCREEN_WIDTH // 2
        py = SCREEN_HEIGHT // 2
        entities.append(('player', local_y, px, py, player))

        # Add other players - convert their local coords to screen position
        # Other players report positions relative to their level
        for pid, pdata in self.client.players.items():
            if 'x' in pdata and 'y' in pdata:
                ox = pdata['x']
                oy = pdata['y']
                # Calculate their GMAP-relative position
                # They're on the same level as us in the GMAP
                gmap_ox = ox  # Assuming same level grid position
                gmap_oy = oy
                opx = gmap_ox * TILE_SIZE + cam_offset_x
                opy = gmap_oy * TILE_SIZE + cam_offset_y
                entities.append(('other', oy, opx, opy, pdata, pid))

        # Add NPCs - same coordinate system as other players
        for npc_id, npc in self.client.npcs.items():
            if 'x' in npc and 'y' in npc:
                nx = npc['x']
                ny = npc['y']
                npx = nx * TILE_SIZE + cam_offset_x
                npy = ny * TILE_SIZE + cam_offset_y
                entities.append(('npc', ny, npx, npy, npc, npc_id))

        # Sort by Y for depth
        entities.sort(key=lambda e: e[1])

        # Render each entity
        for entity in entities:
            if entity[0] == 'player':
                self._render_player(entity[2], entity[3], entity[4], self.player_anim)
            elif entity[0] == 'other':
                self._render_other_player(entity[2], entity[3], entity[4], entity[5])
            elif entity[0] == 'npc':
                self._render_npc(entity[2], entity[3], entity[4], entity[5])

    def _render_player(self, x: float, y: float, player: Player, anim: AnimationState):
        """Render the local player with animation."""
        self._render_animated_entity(x, y, anim, {
            'body_image': player.body_image or 'body.png',
            'head_image': player.head_image or 'head0.png',
            'sword_image': player.sword_image or 'sword1.png',
            'shield_image': player.shield_image or 'shield1.png',
        })

        # Render carried object above player's head
        if player.is_carrying():
            self._render_carried_object(x, y, player)

        # Draw player collision box at CURRENT position
        # This shows the player's hitbox, not where collision is checked
        # The hitbox is roughly 0.8 tiles wide, 0.5 tiles tall, centered at feet

        # Current position marker (red dot at feet)
        pygame.draw.circle(self.screen, (255, 0, 0), (int(x), int(y)), 4)

        # Draw collision box around player (at current position)
        # Box extends: left -0.4, right +0.4, up -0.5, down 0
        box_left = x - 0.4 * TILE_SIZE
        box_right = x + 0.4 * TILE_SIZE
        box_top = y - 0.5 * TILE_SIZE
        box_bottom = y
        collision_rect = pygame.Rect(
            int(box_left), int(box_top),
            int(box_right - box_left), int(box_bottom - box_top)
        )
        pygame.draw.rect(self.screen, (0, 255, 0), collision_rect, 2)

        # Draw tile grid around player
        player_tile_x = int(self.client.x)
        player_tile_y = int(self.client.y)
        tile_offset_x = (self.client.x - player_tile_x) * TILE_SIZE
        tile_offset_y = (self.client.y - player_tile_y) * TILE_SIZE

        for ty in range(-2, 4):
            for tx in range(-2, 4):
                grid_x = int(x - tile_offset_x + tx * TILE_SIZE)
                grid_y = int(y - tile_offset_y + ty * TILE_SIZE)
                grid_rect = pygame.Rect(grid_x, grid_y, TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(self.screen, (255, 255, 255, 128), grid_rect, 1)

    def _render_carried_object(self, x: float, y: float, player: Player):
        """Render the 2x2 object the player is carrying above their head."""
        if not player.carried_tile_ids:
            return

        tile_ids = player.carried_tile_ids
        # Render 2x2 tiles above player's head
        # Each tile is TILE_SIZE, so 2x2 = 2*TILE_SIZE x 2*TILE_SIZE
        obj_width = TILE_SIZE * 2
        obj_height = TILE_SIZE * 2

        # Position above player's head, centered
        obj_x = x - obj_width // 2
        obj_y = y - TILE_SIZE - obj_height - 8  # Above head with some padding

        # Render the 4 tiles
        positions = [(0, 0), (1, 0), (0, 1), (1, 1)]
        for i, (dx, dy) in enumerate(positions):
            if i < len(tile_ids):
                tile_id = tile_ids[i]
                tile_surf = self.tileset_mgr.get_tile_or_color(tile_id)
                tile_x = obj_x + dx * TILE_SIZE
                tile_y = obj_y + dy * TILE_SIZE
                self.screen.blit(tile_surf, (tile_x, tile_y))

    def _render_other_player(self, x: float, y: float, pdata: dict, pid: int):
        """Render another player."""
        # Get or create animation state
        if pid not in self.other_player_anims:
            anim = AnimationState(self.gani_parser)
            anim.set_animation("idle", pdata.get('direction', 2))
            self.other_player_anims[pid] = anim

        anim = self.other_player_anims[pid]

        # Update animation based on player state
        player_anim = pdata.get('animation', 'idle')
        if player_anim != anim.gani.name if anim.gani else '':
            anim.set_animation(player_anim, pdata.get('direction', 2))

        self._render_animated_entity(x, y, anim, {
            'body_image': pdata.get('body_image', 'body.png'),
            'head_image': pdata.get('head_image', 'head0.png'),
            'sword_image': pdata.get('sword_image', 'sword1.png'),
            'shield_image': pdata.get('shield_image', 'shield1.png'),
        })

    def _render_npc(self, x: float, y: float, npc: dict, npc_id: int):
        """Render an NPC."""
        gani_name = npc.get('gani', npc.get('animation'))
        image_name = npc.get('image')

        # Parse and cache visual effects from NPC script and image
        if npc_id not in self.npc_effects:
            script = npc.get('script', '')
            self.npc_effects[npc_id] = parse_npc_visual_effects(script, image_name or '')

        effects = self.npc_effects[npc_id]
        is_light = effects.get('drawaslight', False)
        coloreffect = effects.get('coloreffect')  # (r, g, b, a)

        if gani_name:
            # Use animation
            if npc_id not in self.npc_anims:
                anim = AnimationState(self.gani_parser)
                anim.set_animation(gani_name, npc.get('direction', 2))
                self.npc_anims[npc_id] = anim

            anim = self.npc_anims[npc_id]
            self._render_animated_entity(x, y, anim, {})

        elif image_name:
            # Static sprite
            sprite = self.sprite_mgr.load_sheet(image_name)
            if sprite:
                # Apply visual effects for light NPCs
                if is_light or coloreffect:
                    self._render_light_sprite(sprite, x, y, is_light, coloreffect)
                else:
                    self.screen.blit(sprite, (x - 16, y - 16))
            else:
                self.screen.blit(self.npc_placeholder, (x - 16, y - 16))
        else:
            # Placeholder
            self.screen.blit(self.npc_placeholder, (x - 16, y - 16))

    def _render_light_sprite(self, sprite: pygame.Surface, x: float, y: float,
                              is_light: bool, coloreffect: Optional[Tuple[float, float, float, float]]):
        """Render a sprite with light effects (additive blending, alpha).

        Args:
            sprite: The sprite surface to render
            x, y: Position (center of sprite)
            is_light: If True, use additive blending
            coloreffect: (r, g, b, a) multipliers - r,g,b typically 1.0, a is alpha (0-1)
        """
        # Get sprite dimensions for centering
        w, h = sprite.get_size()

        # Create a copy of the sprite for modification
        light_sprite = sprite.copy()

        # Apply color effect (alpha)
        if coloreffect:
            r, g, b, a = coloreffect
            # Alpha is typically like 0.99 (99% opacity but as a light effect)
            alpha = int(a * 255)
            light_sprite.set_alpha(alpha)

        # Position - center the sprite at (x, y)
        # Light sprites are typically larger and centered
        pos_x = x - w // 2
        pos_y = y - h // 2

        if is_light:
            # Render with additive blending for light effect
            self.screen.blit(light_sprite, (pos_x, pos_y), special_flags=pygame.BLEND_ADD)
        else:
            # Just render with alpha
            self.screen.blit(light_sprite, (pos_x, pos_y))

    def _render_animated_entity(self, x: float, y: float, anim: AnimationState,
                                  equipment: dict):
        """Render an entity using gani animation.

        The gani offsets position sprites within a ~48x48 bounding box.
        The player's (x, y) is at their feet (bottom-center).
        We offset the bounding box so feet are at (x, y).
        """
        frame = anim.get_frame() if anim.gani else None

        if not frame:
            # Fallback to placeholder
            self.screen.blit(self.placeholder_sprite, (x - 16, y - 32))
            return

        # Base offset to position bounding box so character feet are at (x, y)
        # The gani positions sprites relative to a bounding box origin.
        # In Reborn, player (x,y) is at the character's feet (bottom-center).
        # Gani shadow at Y=34, body at Y=16 in a ~48-height box.
        # We want the character's feet (around Y=48 in gani coords) to be at screen (x,y).
        base_offset_x = -24  # Center horizontally (half of 48)
        base_offset_y = -46  # Align feet with position (shadow at 34+12=46 is near bottom)

        # Render each sprite in the frame
        for sprite_id, ox, oy in frame.sprites:
            sprite_def = anim.gani.sprites.get(sprite_id)
            if not sprite_def:
                continue

            # Determine which image to use
            layer = sprite_def.layer
            if layer == "BODY":
                img = equipment.get('body_image', anim.gani.defaults.get('BODY', 'body.png'))
            elif layer == "HEAD":
                img = equipment.get('head_image', anim.gani.defaults.get('HEAD', 'head0.png'))
            elif layer == "SWORD":
                img = equipment.get('sword_image', anim.gani.defaults.get('SWORD', 'sword1.png'))
            elif layer == "SHIELD":
                img = equipment.get('shield_image', anim.gani.defaults.get('SHIELD', 'shield1.png'))
            elif layer == "ATTR1":
                img = anim.gani.defaults.get('ATTR1', 'hat0.png')
            elif layer == "SPRITES":
                # Shadow and effects - use defaults
                img = anim.gani.defaults.get('SPRITES', 'sprites.png')
                # Special case: shadow sprite (id 0) - render our shadow
                if sprite_id == 0:
                    screen_x = x + base_offset_x + ox
                    screen_y = y + base_offset_y + oy
                    self.screen.blit(self.shadow_sprite, (screen_x, screen_y))
                    continue
            else:
                img = anim.gani.defaults.get(layer, 'sprites.png')

            # Get sprite from sheet
            sprite = self.sprite_mgr.get_sprite(
                img,
                sprite_def.x, sprite_def.y,
                sprite_def.width, sprite_def.height
            )

            if sprite:
                # Calculate screen position: base offset + gani sprite offset
                screen_x = x + base_offset_x + ox
                screen_y = y + base_offset_y + oy
                self.screen.blit(sprite, (screen_x, screen_y))

    def _render_ui(self):
        """Render UI elements."""
        # Status text
        local_x = self.client.x % 64
        local_y = self.client.y % 64
        status = f"{self.client._current_level_name}  ({local_x:.1f}, {local_y:.1f})"
        self._draw_text_with_bg(status, 10, 10, (255, 255, 255))

        # Hearts display
        hearts_text = f"Hearts: {self.client.player.hearts:.1f}/{self.client.player.max_hearts:.1f}"
        self._draw_text_with_bg(hearts_text, 10, 30, (255, 100, 100))

        # Equipment info
        equip_text = f"Sword: {self.client.player.sword_power}  Shield: {self.client.player.shield_power}  Glove: {self.client.player.glove_power}"
        self._draw_text_with_bg(equip_text, 10, 50, (200, 200, 100))

        # NPCs and Links count
        npc_text = f"NPCs: {len(self.client.npcs)}  Links: {sum(len(l) for l in self.client.links.values())}"
        self._draw_text_with_bg(npc_text, 10, 70, (100, 200, 100))

        # Swimming status
        ui_y = 90
        if self.is_swimming:
            self._draw_text_with_bg("SWIMMING", 10, ui_y, (100, 200, 255))
            ui_y += 20

        # Door prompt
        door = self._get_non_edge_door()
        if door:
            door_text = f"Door -> {door.get('dest_level', '?')} (press A)"
            self._draw_text_with_bg(door_text, 10, ui_y, (255, 255, 100))
            ui_y += 20

        # Carrying status
        player = self.client.player
        if player.is_carrying():
            carry_text = f"Carrying: {player.carried_object_type.title()} (A to throw)"
            self._draw_text_with_bg(carry_text, 10, ui_y, (100, 255, 100))
            ui_y += 20

        # Sitting status
        if player.is_sitting:
            sit_text = "Sitting (press A to stand)"
            self._draw_text_with_bg(sit_text, 10, ui_y, (255, 200, 100))
            ui_y += 20

        # Chat messages
        y = SCREEN_HEIGHT - 60
        for msg in reversed(self.chat_messages[-5:]):
            self._draw_text_with_bg(msg[:60], 10, y, (255, 255, 255), alpha=150)
            y -= 20

        # Chat input
        if self.typing:
            input_text = f"> {self.chat_input}_"
            pygame.draw.rect(self.screen, (0, 0, 0), (5, SCREEN_HEIGHT - 30, SCREEN_WIDTH - 10, 25))
            text = self.font.render(input_text, True, (255, 255, 0))
            self.screen.blit(text, (10, SCREEN_HEIGHT - 25))

        # Help text
        if not self.typing and not self.inventory_ui.visible:
            if self.debug_mode:
                help_text = "1-7: Type | Click: Apply | RClick: Reset | F1: Exit"
                text = self.font_small.render(help_text, True, (255, 255, 0))
            else:
                help_text = "Arrows: Move | A: Grab | S/Space: Sword | Q: Inv | F1: Debug | F2: Warp"
                text = self.font_small.render(help_text, True, (200, 200, 200))
            self.screen.blit(text, (SCREEN_WIDTH - text.get_width() - 10, 10))

        # Debug mode indicator and hover info
        if self.debug_mode:
            # Get selected type name
            selected_type_names = {
                TileType.NONBLOCK: "Walkable",
                TileType.BLOCKING: "Blocking",
                TileType.WATER: "Water",
                TileType.CHAIR: "Chair",
                TileType.BUSH: "Bush",
                TileType.POT: "Pot",
                TileType.ROCK: "Rock",
            }
            selected_name = selected_type_names.get(self.debug_selected_type, "?")
            debug_text = f"TILE EDIT - Selected: {selected_name} - Corrections: {len(self.tile_corrections)}"
            self._draw_text_with_bg(debug_text, SCREEN_WIDTH // 2 - 150, 30, (255, 255, 0))

            # Show tile info under mouse cursor
            mouse_x, mouse_y = pygame.mouse.get_pos()
            tile_info = self._get_tile_info_at_screen_pos(mouse_x, mouse_y)
            if tile_info:
                tile_id, tile_type, tx, ty = tile_info
                type_names = {
                    TileType.NONBLOCK: "Walkable",
                    TileType.BLOCKING: "BLOCKING",
                    TileType.WATER: "Water",
                    TileType.NEAR_WATER: "Shallow",
                    TileType.CHAIR: "Chair",
                    TileType.BUSH: "Bush",
                    TileType.POT: "Pot",
                    TileType.ROCK: "Rock",
                }
                type_name = type_names.get(tile_type, f"Type {tile_type}")
                info_text = f"Tile {tile_id} ({tx},{ty}): {type_name}"
                self._draw_text_with_bg(info_text, mouse_x + 15, mouse_y + 15, (255, 255, 255))

        # Inventory UI
        self.inventory_ui.render(self.client.player, self.weapons)

    def _draw_text_with_bg(self, text: str, x: int, y: int,
                            color: Tuple[int, int, int], alpha: int = 180):
        """Draw text with a semi-transparent background."""
        text_surf = self.font.render(text, True, color)
        bg = pygame.Surface((text_surf.get_width() + 10, text_surf.get_height() + 4))
        bg.fill((0, 0, 0))
        bg.set_alpha(alpha)
        self.screen.blit(bg, (x - 5, y - 2))
        self.screen.blit(text_surf, (x, y))


class LoginScreen:
    """Pygame login screen for entering credentials."""

    # Layout constants
    FIELD_X = 180
    FIELD_WIDTH = 380
    LABEL_X = 70

    def __init__(self):
        # Initialize pygame if not already
        if not pygame.get_init():
            pygame.init()

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("pyreborn - Login")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 28)
        self.font_small = pygame.font.Font(None, 22)
        self.font_title = pygame.font.Font(None, 42)

        # Input fields
        self.username = ""
        self.password = ""
        self.host = "localhost"
        self.port = "14900"
        self.listserver_host = "listserver.example.com"

        # Which field is active
        self.active_field = "username"  # username, password, host, port, listserver
        self.fields = ["username", "password", "host", "port", "listserver"]

        # Connection mode
        self.use_listserver = True  # Default to listserver mode

        # Error message
        self.error_message = ""

        # Store clickable regions
        self.field_rects = {}
        self.mode_toggle_rect = None
        self.connect_btn_rect = None

    def _try_connect(self) -> dict:
        """Attempt to connect and return credentials dict or None."""
        if self.username and self.password:
            return {
                "username": self.username,
                "password": self.password,
                "use_listserver": self.use_listserver,
                "host": self.host,
                "port": int(self.port) if self.port.isdigit() else 14900,
                "listserver_host": self.listserver_host,
            }
        else:
            self.error_message = "Username and password required"
            return None

    def run(self) -> dict:
        """Run the login screen. Returns dict with credentials or None if cancelled."""
        running = True

        while running:
            for event in pygame.event.get():
                if event.type == QUIT:
                    return None

                elif event.type == KEYDOWN:
                    if event.key == K_ESCAPE:
                        return None

                    elif event.key == K_TAB:
                        # Cycle through visible fields only
                        visible_fields = ["username", "password"]
                        if self.use_listserver:
                            visible_fields.append("listserver")
                        else:
                            visible_fields.extend(["host", "port"])

                        if self.active_field not in visible_fields:
                            self.active_field = visible_fields[0]
                        else:
                            idx = visible_fields.index(self.active_field)
                            if pygame.key.get_mods() & KMOD_SHIFT:
                                self.active_field = visible_fields[(idx - 1) % len(visible_fields)]
                            else:
                                self.active_field = visible_fields[(idx + 1) % len(visible_fields)]

                    elif event.key == K_RETURN:
                        result = self._try_connect()
                        if result:
                            return result

                    elif event.key == K_BACKSPACE:
                        self._handle_backspace()

                    elif event.key == K_F1:
                        self.use_listserver = not self.use_listserver

                    elif event.unicode and event.unicode.isprintable():
                        self._handle_char(event.unicode)

                elif event.type == MOUSEBUTTONDOWN:
                    if event.button == 1:
                        result = self._handle_click(event.pos)
                        if result:
                            return result

            self._render()
            self.clock.tick(60)

        return None

    def _handle_backspace(self):
        """Handle backspace key."""
        if self.active_field == "username":
            self.username = self.username[:-1]
        elif self.active_field == "password":
            self.password = self.password[:-1]
        elif self.active_field == "host":
            self.host = self.host[:-1]
        elif self.active_field == "port":
            self.port = self.port[:-1]
        elif self.active_field == "listserver":
            self.listserver_host = self.listserver_host[:-1]
        self.error_message = ""

    def _handle_char(self, char: str):
        """Handle character input."""
        self.error_message = ""
        if self.active_field == "username" and len(self.username) < 30:
            self.username += char
        elif self.active_field == "password" and len(self.password) < 30:
            self.password += char
        elif self.active_field == "host" and len(self.host) < 50:
            self.host += char
        elif self.active_field == "port" and len(self.port) < 5 and char.isdigit():
            self.port += char
        elif self.active_field == "listserver" and len(self.listserver_host) < 50:
            self.listserver_host += char

    def _handle_click(self, pos) -> dict:
        """Handle mouse click. Returns credentials dict if connect clicked, else None."""
        x, y = pos

        # Check field clicks
        for field_name, rect in self.field_rects.items():
            if rect.collidepoint(pos):
                self.active_field = field_name
                self.error_message = ""
                return None

        # Check mode toggle button
        if self.mode_toggle_rect and self.mode_toggle_rect.collidepoint(pos):
            self.use_listserver = not self.use_listserver
            return None

        # Check connect button
        if self.connect_btn_rect and self.connect_btn_rect.collidepoint(pos):
            return self._try_connect()

        return None

    def _render(self):
        """Render the login screen."""
        # Clear clickable regions
        self.field_rects = {}

        # Background
        self.screen.fill((25, 35, 55))

        # Draw decorative panel
        panel_rect = pygame.Rect(60, 60, SCREEN_WIDTH - 120, SCREEN_HEIGHT - 120)
        pygame.draw.rect(self.screen, (35, 50, 75), panel_rect, border_radius=12)
        pygame.draw.rect(self.screen, (60, 90, 130), panel_rect, 2, border_radius=12)

        # Title
        title = self.font_title.render("pyreborn", True, (100, 180, 255))
        self.screen.blit(title, (SCREEN_WIDTH // 2 - title.get_width() // 2, 85))

        subtitle = self.font_small.render("Reborn Client", True, (150, 150, 180))
        self.screen.blit(subtitle, (SCREEN_WIDTH // 2 - subtitle.get_width() // 2, 125))

        # Layout Y positions with proper spacing
        y_username = 165
        y_password = 215
        y_mode_toggle = 265
        y_server_field = 305
        y_connect_btn = 365
        y_error = 420
        y_help = 440

        # Username field
        self._render_field("Username:", self.username, y_username, "username")

        # Password field
        self._render_field("Password:", "*" * len(self.password), y_password, "password")

        # Connection mode toggle
        mode_text = "Listserver Mode" if self.use_listserver else "Direct Connection"
        mode_color = (100, 200, 150) if self.use_listserver else (200, 150, 100)

        self.mode_toggle_rect = pygame.Rect(self.FIELD_X, y_mode_toggle, 200, 28)
        pygame.draw.rect(self.screen, (40, 55, 80), self.mode_toggle_rect, border_radius=5)
        hover = self.mode_toggle_rect.collidepoint(pygame.mouse.get_pos())
        border_col = (100, 150, 200) if hover else (60, 80, 110)
        pygame.draw.rect(self.screen, border_col, self.mode_toggle_rect, 2, border_radius=5)

        mode_label = self.font_small.render("[F1]", True, (120, 120, 140))
        self.screen.blit(mode_label, (self.LABEL_X, y_mode_toggle + 5))
        mode_surf = self.font_small.render(mode_text, True, mode_color)
        self.screen.blit(mode_surf, (self.FIELD_X + 10, y_mode_toggle + 5))

        # Host/port or listserver field
        if self.use_listserver:
            self._render_field("Listserver:", self.listserver_host, y_server_field, "listserver")
        else:
            self._render_field("Host:", self.host, y_server_field, "host", width=220)
            self._render_field("Port:", self.port, y_server_field, "port", x_offset=240, width=80, label_offset=220)

        # Connect button
        btn_width = 180
        btn_x = SCREEN_WIDTH // 2 - btn_width // 2
        self.connect_btn_rect = pygame.Rect(btn_x, y_connect_btn, btn_width, 42)

        has_creds = bool(self.username and self.password)
        btn_hover = self.connect_btn_rect.collidepoint(pygame.mouse.get_pos())

        if has_creds:
            btn_color = (80, 180, 120) if btn_hover else (60, 140, 100)
        else:
            btn_color = (50, 50, 60)

        pygame.draw.rect(self.screen, btn_color, self.connect_btn_rect, border_radius=8)
        border_col = (120, 220, 160) if (has_creds and btn_hover) else (80, 120, 90)
        pygame.draw.rect(self.screen, border_col, self.connect_btn_rect, 2, border_radius=8)

        btn_text = self.font.render("Connect", True, (255, 255, 255) if has_creds else (100, 100, 100))
        self.screen.blit(btn_text, (self.connect_btn_rect.centerx - btn_text.get_width() // 2,
                                     self.connect_btn_rect.centery - btn_text.get_height() // 2))

        # Error message
        if self.error_message:
            error_surf = self.font_small.render(self.error_message, True, (255, 100, 100))
            self.screen.blit(error_surf, (SCREEN_WIDTH // 2 - error_surf.get_width() // 2, y_error))

        # Help text
        help_text = "Tab: Next field  |  Enter: Connect  |  F1: Toggle mode  |  Esc: Quit"
        help_surf = self.font_small.render(help_text, True, (90, 90, 110))
        self.screen.blit(help_surf, (SCREEN_WIDTH // 2 - help_surf.get_width() // 2, y_help))

        pygame.display.flip()

    def _render_field(self, label: str, value: str, y: int, field_name: str,
                      x_offset: int = 0, width: int = None, label_offset: int = 0):
        """Render an input field."""
        if width is None:
            width = self.FIELD_WIDTH

        x = self.FIELD_X + x_offset

        # Label
        label_surf = self.font_small.render(label, True, (180, 180, 200))
        self.screen.blit(label_surf, (self.LABEL_X + label_offset, y + 6))

        # Input box
        is_active = self.active_field == field_name
        box_color = (50, 70, 100) if is_active else (35, 45, 65)
        border_color = (100, 150, 255) if is_active else (60, 80, 110)

        box_rect = pygame.Rect(x, y, width, 32)
        self.field_rects[field_name] = box_rect

        # Hover effect
        if box_rect.collidepoint(pygame.mouse.get_pos()) and not is_active:
            border_color = (80, 120, 180)

        pygame.draw.rect(self.screen, box_color, box_rect, border_radius=5)
        pygame.draw.rect(self.screen, border_color, box_rect, 2, border_radius=5)

        # Text (truncate if too long)
        display_text = value
        max_chars = (width - 20) // 10  # Rough estimate
        if len(display_text) > max_chars:
            display_text = "..." + display_text[-(max_chars - 3):]

        text_surf = self.font.render(display_text, True, (255, 255, 255))
        self.screen.blit(text_surf, (x + 8, y + 5))

        # Blinking cursor
        if is_active:
            cursor_x = x + 8 + text_surf.get_width() + 2
            if cursor_x < x + width - 5:  # Don't draw cursor outside box
                if pygame.time.get_ticks() % 1000 < 500:
                    pygame.draw.line(self.screen, (255, 255, 255),
                                   (cursor_x, y + 6), (cursor_x, y + 24), 2)


class ServerSelectScreen:
    """Pygame screen for selecting a server from the listserver."""

    def __init__(self, servers: list, username: str):
        self.servers = servers
        self.username = username
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible = 10

        # Initialize pygame if not already
        if not pygame.get_init():
            pygame.init()

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("pyreborn - Server Select")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 28)
        self.font_small = pygame.font.Font(None, 22)
        self.font_title = pygame.font.Font(None, 42)

    def run(self) -> ServerEntry:
        """Run the server selection screen. Returns selected server or None."""
        running = True

        while running:
            for event in pygame.event.get():
                if event.type == QUIT:
                    return None

                elif event.type == KEYDOWN:
                    if event.key == K_ESCAPE:
                        return None

                    elif event.key == K_UP:
                        self.selected_index = max(0, self.selected_index - 1)
                        # Scroll up if needed
                        if self.selected_index < self.scroll_offset:
                            self.scroll_offset = self.selected_index

                    elif event.key == K_DOWN:
                        self.selected_index = min(len(self.servers) - 1, self.selected_index + 1)
                        # Scroll down if needed
                        if self.selected_index >= self.scroll_offset + self.max_visible:
                            self.scroll_offset = self.selected_index - self.max_visible + 1

                    elif event.key == K_RETURN or event.key == K_SPACE:
                        if self.servers:
                            return self.servers[self.selected_index]

                elif event.type == MOUSEBUTTONDOWN:
                    if event.button == 1:  # Left click
                        # Check if clicked on a server entry
                        mouse_y = event.pos[1]
                        entry_start_y = 120
                        entry_height = 50

                        for i in range(min(self.max_visible, len(self.servers) - self.scroll_offset)):
                            entry_y = entry_start_y + i * entry_height
                            if entry_y <= mouse_y < entry_y + entry_height:
                                clicked_index = self.scroll_offset + i
                                if clicked_index == self.selected_index:
                                    # Double-click effect - select
                                    return self.servers[self.selected_index]
                                else:
                                    self.selected_index = clicked_index
                                break

            self._render()
            self.clock.tick(60)

        return None

    def _render(self):
        """Render the server selection screen."""
        # Background
        self.screen.fill((20, 30, 50))

        # Title
        title = self.font_title.render("Select Server", True, (255, 255, 255))
        self.screen.blit(title, (SCREEN_WIDTH // 2 - title.get_width() // 2, 20))

        # User info
        user_text = self.font_small.render(f"Logged in as: {self.username}", True, (150, 200, 255))
        self.screen.blit(user_text, (SCREEN_WIDTH // 2 - user_text.get_width() // 2, 60))

        # Server count
        count_text = self.font_small.render(f"{len(self.servers)} servers available", True, (150, 150, 150))
        self.screen.blit(count_text, (SCREEN_WIDTH // 2 - count_text.get_width() // 2, 85))

        # Server list
        y = 120
        visible_servers = self.servers[self.scroll_offset:self.scroll_offset + self.max_visible]

        for i, server in enumerate(visible_servers):
            actual_index = self.scroll_offset + i
            is_selected = actual_index == self.selected_index

            # Background for entry
            bg_color = (50, 70, 100) if is_selected else (30, 40, 60)
            pygame.draw.rect(self.screen, bg_color, (20, y, SCREEN_WIDTH - 40, 45), border_radius=5)

            if is_selected:
                # Selection border
                pygame.draw.rect(self.screen, (100, 150, 255), (20, y, SCREEN_WIDTH - 40, 45), 2, border_radius=5)

            # Server type indicator
            type_colors = {
                "": (100, 100, 100),      # Normal
                "H ": (205, 127, 50),     # Bronze
                "P ": (255, 215, 0),      # Gold
                "3 ": (100, 200, 255),    # G3D
                "U ": (100, 100, 100),    # Hidden
            }
            type_color = type_colors.get(server.type_prefix, (100, 100, 100))

            # Type badge
            if server.type_prefix.strip():
                badge_text = server.type_prefix.strip()
                badge = self.font_small.render(badge_text, True, type_color)
                pygame.draw.rect(self.screen, (20, 25, 35), (30, y + 5, 25, 18), border_radius=3)
                self.screen.blit(badge, (35, y + 6))

            # Server name
            name_x = 65 if server.type_prefix.strip() else 30
            name = self.font.render(server.name, True, (255, 255, 255))
            self.screen.blit(name, (name_x, y + 5))

            # Server info line
            info = f"{server.player_count} players  |  {server.language}  |  {server.ip}:{server.port}"
            info_text = self.font_small.render(info, True, (150, 150, 150))
            self.screen.blit(info_text, (30, y + 26))

            y += 50

        # Scroll indicators
        if self.scroll_offset > 0:
            arrow_up = self.font.render("▲ More servers above", True, (100, 150, 200))
            self.screen.blit(arrow_up, (SCREEN_WIDTH // 2 - arrow_up.get_width() // 2, 100))

        if self.scroll_offset + self.max_visible < len(self.servers):
            arrow_down = self.font.render("▼ More servers below", True, (100, 150, 200))
            self.screen.blit(arrow_down, (SCREEN_WIDTH // 2 - arrow_down.get_width() // 2, SCREEN_HEIGHT - 60))

        # Instructions
        help_text = "↑/↓: Navigate  |  Enter: Connect  |  Esc: Cancel"
        help_surf = self.font_small.render(help_text, True, (100, 100, 100))
        self.screen.blit(help_surf, (SCREEN_WIDTH // 2 - help_surf.get_width() // 2, SCREEN_HEIGHT - 30))

        pygame.display.flip()


def show_loading_screen(message: str):
    """Show a simple loading screen."""
    if not pygame.get_init():
        pygame.init()

    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("pyreborn")
    font = pygame.font.Font(None, 36)

    screen.fill((20, 30, 50))
    text = font.render(message, True, (255, 255, 255))
    screen.blit(text, (SCREEN_WIDTH // 2 - text.get_width() // 2, SCREEN_HEIGHT // 2 - 20))
    pygame.display.flip()

    # Process events to prevent "not responding"
    pygame.event.pump()


def main():
    """Main entry point."""
    # Check for command line arguments
    username = None
    password = None
    use_listserver = False
    listserver_host = "listserver.example.com"
    listserver_port = 14922
    host = "localhost"
    port = 14900

    if len(sys.argv) >= 3:
        # Credentials provided via command line
        username = sys.argv[1]
        password = sys.argv[2]

        args = sys.argv[3:]
        if "--listserver" in args or "-l" in args:
            use_listserver = True
            flag_idx = args.index("--listserver") if "--listserver" in args else args.index("-l")
            if flag_idx + 1 < len(args) and not args[flag_idx + 1].startswith("-"):
                listserver_host = args[flag_idx + 1]
        else:
            if len(args) >= 1:
                host = args[0]
            if len(args) >= 2:
                port = int(args[1])
    else:
        # No credentials - show login screen
        print("Starting login screen...")
        print("Usage (optional): python -m pyreborn.example_pygame [user] [pass] [--listserver [host]]")

        login_screen = LoginScreen()
        login_result = login_screen.run()

        if not login_result:
            print("Login cancelled.")
            pygame.quit()
            sys.exit(0)

        username = login_result["username"]
        password = login_result["password"]
        use_listserver = login_result["use_listserver"]
        host = login_result["host"]
        port = login_result["port"]
        listserver_host = login_result["listserver_host"]

        # Clean up pygame for re-init
        pygame.quit()

    if use_listserver:
        # Listserver mode - authenticate and show server selection
        print(f"Connecting to listserver at {listserver_host}:{listserver_port}...")
        show_loading_screen(f"Connecting to {listserver_host}...")

        ls = ListServerClient(listserver_host, listserver_port)
        response = ls.login(username, password)

        if not response.success:
            print(f"Listserver login failed: {response.error}")
            pygame.quit()
            sys.exit(1)

        print(f"Login successful! {response.status}")
        print(f"Found {len(response.servers)} servers")

        if not response.servers:
            print("No servers available!")
            pygame.quit()
            sys.exit(1)

        # Show server selection screen
        select_screen = ServerSelectScreen(response.servers, username)
        selected_server = select_screen.run()

        if not selected_server:
            print("No server selected, exiting.")
            pygame.quit()
            sys.exit(0)

        print(f"Selected: {selected_server.display_name}")
        host = selected_server.ip
        port = selected_server.port

        # Clean up pygame for re-init by GameClient
        pygame.quit()

    # Connect to game server
    print(f"Connecting to {host}:{port}...")
    client = Client(host, port, version="6.037")

    if not client.connect():
        print("Failed to connect!")
        sys.exit(1)

    print(f"Logging in as {username}...")
    if not client.login(username, password):
        print("Login failed!")
        client.disconnect()
        sys.exit(1)

    print(f"Logged in! Level: {client.level}, Position: ({client.x:.1f}, {client.y:.1f})")

    # Load GMAP if available
    gmap_name = client.level if client.level.endswith('.gmap') else None
    if gmap_name:
        cache_path = f"cache/levels/{host}_{port}/{gmap_name}"
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                client.load_gmap(f.read())
            client._gmap_base_level = client._current_level_name
            print(f"Loaded GMAP: {client.gmap_width}x{client.gmap_height} grid")

            # Request adjacent levels
            count = client.request_adjacent_levels()
            print(f"Requesting {count} adjacent levels...")
            for _ in range(30):
                client.update(timeout=0.1)
            print(f"Loaded {len(client.levels)} levels")

    # Create and run game client
    print("\nStarting game client...")
    print("Controls: Arrows=Move, A=Grab, S/Space=Sword, D=Weapon, Q=Inventory")
    game = GameClient(client)
    game.run()

    print("Disconnected.")


if __name__ == "__main__":
    main()
