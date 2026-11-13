"""
Pygame game client for pyreborn.

Contains the main GameClient class. Behavior lives in per-concern mixins
under pyreborn/game/ (render, input, actions, collision, setup, minimap,
tile_editor). This module wires them together via __init__ and owns the
frame pipeline: start() once, step() per frame, shutdown() once; run() is the
production loop over them, and the game_tester harnesses call them directly.
"""

import gc
import logging
import os
import sys
import traceback
from contextlib import contextmanager
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

import pygame

from . import Client
from .gani import GaniParser, AnimationState
from .sprites import SpriteManager, TilesetManager, create_placeholder_sprite, create_shadow_sprite
from .sounds import SoundManager, preload_common_sounds
from .inventory_ui import InventoryUI, HeartDisplay
from .npc_handler import NPCHandler
from .gs1_client import ClientGS1
from .gs2_client import ClientGS2
from .prefs import Prefs
from .tiletypes import TileType
from .game.constants import (
    TILE_SIZE, SCREEN_WIDTH, SCREEN_HEIGHT, WALK_SPEED,
    BOMB_FUSE_TIME,
)
from .game.camera import Camera2D
from .game.viewport import Viewport
from .game.chat_state import ChatState
from .game.level_arrival import LevelArrival
from .game.particles_state import Particles
from .game.push_grab import PushGrab
from .game.transition import TransitionState
from .game.assets import FontManager
from .game.hud import HUD
from .game.combat_presentation import CombatPresentation
from .game.render_cache import RenderCache
from .game.callbacks.client_callbacks import Gs2SourceRouter
from .game.setup import SetupMixin
from .game.minimap import MinimapMixin
from .game.collision import CollisionMixin
from .game.input import InputMixin
from .game.actions import ActionsMixin
from .game.render import RenderMixin
from .game.render_world import WorldRenderMixin
from .game.render_entities import EntityRenderMixin
from .game.render_effects import EffectsRenderMixin
from .game.render_objects import LevelObjectsRenderMixin
from .logutil import log_swallowed

logger = logging.getLogger(__name__)


