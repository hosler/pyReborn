"""
Pygame game client for pyreborn.

Contains the main GameClient class. Behavior lives in per-concern mixins
under pyreborn/game/ (render, input, actions, collision, setup, minimap,
tile_editor). This module wires them together via __init__ and run().
"""

import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame

from . import Client
from .gani import GaniParser, AnimationState, direction_from_delta
from .sprites import SpriteManager, TilesetManager, create_placeholder_sprite, create_shadow_sprite
from .sounds import SoundManager, preload_common_sounds
from .inventory_ui import InventoryUI, HeartDisplay
from .npc_handler import NPCHandler
from .gs1_client import ClientGS1
from .player import Player
from .tiletypes import TileType, get_tile_type
from .game.constants import (
    TILE_CORRECTIONS_FILE, TILE_SIZE, SCREEN_WIDTH, SCREEN_HEIGHT,
    TILESET_COLS, TILESET_ROWS, MOVE_STEP, parse_npc_visual_effects,
)
from .game.camera import Camera2D
from .game.viewport import Viewport
from .game.assets import FontManager
from .game.hud import HUD
from .game.setup import SetupMixin
from .game.minimap import MinimapMixin
from .game.tile_editor import TileEditorMixin
from .game.collision import CollisionMixin
from .game.input import InputMixin
from .game.actions import ActionsMixin
from .game.render import RenderMixin
from .game.render_world import WorldRenderMixin
from .game.render_entities import EntityRenderMixin
from .game.render_effects import EffectsRenderMixin
from .game.render_objects import LevelObjectsRenderMixin


