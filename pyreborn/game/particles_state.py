"""Presentation particle registries owned by the game (``self.particles``).

Plain lists of effect dicts plus the one reset a level reload performs.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class Particles:
    breaks: List[dict] = field(default_factory=list)  # thrown-object break bursts
    leaves: List[dict] = field(default_factory=list)  # vegetation fragments
    ripples: List[dict] = field(default_factory=list)  # swim ripples
    leaps: List[dict] = field(default_factory=list)  # GS1 putleaps bursts
    last_ripple_time: float = float('-inf')
    damage_numbers: List[dict] = field(default_factory=list)  # floating hurt numbers

    def clear_level(self) -> None:
        """What a level reload drops: breaks, leaves and ripples. Leaps and
        damage numbers deliberately survive, as they always have."""
        self.breaks.clear()
        self.leaves.clear()
        self.ripples.clear()
