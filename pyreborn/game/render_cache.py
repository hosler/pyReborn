"""RenderCache: the game's derived render state, in one owned object.

Rule for the object: derived state only. Dropping it (assigning a fresh
``RenderCache()``) changes performance, never a pixel;
``tests/unit/test_render_cache_derived.py`` proves that with the frame
baseline. State that must survive (``_requested_assets``, the sprite
managers' own caches) does not live here.

Fields drop the old leading underscore and ``_cache`` suffix. Every group's
fields are declared up front; a group's attributes on the game itself are
removed in the step that migrates that group (A: S2, B: S5, C: S6, R: S8),
and until then the game keeps the old names. Each ``default_factory`` builds
exactly the container the call site built before the move.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ..lru import LruCache


@dataclass
class RenderCache:
    # -- group A: text, entities, gani (render_text / render_entities / render_gani)
    text_surf: LruCache = field(default_factory=lambda: LruCache(500))        # render_text
    text_outline: LruCache = field(default_factory=lambda: LruCache(500))     # render_text
    wrap: LruCache = field(default_factory=lambda: LruCache(300))             # render_text
    nameplate_grid: Optional[Any] = None                                      # render_text
    gani_layer: LruCache = field(default_factory=lambda: LruCache(2000))      # render_gani
    entity_alpha: LruCache = field(default_factory=lambda: LruCache(600))     # render_gani
    npc_gani_split: LruCache = field(default_factory=lambda: LruCache(300))   # render_entities
    other_anim_split: LruCache = field(default_factory=lambda: LruCache(300))  # render_entities
    npc_zoom: LruCache = field(default_factory=lambda: LruCache(100))         # render_entities
    prefetched_gani_names: Set[str] = field(default_factory=set)              # render_entities
    baddy_sheets: Dict[Any, Any] = field(default_factory=dict)                # render_entities

    # -- group B: effects and layers (render_effects / render_layers; S5)
    combat_surface: Dict[Any, Any] = field(default_factory=dict)
    hurt_vignette_ready: bool = False
    # 400 is EffectsRenderMixin._PARTICLE_CACHE_CAP (a literal here so this
    # module imports nothing from the render mixins).
    particle_surf: LruCache = field(default_factory=lambda: LruCache(400))
    ripple_surface: Dict[Any, Any] = field(default_factory=dict)
    day_night_overlay_key: Optional[Any] = None
    day_night_overlay_surface: Optional[Any] = None
    tint_overlay_key: Optional[Any] = None
    tint_overlay_surface: Optional[Any] = None
    tint_hole_scratch: Optional[Any] = None
    light_sprite: LruCache = field(default_factory=lambda: LruCache(300))
    showimg: LruCache = field(default_factory=lambda: LruCache(300))
    showtext_fonts: Dict[Any, Any] = field(default_factory=dict)

    # -- group C: world and objects (render_world / render_objects; S6)
    segment: "OrderedDict[Any, Any]" = field(default_factory=OrderedDict)
    shimmer: Dict[Any, Any] = field(default_factory=dict)
    anim_draw: Optional[Any] = None
    animated_tiles: List[Any] = field(default_factory=list)
    animated_tiles_key: Optional[Any] = None
    shimmer_step_this_frame: int = 0
    shimmer_draw_this_frame: bool = False
    chest_sprite: Dict[Any, Any] = field(default_factory=dict)
    item_sprite: Dict[Any, Any] = field(default_factory=dict)

    # -- group R: render.py (S8)
    zoom_scene_key: Optional[Any] = None
    zoom_scene_surface: Optional[Any] = None
    zoom_scene_cam: Optional[Any] = None
    gui_cam: Optional[Any] = None
    gui_cam_key: Optional[Any] = None
    camera_bounds_key: Optional[Any] = None