class GameClient(
    SetupMixin,
    MinimapMixin,
    CollisionMixin,
    InputMixin,
    ActionsMixin,
    RenderMixin,
    WorldRenderMixin,
    EntityRenderMixin,
    EffectsRenderMixin,
    # The three render mixins that touch a frame inherit FrameContextMixin
    # themselves (so a standalone test harness over one of them still has the
    # lifecycle) — nothing to add here.
    LevelObjectsRenderMixin,
):
    """Enhanced pygame game client with animations and sounds."""

    @property
    def weapons(self) -> List[str]:
        """Visible weapon names from the server-owned live weapon state."""
        return [name for name in self.client.weapons
                if not str(name).startswith('-')]

    # -- the GameShell protocol (gs2_client/game_shell.py) -------------------
    # Public names for what the GS2 runtime reads from its host; the private
    # attributes they wrap stay, because the game layer and game_tester use them.

    #: isfullscreenmode(): the game window has no fullscreen toggle.
    fullscreen = False

    @property
    def day_night_enabled(self) -> bool:
        return getattr(self, '_day_night_enabled', False)

    @day_night_enabled.setter
    def day_night_enabled(self, value: bool) -> None:
        self._day_night_enabled = value

    @property
    def camera_enabled(self) -> bool:
        return getattr(self, '_camera_enabled', False)

    @camera_enabled.setter
    def camera_enabled(self, value: bool) -> None:
        self._camera_enabled = value

    def dismiss_dialogue(self) -> None:
        self._dismiss_dialogue()

    def showtext_font(self, name: str, size: int, bold: bool):
        return self._showtext_font(name, size, bold)

    def selected_weapon_full_index(self) -> int:
        """Index of the equipped weapon in the FULL client.weapons ordering.

        Script surfaces (`#w`, `selectedweapon`, GS2 selectedweapon) index the
        player's whole weapon array — hidden "-" system weapons included —
        while inventory_ui.selected_weapon_idx indexes the FILTERED visible
        list. Feeding the filtered index straight to the scripts made `#w`
        answer whatever weapon happened to sit at that slot of the full dict
        (usually a system weapon), so e.g. GTA's *Clock GUI never opened: its
        `if (!strequals(#w,*Clock)) this.mode = 0;` re-closed it every tick.
        """
        entries = self.weapons
        if not entries:
            return -1
        idx = max(0, min(int(self.inventory_ui.selected_weapon_idx),
                         len(entries) - 1))
        try:
            return list(self.client.weapons).index(entries[idx])
        except ValueError:
            return -1

    def __init__(self, client: Client, password: Optional[str] = None):
        self.client = client
        self.running = True
        # Frame-pipeline lifecycle (see start/step/shutdown).
        self._started = False
        self._shut_down = False
        self._frame_count = 0
        # Contained frame-phase failures, keyed by (phase, exception type,
        # innermost file:line) -> how many times that site has raised.
        self.frame_errors: Dict[Tuple[str, str, str], int] = {}
        # Kept for the F10 RC tools only: RC is a separate connection and has
        # to log in again (see rc_link.py). Without it the overlay says so
        # instead of silently having no RC.
        self.rc_password = password

        # Initialize pygame
        pygame.init()
        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)

        # Native rendering: the game draws straight to the window at its real
        # resolution so it fills the whole window (the world is centred by the
        # camera, with black around the level edges) rather than a scaled 640x480
        # square. self.screen is the window surface; on resize _on_window_resize
        # re-points it and resizes the camera/HUD. SCREEN_WIDTH/HEIGHT are just
        # the virtual-canvas fallback now — live layout uses self.screen_w/
        # self.screen_h.
        #
        # The window opens at the LAST REMEMBERED size (prefs.window_w/h, saved
        # by pygame_screens.py's login/server-select screens), not a bare
        # 640x480: on a tiling WM the login screen already opened at whatever
        # size the WM handed it (and the player likely resized further), so
        # reopening at 640x480 here produced a visible shrink-then-WM-resize
        # jump into the game on every launch.
        prefs = Prefs.load()
        window_w = max(SCREEN_WIDTH, prefs.window_w or SCREEN_WIDTH)
        window_h = max(SCREEN_HEIGHT, prefs.window_h or SCREEN_HEIGHT)
        self.viewport = Viewport(SCREEN_WIDTH, SCREEN_HEIGHT,
                                 window_w=window_w, window_h=window_h,
                                 caption=f"pyreborn - {client.player.account}",
                                 native=True, on_resize=self._on_window_resize)
        self.screen = self.viewport.canvas
        #: Frame pacing only (`run()` calls .tick(60)); NOT the time source,
        #: which is `self.clock` (the client's).
        self.frame_limiter = pygame.time.Clock()

        # Camera: single source of truth for world<->screen mapping, replacing
        # the offset math that used to be copy-pasted into every render method.
        self.camera = Camera2D(self.screen.get_width(), self.screen.get_height(),
                               TILE_SIZE)
        # _sync_camera() memoizes the inputs it last called camera.set_bounds()
        # with in render_cache.camera_bounds_key - see game/render.py.

        # Fonts: keyed/cached via FontManager. self.font / self.font_small remain
        # as aliases for the HUD and small roles the legacy render code uses.
        self.fonts = FontManager()
        self.font = self.fonts.get("hud")
        self.font_small = self.fonts.get("small")

        # Setup asset paths
        self.asset_paths = self._setup_asset_paths()

        # Initialize managers
        self.sprite_mgr = SpriteManager(
            self.asset_paths, fetch_bytes=self.client.get_file,
            clock=self.client.clock)
        self.tileset_mgr = TilesetManager(self.sprite_mgr)
        # Classic (2.x) servers assume the classic client's BUILT-IN default
        # tileset, pics1.png — their scripts only issue addtiledef to RESET
        # back to it after area tilesets (GTA's `addtiledef pics1.png,,0`).
        # Our modern default (dustynewpics1.png) diverges from the classic
        # layout in some ranges (GTA's pond/fountain water drew as bricks),
        # so base classic sessions on the real sheet: local copy if present,
        # and fetch the server's authoritative one either way.
        if str(getattr(self.client, "version", "")).startswith("2."):
            self.tileset_mgr.default_tileset = "pics1.png"
            try:
                if not self.sprite_mgr.load_sheet("pics1.png"):
                    self.client.request_file("pics1.png")
            except Exception:
                log_swallowed(logger)
        # Tiledef applicability is scoped by level-name prefix; seed the
        # login level (later changes flow through _reload_level_scripts).
        self.tileset_mgr.set_current_level(
            getattr(self.client, "current_level_name", "") or "")
        self.sound_mgr = SoundManager(self.asset_paths, clock=self.client.clock)
        self.gani_parser = GaniParser(
            self.asset_paths, fetch_bytes=self.client.get_file)

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
        # Derived render state (text/gani/baddy-sheet caches, ...), see
        # game/render_cache.py. Baddy sprite sheets live in it as `baddy_sheets`.
        self.render_cache = RenderCache()
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
        # Seed the script engines' screen size with the REAL window size
        # before any server script runs. It used to stay at the 800x600
        # default until _feed_gs1_input's per-frame sync -- which never runs
        # while a GS2 GUI text field holds keyboard focus, exactly the state
        # the Login server boots into, so its whole GUI laid itself out for
        # 800x600 in the top-left of a bigger window. _on_window_resize
        # keeps it current from then on.
        self.gs1.screen_w = self.screen.get_width()
        self.gs1.screen_h = self.screen.get_height()
        self._setup_gs1_callbacks()

        # GS2 bytecode VM (weapons/classes/ganis compiled by the server);
        # builtins route through the same GS1 client host surface, so both
        # engines drive the same rendering/callback paths.
        self.gs2 = ClientGS2(self.client, self.gs1).attach()
        self.gs2.game_shell = self
        # The touch handler consults GS2 VMs for its event gate (bytecode
        # NPCs have no GS1 script text to sniff).
        if getattr(self, "npc_handler", None) is not None:
            self.npc_handler.gs2 = self.gs2

        # UI components
        self.inventory_ui = InventoryUI(self.screen, self.sprite_mgr, clock=self.client.clock)
        self.gs1.selected_weapon_index = self.selected_weapon_full_index
        self.heart_display = HeartDisplay(10, 10)
        self.hud = HUD(self)

        # Input state
        # Chat log, chat-line input, scrollback and PM composer (game/chat_state.py).
        self.chat = ChatState()

        # Timing
        self.walk_speed = WALK_SPEED
        self._move_accum = 0.0  # Walk distance not yet applied as a MOVE_STEP
        self._frame_dt = 0.0    # Most recent frame delta (presentation only)
        # "Never" is -inf, so the first action right after the session
        # starts is never held back by a cooldown (sim time starts at 0).
        self.last_action_time = float('-inf')
        # Cooldowns in simulation seconds, compared with clock.passed: 7 ticks
        # between actions, 4 between sword swings. The code before the tick
        # model allowed the next one strictly after 0.3 s / 0.15 s; on the
        # tick grid that is the 7th / 4th tick (no reference counter found).
        self.action_delay = 0.35
        # Sword has its own, much shorter, cooldown so it can be spam-swung.
        self.last_sword_time = float('-inf')
        self.sword_delay = 0.2

        # Key state tracking
        self.key_just_pressed: Dict[int, bool] = {}
        # GS1 `keypressed` events queued by _handle_events, fired from
        # _handle_input once keys_dir is refreshed (see game/input.py).
        self._gs1_keypress_queue: List[Tuple[int, str]] = []

        # World rendering
        self.world_surface: Optional[pygame.Surface] = None
        # Tier 4a's animated-tile list, its memo key and the shimmer ramp
        # flags live in render_cache (animated_tiles*, shimmer_*_this_frame).

        # Placeholders
        self.placeholder_sprite = create_placeholder_sprite(32, 32, (200, 50, 200))
        self.shadow_sprite = create_shadow_sprite()
        self.npc_placeholder = create_placeholder_sprite(32, 32, (50, 200, 50))

        # Current animation name (for tracking changes)
        self.current_anim_name = "idle"
        self.is_moving = False
        self.is_swimming = False  # Track if player is in water

        # Built-in push/grab/pull prediction; actions dispatch NPC triggers.
        self.push = PushGrab()
        # Level arrival + link-warp guards (see game/level_arrival.py).
        self.arrival = LevelArrival()

        # Draw position of the local player: the authoritative position
        # interpolated between the last two ticks (_update_visual_position).
        self.visual_x = 0.0
        self.visual_y = 0.0
        # Held-frame / slide presentation state (see game/transition.py).
        self.transition = TransitionState(
            seen_epoch=self.client.local_level_transition_epoch)
        # Player sprite top-left in render frame, set each frame by _sync_camera.
        self._player_render_pos = (0.0, 0.0)
        # Draw positions of moving things between the last two ticks
        # (presentation only; see game/interpolation.py).
        from .game.interpolation import TickInterpolator
        self.interpolator = TickInterpolator()

        # Floating damage numbers live in self.particles.
        self.combat_presentation = CombatPresentation()
        self.gs2_sources = Gs2SourceRouter()

        # Unified local/remote bomb registry.
        self.active_bombs: List[dict] = []
        self.bomb_fuse_time = BOMB_FUSE_TIME

        # Active projectiles - each: {'x': float, 'y': float, 'dx': float, 'dy': float, 'time': float, 'gani': str}
        self.active_projectiles: List[dict] = []

        # Thrown liftables in flight — see _throw_object /
        # _update_and_render_thrown. Each: {'tiles', 'x', 'y', 'z', 'z0',
        # 'dx', 'dy', 'speed', 'dist', 'range'}.
        self.thrown_objects: List[dict] = []
        # Break bursts when a thrown object lands/hits — each: {'x', 'y',
        # 'time', 'color'} with a handful of scattering particles.
        self.particles = Particles()

        self.horse_anims: Dict[Tuple[float, float], AnimationState] = {}

        # Tier 3d: seteffect screen tint - {'r','g','b','a'} 0..255 or None.
        self.screen_tint: Optional[dict] = None

        # Dialogue box state (for say2/signs)
        self.dialogue_text: Optional[str] = None
        self.dialogue_classic_font: bool = False
        from .game.dialogue import DialoguePager
        self.dialogue_pager = DialoguePager()

        # Speech bubble state (for say/chat - shows above entity heads)
        self.local_chat_text: str = ""  # Local player's chat bubble
        self.local_chat_time: Optional[float] = None  # None: no bubble yet
        self.npc_chat_texts: Dict[int, Tuple[str, float]] = {}  # npc_id -> (text, time)
        self.chat_bubble_duration: float = 4.0  # How long chat bubbles stay visible

        # Debug/tile editing mode
        self.debug_mode = False
        # Noclip: ignore client-side collision so the player can walk through
        # walls. Mainly an escape hatch for bad server spawns (e.g. classic 2.22
        # servers that warp you into a border-wall tile and leave you stuck).
        self.noclip = False

        # Minimap state
        self.minimap_data: Optional[bytes] = None
        self.minimap_surface: Optional[pygame.Surface] = None
        self._minimap_native_surface: Optional[pygame.Surface] = None
        self.bigmap_surface: Optional[pygame.Surface] = None
        self.minimap_visible = True  # Toggle with M key
        self.big_map_visible = False
        self.minimap_size = (100, 100)  # Display size in pixels
        # Image names the two map surfaces were built from (PLO_BIGMAP drives
        # bigmap_surface, PLO_MINIMAP drives minimap_surface; see
        # game/minimap.py _ensure_bigmap_surface / _ensure_minimap_surface).
        self._bigmap_image_name: Optional[str] = None
        self._minimap_image_name: Optional[str] = None

        # Ghost mode state
        self.ghost_mode = self.client.ghost_mode

        # Controls/help overlay (toggle with H)
        self.show_help = False

        # Player list (F7) + private messaging.
        self.show_player_list = False
        self.player_list_sel = 0          # selected row in the player list

        # Server list (F8) for switching servers. `servers` is populated by the
        # launcher (the listserver result); switch_server is set when the user
        # picks one, and run() returns it so the launcher reconnects.
        self.show_server_list = False
        self.server_list_sel = 0
        self.servers: List = []
        self.switch_server = None
        #: The frame tick the next session starts with: this one's when a
        #: script serverwarp moves us (the reference keeps it), None (50 ms)
        #: when the player picks the server.
        self.switch_frame_tick: Optional[int] = None

        # Suppress "X entered" spam from the login roster dump: join
        # announcements only fire after this time (set when the loop starts).
        self.roster_ready_time = float('inf')

        # -- state formerly created lazily (by a getattr guard, in start(), or
        # as a class-level default). Each value is the one every guard falls
        # back to, so a game behaves as it did when the name was absent. A
        # None below is "not seen yet" (a sentinel the guard sites test for),
        # not a placeholder to replace.
        # Actions
        self._ledge_jump = None
        self._frozen_until = 0.0
        self._swim_in_lava = False
        self._step_parity = 0
        self._footstep_tick = None
        self._sleep_level = None
        self._sleep_was_moving = False
        self._sign_contact_key = None
        self._ground_ticks = None          # built on first use (actions)
        self._giveaway_item = None
        self._found_chest_level = None
        self._item_take_sent = set()
        self._item_first_seen = {}
        self._death_started = None
        # Input
        self._latch_context = None
        self._mouse_left_latched = False
        self.server_warp_prompt = None
        self.hud_notice = None
        self._overlay_stack = None         # built on first use (input)
        # Script requests and presentation
        self._pending_self_shoots = []
        self._scripted_player_ani = None
        self._camera_focus = None
        self._camera_shake_started = None
        self._current_music_name = None
        self._pending_music = None
        self._gs2_shape1_npcs = set()
        self._low_hearts_next_beep = 0.0
        self._dbg = False                  # start() reads PYREBORN_DEBUG
        self._was_dead = False
        self._frame_ctx = None
        self._swamp_pos = None
        self._swamp_slot = None
        self._npc_visual_epoch = None      # built on first use (render_collect)
        self._chest_reveals = []
        self._chest_reveal_snapshots = {}
        # Settings mirrors. SettingsOverlay (below) applies the saved prefs to
        # _day_night_enabled and _low_hearts_warning_enabled.
        self._camera_enabled = False
        # Lazy UI objects: built on first use, so no connection or window
        # state exists until then.
        self.rc_ui = None
        self.dev_ui = None
        self.level_editor = None
        self.editor_overlay = None
        self.tile_palette = None

        # Setup callbacks
        self._setup_callbacks()

        # Apply saved live settings during construction. Leaving this until
        # the first event pass allowed other callers to consume the camera's
        # initial transform before the preferred zoom invalidated it.
        self._ensure_settings_ui()

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
        surface and resize the camera + HUD so the world stays centered and the
        HUD re-anchors to the new corners."""
        self.screen = self.viewport.canvas
        self.camera.resize(w, h)
        # keep the script engines' canvas dims live (screenwidth/
        # GUIContainer reads; the GS2 GUI manager additionally propagates
        # Torque horizSizing/vertSizing deltas itself at render time)
        if getattr(self, "gs1", None) is not None:
            self.gs1.screen_w = w
            self.gs1.screen_h = h
        if getattr(self, "hud", None) is not None:
            self.hud.ui.resize(w, h)
        if getattr(self, "inventory_ui", None) is not None:
            self.inventory_ui.screen = self.screen

    # ------------------------------------------------------------------
    # Frame pipeline: start() once, step() once per frame, shutdown() once.
    # run() is the production driver. game_tester harnesses and tests call
    # start()/step() directly, so every one of them runs the same frame the
    # player does; a phase added to step() reaches all of them at once.
    #
    # Timing model (pyreborn/clock.py): the simulation runs in ticks
    # (`_simulation_tick`) of the frame tick, 50 ms unless a script changes
    # it (adventure_setframetick); a frame runs at most
    # Clock.MAX_TICKS_PER_FRAME of them and drops late time beyond that, like
    # the reference (AndroidInterface.cpp:170-179). Events, network and the
    # render run every frame; the render interpolates moving things between
    # the last two ticks (`clock.alpha`).
    # ------------------------------------------------------------------

    #: The error-containment groups of step(), in the order they run. The
    #: ones from "world" to "level" run once per tick.
    FRAME_PHASES = ("input", "network", "world", "movement", "gs1", "gs2",
                    "level", "render")

    #: Clamp on the presentation dt (`_frame_dt`, fades and particles). The
    #: simulation never sees it: it advances by whole ticks.
    MAX_FRAME_DT = 0.1

    def start(self) -> None:
        """One-time setup before the first frame. Calling it again is a no-op.

        Seeds the visual position, runs the level's NPC scripts and their
        playerenters, snapshots the collision shapes they recorded
        (setshape/setshape2), and remembers which level the GS1 engine is
        loaded for so the per-tick level-change detector only re-runs on an
        actual warp."""
        if self._started:
            return
        self._started = True
        self._dbg = bool(os.environ.get("PYREBORN_DEBUG"))
        self._frame_count = 0
        # From here on this game runs the ticks; client.update() only reads.
        self.clock.host_driven = True

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
        self.arrival.gs1_level = self.client.current_level_name
        self.arrival.visual_epoch = self.client.plain_level_change_epoch

        # Let the login roster dump settle before announcing further joins.
        self.roster_ready_time = self.clock.frame_now() + 2.0

    def step(self, dt: float, *,
             events: Optional[Iterable["pygame.event.Event"]] = None,
             strict: bool = True, net_timeout: float = 0.0) -> None:
        """Run exactly one frame: events, network, the due simulation ticks,
        then the render.

        ``dt`` is the real seconds since the previous frame. It feeds the
        tick accumulator (``clock.ticks_due``): a frame that completes a
        tick (``clock.tick_length``, 50 ms by default) runs ONE
        `_simulation_tick`; late time beyond Clock.MAX_TICKS_PER_FRAME ticks
        is dropped, never caught up. At 60 fps and the default tick a tick
        runs every third frame. ``_frame_dt`` (dt clamped to
        MAX_FRAME_DT) is presentation only. ``events`` are posted to the
        pygame event queue before the input phase drains it (a harness's
        synthetic input). ``net_timeout`` is how long ``client.update`` may
        wait for packets; the production loop passes 0 because
        ``frame_limiter.tick`` already paces it.

        Per frame:
          input       pygame events; key and click EDGES are latched until a
                      tick consumes them (`key_just_pressed`)
          network     packets, applied as they arrive (Client.update, which
                      runs no tick while a game drives them)
        Per tick (`_simulation_tick`, 0..MAX_TICKS_PER_FRAME times), in the
        reference's order (see `_simulation_tick`):
          world       the Client's own tick (NPC moves, items, sword, arrows,
                      bombs), NPCs that streamed in late, death state and
                      respawn, one gani step, bombs, arrows, flying and
                      thrown objects
          movement    held keys sampled now, plus the latched edges; walking
                      and actions; the low-hearts reminder; actionprojectile2
                      for our own shots
          gs1         GS1 coroutines, then timeouts (one tick of script time)
          gs2         GS2 coroutines, then timeouts (settimer / onTimeout)
          level       a pending script warp, the scripted-movement link
                      check, the keydown2 input snapshot, the GS1 reload on a
                      level change, swimming
          (the tick's position goes out as ONE packet at its end)
        Per frame again:
          render      interpolated draw positions, the whole draw, which ends
                      with viewport.present()

        ``strict=True`` (the default, for harnesses and tests) lets a phase's
        exception propagate. ``run()`` passes ``strict=False``: a failing phase
        is logged once per failing site with its traceback, counted in
        ``frame_errors``, and the frame continues with the next phase.
        Either way a failed render pass drops its half-built frame context.
        ``KeyboardInterrupt`` and ``SystemExit`` always propagate."""
        self._frame_count += 1
        self._frame_dt = min(max(dt, 0.0), self.MAX_FRAME_DT)
        clock = self.clock
        clock.host_driven = True

        # Behavioral heartbeat (PYREBORN_DEBUG=1): every ~2s log what the
        # player is actually doing, to diagnose "stuff stopped working".
        if getattr(self, '_dbg', False) and self._frame_count % 120 == 0:
            p = self.client.player
            print(f"[hb] f={self._frame_count} t={clock.tick} lvl={self.client.current_level_name} "
                  f"pos=({self.client.x:.1f},{self.client.y:.1f}) dir={p.direction} "
                  f"moving={getattr(self,'is_moving',None)} sitting={getattr(p,'is_sitting',None)} "
                  f"hearts={p.hearts} npcs={len(self.client.npcs)} scripts={len(self.gs1.scripts)}",
                  file=sys.stderr)

        for event in events or ():
            pygame.event.post(event)

        with self._frame_phase("input", strict):
            self._handle_events()

        with self._frame_phase("network", strict):
            # Non-blocking in production: frame_limiter.tick(60) already
            # paces the loop, so update()'s default 10ms select() wait on
            # top of it would only add input latency.
            self.client.update(timeout=net_timeout)

        for _ in range(clock.ticks_due(dt)):
            self._simulation_tick(strict)

        with self._frame_phase("render", strict):
            self._update_visual_position(clock.alpha)
            self._render()

    def _simulation_tick(self, strict: bool) -> None:
        """One tick of the simulation (see `step()`); it runs every
        `clock.tick_length` seconds (the frame tick, 50 ms by default).

        The phases follow the reference's timer pass (network first, which
        `step()` pumps per frame; TAdventure.cpp:471-496): the player's
        timer (TPlayer.cpp:7211) counts its counters and animates the
        objects (TServerPlayer.cpp:454-457 -> TServerNPC.cpp:1477-1484 ->
        TServerLevel.cpp:1212-1224), then reads the keys and moves
        (keyCheck, TPlayer.cpp:7331-7339); the scripts run after that
        (doNPCActions, TPlayer.cpp:7374, :6395-6406, runs every script),
        the warp a script asked for is sent right after them (:6401-6406),
        then the level links are tested (testForMapLinks, :7375-7379); the
        props go out last (sendOutgoing, TAdventure.cpp:496)."""
        clock = self.clock
        clock.begin_tick()
        clock._in_tick = True
        now = clock.sim_now()
        # One tick of every per-tick mechanic: a fixed amount whatever the
        # frame tick (Clock.TICK_SECONDS).
        tick = clock.TICK_SECONDS
        try:
            with self.client.movement_batch():
                with self._frame_phase("world", strict):
                    # The Client's own tick: NPC moves, items, sword, arrows,
                    # bombs, hideplayer, explosions, the emoticon counter.
                    self.client.run_tick()
                    # Load + run NPCs that streamed in after startup (slow
                    # server).
                    self._load_new_npcs()
                    # Death state and respawn (the timer's HP check comes
                    # before keyCheck, TPlayer.cpp:7223-7226).
                    self._update_death_state(now)
                    if getattr(self, '_was_dead', False) and self.client.player.hearts > 0:
                        # We respawned! Reset animation to idle
                        self.player_anim.set_animation("idle", self.client.player.direction)
                        self._was_dead = False
                    self._was_dead = self.client.player.hearts <= 0
                    # One gani step for every animation, then bombs, arrows,
                    # flying objects, thrown objects and the pushaway nudge.
                    # They keep running during a level transition: the
                    # reference's timer runs on the loading screen too
                    # (GuiCanvas.cpp:1540-1545).
                    self._update_animations(tick)
                    self._advance_combat_objects(tick, now)

                with self._frame_phase("movement", strict):
                    self._handle_input(now)
                    self._update_low_hearts_warning()
                    # Fire actionprojectile2 for projectiles we shot ourselves.
                    self._process_self_shoots()

                # This tick's step of the script clock: frametick/1000, or
                # the real time since the last tick below a 50 ms frame tick
                # (TScriptUniverse.cpp:226-231, Clock.begin_tick).
                script_dt = clock.script_dt
                with self._frame_phase("gs1", strict):
                    # Resume scripts suspended on `sleep` whose timer elapsed,
                    # then the `timeout` events.
                    self.gs1.process_coroutines(script_dt)
                    self.gs1.process_timeouts(script_dt)

                with self._frame_phase("gs2", strict):
                    self.gs2.process_coroutines(script_dt)
                    # GS2 VM onTimeout scheduling (settimer / this.timeout).
                    self.gs2.process_timeouts(script_dt)
                # A timer armed from here on counts from the next tick.
                clock.end_script_pass()

                with self._frame_phase("level", strict):
                    # A GS1 setlevel2/serverwarp (e.g. arena entry) requested
                    # a warp; perform it now, after the scripts, not
                    # mid-script (re-entrant).
                    self._process_pending_warp()
                    # Scripted movement (disabledefmovement) writes player x/y
                    # from the script engines above, bypassing _move()'s link
                    # check - probe door links here on any position change.
                    self._check_scripted_link_warp()
                    # Snapshot held keys so keydown2(code, edge=true) sees
                    # just-pressed exactly once.
                    self.gs1.advance_input_frame()
                    # Reload the GS1 engine when we land in a new level
                    # (script warp, door, or server-initiated), once its NPCs
                    # have streamed in.
                    self._check_level_change()
                    # Swimming state (in case of a warp or a server move).
                    self._update_swimming_state()
        finally:
            clock._in_tick = False
            clock.end_script_pass()
            # The tick consumed every latched edge.
            self._end_input_tick()

    def _advance_combat_objects(self, dt: float, now: float) -> None:
        """One tick of bombs, arrows, flying objects, thrown objects and the
        pushaway nudge."""
        self._advance_bombs()
        self._update_projectiles(dt)
        self._update_thrown(dt)

    @contextmanager
    def _frame_phase(self, phase: str, strict: bool) -> Iterator[None]:
        """Error boundary around one phase of step() (see its docstring)."""
        try:
            yield
        except Exception as exc:
            if phase == "render":
                # A pass that raised left its FrameContext open (in_frame,
                # half-queued world draws and lights). Drop it, so anything
                # that asks for a context before the next frame begins gets a
                # fresh idle one instead of queueing into a dead frame.
                self._frame_ctx = None
            if strict:
                raise
            self._contain_frame_error(phase, exc)
            if phase == "input" and pygame.event.get(pygame.QUIT):
                # The failure may have come before the queue was read; a
                # pending close request must still end the loop.
                self.running = False

    def _contain_frame_error(self, phase: str, exc: BaseException) -> None:
        """Log a contained phase failure once per site; count every repeat."""
        frames = traceback.extract_tb(exc.__traceback__)
        where = f"{frames[-1].filename}:{frames[-1].lineno}" if frames else "?"
        key = (phase, type(exc).__name__, where)
        count = self.frame_errors.get(key, 0) + 1
        self.frame_errors[key] = count
        if count == 1:
            logger.error(
                "Frame phase %r raised %s at %s; the frame continues (repeats "
                "from this site are counted in GameClient.frame_errors)",
                phase, type(exc).__name__, where,
                exc_info=(type(exc), exc, exc.__traceback__))
        elif count in (10, 100, 1000) or count % 10000 == 0:
            logger.warning("Frame phase %r: %s at %s has raised %d times",
                           phase, type(exc).__name__, where, count)

    def shutdown(self, *, remember_window: bool = True) -> None:
        """End the session. Safe to call more than once; only the first call
        acts, and one failing step does not skip the rest.

        Saves the window size to prefs (``remember_window``; harnesses pass
        False so a test run does not rewrite the player's prefs), disconnects
        the game connection, shuts down the RC and NC link workers, stops
        sound and music, and quits pygame."""
        if self._shut_down:
            return
        self._shut_down = True

        def attempt(label, fn):
            try:
                fn()
            except Exception:
                logger.warning("shutdown: %s failed", label, exc_info=True)

        if remember_window:
            # Remember whatever size the WM/player left the window at,
            # mirroring pygame_screens.py's _Screen._finish, so the next
            # launch (login screen, then this game) opens at it instead of
            # snapping back to whatever prefs.json had before this session.
            attempt("saving the window size",
                    lambda: Prefs.load().remember_window_size(
                        self.screen_w, self.screen_h))
        attempt("disconnect", self.client.disconnect)
        # The RC link is a second connection on its own thread (and the dev
        # playground's NC link a third); drop them with the game one so a
        # server switch doesn't leave them logged in.
        for name in ('rc_ui', 'dev_ui'):
            ui = getattr(self, name, None)
            if ui is not None:
                attempt(f"{name} shutdown", ui.shutdown)
        sound_mgr = getattr(self, 'sound_mgr', None)
        if sound_mgr is not None:
            attempt("stopping sounds", sound_mgr.stop_all)
            attempt("stopping music", sound_mgr.stop_music)
        attempt("releasing fonts", self._release_fonts)
        attempt("pygame quit", pygame.quit)

    def _release_fonts(self) -> None:
        """Drop every Font reference the game holds. pygame keeps the file
        handle of a Font that outlives ``pygame.quit()``, which leaked five
        ``freesansbold.ttf`` descriptors per session. Called by shutdown()
        just before the quit; the game cannot draw text afterwards."""
        self.fonts.close()
        self.font = self.font_small = None
        self.render_cache.showtext_fonts.clear()
        inventory = getattr(self, 'inventory_ui', None)
        if inventory is not None:
            inventory.release_fonts()
        gc.collect()

    def run(self):
        """Main game loop: start(), step() until quit or disconnect, and
        shutdown() however the loop ends (an escaped exception included).

        Returns the server the player picked from the F8 list, so the launcher
        can reconnect, or None for a normal quit or a lost connection."""
        try:
            # Measured from before startup, as it always was: the first
            # frame's dt covers the startup work (and is clamped).
            last_time = self.clock.frame_now()
            self.start()
            print(f"Starting game loop. running={self.running}, connected={self.client.connected}")

            while self.running and self.client.connected:
                current_time = self.clock.frame_now()
                dt = current_time - last_time
                last_time = current_time
                self.step(dt, strict=False)
                # Cap the display rate. The simulation is not tied to it: it
                # advances in frame ticks whatever the frame rate (one per
                # frame at most, so a tick shorter than the frame runs once
                # per frame).
                self.frame_limiter.tick(60)

            print(f"Game loop exited after {self._frame_count} frames. "
                  f"running={self.running}, connected={self.client.connected}")
            if self.running and not self.client.connected:
                reason = getattr(self.client, 'disconnect_reason', '') or ''
                print(f"Connection to the server was lost{': ' + reason if reason else ''}")
        finally:
            self.shutdown()

        # If the player picked another server from the F8 list, hand it back to
        # the launcher so it can reconnect. None = normal quit.
        return self.switch_server
