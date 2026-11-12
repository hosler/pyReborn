"""Font-aware wrapping and paging for the in-game dialogue box."""

import csv
import re
from dataclasses import dataclass
from itertools import chain
from typing import Callable, List, Optional, Tuple

# Control-function -> bound key display name, matching the gs1_index column
# of game/keymap.py (scripting-gs1-functions.md control table):
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


@dataclass(frozen=True)
class SignImage:
    name: str
    part: Optional[Tuple[int, int, int, int]] = None

    def load(self, sprite_mgr):
        if sprite_mgr is None:
            return None
        if self.part is not None:
            return sprite_mgr.get_sprite(self.name, *self.part)
        return sprite_mgr.load_sheet(self.name)

    def width(self, surface):
        if surface is None:
            return 0
        return self.part[2] if self.part is not None else surface.get_width()


class SignText(str):
    """A display string with an ordered token-to-image mapping."""

    def __new__(cls, text, images):
        value = super().__new__(cls, text)
        value.images = images
        return value

    def segments(self, line):
        start = 0
        for index, char in enumerate(line):
            if char in self.images:
                if start < index:
                    yield line[start:index]
                yield self.images[char]
                start = index + 1
        if start < len(line):
            yield line[start:]

    def measure(self, line, measure_text, sprite_mgr):
        return sum(measure_text(segment) if isinstance(segment, str)
                   else segment.width(segment.load(sprite_mgr))
                   for segment in self.segments(line))


def layout_dialogue_line(line, font, color, sign_text=None, sprite_mgr=None):
    """Return surfaces with pen advances, total width, and row height."""
    segments = sign_text.segments(line) if sign_text is not None else [line]
    runs = []
    width = 0
    height = font.get_linesize()
    for segment in segments:
        if isinstance(segment, str):
            surface = font.render(segment, True, color)
            advance = font.size(segment)[0]
        else:
            surface = segment.load(sprite_mgr)
            advance = segment.width(surface)
            if surface is not None:
                height = max(height, surface.get_height())
        if surface is not None:
            runs.append((surface, advance))
        width += advance
    return runs, width, height


def format_sign_text(text: str) -> SignText:
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
    - ``#i(image[,x,y,w,h])`` becomes one private-use character per image,
      with specs in the returned string's ordered ``images`` mapping, per
      TPlayer.cpp:4506 parseSignImages. Malformed markers lose only ``#i``.
      Image tokens occupy pixel width at the pen, per TPlayer.cpp:4434
      drawStringLine; our rows grow to fit their tallest image.
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
    text = re.sub(r'#([udlrABXYh])',
                  lambda m: _SIGN_SYMBOL_NAMES[m.group(1)], text)
    images = {}
    used_chars = set(text)
    tokens = (chr(code) for code in chain(range(0xE000, 0xF900),
                                         range(0xF0000, 0xFFFFE),
                                         range(0x100000, 0x10FFFE))
              if chr(code) not in used_chars)

    def _image_escape(spec):
        name = spec
        part = None
        if ',' in spec:
            try:
                parts = next(csv.reader([spec], skipinitialspace=True))
            except csv.Error:
                parts = spec.split(',')
            name = parts[0].strip()
            if len(parts) > 4:
                def _integer(value):
                    try:
                        return int(value)
                    except ValueError:
                        return 0
                part = tuple(_integer(value) for value in parts[1:5])
        token = next(tokens)
        images[token] = SignImage(name, part)
        return token

    output = []
    start = 0
    while (marker := text.find('#i', start)) >= 0:
        output.append(text[start:marker])
        start = marker + 2
        if text[start:start + 1] != '(':
            continue
        depth = 0
        for end in range(start, len(text)):
            if text[end] == '(':
                depth += 1
            elif text[end] == ')':
                depth -= 1
                if depth == 0:
                    output.append(_image_escape(text[start + 1:end]))
                    start = end + 1
                    break
    output.append(text[start:])
    text = ''.join(output)
    # Trim blank boundary lines; image tokens keep image-only lines nonempty.
    lines = text.split('\n')
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return SignText('\n'.join(lines), images)


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

