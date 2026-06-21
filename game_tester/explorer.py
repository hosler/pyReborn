"""
ExplorerBot - Autonomous exploration AI for finding edge cases.

Wanders the game world, tries random actions, and detects anomalies.
"""

import time
import random
from typing import List, Set, Tuple, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

from .game_bot import GameBot, Issue
from .bug_detector import BugDetector


class ActionType(Enum):
    """Types of actions the explorer can take."""
    MOVE = "move"
    WALK_TO = "walk_to"
    SWORD = "sword"
    SHOOT = "shoot"
    BOMB = "bomb"
    CHAT = "chat"
    PICKUP = "pickup"
    USE_DOOR = "use_door"
    INTERACT_NPC = "interact_npc"
    WAIT = "wait"


@dataclass
class ExploreResult:
    """Result of an exploration session."""
    duration: float
    tiles_visited: int
    total_tiles: int
    actions_performed: int
    anomalies_detected: int
    issues: List[Issue] = field(default_factory=list)
    action_log: List[Dict[str, Any]] = field(default_factory=list)


class ExplorerBot:
    """
    Autonomous exploration AI that wanders and tests randomly.

    Usage:
        bot = GameBot("explorer", "localhost", 14900)
        bot.connect()
        explorer = ExplorerBot(bot)
        result = explorer.explore(duration=60.0)
        print(f"Visited {result.tiles_visited} tiles")
        print(f"Found {result.anomalies_detected} anomalies")
    """

    # Action weights (higher = more likely to be chosen)
    ACTION_WEIGHTS = {
        ActionType.MOVE: 50,       # Most common - basic movement
        ActionType.WALK_TO: 20,    # Pathfinding to random location
        ActionType.SWORD: 10,      # Combat test
        ActionType.SHOOT: 5,       # Arrow test
        ActionType.BOMB: 3,        # Bomb test
        ActionType.CHAT: 5,        # Chat test
        ActionType.PICKUP: 8,      # Item pickup
        ActionType.USE_DOOR: 10,   # Door/warp test
        ActionType.INTERACT_NPC: 8,  # NPC interaction
        ActionType.WAIT: 5,        # Idle/wait
    }

    def __init__(self, bot: GameBot):
        self.bot = bot
        self.visited_tiles: Set[Tuple[int, int]] = set()
        self.action_history: List[Dict[str, Any]] = []
        self.anomalies: List[Issue] = []

        # Exploration state
        self._last_position = (0.0, 0.0)
        self._stuck_count = 0
        self._current_target: Optional[Tuple[float, float]] = None

    def explore(self, duration: float = 60.0, verbose: bool = False) -> ExploreResult:
        """
        Explore autonomously for the specified duration.

        Args:
            duration: How long to explore in seconds
            verbose: Print actions as they happen

        Returns:
            ExploreResult with statistics and findings
        """
        start_time = time.time()
        end_time = start_time + duration
        actions_performed = 0

        if verbose:
            print(f"[Explorer] Starting {duration}s exploration...")

        while time.time() < end_time:
            # Track visited tile
            tile_x = int(self.bot.x)
            tile_y = int(self.bot.y)
            self.visited_tiles.add((tile_x, tile_y))

            # Choose and execute action
            action = self._choose_action()
            success = self._execute_action(action, verbose)
            actions_performed += 1

            # Log action
            self.action_history.append({
                'time': time.time() - start_time,
                'action': action.value,
                'position': (self.bot.x, self.bot.y),
                'success': success
            })

            # Check for anomalies
            self._check_for_anomalies()

            # Update bot state
            self.bot.update(0.1)

        # Final stats
        total_duration = time.time() - start_time

        if verbose:
            print(f"[Explorer] Finished. Visited {len(self.visited_tiles)} tiles, "
                  f"{actions_performed} actions, {len(self.anomalies)} anomalies")

        return ExploreResult(
            duration=total_duration,
            tiles_visited=len(self.visited_tiles),
            total_tiles=64 * 64,  # Standard level size
            actions_performed=actions_performed,
            anomalies_detected=len(self.anomalies),
            issues=self.anomalies.copy(),
            action_log=self.action_history.copy()
        )

    def _choose_action(self) -> ActionType:
        """
        Choose next action based on weights and current state.

        Prioritizes:
        - Unexplored areas
        - Nearby items/NPCs/doors
        - Random weighted selection otherwise
        """
        # Check for nearby interesting things
        if self.bot.items:
            # Items on ground - try to pick up
            return ActionType.PICKUP

        if self.bot.npcs:
            # NPCs visible - maybe interact
            if random.random() < 0.3:
                return ActionType.INTERACT_NPC

        # Check for door at current position
        link = self.bot.client.check_link_collision()
        if link and random.random() < 0.2:
            return ActionType.USE_DOOR

        # Check if stuck - if so, try different action
        if self._is_stuck():
            self._stuck_count += 1
            if self._stuck_count > 5:
                # Try something different
                self._stuck_count = 0
                return random.choice([ActionType.WALK_TO, ActionType.USE_DOOR, ActionType.SWORD])
        else:
            self._stuck_count = 0

        # Prioritize unexplored areas
        if random.random() < 0.3:
            unexplored = self._find_unexplored_direction()
            if unexplored:
                self._current_target = unexplored
                return ActionType.WALK_TO

        # Weighted random selection
        return self._weighted_random_action()

    def _weighted_random_action(self) -> ActionType:
        """Select action based on weights."""
        total_weight = sum(self.ACTION_WEIGHTS.values())
        r = random.uniform(0, total_weight)

        cumulative = 0
        for action, weight in self.ACTION_WEIGHTS.items():
            cumulative += weight
            if r <= cumulative:
                return action

        return ActionType.MOVE  # Default

    def _execute_action(self, action: ActionType, verbose: bool = False) -> bool:
        """Execute the chosen action."""
        if verbose:
            print(f"  [{action.value}] at ({self.bot.x:.1f}, {self.bot.y:.1f})")

        self._last_position = (self.bot.x, self.bot.y)

        if action == ActionType.MOVE:
            # Random direction
            dx = random.choice([-1, 0, 1])
            dy = random.choice([-1, 0, 1])
            if dx == 0 and dy == 0:
                dx = 1  # At least move somewhere
            return self.bot.move(dx, dy)

        elif action == ActionType.WALK_TO:
            # Walk to target or random location
            if self._current_target:
                target_x, target_y = self._current_target
                self._current_target = None
            else:
                target_x = random.uniform(5, 59)
                target_y = random.uniform(5, 59)
            return self.bot.walk_to(target_x, target_y, timeout=5.0)

        elif action == ActionType.SWORD:
            direction = random.randint(0, 3)
            return self.bot.sword_attack(direction)

        elif action == ActionType.SHOOT:
            direction = random.randint(0, 3)
            return self.bot.shoot(direction)

        elif action == ActionType.BOMB:
            return self.bot.drop_bomb(power=1)

        elif action == ActionType.CHAT:
            messages = [
                "Testing...",
                f"Explorer at ({self.bot.x:.0f}, {self.bot.y:.0f})",
                "Hello world!",
                "Beep boop",
            ]
            return self.bot.say(random.choice(messages))

        elif action == ActionType.PICKUP:
            if self.bot.items:
                pos = list(self.bot.items.keys())[0]
                return self.bot.pickup_item(pos[0], pos[1])
            return False

        elif action == ActionType.USE_DOOR:
            return self.bot.use_nearest_door()

        elif action == ActionType.INTERACT_NPC:
            npc_id = self.bot.get_nearest_npc()
            if npc_id:
                return self.bot.interact_with_npc(npc_id)
            return False

        elif action == ActionType.WAIT:
            self.bot.update(0.5)
            return True

        return False

    def _is_stuck(self) -> bool:
        """Check if bot hasn't moved."""
        dx = abs(self.bot.x - self._last_position[0])
        dy = abs(self.bot.y - self._last_position[1])
        return dx < 0.1 and dy < 0.1

    def _find_unexplored_direction(self) -> Optional[Tuple[float, float]]:
        """Find a nearby unexplored tile to target."""
        current_x = int(self.bot.x)
        current_y = int(self.bot.y)

        # Check tiles in expanding radius
        for radius in range(1, 10):
            candidates = []
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if abs(dx) == radius or abs(dy) == radius:  # Edge of square
                        tx, ty = current_x + dx, current_y + dy
                        if 1 <= tx <= 62 and 1 <= ty <= 62:  # In bounds
                            if (tx, ty) not in self.visited_tiles:
                                candidates.append((float(tx), float(ty)))

            if candidates:
                return random.choice(candidates)

        return None

    def _check_for_anomalies(self):
        """Check for anomalies after each action."""
        # Position checks
        result = BugDetector.check_out_of_bounds(self.bot.client)
        if not result.passed:
            self._add_anomaly("HIGH", "position", result.message, result.details)

        # Position discontinuity (teleportation)
        if len(self.bot.position_history) >= 2:
            result = BugDetector.check_position_discontinuity(
                self.bot.position_history[-10:], max_jump=10.0
            )
            if not result.passed:
                self._add_anomaly("WARN", "position", result.message, result.details)

        # Connection check
        if not self.bot.connected:
            self._add_anomaly("HIGH", "connection", "Unexpected disconnect")

        # Check for invalid tile data
        if self.bot.tiles:
            tile_idx = int(self.bot.y) * 64 + int(self.bot.x)
            if 0 <= tile_idx < len(self.bot.tiles):
                tile = self.bot.tiles[tile_idx]
                if tile < 0 or tile > 65535:
                    self._add_anomaly("MEDIUM", "data",
                                     f"Invalid tile value {tile} at ({self.bot.x:.0f}, {self.bot.y:.0f})")

    def _add_anomaly(self, severity: str, category: str, description: str,
                     details: Optional[Dict[str, Any]] = None):
        """Add a detected anomaly."""
        # Avoid duplicate anomalies
        for existing in self.anomalies:
            if existing.description == description:
                return

        self.anomalies.append(Issue(
            timestamp=time.time(),
            severity=severity,
            category=category,
            description=description,
            context=details or {}
        ))

    def get_coverage_map(self) -> List[List[bool]]:
        """Get a 64x64 grid showing visited tiles."""
        grid = [[False] * 64 for _ in range(64)]
        for x, y in self.visited_tiles:
            if 0 <= x < 64 and 0 <= y < 64:
                grid[y][x] = True
        return grid

    def get_coverage_percentage(self) -> float:
        """Get percentage of level tiles visited."""
        return len(self.visited_tiles) / (64 * 64) * 100

    def print_coverage_map(self):
        """Print ASCII coverage map."""
        grid = self.get_coverage_map()
        print("Coverage Map (. = visited, # = unvisited):")
        for y in range(0, 64, 2):  # Print every other row for compactness
            row = ""
            for x in range(0, 64, 2):  # Print every other column
                if grid[y][x]:
                    row += "."
                else:
                    row += "#"
            print(row)
        print(f"Coverage: {self.get_coverage_percentage():.1f}%")
