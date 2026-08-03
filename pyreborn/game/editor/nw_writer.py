"""Write client level state as GLEVNW01 text.

NPC scripts are not delivered by the game connection.  Callers must fetch
them separately and supply an entry for every NPC in the level.  Missing
entries raise :class:`MissingNpcScriptError`; an empty script is accepted only
when it was explicitly supplied.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


LEVEL_SIZE = 64
TILE_COUNT = LEVEL_SIZE * LEVEL_SIZE
BOARD_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
)


class MissingNpcScriptError(ValueError):
    """Raised when serializing an NPC whose script was not supplied."""


def _single_line(value: Any, field: str) -> str:
    text = str(value)
    if "\n" in text or "\r" in text:
        raise ValueError(f"{field} cannot contain a newline")
    return text


def _block_text(value: Any, terminator: str, field: str) -> str:
    """One block body, without the trailing newline the wire delivers.

    A sign arrives as ``"line one\\nline two\\n"``, and the terminator goes on
    its own line below, so keeping that newline writes a blank line INSIDE the
    block.  Reading the level back then makes that blank line part of the sign,
    and the sign grows another one on every export -> reload round trip.
    """
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if terminator in text.split("\n"):
        raise ValueError(f"{field} contains reserved line {terminator}")
    return text


def _encode_board(board: Sequence[int]) -> list[str]:
    if len(board) != TILE_COUNT:
        raise ValueError(f"board must contain exactly {TILE_COUNT} tiles")
    rows = []
    for y in range(LEVEL_SIZE):
        encoded = []
        for x in range(LEVEL_SIZE):
            tile_id = int(board[y * LEVEL_SIZE + x])
            if not 0 <= tile_id <= 4095:
                raise ValueError(f"tile ({x}, {y}) id {tile_id} is not representable")
            encoded.extend((BOARD_ALPHABET[tile_id // 64],
                            BOARD_ALPHABET[tile_id % 64]))
        rows.append(f"BOARD 0 {y} 64 0 {''.join(encoded)}")
    return rows


def _chest_fields(chest: Any) -> tuple[Any, Any, Any, Any]:
    if isinstance(chest, Mapping):
        return chest["x"], chest["y"], chest["item"], chest.get("sign", 0)
    if len(chest) not in (3, 4):
        raise ValueError(f"chest must have 3 or 4 fields: {chest!r}")
    return (*chest, 0) if len(chest) == 3 else tuple(chest)


def _baddy_fields(baddy: Mapping[str, Any]) -> tuple[int, int, int, list[str]]:
    if "x" not in baddy or "y" not in baddy:
        raise ValueError(f"baddy is missing x or y: {baddy!r}")
    verses = [_single_line(baddy.get(key) or "", f"baddy {key}")
              for key in ("verse_sight", "verse_hurt", "verse_attack")]
    if "BADDYEND" in verses:
        raise ValueError("baddy verse contains reserved line BADDYEND")
    return int(baddy["x"]), int(baddy["y"]), int(baddy.get("type", 0)), verses


def serialize_level(
    level_name: str,
    board: Sequence[int],
    links: Iterable[Mapping[str, Any]],
    signs: Mapping[tuple[Any, Any], str],
    chests: Iterable[Any],
    npcs: Mapping[Any, Mapping[str, Any]],
    npc_scripts: Mapping[Any, str],
    baddies: Iterable[Mapping[str, Any]] = (),
) -> str:
    """Return one level's live state in GLEVNW01 format.

    NPC records attributed to another level are ignored.  An NPC without an
    ``_level`` property is treated as belonging to ``level_name``, matching the
    active-level shape used by the client.
    """
    level_npcs = [
        (npc_id, npc) for npc_id, npc in npcs.items()
        if npc.get("_level", level_name) == level_name
    ]
    missing = [npc_id for npc_id, _npc in level_npcs
               if npc_id not in npc_scripts]
    if missing:
        names = ", ".join(str(npc_id) for npc_id in missing)
        raise MissingNpcScriptError(f"missing script for NPC {names}")

    lines = ["GLEVNW01", *_encode_board(board)]

    for link in links:
        required = ("dest_level", "x", "y", "width", "height",
                    "dest_x", "dest_y")
        absent = [field for field in required if field not in link]
        if absent:
            raise ValueError(f"link is missing fields: {', '.join(absent)}")
        values = [_single_line(link[field], f"link {field}")
                  for field in required]
        if not values[0]:
            raise ValueError("link destination level cannot be empty")
        lines.append("LINK " + " ".join(values))

    for (x, y), text in signs.items():
        sign_text = _block_text(text, "SIGNEND", f"sign ({x}, {y})")
        lines.extend((f"SIGN {int(x)} {int(y)}", sign_text, "SIGNEND"))

    for chest in chests:
        x, y, item, sign = _chest_fields(chest)
        item_name = _single_line(item, "chest item")
        if not item_name or any(character.isspace() for character in item_name):
            raise ValueError("chest item must be one non-whitespace token")
        lines.append(f"CHEST {int(x)} {int(y)} {item_name} {int(sign)}")

    # Baddies sit between the chests and the NPCs, and carry three verse lines
    # whether or not they are set, exactly as the reference server writes them
    # (GServer-v2 Level.cpp:900-908). Its reader takes a type name or a numeric
    # id (LevelBaddy.cpp:44-62); the numeric id is what the wire gives us and
    # what its own writer emits.
    for baddy in baddies:
        x, y, baddy_type, verses = _baddy_fields(baddy)
        lines.extend((f"BADDY {x} {y} {baddy_type}", *verses, "BADDYEND"))

    for npc_id, npc in level_npcs:
        if "x" not in npc or "y" not in npc:
            raise ValueError(f"NPC {npc_id} is missing x or y")
        image = _single_line(npc.get("image") or "-", f"NPC {npc_id} image")
        script = _block_text(npc_scripts[npc_id], "NPCEND",
                             f"NPC {npc_id} script")
        lines.extend((f"NPC {image} {npc['x']} {npc['y']}", script, "NPCEND"))

    return "\n".join(lines) + "\n"
