"""Render-only timing state for hurt, death, and respawn presentation."""

from dataclasses import dataclass


@dataclass
class CombatPresentation:
    """Visual combat state. No value here participates in game simulation."""

    INVULN_SECONDS = 1.2
    BLINK_HZ = 10.0
    HIT_FLASH_SECONDS = 0.15
    DEATH_FADE_SECONDS = 1.0
    DEATH_OVERLAY_DELAY = 0.35
    RESPAWN_FADE_SECONDS = 0.5

    hurt_started: float = -100.0
    hurt_until: float = -100.0
    death_started: float | None = None
    respawn_started: float | None = None
    warp_started: bool = False

    def hurt(self, now: float, dead: bool = False) -> None:
        self.hurt_started = now
        self.hurt_until = now + self.INVULN_SECONDS
        if dead and self.death_started is None:
            self.death_started = now
            self.respawn_started = None
            self.warp_started = False

    def sync(self, dead: bool, warp_active: bool, now: float) -> None:
        if dead:
            if self.death_started is None:
                self.death_started = now
                self.respawn_started = None
            self.warp_started = self.warp_started or warp_active
        elif self.death_started is not None:
            self.death_started = None
            self.warp_started = False
            self.respawn_started = now
        if self.respawn_started is not None \
                and now - self.respawn_started >= self.RESPAWN_FADE_SECONDS:
            self.respawn_started = None

    def player_alpha(self, now: float, base_alpha: int = 255) -> int:
        if now >= self.hurt_until:
            return base_alpha
        dim = int((now - self.hurt_started) * self.BLINK_HZ) % 2 == 1
        return min(base_alpha, 105) if dim else base_alpha

    def hit_flash_alpha(self, now: float) -> int:
        age = now - self.hurt_started
        if not 0 <= age < self.HIT_FLASH_SECONDS:
            return 0
        return round(100 * (1.0 - age / self.HIT_FLASH_SECONDS))

    def death_fade_alpha(self, now: float) -> int:
        if self.death_started is None:
            return 0
        age = max(0.0, now - self.death_started)
        return round(190 * min(1.0, age / self.DEATH_FADE_SECONDS))

    def show_death_overlay(self, now: float) -> bool:
        return bool(self.death_started is not None
                    and not self.warp_started
                    and now - self.death_started + 1e-9
                    >= self.DEATH_OVERLAY_DELAY)

    def respawn_fade_alpha(self, now: float) -> int:
        if self.respawn_started is None:
            return 0
        age = max(0.0, now - self.respawn_started)
        return round(255 * max(0.0, 1.0 - age / self.RESPAWN_FADE_SECONDS))
