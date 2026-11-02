"""Static A* planning in world tile coordinates, with optional soft costs."""

import heapq
import math
import time
from enum import Enum
from itertools import count
from typing import Callable, List, Optional, Tuple


Position = Tuple[float, float]
STEP = 0.5


class PathFailure(Enum):
    UNREACHABLE = "unreachable"


UNREACHABLE = PathFailure.UNREACHABLE


def plan_path(start: Position, goal: Position,
              blocked: Callable[[float, float], bool],
              cost: Optional[Callable[[float, float], float]] = None,
              max_nodes: int = 768,
              deadline: float | None = None) -> List[Position] | PathFailure | None:
    """Return lattice waypoints, including a start correction when needed.

    Snap start to the nearest clear half-tile node within two tiles, and emit
    that correction first. Goal is rounded to the world half-tile lattice;
    the caller must approach the exact goal after following the waypoints.
    Cardinal steps cost 1; diagonals cost sqrt(2) and cannot cut blocked corners.
    cost(x, y) adds a finite, nonnegative penalty for entering a cell. A search
    expands at most max_nodes distinct cells, including start and goal.
    deadline uses time.monotonic(); check it before probing and every 256
    expansions. Collision results are cached for this search only.
    UNREACHABLE means the reachable set was exhausted. None means a cutoff
    or an unusable snapped endpoint; neither proves the exact goal unreachable.
    """
    if max_nodes <= 0 or (deadline is not None and time.monotonic() > deadline):
        return None
    origin = tuple(round(value / STEP) for value in start)
    destination = tuple(round(value / STEP) for value in goal)

    def position(cell):
        return cell[0] * STEP, cell[1] * STEP

    blocked_cells = {}

    def is_blocked(cell):
        if cell not in blocked_cells:
            blocked_cells[cell] = blocked(*position(cell))
        return blocked_cells[cell]

    candidates = [(origin[0] + dx, origin[1] + dy)
                  for dx in range(-4, 5) for dy in range(-4, 5)]
    candidates.sort(key=lambda cell: math.dist(start, position(cell)))
    origin = None
    for cell in candidates:
        if deadline is not None and time.monotonic() > deadline:
            return None
        if not is_blocked(cell):
            origin = cell
            break
    if origin is None:
        return None
    correction = [position(origin)] if position(origin) != start else []
    if destination == origin:
        return correction
    if is_blocked(destination):
        return None

    def heuristic(cell):
        dx, dy = abs(destination[0] - cell[0]), abs(destination[1] - cell[1])
        return max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)

    sequence = count()
    frontier = [(heuristic(origin), next(sequence), 0.0, origin)]
    distances = {origin: 0.0}
    parents = {}
    visited = set()
    while frontier:
        _, _, distance, current = heapq.heappop(frontier)
        if current in visited:
            continue
        if len(visited) >= max_nodes:
            return None
        if (len(visited) % 256 == 0 and deadline is not None
                and time.monotonic() > deadline):
            return None
        visited.add(current)
        if current == destination:
            path = []
            while current != origin:
                path.append(position(current))
                current = parents[current]
            return correction + path[::-1]

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
    if deadline is not None and time.monotonic() > deadline:
        return None
    return UNREACHABLE
