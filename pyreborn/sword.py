"""Sword timing and probes from TPlayer.cpp:5438-5494, :6484-6520."""

from dataclasses import dataclass

TICK = 0.05
SWORD_TICKS = 5  # sword.gani: five steps; animatePlayer compares counter >4.
SPIN_TICKS = 13  # spin.gani in both content roots has thirteen steps.
NPC_OFFSETS = ((-0.5, -1.8), (-1.8, -0.5), (-0.5, 1.8), (1.8, -0.5))


def npc_probe(x, y, direction):
    dx, dy = NPC_OFFSETS[direction]
    return x + 1.5 + dx, y + 2.0 + dy


def owns_spin(client):
    # TPlayer.cpp:6888-6892, :7701-7706: item 24 is data pointer 2.
    # getStatusFlags (:2720-2724) exposes it as status bit 0x40.
    return bool(client.player.status & 0x40 or any(
        str(name).lower() == 'spinattack' for name in client.weapons))


def play_sword_pose(game):
    name = game.client.player.animation
    if name == 'spin':
        gani = game.gani_parser.parse('spin')
        if gani is None:
            name = 'idle'
        else:
            prefetch = getattr(game, '_prefetch_gani_assets', None)
            if prefetch is not None:
                prefetch(gani)
    game._play_action_animation(name, broadcast=False)


@dataclass
class SwordState:
    started: float
    direction: int
    spin: bool = False
    tick: int = 0

    @property
    def duration(self):
        return (SPIN_TICKS if self.spin else SWORD_TICKS) * TICK

    def sword_direction(self, tick):
        # TServerPlayer.cpp:1003-1013: rotation changes every TWO steps.
        return ((self.direction + tick // 2) % 4
                if self.spin and tick <= 7 else self.direction)

    def due(self, now):
        count = SPIN_TICKS if self.spin else SWORD_TICKS
        end = min(count, int((max(0, now - self.started) + 1e-9) / TICK) + 1)
        while self.tick < end:
            tick = self.tick
            self.tick += 1
            yield tick, self.sword_direction(tick)
