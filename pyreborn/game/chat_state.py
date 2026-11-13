"""Chat log, chat-line input, scrollback and PM composer state (``self.chat``).

``append`` is the one place a line enters the log: it trims to
``CHAT_HISTORY_CAP`` and advances ``seq``.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from .constants import CHAT_HISTORY_CAP


@dataclass
class ChatState:
    typing: bool = False  # the chat line input is open
    input: str = ""  # text typed into the chat line so far
    messages: List[str] = field(default_factory=list)  # the chat log, capped
    # Monotonic count of appends: unlike len(messages) it keeps growing once
    # the log sits at CHAT_HISTORY_CAP (every append then pops a line), so
    # the scroll indicator's "N new" stays honest.
    seq: int = 0
    # Messages back from the live tail (0 = at bottom); PageUp/PageDown move it.
    scroll: int = 0
    # ``seq`` when scrolling started, so hud.py can show "N new" while scrolled.
    scroll_baseline: int = 0
    pm_target_id: Optional[int] = None  # player we're composing a PM to
    pm_input: str = ""

    def append(self, line: str) -> None:
        """Append one chat-log line, trim to the cap, and advance ``seq``."""
        self.messages.append(line)
        if len(self.messages) > CHAT_HISTORY_CAP:
            self.messages.pop(0)
        self.seq += 1
