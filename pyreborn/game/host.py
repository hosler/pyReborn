"""GameHost: every instance attribute a GameClient has, declared once.

Annotations only. A bare annotation creates no attribute, so ``getattr`` /
``hasattr`` / ``vars(game)`` behave exactly as they did before this class
existed. The eight root mixins of the GameClient MRO inherit it (``GameHost``
sits just before ``object`` in the MRO), which gives every mixin one catalogue
of what ``self`` holds. It is a base class, not a Protocol: a Protocol would
need a ``self: GameHost`` annotation on every method.

``tests/unit/test_game_state_declared.py`` enforces the catalogue:

* every store to a game attribute in the game layer names an annotation here
  (or a method/property);
* the annotations equal ``vars(game)`` after ``__init__``, plus the names the
  test's ``LAZY_ALLOWED`` and ``CLASS_LEVEL`` lists carry.

Editing rules (the sections below follow the cluster plan, one section per
owned object, so a cluster step edits only its own section):

* add an attribute to ``GameClient.__init__`` and to its section here in the
  same change; a name the game creates lazily goes in ``LAZY_ALLOWED`` too, and
  leaves it again the moment ``__init__`` assigns it;
* a moved cluster replaces its section's lines with ``<object>: "<Class>"``;
* only data attributes are annotated, never properties (a property that a
  subclass defines over a writeable annotation is a type error).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    import pygame

    from ..client import Client
    from ..gani import AnimationState, GaniParser
    from ..gs1_client import ClientGS1
    from ..gs2_client import ClientGS2
    from ..inventory_ui import HeartDisplay, InventoryUI
    from ..lru import LruCache
    from ..npc_handler import NPCHandler
    from ..sounds import SoundManager
    from ..sprites import SpriteManager, TilesetManager
    from .assets import FontManager
    from .camera import Camera2D
    from .combat_presentation import CombatPresentation
    from .dialogue import DialoguePager
    from .frame_context import FrameContext
    from .hud import HUD
    from .interpolation import TickInterpolator
    from .settings_ui import SettingsOverlay
    from .viewport import Viewport


class GameHost:
    """Declared state of a GameClient (see the module docstring)."""

    # -- core: session, window, managers (GameShell members and managers) ----
    client: "Client"
    screen: "pygame.Surface"
    camera: "Camera2D"
    viewport: "Viewport"
    hud: "HUD"
    gs1: "ClientGS1"
    gs2: "ClientGS2"
    npc_handler: "NPCHandler"
    sprite_mgr: "SpriteManager"
    tileset_mgr: "TilesetManager"
    sound_mgr: "SoundManager"
    inventory_ui: "InventoryUI"
    heart_display: "HeartDisplay"
    gani_parser: "GaniParser"
    interpolator: "TickInterpolator"
    settings_ui: "SettingsOverlay"
    asset_paths: List[Any]
    frame_limiter: "pygame.time.Clock"
    frame_errors: Dict[str, Any]
    running: bool
    servers: List[Any]
    switch_server: Optional[Any]
    switch_frame_tick: Optional[int]
    rc_password: Optional[str]
    ghost_mode: int
    noclip: bool
    debug_mode: bool
    _started: bool
    _shut_down: bool
    _frame_count: int
    _frame_dt: float
    _dbg: bool
    _was_dead: bool
    _frame_ctx: Optional["FrameContext"]
    _overlay_stack: Optional[Any]
    _requested_assets: Set[str]

    # -- fonts and placeholder art -------------------------------------------
    font: Optional["pygame.font.Font"]
    font_small: Optional["pygame.font.Font"]
    fonts: "FontManager"
    placeholder_sprite: "pygame.Surface"
    shadow_sprite: "pygame.Surface"
    npc_placeholder: "pygame.Surface"

    # -- player state and timing (kept as declared attributes) ---------------
    is_moving: bool
    is_swimming: bool
    visual_x: float
    visual_y: float
    player_anim: "AnimationState"
    current_anim_name: str
    walk_speed: float
    action_delay: float
    sword_delay: float
    last_action_time: float
    last_sword_time: float
    bomb_fuse_time: float
    _move_accum: float
    _player_render_pos: Tuple[float, float]
    _pushaway_velocity: Tuple[float, float]
    _triggeraction_sent: Dict[Any, Any]
    _camera_enabled: bool
    _day_night_enabled: bool
    screen_tint: Optional[Any]
    key_just_pressed: Dict[Any, Any]
    _gs1_keypress_queue: List[Any]
    _ledge_jump: Optional[Any]
    _frozen_until: float
    _swim_in_lava: bool
    _step_parity: int
    _footstep_tick: Optional[int]
    _sleep_level: Optional[str]
    _sleep_was_moving: bool
    _sign_contact_key: Optional[Any]
    _ground_ticks: Tuple[Any, Any]
    _giveaway_item: Optional[Any]
    _found_chest_level: Optional[str]
    _item_take_sent: Set[Any]
    _item_first_seen: Dict[Any, Any]
    _death_started: Optional[float]

    # -- simulation entity lists ---------------------------------------------
    active_projectiles: List[Any]
    thrown_objects: List[Any]
    other_thrown_objects: List[Any]
    active_bombs: List[Any]

    # -- per-entity animation and visual state -------------------------------
    baddy_anims: Dict[Any, Any]
    horse_anims: Dict[Any, Any]
    npc_anims: Dict[Any, Any]
    npc_visual: Dict[Any, Any]
    npc_effects: Dict[Any, Any]
    npc_chat_texts: Dict[Any, Any]
    other_player_anims: Dict[Any, Any]
    other_player_visual: Dict[Any, Any]
    local_chat_text: str
    local_chat_time: Optional[float]
    chat_bubble_duration: float
    dialogue_text: Optional[str]
    dialogue_pager: "DialoguePager"
    dialogue_classic_font: bool
    _npc_visual_epoch: Dict[Any, Any]
    _swamp_pos: Optional[Any]
    _swamp_slot: Optional[Any]
    _chest_reveals: List[Any]
    _chest_reveal_snapshots: Dict[Any, Any]

    # -- push/grab (PushGrab, S1) --------------------------------------------
    _push_hold_dir: Optional[int]
    _push_hold_start: Optional[float]
    _push_counter: int
    _push_fire_cycle: int
    _push_fired: bool
    is_pushing: bool
    grab_state: Optional[Any]
    _grab_direction: Optional[int]
    _pull_started: Optional[float]
    _pull_fired: bool
    _pull_counter: int

    # -- level arrival (LevelArrival, S4) ------------------------------------
    _gs1_level: Optional[str]
    _gs1_visual_level_epoch: Optional[int]
    _gs1_playerenters_pending: bool
    _level_change_pending: Optional[str]
    _level_change_at: float
    _pending_gs1_warp: Optional[Tuple[str, float, float]]
    _was_on_link: bool
    _link_arrival: Optional[Any]
    _scripted_link_pos: Optional[Any]
    _scripted_gmap_cell: Optional[Any]

    # -- level transition (TransitionState, S8) -----------------------------
    _level_transition_slide: Optional[Dict[str, Any]]
    _level_transition_input_frozen: bool
    _transition_frame: Optional["pygame.Surface"]
    _transition_scene_frame: Optional["pygame.Surface"]
    _death_base_frame: Optional["pygame.Surface"]
    _seen_level_transition_epoch: int

    # -- render caches, group A: text, entities, gani (RenderCache, S2) ------
    _text_surf_cache: "LruCache"
    _text_outline_cache: "LruCache"
    _wrap_cache: "LruCache"
    _nameplate_grid: Optional[Any]
    _gani_layer_cache: "LruCache"
    _entity_alpha_cache: "LruCache"
    _npc_gani_split_cache: "LruCache"
    _other_anim_split_cache: "LruCache"
    _npc_zoom_cache: "LruCache"
    _prefetched_gani_names: Set[str]
    baddy_sheets: Dict[Any, Any]

    # -- render caches, group B: effects and layers (RenderCache, S5) --------
    _combat_surface_cache: Dict[Any, Any]
    _hurt_vignette_ready: bool
    _particle_surf_cache: "LruCache"
    _ripple_surface_cache: Dict[Any, Any]
    _day_night_overlay_key: Optional[Any]
    _day_night_overlay_surface: Optional["pygame.Surface"]
    _tint_overlay_key: Optional[Any]
    _tint_overlay_surface: Optional["pygame.Surface"]
    _tint_hole_scratch: Optional["pygame.Surface"]
    _light_sprite_cache: "LruCache"
    _showimg_cache: "LruCache"
    _showtext_fonts: Dict[Any, Any]

    # -- render caches, group C: world and objects (RenderCache, S6) ---------
    world_surface: Optional["pygame.Surface"]
    _segment_cache: Any
    _shimmer_cache: Dict[Any, Any]
    _anim_draw: Optional[Any]
    _animated_tiles: List[Any]
    _animated_tiles_key: Optional[Any]
    _shimmer_step_this_frame: int
    _shimmer_draw_this_frame: bool
    _chest_sprite_cache: Dict[Any, Any]
    _item_sprite_cache: Dict[Any, Any]

    # -- render caches, group R: render.py (RenderCache, S8) -----------------
    _zoom_scene_key: Optional[Any]
    _zoom_scene_surface: Optional["pygame.Surface"]
    _zoom_scene_cam: Optional["Camera2D"]
    _gui_cam: Optional["Camera2D"]
    _gui_cam_key: Optional[Any]
    _camera_bounds_key: Optional[Any]

    # -- particles (Particles, S9) -------------------------------------------
    break_effects: List[Any]
    leaf_particles: List[Any]
    water_ripples: List[Any]
    leap_bursts: List[Any]
    _last_ripple_time: float
    damage_numbers: List[Any]
    explosion_duration: float
    grass_tile_id: int

    # -- chat (ChatState, S10) -----------------------------------------------
    typing: bool
    chat_input: str
    chat_messages: List[Any]
    chat_seq: int
    chat_scroll: int
    _chat_scroll_baseline: int
    pm_target_id: Optional[int]
    pm_input: str

    # -- combat presentation and GS2 source routing (S3) ---------------------
    combat_presentation: "CombatPresentation"
    _presented_hurt_stamp: Optional[Any]
    _presented_hurt_generation: Optional[int]
    _gs2_source_attempts: Dict[Any, int]
    _gs2_source_warned: Set[Any]
    _gs2_source_compiler: Optional[Any]

    # -- setup and script requests -------------------------------------------
    _pending_self_shoots: List[Any]
    _scripted_player_ani: Optional[str]
    _camera_focus: Optional[Tuple[float, float]]
    _camera_shake_started: Optional[float]
    _current_music_name: Optional[str]
    _pending_music: Optional[str]
    _gs2_shape1_npcs: Set[Any]
    _low_hearts_next_beep: float
    _low_hearts_warning_enabled: bool

    # -- input state and overlays ---------------------------------------------
    _latch_context: Optional[Any]
    _mouse_left_latched: bool
    _vk_cache: Dict[Any, Any]
    server_warp_prompt: Optional[Any]
    hud_notice: Optional[Tuple[str, float]]
    show_help: bool
    show_player_list: bool
    show_server_list: bool
    big_map_visible: bool
    player_list_sel: int
    server_list_sel: int
    roster_ready_time: float
    fullscreen: bool

    # -- lazy UIs (created on first use, stay None until then) ---------------
    rc_ui: Optional[Any]
    dev_ui: Optional[Any]
    level_editor: Optional[Any]
    editor_overlay: Optional[Any]
    tile_palette: Optional[Any]

    # -- minimap and bigmap ----------------------------------------------------
    minimap_visible: bool
    minimap_size: Tuple[int, int]
    minimap_data: Optional[Any]
    minimap_surface: Optional["pygame.Surface"]
    bigmap_surface: Optional["pygame.Surface"]
    _minimap_image_name: Optional[str]
    _bigmap_image_name: Optional[str]
    _minimap_native_surface: Optional["pygame.Surface"]
