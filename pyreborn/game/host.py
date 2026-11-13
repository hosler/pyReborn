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
* the annotations equal ``vars(game)`` after ``__init__``, plus the test's
  ``CLASS_LEVEL`` names; nothing is assigned later, and no ``getattr`` /
  ``hasattr`` guard reads a declared name.

Editing rules (the sections below follow the cluster plan, one section per
owned object, so a cluster step edits only its own section):

* add an attribute to ``GameClient.__init__`` and to its section here in the
  same change. A value that fills on first use starts as ``None`` or empty in
  ``__init__``; there is no lazy attribute and no guard on a declared name;
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
    from ..gs1_client.runtime import ClientGS1
    from ..gs2_client import ClientGS2
    from ..inventory_ui import HeartDisplay, InventoryUI
    from ..npc_handler import NPCHandler
    from ..sounds import SoundManager
    from ..sprites import SpriteManager, TilesetManager
    from .assets import FontManager
    from .camera import Camera2D
    from .chat_state import ChatState
    from .callbacks.client_callbacks import Gs2SourceRouter
    from .combat_presentation import CombatPresentation
    from .dialogue import DialoguePager
    from .frame_context import FrameContext
    from .hud import HUD
    from .interpolation import TickInterpolator
    from .level_arrival import LevelArrival
    from .particles_state import Particles
    from .push_grab import PushGrab
    from .transition import TransitionState
    from .render_cache import RenderCache
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
    _ground_ticks: Optional[Tuple[Any, Any]]
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
    push: "PushGrab"

    # -- level arrival (LevelArrival, S4) ------------------------------------
    arrival: "LevelArrival"

    # -- level transition (TransitionState, S8) -----------------------------
    transition: "TransitionState"

    # -- render caches (RenderCache; groups A and B moved, C/R below) -------
    render_cache: "RenderCache"

    # -- render caches, group C: world and objects (RenderCache, S6) ---------
    world_surface: Optional["pygame.Surface"]

    # -- particles (Particles, S9) -------------------------------------------
    particles: "Particles"

    # -- chat (ChatState, S10) -----------------------------------------------
    chat: "ChatState"

    # -- combat presentation and GS2 source routing (S3) ---------------------
    combat_presentation: "CombatPresentation"
    gs2_sources: "Gs2SourceRouter"

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

    # -- method stubs for cross-mixin calls (type checking only) -------------
    # Nothing under this block executes: it gives mypy the signature of every
    # method or property one mixin calls on another (or on GameClient), copied
    # from the defining class. tests/unit/test_game_host_stubs.py keeps each
    # stub equal to inspect.signature of the real method. Add a stub when a
    # mixin starts calling a method another class defines; delete it when the
    # method goes.
    if TYPE_CHECKING:

        # GameClient
        @property
        def screen_h(self) -> int: ...
        @property
        def screen_w(self) -> int: ...
        @property
        def weapons(self) -> List[str]: ...

        # SetupMixin
        def _check_level_change(self): ...
        def _load_new_npcs(self): ...
        def _load_npc_scripts(self): ...
        def _play_audio(self, name: str): ...
        def _process_pending_warp(self): ...
        def _process_self_shoots(self): ...
        def _setup_asset_paths(self) -> List[Path]: ...
        def _setup_callbacks(self): ...
        def _setup_gs1_callbacks(self): ...
        def _trigger_playerenters(self): ...
        def _update_low_hearts_warning(
            self, now: Optional[float] = None
        ) -> bool: ...

        # CollisionMixin
        def _blocked_sample_count(self, x: float, y: float) -> int: ...
        def _can_ledge_jump(self, direction): ...
        def _check_water_at_position(self, x: float, y: float) -> bool: ...
        def _corner_assist_offset(
            self, dx: int, dy: int
        ) -> Optional[Tuple[int, int]]: ...
        def _effective_tile_type(self, x: float, y: float) -> int: ...
        def _get_tile_at(self, x: float, y: float) -> int: ...
        def _is_blocked_at(
            self, x: float, y: float, *, check_players=True, include_local=False
        ) -> bool: ...
        def _is_position_blocked(
            self, x: float, y: float, dx: int = 0, dy: int = 0
        ) -> bool: ...
        def _is_tile_blocking(self, tile_id: int) -> bool: ...
        def _ledge_ahead(self, direction): ...
        def _level_tiles_at(self, x: float, y: float): ...
        def _player_blocks(
            self, x: float, y: float, *, include_local=False
        ) -> bool: ...
        def _player_feet(self) -> Tuple[float, float]: ...
        def _player_ground(self) -> Tuple[float, float]: ...
        def _position_out_of_bounds(self, x: float, y: float) -> bool: ...
        def _tile_type(self, tile_id: int) -> int: ...
        def _touch_points(self, direction: int) -> List[Tuple[float, float]]: ...
        def _world_to_level_local(self, x: float, y: float) -> Tuple[int, int]: ...

        # InputMixin
        def _end_input_tick(self) -> None: ...
        def _handle_events(self): ...
        def _handle_input(self, current_time: float): ...
        def _update_death_state(self, current_time): ...

        # ActionsMixin
        def _advance_ground_effects(self, dt): ...
        def _advance_hurt(self, dt): ...
        def _advance_ledge_jump(self, dt): ...
        def _auto_pickup_items(self) -> int: ...
        def _check_scripted_link_warp(self) -> bool: ...
        def _clear_grab_state(self): ...
        def _clear_push_hold(self): ...
        def _cycle_weapon(self): ...
        def _dismiss_dialogue(self): ...
        def _facing_delta(self, direction: int) -> Tuple[int, int]: ...
        def _giveaway_drop(self) -> bool: ...
        def _giveaway_select(self): ...
        def _hide_or_unhide(self): ...
        def _is_hidden(self) -> bool: ...
        def _move(self, dx: int, dy: int): ...
        def _scripted_movement_touch(self, keys): ...
        def _swing_sword(self): ...
        def _throw_object(self): ...
        def _try_grab(self): ...
        def _try_pickup(self, dx: int, dy: int): ...
        def _update_grab_pull_state(self, dx: int, dy: int): ...
        def _update_sitting_state(self): ...
        def _update_sleeping_state(self): ...
        def _update_swimming_state(self): ...
        def _use_weapon(self): ...

        # RenderMixin
        def _render(self): ...
        def _update_animations(self, dt: float): ...
        def _update_visual_position(self, alpha: float): ...
        def _world_to_screen(
            self, world_x: float, world_y: float
        ) -> Tuple[float, float]: ...

        # WorldRenderMixin
        def _render_animated_tiles(self): ...
        def _render_world(self): ...

        # EntityRenderMixin
        def _render_baddy(self, x: float, y: float, baddy: dict, baddy_id: int): ...
        def _render_horse(self, x: float, y: float, horse: dict, key): ...
        def _render_layer_rec(self, rec: dict) -> None: ...
        def _render_npc(
            self,
            x: float,
            y: float,
            npc: dict,
            npc_id: int,
            frame: Optional[FrameContext] = None,
        ): ...
        def _render_npc_layers(
            self,
            imgs: dict,
            over: bool,
            on_screen_only: bool = False,
            gui: bool = False,
        ): ...
        def _render_other_player(
            self,
            x: float,
            y: float,
            pdata: dict,
            pid: int,
            frame: Optional[FrameContext] = None,
        ): ...
        def _render_player(
            self,
            x: float,
            y: float,
            player: Player,
            anim: AnimationState,
            frame: Optional[FrameContext] = None,
        ): ...
        def _request_asset(self, filename: str): ...
        def _status_label(self, status) -> str: ...

        # EntityCollectMixin
        def _collect_chests(
            self, out: List["_Entity"], frame: FrameContext
        ) -> None: ...
        def _collect_items(
            self, out: List["_Entity"], frame: FrameContext
        ) -> None: ...
        @staticmethod
        def _depth_sort_key(world_y: float, height_tiles: float) -> float: ...
        def _draw_chest_entity(
            self, ent: "_Entity", frame: FrameContext
        ) -> None: ...
        def _draw_item_entity(
            self, ent: "_Entity", frame: FrameContext
        ) -> None: ...
        def _entity_on_screen(
            self,
            px: float,
            py: float,
            margin: int = 96,
            width: float = 0.0,
            height: float = 0.0,
            screen_size: Optional[Tuple[int, int]] = None,
        ) -> bool: ...
        def _render_entities(self, frame: Optional[FrameContext] = None): ...

        # EffectsRenderMixin
        def _add_remote_bomb(self, info: dict, now: Optional[float] = None): ...
        def _advance_bombs(self) -> None: ...
        def _client_bomb_record(self, bomb: dict): ...
        def _render_bombs(self, frame: Optional[FrameContext] = None): ...
        def _render_break_effects(self): ...
        def _render_carried_bomb(self, x, y, bomb=None): ...
        def _render_combat_presentation(self): ...
        def _render_damage_numbers(self): ...
        def _render_layer_emitter(self, rec: dict, emitter) -> None: ...
        def _render_leaf_particles(self): ...
        def _render_leaps(self): ...
        def _render_projectiles(
            self, frame: Optional[FrameContext] = None
        ) -> None: ...
        def _render_screen_tint(self, frame: Optional[FrameContext] = None): ...
        def _render_server_explosions(
            self, frame: Optional[FrameContext] = None
        ): ...
        def _render_thrown(self, frame: Optional[FrameContext] = None) -> None: ...
        def _render_water_ripples(self): ...
        def _spawn_leaps(self, leap_type: int, x: float, y: float, now=None): ...
        def _update_projectiles(self, dt: float) -> None: ...
        def _update_thrown(self, dt: float) -> None: ...

        # LevelObjectsRenderMixin
        def _check_and_render_signs(self): ...
        def _current_segment_info(self): ...
        def _current_segment_origin(self): ...
        def _get_chest_sprite(self, opened: bool) -> Optional[pygame.Surface]: ...
        def _get_item_sprite(self, item_type: str) -> pygame.Surface: ...
        def _render_chest_reveals(self, now_ms: Optional[int] = None) -> None: ...

        # ClockedMixin
        @property
        def clock(self): ...

        # RenderTextMixin
        def _place_nameplate(
            self,
            name_x: float,
            name_y: float,
            size: Tuple[int, int],
            frame: Optional[FrameContext] = None,
        ) -> Tuple[float, float]: ...
        def _render_speech_bubble(self, x: float, y: float, text: str): ...
        def _render_text_outlined_cached(
            self,
            font: pygame.font.Font,
            text: str,
            color: Tuple[int, int, int],
            outline_color: Tuple[int, int, int] = (0, 0, 0),
        ) -> pygame.Surface: ...

        # LayerRenderMixin
        @staticmethod
        def _fade_surface_edges(surf: pygame.Surface, frac: float = 0.35): ...
        def _layer_draw_size(self, rec) -> Tuple[float, float]: ...
        @staticmethod
        def _layer_is_gui(rec) -> bool: ...
        def _layer_place_for_sort(self, rec, screen_size=None): ...
        def _layer_pos(self, rec): ...
        def _poly_layer_on_screen(self, rec) -> bool: ...
        def _render_deferred_lights(self, frame: Optional[FrameContext] = None): ...
        def _render_light_sprite(
            self,
            sprite: pygame.Surface,
            x: float,
            y: float,
            is_light: bool,
            coloreffect: Optional[Tuple[float, float, float, float]],
            frame: Optional[FrameContext] = None,
        ): ...
        def _render_showani_rec(self, rec: dict): ...
        def _render_showimg_rec(self, rec: dict): ...
        def _render_showpoly_rec(self, rec: dict): ...
        def _render_showtext_rec(self, rec: dict): ...
        def _showtext_font(self, name: str, size: int, bold: bool): ...

        # GaniRenderMixin
        def _render_animated_entity(
            self,
            x: float,
            y: float,
            anim: AnimationState,
            equipment: dict,
            alpha: int = 255,
        ): ...

        # FlyingObjectsMixin
        def _advance_flying(self, proj: dict, dt: float) -> bool: ...

        # FrameContextMixin
        def _begin_frame(self) -> FrameContext: ...
        def _frame_context(self) -> FrameContext: ...


# Names the method stubs above use that the data sections do not import.
# Kept apart from the import block at the top so a cluster step that edits
# that block never collides with this one.
if TYPE_CHECKING:
    from pathlib import Path

    from ..player import Player
    from .render_shared import _Entity