class GameClient(
    SetupMixin,
    MinimapMixin,
    TileEditorMixin,
    CollisionMixin,
    InputMixin,
    ActionsMixin,
    RenderMixin,
    WorldRenderMixin,
    EntityRenderMixin,
    EffectsRenderMixin,
    LevelObjectsRenderMixin,
):
    """Enhanced pygame game client with animations and sounds."""

    def __init__(self, client: Client):
        self.client = client
        self.running = True

        # Initialize pygame
        pygame.init()
        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)

        # Native rendering: the game draws straight to the window at its real
        # resolution so it fills the whole window (the world is centred by the
        # camera, with black around the level edges) rather than a scaled 640x480
        # square. self.screen is the window surface; on resize _on_window_resize
        # re-points it and resizes the camera/HUD. SCREEN_WIDTH/HEIGHT are just
        # the initial size now — live layout uses self.screen_w/self.screen_h.
        self.viewport = Viewport(SCREEN_WIDTH, SCREEN_HEIGHT,
                                 caption=f"pyreborn - {client.player.account}",
                                 native=True, on_resize=self._on_window_resize)
        self.screen = self.viewport.canvas
        self.clock = pygame.time.Clock()

        # Camera: single source of truth for world<->screen mapping, replacing
        # the offset math that used to be copy-pasted into every render method.
        self.camera = Camera2D(self.screen.get_width(), self.screen.get_height(),
                               TILE_SIZE)

        # Fonts: keyed/cached via FontManager. self.font / self.font_small remain
        # as aliases for the HUD and small roles the legacy render code uses.
        self.fonts = FontManager()
        self.font = self.fonts.get("hud")
        self.font_small = self.fonts.get("small")

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
        self.baddy_anims: Dict[int, AnimationState] = {}
        # Assets (NPC/player images) already requested from the server.
        self._requested_assets: set = set()
        # Visual positions for NPCs (for smooth interpolation)
        self.npc_visual: Dict[int, Tuple[float, float]] = {}

        # Visual effects for NPCs (drawaslight, setcoloreffect)
        self.npc_effects: Dict[int, dict] = {}

        # NPC handler for touch detection and script execution
        self.npc_handler = NPCHandler(self.client)

        # GS1 interpreter for NPC scripts (shared engine, client-side host)
        self.gs1 = ClientGS1(self.client)
        self._setup_gs1_callbacks()

        # UI components
        self.inventory_ui = InventoryUI(self.screen, self.sprite_mgr)
        self.heart_display = HeartDisplay(10, 10)
        self.hud = HUD(self)

        # Input state
        self.typing = False
        self.chat_input = ""
        self.chat_messages: List[str] = []

        # Timing
        self.walk_speed = 8.0   # Movement speed in tiles/second (frame-rate independent)
        self._move_accum = 0.0  # Accumulates sub-step movement across frames
        self._frame_dt = 0.0    # Most recent frame delta, set by run()
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
        # Link-warp guards. `_was_on_link`: True while standing on a warp link, so
        # links only fire on the rising edge (stepping ON) — no bounce across
        # overlapping links. `_link_arrival`: the spot a warp last dropped us;
        # while within ~1.5 tiles of it, link warps stay suppressed even if the
        # destination level's links stream in a few frames late — this is what
        # stops the "warp loop" on downward crossings.
        self._was_on_link = False
        self._link_arrival = None

        # Smooth movement - visual position tracks the authoritative position.
        self.visual_x = 0.0
        self.visual_y = 0.0
        # Player sprite top-left in render frame, set each frame by _sync_camera.
        self._player_render_pos = (0.0, 0.0)
        # How fast the camera/local-player visual chases the real position. Kept
        # well above walk_speed (8) so it locks on each frame (no floaty lag).
        self.follow_speed = 24.0
        self.lerp_speed = 18.0  # still used to ease *other* players' positions

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
        # Noclip: ignore client-side collision so the player can walk through
        # walls. Mainly an escape hatch for bad server spawns (e.g. classic 2.22
        # servers that warp you into a border-wall tile and leave you stuck).
        self.noclip = False
        self.tile_corrections: Dict[int, int] = {}  # tile_id -> corrected TileType
        self.debug_selected_type = TileType.NONBLOCK  # Currently selected tile type for editing
        self._load_tile_corrections()

        # Minimap state
        self.minimap_data: Optional[bytes] = None
        self.minimap_surface: Optional[pygame.Surface] = None
        self.minimap_visible = True  # Toggle with M key
        self.minimap_size = (100, 100)  # Display size in pixels

        # Ghost mode state
        self.ghost_mode = False

        # Controls/help overlay (toggle with H)
        self.show_help = False

        # Player list (F7) + private messaging.
        self.show_player_list = False
        self.player_list_sel = 0          # selected row in the player list
        self.pm_target_id: Optional[int] = None  # player we're composing a PM to
        self.pm_input = ""

        # Server list (F8) for switching servers. `servers` is populated by the
        # launcher (the listserver result); switch_server is set when the user
        # picks one, and run() returns it so the launcher reconnects.
        self.show_server_list = False
        self.server_list_sel = 0
        self.servers: List = []
        self.switch_server = None

        # Suppress "X entered" spam from the login roster dump: join
        # announcements only fire after this time (set when the loop starts).
        self.roster_ready_time = float('inf')

        # Removed tiles tracking (for pickup/throw mechanics)
        # Maps (level_name, x, y) -> original_tile_id
        self.removed_tiles: Dict[Tuple[str, int, int], int] = {}

        # Grass/dirt tile ID to replace picked up objects
        self.grass_tile_id = 0  # Will be detected or default to 0

        # Setup callbacks
        self._setup_callbacks()

    # Live canvas dimensions. With native rendering the window is the canvas, so
    # all layout/centering reads these instead of the fixed SCREEN_WIDTH/HEIGHT.
    @property
    def screen_w(self) -> int:
        return self.screen.get_width()

    @property
    def screen_h(self) -> int:
        return self.screen.get_height()

    def _on_window_resize(self, w: int, h: int):
        """Window resized (native mode): re-point self.screen at the new window
        surface and resize the camera + HUD so the world stays centred and the
        HUD re-anchors to the new corners."""
        self.screen = self.viewport.canvas
        self.camera.resize(w, h)
        if getattr(self, "hud", None) is not None:
            self.hud.ui.resize(w, h)
        if getattr(self, "inventory_ui", None) is not None:
            self.inventory_ui.screen = self.screen

    def run(self):
        """Main game loop."""
        last_time = time.time()
        frame_count = 0

        # Initialize visual position to actual position
        self.visual_x = self.client.x
        self.visual_y = self.client.y

        # Check initial swimming state
        self._update_swimming_state()

        # Load + run NPC scripts, then snapshot collision shapes the engine
        # recorded during playerenters (setshape/setshape2).
        self._load_npc_scripts()
        self._trigger_playerenters()
        self.npc_handler.update_npcs()
        # Remember which level the GS1 engine is loaded for so the loop's
        # level-change detector only re-runs on an actual warp.
        self._gs1_level = self.client._current_level_name

        # Let the login roster dump settle before announcing further joins.
        self.roster_ready_time = time.time() + 2.0

        print(f"Starting game loop. running={self.running}, connected={self.client.connected}")

        while self.running and self.client.connected:
            frame_count += 1
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time
            # Clamp dt so a stall (e.g. window drag) can't teleport the player
            self._frame_dt = min(dt, 0.1)

            # Handle events
            self._handle_events()

            # Handle held key input
            self._handle_input(current_time)

            # Update client (process packets)
            self.client.update()

            # A GS1 setlevel2/serverwarp (e.g. arena entry) requested a warp;
            # perform it now, between events, not mid-script (re-entrant).
            self._process_pending_warp()
            # Fire actionprojectile2 for projectiles we shot ourselves.
            self._process_self_shoots()
            # Drive NPC `timeout` events (proximity checks, room-join logic, ...).
            self.gs1.process_timeouts(self._frame_dt)
            # Reload the GS1 engine when we land in a new level (script warp,
            # door, or server-initiated), once its NPCs have streamed in.
            self._check_level_change()

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

        # If the player picked another server from the F8 list, hand it back to
        # the launcher so it can reconnect. None = normal quit.
        return self.switch_server

