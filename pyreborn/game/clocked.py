"""The clock a game-layer mixin reads: its client's.

`Client` owns the one clock (pyreborn/clock.py). Every `GameClient` mixin that
times something (a fuse, a bubble, an animation frame, a hurt window) reads
`self.clock`; inheriting this gives it that, and a test harness that mixes in
one of them and holds a real `Client` gets it for free.
"""

from .host import GameHost


class ClockedMixin(GameHost):
    @property
    def clock(self):
        """The client's clock (`self.client.clock`)."""
        return self.client.clock
