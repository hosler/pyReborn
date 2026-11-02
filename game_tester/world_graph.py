"""Socket-free level routing through directed links and GMAP seams."""

from collections import deque
from dataclasses import dataclass
import math
from pathlib import Path
import threading


@dataclass(frozen=True)
class Hop:
    """One level transition, with a source-local rectangle and destination.

    Destination coordinates are numbers or the literal playerx/playery (keep
    that local player coordinate). A seam rectangle spans a segment boundary;
    it describes ordinary movement, never a warp.
    """

    source_level: str
    x: float
    y: float
    width: float
    height: float
    dest_level: str
    dest_x: float | str
    dest_y: float | str
    seam: bool = False


class WorldGraph:
    """Thread-safe level graph; one instance is shared by all daemon bots."""

    def __init__(self):
        self._lock = threading.Lock()
        self._edges: dict[str, list[Hop]] = {}
        self._names: dict[str, str] = {}

    def _name(self, name):
        name = str(name).strip()
        return self._names.setdefault(name.casefold(), name)

    def _add(self, hop):
        edges = self._edges.setdefault(hop.source_level.casefold(), [])
        if hop not in edges:
            if hop.seam:
                edges.insert(0, hop)
            else:
                edges.append(hop)

    @classmethod
    def from_world_dir(cls, path) -> "WorldGraph":
        """Read recursive .nw LINK records and .gmap segment grids."""
        graph = cls()
        files = sorted(p for p in Path(path).rglob('*') if p.is_file())
        # Register file spelling before resolving mixed-case destinations.
        for file in files:
            if file.suffix.casefold() == '.nw':
                graph._name(file.name)
        for file in files:
            if file.suffix.casefold() == '.nw':
                for line in file.read_text(errors='replace').splitlines():
                    parts = line.split()
                    if len(parts) == 8 and parts[0] == 'LINK':
                        graph.add_observed(file.name, [dict(zip(
                            ('dest_level', 'x', 'y', 'width', 'height',
                             'dest_x', 'dest_y'), parts[1:]))])
            elif file.suffix.casefold() == '.gmap':
                graph._read_gmap(file.read_text(errors='replace'))
        return graph

    def _read_gmap(self, text):
        width, reading, names = 0, False, []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith('WIDTH '):
                try:
                    width = int(line.split()[1])
                except (ValueError, IndexError):
                    return
            elif line == 'LEVELNAMES':
                reading = True
            elif line in ('LEVELNAMESEND', 'LEVELNAMES END'):
                reading = False
            elif reading:
                names.extend(token.strip().strip('"').strip()
                             for token in line.split(',') if token.strip().strip('"').strip())
        if width <= 0:
            return
        grid = {(i % width, i // width): self._name(name)
                for i, name in enumerate(names)}
        self._add_seams(grid)

    def _add_seams(self, grid):
        for (gx, gy), source in grid.items():
            source = self._name(source)
            for dx, dy, rect in ((1, 0, (64, 0, .5, 64)),
                                 (-1, 0, (-.5, 0, .5, 64)),
                                 (0, 1, (0, 64, 64, .5)),
                                 (0, -1, (0, -.5, 64, .5))):
                dest = grid.get((gx + dx, gy + dy))
                if dest:
                    self._add(Hop(source, *rect, self._name(dest), 'playerx', 'playery', True))

    def add_observed(self, level, links) -> None:
        """Merge client.links[level] records, skipping malformed entries."""
        with self._lock:
            source = self._name(level)
            for link in links:
                try:
                    dest = link['dest_level']
                    if not isinstance(dest, str) or not dest.strip():
                        continue
                    rect = tuple(float(link[key]) for key in ('x', 'y', 'width', 'height'))
                    if not all(math.isfinite(n) for n in rect) or min(rect[2:]) <= 0:
                        continue
                    coords = []
                    for key in ('dest_x', 'dest_y'):
                        value = str(link[key]).casefold()
                        value = value if value in ('playerx', 'playery') else float(value)
                        if isinstance(value, float) and not math.isfinite(value):
                            raise ValueError('nonfinite destination')
                        coords.append(value)
                    self._add(Hop(source, *rect, self._name(dest), *coords))
                except (KeyError, ValueError, TypeError):
                    continue

    def neighbours(self, level) -> list[Hop]:
        """Return outgoing hops; level lookup is case-insensitive."""
        with self._lock:
            return list(self._edges.get(str(level).casefold(), ()))

    def route(self, src, dst) -> list[Hop] | None:
        """BFS for the fewest level transitions; [] means already there."""
        with self._lock:
            src, dst = str(src).casefold(), str(dst).casefold()
            parents = {src: None}
            queue = deque([src])
            while queue:
                current = queue.popleft()
                if current == dst:
                    route = []
                    while parents[current] is not None:
                        hop = parents[current]
                        route.append(hop)
                        current = hop.source_level.casefold()
                    return route[::-1]
                # Read directly: neighbours() acquires the same non-reentrant lock.
                for hop in self._edges.get(current, ()):
                    dest = hop.dest_level.casefold()
                    if dest not in parents:
                        parents[dest] = hop
                        queue.append(dest)
            return None
