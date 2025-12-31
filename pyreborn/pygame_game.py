"""
Pygame game client for pyreborn.

Contains the main GameClient class that handles rendering, input, and game logic.
"""

import time
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame
from pygame.locals import (
    QUIT, KEYDOWN, MOUSEBUTTONDOWN,
    K_ESCAPE, K_RETURN, K_q, K_a, K_s, K_d, K_SPACE,
    K_UP, K_DOWN, K_LEFT, K_RIGHT,
    K_F1, K_F2, K_1, K_2, K_3, K_4, K_5, K_6, K_7
)

from . import Client
from .gani import GaniParser, AnimationState, direction_from_delta
from .sprites import SpriteManager, TilesetManager, create_placeholder_sprite, create_shadow_sprite
from .sounds import SoundManager, preload_common_sounds
from .inventory_ui import InventoryUI, HeartDisplay
from .npc_handler import NPCHandler
from .gs1_interpreter import GS1Interpreter
from .player import Player
from .tiletypes import TileType, get_tile_type

# Tile type corrections file
TILE_CORRECTIONS_FILE = Path(__file__).parent / "tile_corrections.json"

# Constants
TILE_SIZE = 16
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 480
TILESET_COLS = 128
TILESET_ROWS = 32


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
        # Visual positions for other players (for smooth interpolation)
        self.other_player_visual: Dict[int, Tuple[float, float]] = {}

        # Animation states for NPCs
        self.npc_anims: Dict[int, AnimationState] = {}
        # Visual positions for NPCs (for smooth interpolation)
        self.npc_visual: Dict[int, Tuple[float, float]] = {}

        # Visual effects for NPCs (drawaslight, setcoloreffect)
        self.npc_effects: Dict[int, dict] = {}

        # NPC handler for touch detection and script execution
        self.npc_handler = NPCHandler(self.client)

        # GS1 interpreter for NPC scripts
        self.gs1 = GS1Interpreter(self.client)
        self._setup_gs1_callbacks()

        # UI components
        self.inventory_ui = InventoryUI(self.screen, self.sprite_mgr)
        self.heart_display = HeartDisplay(10, 30)

        # Input state
        self.typing = False
        self.chat_input = ""
        self.chat_messages: List[str] = []

        # Timing
        self.last_move_time = 0.0
        self.move_delay = 0.016  # 16ms between moves (~60 updates/sec, 0.25 steps = 15 tiles/sec)
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

        # Combat effects - floating damage numbers
        # Each entry: {'x': float, 'y': float, 'damage': float, 'time': float, 'duration': float}
        self.damage_numbers: List[dict] = []
        self.hurt_flash_time = 0.0  # Time when player was last hurt (for flash effect)

        # Active bombs - each: {'x': float, 'y': float, 'time': float, 'power': int, 'exploded': bool}
        self.active_bombs: List[dict] = []
        self.bomb_fuse_time = 2.0  # Seconds before bomb explodes
        self.explosion_duration = 0.5  # How long explosion visual lasts

        # Active projectiles - each: {'x': float, 'y': float, 'dx': float, 'dy': float, 'time': float, 'gani': str}
        self.active_projectiles: List[dict] = []

        # Dialogue box state (for say2/signs)
        self.dialogue_text: Optional[str] = None
        self.dialogue_time: float = 0.0
        self.dialogue_duration: float = 5.0  # Auto-dismiss after 5 seconds

        # Speech bubble state (for say/chat - shows above entity heads)
        self.local_chat_text: str = ""  # Local player's chat bubble
        self.local_chat_time: float = 0.0
        self.npc_chat_texts: Dict[int, Tuple[str, float]] = {}  # npc_id -> (text, time)
        self.chat_bubble_duration: float = 4.0  # How long chat bubbles stay visible

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

        self.client.on_chat = on_chat
        self.client.on_hurt = on_hurt

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
        # Blocking includes solid walls and objects like bushes, rocks, pots
        return tile_type in (
            TileType.BLOCKING,
            TileType.BED_UPPER,
            TileType.BED_LOWER,
            TileType.THROW_THROUGH,
            TileType.BUSH,
            TileType.ROCK,
            TileType.POT,
        )

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

        # Load NPC scripts and trigger playerenters events
        self._load_npc_scripts()
        self._trigger_playerenters()

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

            # Check for respawn (death -> alive transition)
            if hasattr(self, '_was_dead') and self._was_dead and self.client.player.hearts > 0:
                # We respawned! Reset animation to idle
                self.player_anim.set_animation("idle", self.client.player.direction)
                self._was_dead = False
            # Track death state
            self._was_dead = self.client.player.hearts <= 0

            # Update swimming state (in case of server-side warps)
            self._update_swimming_state()

            # Update visual position (smooth interpolation)
            self._update_visual_position(dt)

            # Update animations
            self._update_animations(dt)

            # Update and render projectiles (needs dt for movement)
            self._last_dt = dt

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
                # Set local player's chat bubble
                self.local_chat_text = self.chat_input
                self.local_chat_time = time.time()
                # Also add to chat log
                self.chat_messages.append(f"[You] {self.chat_input}")
                if len(self.chat_messages) > 10:
                    self.chat_messages.pop(0)
            self.chat_input = ""
            self.typing = False
        elif event.key == K_ESCAPE:
            self.chat_input = ""
            self.typing = False
        elif event.key == pygame.K_BACKSPACE:
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

        # Update direction
        direction = direction_from_delta(dx, dy)

        # Check NPC touch after movement
        self.npc_handler.process_movement(self.client.x, self.client.y, direction)

        # Update swimming state after move
        self._update_swimming_state()
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

        # Check for door link at new position (auto-warp on walk-into)
        door_link = self._get_non_edge_door()
        if door_link:
            self._use_door_link(door_link)

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

        # Check for sign NPC nearby
        sign_text = self._check_sign_nearby()
        if sign_text:
            # Display sign text in dialogue box
            self._show_dialogue(sign_text)
            return

        # Check for door link
        door_link = self._get_non_edge_door()
        if door_link:
            self._use_door_link(door_link)
            return

        # Try to pickup item at current position
        self.client.pickup_item()

    def _check_sign_nearby(self) -> Optional[str]:
        """Check for sign NPC nearby and return its text if found."""
        import re
        player = self.client.player
        px, py = player.x, player.y

        # Check in front of player based on direction
        dx_map = {0: 0, 1: -1, 2: 0, 3: 1}
        dy_map = {0: -1, 1: 0, 2: 1, 3: 0}
        check_x = px + dx_map.get(player.direction, 0)
        check_y = py + dy_map.get(player.direction, 0)

        for npc_id, npc in self.client.npcs.items():
            npc_x = npc.get('x', 0)
            npc_y = npc.get('y', 0)

            # Check if NPC is close to check position
            if abs(npc_x - check_x) < 1.5 and abs(npc_y - check_y) < 1.5:
                # Check if this NPC is a sign (has signlink or setplayerprop #c)
                script = npc.get('script', '')
                image = npc.get('image', '')

                # Look for sign-like images
                if 'sign' in image.lower():
                    # Extract message from script
                    match = re.search(r'setplayerprop\s+#c\s*,?\s*([^;]+)', script, re.IGNORECASE)
                    if match:
                        return match.group(1).strip()
                    # Try to find any text in the script
                    match = re.search(r'message\s+([^;]+)', script, re.IGNORECASE)
                    if match:
                        return match.group(1).strip()
                    # Default to NPC image name if it's a sign
                    return f"(Sign: {image})"

        return None

    def _show_dialogue(self, text: str):
        """Show dialogue text in the dialogue box."""
        self.dialogue_text = text
        self.dialogue_time = time.time()

    def _dismiss_dialogue(self):
        """Dismiss the current dialogue."""
        self.dialogue_text = None

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
                # Spawn visual projectile
                import math
                direction = self.client.player.direction
                speed = 8.0  # Tiles per second
                # Direction to velocity
                dx_map = {0: 0, 1: -speed, 2: 0, 3: speed}
                dy_map = {0: -speed, 1: 0, 2: speed, 3: 0}
                self.active_projectiles.append({
                    'x': self.client.player.x,
                    'y': self.client.player.y,
                    'dx': dx_map.get(direction, 0),
                    'dy': dy_map.get(direction, 0),
                    'time': time.time(),
                    'direction': direction,
                    'gani': 'arrow',
                    'max_distance': 10.0,  # Max distance in tiles
                    'start_x': self.client.player.x,
                    'start_y': self.client.player.y,
                })
            elif "bomb" in weapon.lower():
                self.client.drop_bomb(self.client.player.bomb_power)
                # Spawn visual bomb at player position
                self.active_bombs.append({
                    'x': self.client.player.x,
                    'y': self.client.player.y,
                    'time': time.time(),
                    'power': self.client.player.bomb_power,
                    'exploded': False,
                })
            else:
                # Default to sword attack
                self.client.sword_attack(self.client.player.direction)

    def _cycle_weapon(self):
        """Cycle through available weapons."""
        self.inventory_ui.cycle_weapon(self.weapons)

    def _use_door_link(self, door_link: dict):
        """Use a door link to warp to another level."""
        self.client.use_link(door_link)
        # Update visual position to match new position
        self.visual_x = self.client.x
        self.visual_y = self.client.y
        # Force world surface redraw
        self.world_surface = None
        # Load and trigger NPC scripts for new level
        self._load_npc_scripts()
        self._trigger_playerenters()
        self.npc_handler.trigger_playerenters()

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

        Player world position (x, y) is TOP-LEFT of sprite.
        Collision happens at feet: +1 tile right, +3 tiles down from position.
        """
        # Offset from entity position to feet position
        feet_offset_x = 1.0  # Center of 2-tile wide sprite
        feet_offset_y = 3.0  # Bottom of 3-tile tall sprite

        check_offsets = []

        # Check at center (feet position) - no extra offset in movement direction
        if dx < 0:  # Moving left
            check_offsets.append((feet_offset_x, feet_offset_y))
        elif dx > 0:  # Moving right
            check_offsets.append((feet_offset_x, feet_offset_y))

        if dy < 0:  # Moving up
            check_offsets.append((feet_offset_x, feet_offset_y))
        elif dy > 0:  # Moving down
            check_offsets.append((feet_offset_x, feet_offset_y))

        # If no direction, just check feet position (standing still)
        if not check_offsets:
            check_offsets = [(feet_offset_x, feet_offset_y)]

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

        # Render combat effects (damage numbers, bombs, projectiles)
        self._render_damage_numbers()
        self._render_bombs()
        self._update_and_render_projectiles(getattr(self, '_last_dt', 0.016))

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

        # Add other players - convert their local coords to world coords
        for pid, pdata in self.client.players.items():
            if 'x' in pdata and 'y' in pdata:
                ox = pdata.get('x')
                oy = pdata.get('y')

                if ox is None or oy is None:
                    continue

                # Convert to world coords based on their level in GMAP
                player_level = pdata.get('level', '')
                world_x, world_y = ox, oy

                if self.client.gmap_grid:
                    found = False
                    if player_level:
                        for (gx, gy), level_name in self.client.gmap_grid.items():
                            if level_name == player_level:
                                world_x = ox + gx * 64
                                world_y = oy + gy * 64
                                found = True
                                break

                    # If no level set, assume same sub-level as local player
                    if not found and self.client._current_level_name:
                        for (gx, gy), level_name in self.client.gmap_grid.items():
                            if level_name == self.client._current_level_name:
                                world_x = ox + gx * 64
                                world_y = oy + gy * 64
                                break

                # Smooth interpolation for other players
                if pid in self.other_player_visual:
                    vx, vy = self.other_player_visual[pid]
                    # Interpolate toward target position
                    lerp = min(1.0, self.lerp_speed * 0.033)  # Assume ~30fps
                    vx += (world_x - vx) * lerp
                    vy += (world_y - vy) * lerp
                    self.other_player_visual[pid] = (vx, vy)
                else:
                    # First time seeing this player, snap to position
                    vx, vy = world_x, world_y
                    self.other_player_visual[pid] = (vx, vy)

                opx = vx * TILE_SIZE + cam_offset_x
                opy = vy * TILE_SIZE + cam_offset_y
                entities.append(('other', vy, opx, opy, pdata, pid))

        # Add NPCs - use world coords if available (for GMAP), else local
        for npc_id, npc in self.client.npcs.items():
            # Prefer world coords (converted from local + grid offset)
            nx = npc.get('world_x', npc.get('x'))
            ny = npc.get('world_y', npc.get('y'))
            if nx is not None and ny is not None:
                # Interpolate NPC position for smooth movement
                if npc_id in self.npc_visual:
                    vx, vy = self.npc_visual[npc_id]
                    lerp = min(1.0, self.lerp_speed * 0.033)
                    vx += (nx - vx) * lerp
                    vy += (ny - vy) * lerp
                    self.npc_visual[npc_id] = (vx, vy)
                else:
                    vx, vy = nx, ny
                    self.npc_visual[npc_id] = (vx, vy)

                npx = vx * TILE_SIZE + cam_offset_x
                npy = vy * TILE_SIZE + cam_offset_y
                entities.append(('npc', vy, npx, npy, npc, npc_id))

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

    def _render_damage_numbers(self):
        """Render floating damage numbers."""
        current_time = time.time()

        # Get camera offset
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64
        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE
        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        # Update and render each damage number
        active_numbers = []
        for dmg in self.damage_numbers:
            elapsed = current_time - dmg['time']
            if elapsed < dmg['duration']:
                # Calculate position (float up over time)
                float_offset = elapsed * 30  # Float up 30 pixels per second
                alpha = int(255 * (1.0 - elapsed / dmg['duration']))

                # Convert world position to screen position
                screen_x = dmg['x'] * TILE_SIZE + cam_offset_x
                screen_y = (dmg['y'] * TILE_SIZE + cam_offset_y) - float_offset

                # Render damage text
                damage_text = str(int(dmg['damage'] * 2))  # Display as half-hearts
                text_surf = self.font.render(damage_text, True, (255, 50, 50))
                text_surf.set_alpha(alpha)

                # Shadow
                shadow_surf = self.font.render(damage_text, True, (0, 0, 0))
                shadow_surf.set_alpha(alpha)

                self.screen.blit(shadow_surf, (screen_x + 1, screen_y + 1))
                self.screen.blit(text_surf, (screen_x, screen_y))

                active_numbers.append(dmg)

        self.damage_numbers = active_numbers

    def _render_bombs(self):
        """Render active bombs and explosions."""
        current_time = time.time()

        # Get camera offset
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64
        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE
        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        active_bombs = []
        for bomb in self.active_bombs:
            elapsed = current_time - bomb['time']

            # Convert world position to screen position
            screen_x = bomb['x'] * TILE_SIZE + cam_offset_x
            screen_y = bomb['y'] * TILE_SIZE + cam_offset_y

            if not bomb['exploded'] and elapsed < self.bomb_fuse_time:
                # Bomb is still counting down - render bomb sprite
                # Flash faster as fuse runs out
                flash_rate = 5 + (elapsed / self.bomb_fuse_time) * 10
                if int(elapsed * flash_rate) % 2 == 0:
                    # Draw bomb (simple circle for now)
                    pygame.draw.circle(self.screen, (50, 50, 50), (int(screen_x), int(screen_y)), 8)
                    pygame.draw.circle(self.screen, (30, 30, 30), (int(screen_x), int(screen_y)), 6)
                    # Fuse spark
                    fuse_x = screen_x + 4
                    fuse_y = screen_y - 8
                    pygame.draw.circle(self.screen, (255, 200, 50), (int(fuse_x), int(fuse_y)), 3)
                active_bombs.append(bomb)

            elif elapsed < self.bomb_fuse_time + self.explosion_duration:
                # Explosion phase
                if not bomb['exploded']:
                    bomb['exploded'] = True
                    # Play explosion sound
                    self.sound_mgr.play("explode.wav")

                explosion_elapsed = elapsed - self.bomb_fuse_time
                explosion_progress = explosion_elapsed / self.explosion_duration

                # Expanding explosion radius
                radius = int(16 + bomb['power'] * 16 * explosion_progress)
                alpha = int(255 * (1.0 - explosion_progress))

                # Draw explosion circles
                explosion_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
                pygame.draw.circle(explosion_surf, (255, 150, 50, alpha), (radius, radius), radius)
                pygame.draw.circle(explosion_surf, (255, 100, 0, alpha), (radius, radius), int(radius * 0.7))
                pygame.draw.circle(explosion_surf, (255, 200, 100, alpha), (radius, radius), int(radius * 0.4))

                self.screen.blit(explosion_surf, (screen_x - radius, screen_y - radius))
                active_bombs.append(bomb)
            # else: bomb finished, don't add to active list

        self.active_bombs = active_bombs

    def _update_and_render_projectiles(self, dt: float):
        """Update and render active projectiles."""
        current_time = time.time()

        # Get camera offset
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64
        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE
        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        active_projectiles = []
        for proj in self.active_projectiles:
            # Update position
            proj['x'] += proj['dx'] * dt
            proj['y'] += proj['dy'] * dt

            # Check if projectile exceeded max distance
            dist_x = proj['x'] - proj['start_x']
            dist_y = proj['y'] - proj['start_y']
            distance = (dist_x ** 2 + dist_y ** 2) ** 0.5

            if distance < proj['max_distance']:
                # Convert world position to screen position
                screen_x = proj['x'] * TILE_SIZE + cam_offset_x
                screen_y = proj['y'] * TILE_SIZE + cam_offset_y

                # Draw arrow based on direction
                direction = proj['direction']
                if direction == 0:  # up
                    points = [(screen_x, screen_y - 8), (screen_x - 3, screen_y + 4), (screen_x + 3, screen_y + 4)]
                elif direction == 1:  # left
                    points = [(screen_x - 8, screen_y), (screen_x + 4, screen_y - 3), (screen_x + 4, screen_y + 3)]
                elif direction == 2:  # down
                    points = [(screen_x, screen_y + 8), (screen_x - 3, screen_y - 4), (screen_x + 3, screen_y - 4)]
                else:  # right
                    points = [(screen_x + 8, screen_y), (screen_x - 4, screen_y - 3), (screen_x - 4, screen_y + 3)]

                pygame.draw.polygon(self.screen, (139, 69, 19), points)  # Brown arrow
                pygame.draw.polygon(self.screen, (80, 40, 10), points, 1)  # Outline

                active_projectiles.append(proj)

        self.active_projectiles = active_projectiles

    def _render_player(self, x: float, y: float, player: Player, anim: AnimationState):
        """Render the local player with animation."""
        # Check if player should flash (hurt effect)
        hurt_elapsed = time.time() - self.hurt_flash_time
        hurt_visible = True
        if hurt_elapsed < 0.5:  # Flash for 0.5 seconds
            # Blink every 0.1 seconds
            hurt_visible = int(hurt_elapsed * 10) % 2 == 0

        if hurt_visible:
            self._render_animated_entity(x, y, anim, {
                'body_image': player.body_image or 'body.png',
                'head_image': player.head_image or 'head0.png',
                'sword_image': player.sword_image or 'sword1.png',
                'shield_image': player.shield_image or 'shield1.png',
            })

        # Render carried object above player's head
        if player.is_carrying():
            self._render_carried_object(x, y, player)

        # Render local player's chat bubble (if active and not timed out)
        if self.local_chat_text and time.time() - self.local_chat_time < self.chat_bubble_duration:
            self._render_speech_bubble(x, y, self.local_chat_text)

        # Render nickname below local player
        nickname = player.nickname or player.account
        if nickname:
            name_surf = self.font_small.render(nickname, True, (255, 255, 255))
            name_x = x - name_surf.get_width() // 2 + 16
            name_y = y + 48
            shadow_surf = self.font_small.render(nickname, True, (0, 0, 0))
            self.screen.blit(shadow_surf, (name_x + 1, name_y + 1))
            self.screen.blit(name_surf, (name_x, name_y))

        # Draw player collision box at feet position
        # Entity position (x, y) is TOP-LEFT of sprite bounding box
        # Player sprite is ~2 tiles wide, ~3 tiles tall
        # Feet/shadow are at BOTTOM-CENTER: +1 tile right, +3 tiles down
        feet_x = x + TILE_SIZE  # Center of sprite width
        feet_y = y + TILE_SIZE * 3  # Bottom of sprite height

        # Current position marker (red dot at feet)
        pygame.draw.circle(self.screen, (255, 0, 0), (int(feet_x), int(feet_y)), 4)

        # Draw collision box around player (at feet position)
        # Box extends: left -0.3, right +0.3, up -0.5, down 0 (narrow for 2-tile paths)
        box_left = feet_x - 0.3 * TILE_SIZE
        box_right = feet_x + 0.3 * TILE_SIZE
        box_top = feet_y - 0.5 * TILE_SIZE
        box_bottom = feet_y
        collision_rect = pygame.Rect(
            int(box_left), int(box_top),
            int(box_right - box_left), int(box_bottom - box_top)
        )
        pygame.draw.rect(self.screen, (0, 255, 0), collision_rect, 2)

        # Draw tile grid around player feet
        # Feet world position = entity position + (1, 3) tiles
        feet_world_x = self.client.x + 1.0
        feet_world_y = self.client.y + 3.0
        feet_tile_x = int(feet_world_x)
        feet_tile_y = int(feet_world_y)
        tile_offset_x = (feet_world_x - feet_tile_x) * TILE_SIZE
        tile_offset_y = (feet_world_y - feet_tile_y) * TILE_SIZE

        for ty in range(-3, 2):
            for tx in range(-2, 3):
                grid_x = int(feet_x - tile_offset_x + tx * TILE_SIZE)
                grid_y = int(feet_y - tile_offset_y + ty * TILE_SIZE)
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
        # Get animation name - could be 'ani' or 'animation'
        player_anim = pdata.get('ani') or pdata.get('animation') or 'idle'
        # Get direction from sprite prop (lower 2 bits) or direction field
        direction = pdata.get('direction', 2)
        if 'sprite' in pdata:
            direction = pdata['sprite'] & 0x03  # Lower 2 bits = direction

        # Get or create animation state
        if pid not in self.other_player_anims:
            anim = AnimationState(self.gani_parser)
            anim.set_animation(player_anim, direction)
            self.other_player_anims[pid] = anim

        anim = self.other_player_anims[pid]

        # Update animation if changed
        current_name = anim.gani.name if anim.gani else ''
        if player_anim != current_name or anim.direction != direction:
            anim.set_animation(player_anim, direction)

        self._render_animated_entity(x, y, anim, {
            'body_image': pdata.get('body_image', 'body.png'),
            'head_image': pdata.get('head_image', 'head0.png'),
            'sword_image': pdata.get('sword_image', 'sword1.png'),
            'shield_image': pdata.get('shield_image', 'shield1.png'),
        })

        # Render chat bubble above player (if they have chat text)
        chat_text = pdata.get('chat', '')
        if chat_text:
            self._render_speech_bubble(x, y, chat_text)

        # Render nickname below player
        nickname = pdata.get('nick') or pdata.get('account') or ''
        if nickname:
            name_surf = self.font_small.render(nickname, True, (255, 255, 255))
            # Center name below player (player sprite is ~48 pixels tall)
            name_x = x - name_surf.get_width() // 2 + 16
            name_y = y + 48
            # Add shadow for readability
            shadow_surf = self.font_small.render(nickname, True, (0, 0, 0))
            self.screen.blit(shadow_surf, (name_x + 1, name_y + 1))
            self.screen.blit(name_surf, (name_x, name_y))

    def _render_speech_bubble(self, x: float, y: float, text: str):
        """Render a speech bubble above an entity."""
        if not text:
            return

        # Render text with word wrapping (max ~15 chars per line)
        max_width = 120
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            test_surf = self.font_small.render(test_line, True, (0, 0, 0))
            if test_surf.get_width() > max_width and current_line:
                lines.append(current_line)
                current_line = word
            else:
                current_line = test_line

        if current_line:
            lines.append(current_line)

        # Limit to 3 lines max
        lines = lines[:3]

        # Calculate bubble dimensions
        line_height = 14
        padding = 4
        bubble_height = len(lines) * line_height + padding * 2
        bubble_width = max(self.font_small.render(line, True, (0, 0, 0)).get_width() for line in lines) + padding * 2

        # Position bubble above entity (centered, above head)
        bubble_x = x + 16 - bubble_width // 2
        bubble_y = y - bubble_height - 8

        # Draw bubble background (white with black border)
        pygame.draw.rect(self.screen, (255, 255, 255),
                        (bubble_x, bubble_y, bubble_width, bubble_height))
        pygame.draw.rect(self.screen, (0, 0, 0),
                        (bubble_x, bubble_y, bubble_width, bubble_height), 1)

        # Draw small triangle pointer
        pointer_x = x + 16
        pygame.draw.polygon(self.screen, (255, 255, 255), [
            (pointer_x - 4, bubble_y + bubble_height),
            (pointer_x + 4, bubble_y + bubble_height),
            (pointer_x, bubble_y + bubble_height + 6)
        ])
        pygame.draw.lines(self.screen, (0, 0, 0), False, [
            (pointer_x - 4, bubble_y + bubble_height),
            (pointer_x, bubble_y + bubble_height + 6),
            (pointer_x + 4, bubble_y + bubble_height)
        ], 1)

        # Draw text lines
        for i, line in enumerate(lines):
            text_surf = self.font_small.render(line, True, (0, 0, 0))
            text_x = bubble_x + padding
            text_y = bubble_y + padding + i * line_height
            self.screen.blit(text_surf, (text_x, text_y))

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
            # Static sprite - position at top-left of NPC coords (no offset)
            sprite = self.sprite_mgr.load_sheet(image_name)
            if sprite:
                # Apply visual effects for light NPCs
                if is_light or coloreffect:
                    self._render_light_sprite(sprite, x, y, is_light, coloreffect)
                else:
                    self.screen.blit(sprite, (x, y))
            else:
                self.screen.blit(self.npc_placeholder, (x, y))
        else:
            # Placeholder
            self.screen.blit(self.npc_placeholder, (x, y))

        # Render NPC chat bubble if active (and not timed out)
        if npc_id in self.npc_chat_texts:
            text, chat_time = self.npc_chat_texts[npc_id]
            if time.time() - chat_time < self.chat_bubble_duration:
                self._render_speech_bubble(x, y, text)

    def _render_light_sprite(self, sprite: pygame.Surface, x: float, y: float,
                              is_light: bool, coloreffect: Optional[Tuple[float, float, float, float]]):
        """Render a sprite with light effects (additive blending, alpha).

        Args:
            sprite: The sprite surface to render
            x, y: Position (top-left of NPC tile, like other NPC images)
            is_light: If True, use additive blending
            coloreffect: (r, g, b, a) multipliers - r,g,b typically 1.0, a is alpha (0-1)
        """
        # Create a copy of the sprite for modification
        light_sprite = sprite.copy()

        # Apply color effect (alpha)
        if coloreffect:
            r, g, b, a = coloreffect
            # Alpha is typically like 0.99 (99% opacity but as a light effect)
            alpha = int(a * 255)
            light_sprite.set_alpha(alpha)

        # Position - place light sprite with top-left at NPC position
        # User testing confirmed this positioning is correct for light effects
        pos_x = x
        pos_y = y

        if is_light:
            # Render with additive blending for light effect
            self.screen.blit(light_sprite, (pos_x, pos_y), special_flags=pygame.BLEND_ADD)
        else:
            # Just render with alpha
            self.screen.blit(light_sprite, (pos_x, pos_y))

    def _render_animated_entity(self, x: float, y: float, anim: AnimationState,
                                  equipment: dict):
        """Render an entity using gani animation.

        The gani offsets position sprites within a bounding box.
        Position (x, y) is the top-left of the entity's tile position.
        """
        frame = anim.get_frame() if anim.gani else None

        if not frame:
            # Fallback to placeholder - position at top-left
            self.screen.blit(self.placeholder_sprite, (x, y))
            return

        # No base offset - gani sprite positions are relative to entity position
        # Entity position (x, y) is the top-left of the tile
        base_offset_x = 0
        base_offset_y = 0

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

        # Dialogue box
        if self.dialogue_text:
            elapsed = time.time() - self.dialogue_time
            if elapsed < self.dialogue_duration:
                # Fade out in last 0.5 seconds
                alpha = 255 if elapsed < self.dialogue_duration - 0.5 else int(255 * (self.dialogue_duration - elapsed) / 0.5)

                # Draw dialogue box
                box_width = min(SCREEN_WIDTH - 40, 400)
                box_height = 60
                box_x = (SCREEN_WIDTH - box_width) // 2
                box_y = SCREEN_HEIGHT - 150

                # Background
                box_surf = pygame.Surface((box_width, box_height), pygame.SRCALPHA)
                pygame.draw.rect(box_surf, (0, 0, 50, min(200, alpha)), (0, 0, box_width, box_height))
                pygame.draw.rect(box_surf, (100, 100, 200, min(255, alpha)), (0, 0, box_width, box_height), 2)
                self.screen.blit(box_surf, (box_x, box_y))

                # Text (word wrap)
                words = self.dialogue_text.split()
                lines = []
                current_line = ""
                for word in words:
                    test_line = current_line + (" " if current_line else "") + word
                    if self.font_small.size(test_line)[0] < box_width - 20:
                        current_line = test_line
                    else:
                        if current_line:
                            lines.append(current_line)
                        current_line = word
                if current_line:
                    lines.append(current_line)

                text_y = box_y + 10
                for line in lines[:3]:  # Max 3 lines
                    text_surf = self.font_small.render(line, True, (255, 255, 255))
                    text_surf.set_alpha(alpha)
                    self.screen.blit(text_surf, (box_x + 10, text_y))
                    text_y += 18
            else:
                self.dialogue_text = None

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
