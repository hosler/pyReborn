"""Round-trip coverage for the client-side GLEVNW01 writer."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

from pyreborn.game.editor.nw_writer import (
    BOARD_ALPHABET, MissingNpcScriptError, serialize_level,
)


def _parse_level(text):
    parsed = {"tiles": [0] * 4096, "links": [], "signs": {},
              "chests": [], "npcs": [], "baddies": []}
    lines = text.splitlines()
    assert lines.pop(0) == "GLEVNW01"
    index = 0
    while index < len(lines):
        parts = lines[index].split()
        index += 1
        if not parts:
            continue
        if parts[0] == "BOARD":
            start_x, y, width = map(int, parts[1:4])
            data = parts[5]
            for offset in range(width):
                high = BOARD_ALPHABET.index(data[offset * 2])
                low = BOARD_ALPHABET.index(data[offset * 2 + 1])
                parsed["tiles"][y * 64 + start_x + offset] = high * 64 + low
        elif parts[0] == "LINK":
            parsed["links"].append({
                "dest_level": " ".join(parts[1:-6]),
                "x": int(parts[-6]), "y": int(parts[-5]),
                "width": int(parts[-4]), "height": int(parts[-3]),
                "dest_x": parts[-2], "dest_y": parts[-1],
            })
        elif parts[0] == "SIGN":
            body = []
            while lines[index].strip() != "SIGNEND":
                body.append(lines[index])
                index += 1
            index += 1
            parsed["signs"][(int(parts[1]), int(parts[2]))] = "\n".join(body)
        elif parts[0] == "CHEST":
            parsed["chests"].append((int(parts[1]), int(parts[2]),
                                      parts[3], int(parts[4])))
        elif parts[0] == "BADDY":
            # GServer-v2 LevelLoader.cpp:804 takes the first three lines up to
            # BADDYEND as the verses, whatever they contain.
            verses = []
            while lines[index].strip() != "BADDYEND":
                verses.append(lines[index])
                index += 1
            index += 1
            parsed["baddies"].append((int(parts[1]), int(parts[2]),
                                      int(parts[3]), verses[:3]))
        elif parts[0] == "NPC":
            body = []
            while lines[index].strip() != "NPCEND":
                body.append(lines[index])
                index += 1
            index += 1
            parsed["npcs"].append((" ".join(parts[1:-2]), float(parts[-2]),
                                    float(parts[-1]), "\n".join(body)))
    return parsed


def _serialize(**overrides):
    values = {
        "level_name": "workshop.nw", "board": [0] * 4096,
        "links": [], "signs": {}, "chests": [], "npcs": {},
        "npc_scripts": {},
    }
    values.update(overrides)
    return serialize_level(**values)


def test_level_state_round_trips_through_format_parser():
    board = [index % 4096 for index in range(4096)]
    link = {"x": 2, "y": 3, "width": 4, "height": 5,
            "dest_level": "next room.nw", "dest_x": "30.5", "dest_y": "31"}
    sign_text = 'AZaz09!?-.,#>()"\':/~& <;\n#A ## [brackets]'
    text = _serialize(
        board=board, links=[link], signs={(7, 8): sign_text},
        chests=[{"x": 9, "y": 10, "item": "greenrupee", "sign": 2}],
        npcs={42: {"_level": "workshop.nw", "x": 11.5, "y": 12,
                   "image": "guide.png"}},
        npc_scripts={42: "if (created) {\n  message Welcome!;\n}"},
    )
    parsed = _parse_level(text)

    assert parsed["tiles"] == board
    assert parsed["links"] == [link]
    assert parsed["signs"] == {(7, 8): sign_text}
    assert parsed["chests"] == [(9, 10, "greenrupee", 2)]
    assert parsed["npcs"] == [
        ("guide.png", 11.5, 12.0, "if (created) {\n  message Welcome!;\n}")
    ]


def test_baddies_survive_the_round_trip_with_all_three_verses():
    # Leaving baddies out of the writer silently DELETED every one of them
    # from an exported level: a real export against GServer-v2 came back
    # without the graysoldier the reference copy still had.
    baddy = {"x": 25.0, "y": 25.0, "type": 0, "verse_sight": "hello",
             "verse_hurt": "hurt", "verse_attack": "dead"}
    parsed = _parse_level(_serialize(baddies=[baddy]))
    assert parsed["baddies"] == [(25, 25, 0, ["hello", "hurt", "dead"])]


def test_a_baddy_with_no_verses_still_writes_three_lines():
    # The reader counts lines, so a missing verse has to be an EMPTY line and
    # not an absent one, or the verses below it shift up a slot.
    parsed = _parse_level(_serialize(baddies=[{"x": 3, "y": 4, "type": 5}]))
    assert parsed["baddies"] == [(3, 4, 5, ["", "", ""])]


def test_sign_text_does_not_grow_a_blank_line_per_round_trip():
    # Signs arrive from the wire with a trailing newline. Writing it puts a
    # blank line above SIGNEND, which reads back as part of the sign - so the
    # sign gained one more blank line on every export -> reload cycle.
    text = _serialize(signs={(1, 2): "line one\nline two\n"})
    assert _parse_level(text)["signs"] == {(1, 2): "line one\nline two"}


def test_full_board_preserves_both_tile_id_extremes():
    board = [0, 4095] * 2048
    assert _parse_level(_serialize(board=board))["tiles"] == board


def test_missing_npc_script_is_named_and_refused():
    with pytest.raises(MissingNpcScriptError, match=r"NPC 77"):
        _serialize(npcs={77: {"x": 1, "y": 2, "image": "guard.png"}})


def test_empty_level_features_serialize_fine():
    text = _serialize()
    parsed = _parse_level(text)
    assert len([line for line in text.splitlines() if line.startswith("BOARD ")]) == 64
    assert parsed["signs"] == {}
    assert parsed["links"] == []
    assert parsed["npcs"] == []
