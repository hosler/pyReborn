"""Font-aware wrapping and paging for the in-game dialogue box."""

import re
from typing import Callable, List

# Control-function -> bound key display name, matching input.py's
# _feed_gs1_input mapping (scripting-gs1-functions.md control table):
# 0=up 1=left 2=down 3=right 4=weapon(D) 5=sword(S) 6=grab(A) 7=map(M)
# 8=chat(Tab) 9=inventory(Q) 10=pause(P, unbound here).
_SIGN_KEY_NAMES = {
    0: "Up", 1: "Left", 2: "Down", 3: "Right", 4: "D", 5: "S", 6: "A",
    7: "M", 8: "Tab", 9: "Q", 10: "P",
}

# Sign button-symbol escapes (GServer LevelSign.cpp signSymbols): the real
# client draws these as key/arrow glyphs; render readable names instead of
# leaking the raw "#u"/"#A" tokens into the box.
_SIGN_SYMBOL_NAMES = {
    'u': "Up", 'd': "Down", 'l': "Left", 'r': "Right",
    'A': "A", 'B': "B", 'X': "X", 'Y': "Y", 'h': "Start",
}


def format_sign_text(text: str) -> str:
    """Translate decoded sign-code escapes into displayable text.

    The wire decoder (packets.decode_sign_text) is a faithful mirror of
    GServer's decodeSignCode and leaves the classic escape tokens in the
    string; the real client renders them as glyphs. Translations here follow
    LevelSign.cpp's encoder semantics:

    - ``#K(nn)`` is the server's escape for a raw character with ASCII code
      nn ("Write the character code directly into the sign") -> chr(nn).
      Filenames survive this: eye#K(95)bomber.png -> eye_bomber.png.
    - ``#k(n)`` shows the key bound to control function n -> our binding
      names (see _SIGN_KEY_NAMES).
    - ``#u/#d/#l/#r/#A/...`` button symbols -> readable names.
    - ``#i(image[,x,y,w,h])`` inline images aren't drawn in the text box ->
      dropped (a leading empty ``#i()`` line collapses away via the strip).
    - ``#b`` is a line break (same translation packet_codec's parse_say2
      already applies on the wire); done FIRST so a ``#K(35)``-escaped ``#``
      followed by a literal ``b`` can't be misread as a break.
    """
    def _chr_escape(m):
        try:
            code = int(m.group(1))
        except ValueError:
            return m.group(0)
        return chr(code) if 32 <= code < 127 else ''

    def _key_escape(m):
        try:
            return _SIGN_KEY_NAMES.get(int(m.group(1)), m.group(0))
        except ValueError:
            return m.group(0)

    text = text.replace('#b', '\n')
    text = re.sub(r'#K\((\d+)\)', _chr_escape, text)
    text = re.sub(r'#k\((\d+)\)', _key_escape, text)
    text = re.sub(r'#i\([^)]*\)', '', text)
    text = re.sub(r'#([udlrABXYh])',
                  lambda m: _SIGN_SYMBOL_NAMES[m.group(1)], text)
    # Drop lines that became empty after an inline-image strip, but keep
    # deliberate blank lines (they were whitespace-only on the wire too).
    lines = text.split('\n')
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines)


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

