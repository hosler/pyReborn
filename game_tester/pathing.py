"""Static A* planning in world tile coordinates, with optional soft costs."""

import heapq
import math
import time
from itertools import count
from typing import Callable, List, Optional, Tuple


Position = Tuple[float, float]
STEP = 0.5


def plan_path(start: Position, goal: Position,
              blocked: Callable[[float, float], bool],
              cost: Optional[Callable[[float, float], float]] = None,
              max_nodes: int = 768,
              deadline: float | None = None) -> Optional[List[Position]]:
    """Return waypoints after start, including goal, or None if no route fits.

    The half-tile lattice is anchored at start, preserving sub-tile positions.
    Goal is rounded to its nearest lattice point (at most 0.25 tile per axis).
    Cardinal steps cost 1; diagonals cost sqrt(2) and cannot cut blocked corners.
    cost(x, y) adds a finite, nonnegative penalty for entering a cell. A search
    expands at most max_nodes distinct cells, including start and goal.
    deadline uses time.monotonic(); check it before probing and every 256
    expansions. Collision results are cached for this search only.
    """
    if max_nodes <= 0 or (deadline is not None and time.monotonic() > deadline):
        return None
    destination = tuple(round((goal[i] - start[i]) / STEP) for i in (0, 1))

    def position(cell):
        return start[0] + cell[0] * STEP, start[1] + cell[1] * STEP

    blocked_cells = {}

    def is_blocked(cell):
        if cell not in blocked_cells:
            blocked_cells[cell] = blocked(*position(cell))
        return blocked_cells[cell]

    if destination == (0, 0):
        return []
    if is_blocked(destination):
        return None

    def heuristic(cell):
        dx, dy = abs(destination[0] - cell[0]), abs(destination[1] - cell[1])
        return max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)

    sequence = count()
    frontier = [(heuristic((0, 0)), next(sequence), 0.0, (0, 0))]
    distances = {(0, 0): 0.0}
    parents = {}
    visited = set()
    while frontier and len(visited) < max_nodes:
        _, _, distance, current = heapq.heappop(frontier)
        if current in visited:
            continue
        if (len(visited) % 256 == 0 and deadline is not None
                and time.monotonic() > deadline):
            return None
        visited.add(current)
        if current == destination:
            path = []
            while current != (0, 0):
                path.append(position(current))
                current = parents[current]
            return path[::-1]

        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            neighbor = current[0] + dx, current[1] + dy
            if neighbor in visited or is_blocked(neighbor):
                continue
            if dx and dy and (is_blocked((current[0] + dx, current[1]))
                              or is_blocked((current[0], current[1] + dy))):
                continue
            penalty = cost(*position(neighbor)) if cost else 0.0
            if not math.isfinite(penalty) or penalty < 0:
                raise ValueError("Path costs must be finite and nonnegative")
            candidate = distance + (math.sqrt(2) if dx and dy else 1) + penalty
            if candidate >= distances.get(neighbor, math.inf):
                continue
            distances[neighbor] = candidate
            parents[neighbor] = current
            heapq.heappush(frontier, (candidate + heuristic(neighbor),
                                     next(sequence), candidate, neighbor))
    return None
