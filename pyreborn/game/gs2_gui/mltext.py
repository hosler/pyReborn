from __future__ import annotations

from typing import List, Optional, Tuple


# =============================================================================
# GuiMLTextCtrl mini-HTML
#
# The wire text is Torque ML ("<font size=4><b><i>Account:</i></b></font>
# hosler<br>", headings, <center>, <a href=...>). Full HTML is out of
# scope; this handles exactly the vocabulary the live Login server sends
# so the panes read cleanly instead of showing raw markup.
# =============================================================================

_ML_TOKEN_RE = None                     # compiled lazily (re import below)

#: Torque <font size=N> steps mapped to pixel sizes around the profile base
_ML_FONT_SIZES = {1: 9, 2: 11, 3: 13, 4: 15, 5: 17, 6: 20, 7: 24}
_ML_HEADING_SIZES = {1: 24, 2: 21, 3: 19, 4: 17, 5: 15, 6: 13}
_ML_LINK_COLOR = (224, 224, 255)

_ML_ENTITIES = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
                "&quot;": '"', "&#39;": "'"}


class _MLSegment:
    __slots__ = ("text", "bold", "italic", "size", "color", "link", "href")

    def __init__(self, text, bold, italic, size, color, link, href=None):
        self.text = text
        self.bold = bold
        self.italic = italic
        self.size = size            # None = profile base size
        self.color = color          # None = profile font color
        self.link = link
        #: the enclosing <a href=...> attribute value, kept for onURL --
        #: the engine's THTMLActiveLink indexes exactly this string
        #: (THTMLPage.cpp:677-685); None outside a link or with no href
        self.href = href


def _ml_parse_color(value: str):
    value = (value or "").strip().strip('"').strip("'")
    if value.startswith("#"):
        value = value[1:]
        try:
            if len(value) >= 6:
                return (int(value[0:2], 16), int(value[2:4], 16),
                        int(value[4:6], 16))
        except ValueError:
            return None
    named = {"white": (255, 255, 255), "black": (0, 0, 0),
             "red": (224, 64, 64), "yellow": (240, 224, 96),
             "green": (96, 224, 96), "blue": (120, 160, 255)}
    return named.get(value.lower())


def parse_mltext(text: str):
    """Parse Torque ML text into paragraphs: (align, [segments]) lists.
    Unknown tags are stripped; <br>/<p>/<h*> produce line breaks."""
    import re
    global _ML_TOKEN_RE
    if _ML_TOKEN_RE is None:
        _ML_TOKEN_RE = re.compile(r"<[^<>]*>")
    for ent, ch in _ML_ENTITIES.items():
        text = text.replace(ent, ch)

    paragraphs: List[Tuple[str, List[_MLSegment]]] = []
    cur: List[_MLSegment] = []
    bold = 0
    italic = 0
    align_stack: List[str] = []
    size_stack: List[Optional[int]] = []
    color_stack: List[Optional[Tuple[int, int, int]]] = []
    link_depth = 0
    href_stack: List[Optional[str]] = []
    ignore_linebreaks = False

    def cur_align() -> str:
        return align_stack[-1] if align_stack else "left"

    def flush(force: bool = False):
        # Block-tag boundaries (h*, p, center) only break a line when there
        # is pending text; <br> forces a break so "<br><br>" keeps the
        # intentional blank line.
        nonlocal cur
        if cur or force:
            paragraphs.append((cur_align(), cur))
            cur = []

    def emit(run: str):
        if not run:
            return
        cur.append(_MLSegment(
            run, bold > 0, italic > 0,
            size_stack[-1] if size_stack else None,
            (_ML_LINK_COLOR if link_depth > 0
             else (color_stack[-1] if color_stack else None)),
            link_depth > 0,
            (href_stack[-1] if link_depth > 0 and href_stack else None)))

    pos = 0
    for m in _ML_TOKEN_RE.finditer(text):
        raw = text[pos:m.start()]
        if raw:
            if not ignore_linebreaks and "\n" in raw:
                parts = raw.split("\n")
                for i, part in enumerate(parts):
                    emit(part)
                    if i < len(parts) - 1:
                        flush(force=True)
            else:
                emit(raw.replace("\n", " "))
        pos = m.end()
        tag = m.group(0)[1:-1].strip()
        name, _, attrs = tag.partition(" ")
        name = name.lower()
        closing = name.startswith("/")
        if closing:
            name = name[1:]
        if name in ("br", "br/"):
            flush(force=True)
        elif name == "p":
            flush()
            if closing:
                if align_stack:
                    align_stack.pop()
            else:
                am = None
                for chunk in attrs.split():
                    k, _, v = chunk.partition("=")
                    if k.lower() == "align":
                        am = v.strip('"').strip("'").lower()
                align_stack.append(am or cur_align())
        elif name == "center":
            flush()
            if closing:
                if align_stack:
                    align_stack.pop()
            else:
                align_stack.append("center")
        elif name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            flush()
            if closing:
                bold = max(0, bold - 1)
                if size_stack:
                    size_stack.pop()
            else:
                bold += 1
                size_stack.append(_ML_HEADING_SIZES.get(int(name[1]), 17))
        elif name in ("b", "strong"):
            bold = max(0, bold - 1) if closing else bold + 1
        elif name in ("i", "em"):
            italic = max(0, italic - 1) if closing else italic + 1
        elif name == "font":
            if closing:
                if size_stack:
                    size_stack.pop()
                if color_stack:
                    color_stack.pop()
            else:
                fsize = size_stack[-1] if size_stack else None
                fcolor = color_stack[-1] if color_stack else None
                for chunk in attrs.split():
                    k, _, v = chunk.partition("=")
                    k = k.lower()
                    if k == "size":
                        try:
                            fsize = _ML_FONT_SIZES.get(
                                int(v.strip('"').strip("'")), fsize)
                        except ValueError:
                            pass
                    elif k == "color":
                        fcolor = _ml_parse_color(v) or fcolor
                size_stack.append(fsize)
                color_stack.append(fcolor)
        elif name == "a":
            if closing:
                link_depth = max(0, link_depth - 1)
                if href_stack:
                    href_stack.pop()
            else:
                link_depth += 1
                href = None
                for chunk in attrs.split():
                    ak, _, av = chunk.partition("=")
                    if ak.lower() == "href":
                        href = av.strip('"').strip("'")
                href_stack.append(href)
        elif name == "ignorelinebreaks":
            ignore_linebreaks = True
        # anything else (img, table, spans...) is stripped silently
    tail = text[pos:]
    if tail:
        if not ignore_linebreaks and "\n" in tail:
            parts = tail.split("\n")
            for i, part in enumerate(parts):
                emit(part)
                if i < len(parts) - 1:
                    flush(force=True)
        else:
            emit(tail.replace("\n", " "))
    flush()
    # collapse trailing empty paragraphs (every closing tag flushed one)
    while len(paragraphs) > 1 and not paragraphs[-1][1]:
        paragraphs.pop()
    return paragraphs


# =============================================================================
# Control tree
# =============================================================================
