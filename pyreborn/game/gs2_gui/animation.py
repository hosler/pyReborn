from __future__ import annotations

import math
from typing import Any, Optional, Tuple

from reborn_protocol.gs2 import GS2Object, to_bool, to_num, to_str


_TRANSITIONS = (
    "transform", "fadeout", "fadein", "moveoutleft", "moveinleft",
    "moveoutright", "moveinright", "moveouttop", "moveintop",
    "moveoutbottom", "moveinbottom", "moveupdown", "moveleftright",
    "flipoutleft", "flipinleft", "flipoutright", "flipinright",
    "rotateoutleft", "rotateinleft", "rotateoutright", "rotateinright",
    "zoomin", "zoomout", "zoominout", "growin", "growout", "shrinkin",
    "shrinkout",
)
_IN_OUT_TRANSITIONS = frozenset({
    "fadeout", "fadein", "moveoutleft", "moveinleft", "moveouttop",
    "moveintop", "moveoutbottom", "moveinbottom", "flipoutleft",
    "flipinleft", "flipinright", "rotateoutleft", "rotateoutright",
    "rotateinright", "zoomin", "zoomout", "growout", "shrinkout",
})
_SHOW_ON_FINISH = frozenset({
    "fadein", "moveinleft", "moveintop", "moveinbottom", "flipinleft",
    "flipinright", "rotateinright", "zoomin",
})
_PROPERTIES = frozenset({
    "currenttime", "alpha", "amplitude", "bounds", "delay", "duration",
    "interval", "rotation", "sound", "tabfirstonshow", "timing",
    "transition",
})


def _bounds(value: Any) -> Optional[Tuple[float, float, float, float]]:
    if isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = to_str(value).replace(",", " ").split()
    if len(parts) < 4:
        return None
    return tuple(to_num(part) for part in parts[:4])


class TGUIAnimation(GS2Object):
    """One script-owned description of a control animation."""

    def __init__(self, owner):
        super().__init__(name="TGUIAnimation")
        self.owner = owner
        self.currenttime = 0.0
        self.alpha = 1.0
        self.amplitude = 32.0
        self.delay = 0.0
        self.duration = 1.0
        self.interval = 1.0
        self.rotation = 0.0
        self.sound = ""
        self.tabfirstonshow = True
        self.timing = "linear"
        self.transition = ""
        self._target_bounds: Optional[Tuple[float, float, float, float]] = None
        self._has_alpha = False
        self._has_rotation = False
        self._started = False
        self._original_bounds = None
        self._original_alpha = 1.0
        self._original_rotation = 0.0

    def has(self, key: str) -> bool:
        return key.lower() in _PROPERTIES or super().has(key)

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "bounds":
            value = self._target_bounds or self.owner.animation_bounds()
            return " ".join(str(int(v)) if float(v).is_integer() else str(v)
                            for v in value)
        if k in _PROPERTIES:
            value = getattr(self, k)
            if k == "tabfirstonshow":
                return 1.0 if value else 0.0
            return value
        return super().get(k)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k not in _PROPERTIES:
            super().set(k, value)
            return
        if k == "bounds":
            parsed = _bounds(value)
            if parsed is not None:
                self._target_bounds = parsed
            return
        if k in {"currenttime", "alpha", "amplitude", "delay", "duration",
                 "interval", "rotation"}:
            setattr(self, k, to_num(value))
            if k == "alpha":
                self._has_alpha = True
            elif k == "rotation":
                self._has_rotation = True
            return
        if k == "tabfirstonshow":
            self.tabfirstonshow = to_bool(value)
        elif k == "timing":
            timing = to_str(value).lower()
            self.timing = timing if timing in {"linear", "sinus"} else "linear"
        elif k == "transition":
            transition = to_str(value).lower()
            self.transition = transition if transition in _TRANSITIONS else ""
        else:
            self.sound = to_str(value)

    @property
    def is_in_out(self) -> bool:
        return self.transition in _IN_OUT_TRANSITIONS

    def _begin(self) -> None:
        if self._started:
            return
        self._started = True
        self._original_bounds = self.owner.animation_bounds()
        self._original_alpha = self.owner.alpha
        self._original_rotation = self.owner.rotation
        if self.transition == "fadein":
            self.owner.alpha = 0.0

    def advance(self, seconds: float) -> bool:
        if self.owner is None or self.duration <= 0.0 or not self.transition:
            return False
        self.currenttime += seconds if seconds > 0.0 else 0.016
        if self.currenttime < self.delay:
            return True
        self._begin()
        progress = min(1.0, (self.currenttime - self.delay) / self.duration)
        if self.timing == "sinus":
            progress = math.sin(progress * math.pi / 2.0)
        if self.transition == "transform":
            self._apply_transform(progress)
        elif self.transition == "fadeout":
            self.owner.alpha = self._original_alpha * (1.0 - progress)
        elif self.transition == "fadein":
            self.owner.alpha = self._original_alpha * progress
        else:
            self.owner.visible = True
        if progress < 1.0:
            return True
        self.currenttime = self.delay + self.duration
        if self.transition == "fadeout":
            self.owner.visible = False
            self.owner.alpha = self._original_alpha
        elif self.transition == "fadein":
            self.owner.visible = True
            self.owner.alpha = self._original_alpha
        elif self.transition != "transform":
            self.owner.visible = self.transition in _SHOW_ON_FINISH
        return False

    def _apply_transform(self, progress: float) -> None:
        if self._target_bounds is not None:
            start = self._original_bounds
            target = self._target_bounds
            values = tuple(int(a + (b - a) * progress + 0.5)
                           for a, b in zip(start, target))
            self.owner.apply_animation_bounds(values)
        if self._has_alpha:
            self.owner.alpha = self._original_alpha + (
                self.alpha - self._original_alpha) * progress
        if self._has_rotation:
            self.owner.rotation = self._original_rotation + (
                self.rotation - self._original_rotation) * progress
