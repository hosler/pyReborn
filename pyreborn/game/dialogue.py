"""Font-aware wrapping and paging for the in-game dialogue box."""

from typing import Callable, List


def wrap_dialogue(text: str, measure: Callable[[str], int], max_width: int) -> List[str]:
    """Wrap text by rendered width while retaining explicit line boundaries."""
    lines: List[str] = []
    for paragraph in text.split('\n'):
        words = paragraph.split()
        current = ""
        for source_word in words:
            word = source_word
            chunks = []
            while measure(word) > max_width and len(word) > 1:
                cut = len(word) - 1
                while cut > 1 and measure(word[:cut]) > max_width:
                    cut -= 1
                chunks.append(word[:cut])
                word = word[cut:]
            chunks.append(word)
            for chunk in chunks:
                candidate = current + (" " if current else "") + chunk
                if measure(candidate) <= max_width:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = chunk
        if current:
            lines.append(current)
        elif not words:
            lines.append("")
    return lines


class DialoguePager:
    """A line-oriented viewport over wrapped dialogue text."""

    def __init__(self, page_size: int = 3):
        self.page_size = page_size
        self.text = ""
        self.lines: List[str] = []
        self.offset = 0

    def replace(self, text: str, measure: Callable[[str], int], max_width: int):
        self.text = text
        self.lines = wrap_dialogue(text, measure, max_width)
        self.offset = 0

    @property
    def visible_lines(self) -> List[str]:
        return self.lines[self.offset:self.offset + self.page_size]

    @property
    def has_more(self) -> bool:
        return self.offset + self.page_size < len(self.lines)

    def advance(self) -> bool:
        """Advance one page; return False when the final page should close."""
        if not self.has_more:
            return False
        self.offset = min(len(self.lines) - 1, self.offset + self.page_size)
        return True

    def scroll(self, amount: int):
        maximum = max(0, len(self.lines) - self.page_size)
        self.offset = max(0, min(maximum, self.offset + amount))

