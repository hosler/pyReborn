"""Client-side prop parsers on the shared descriptor table.

The four parsers (self props, other-player props, NPC props, baddy props) share
one wire table but deliberately keep their own key names and precedence rules;
these pin the differences that are on purpose.
"""

from pyreborn.packets import (
    parse_baddy_props,
    parse_npc_props,
    parse_other_player,
    parse_player_props,
)


def gchar(value: int) -> bytes:
    return bytes(((value + 32) & 0xFF,))


def gstring(text: str) -> bytes:
    return gchar(len(text)) + text.encode('latin-1')


def gint3(value: int) -> bytes:
    return bytes((((value >> 14) & 0x7F) + 32, ((value >> 7) & 0x7F) + 32,
                  (value & 0x7F) + 32))


# =============================================================================
# Deliberate self-vs-other differences
# =============================================================================

def test_empty_chat_clears_the_bubble_only_for_other_players():
    """An empty CURCHAT from another player means "clear the bubble"; in our own
    props packet there is nothing to act on."""
    body = gchar(12) + gchar(0)
    assert parse_other_player(gchar(0) + gchar(7) + body)['chat'] == ''
    assert 'chat' not in parse_player_props(body)


def test_account_name_precedence_differs_by_context():
    """First wins for our own props (the account we authenticated as), last wins
    for another player (the server re-sends it on rename)."""
    twice = gchar(34) + gstring("first") + gchar(34) + gstring("second")
    # Repeating a prop id breaks the ascending-order invariant, so the parse
    # stops at the second one either way - assert on a single-prop packet plus
    # the seeded-dict behaviour instead.
    assert parse_player_props(gchar(34) + gstring("first"))['account'] == "first"
    assert parse_other_player(
        gchar(0) + gchar(7) + gchar(34) + gstring("bob"))['account'] == "bob"
    assert parse_player_props(twice)['account'] == "first"


def test_other_player_keeps_the_packet_header_id():
    """PLPROP_ID inside the body must not override the leading gshort."""
    data = gchar(0) + gchar(7) + gchar(14) + gchar(0) + gchar(9)
    assert parse_other_player(data)['id'] == 7


def test_self_props_surface_inventory_and_id():
    data = (gchar(1) + gchar(6) + gchar(2) + gchar(9)
            + gchar(3) + gint3(4096)
            + gchar(5) + gchar(3)
            + gchar(14) + gchar(0) + gchar(9)
            + gchar(19) + gchar(2)
            + gchar(24) + gint3(1234))
    props = parse_player_props(data)
    assert props['max_hearts'] == 6.0        # whole hearts, not halves
    assert props['hearts'] == 4.5
    assert props['rupees'] == 4096
    assert props['bombs'] == 3
    assert props['id'] == 9
    assert props['carry_sprite'] == 2
    assert props['carry_npc'] == 1234


def test_other_player_props_use_their_own_key_names():
    data = (gchar(0) + gchar(7)
            + gchar(0) + gstring("Bob")
            + gchar(10) + gstring("walk")
            + gchar(75) + gstring("linux"))
    props = parse_other_player(data)
    assert props['nickname'] == "Bob"
    assert props['ani'] == "walk"           # 'animation' in the self parser
    assert props['os_type'] == "linux"      # not surfaced by the self parser


def test_joinleave_is_only_surfaced_for_other_players():
    data = gchar(0) + gchar(7) + gchar(50) + gchar(0)
    assert parse_other_player(data)['joinleave'] == 0
    assert 'joinleave' not in parse_player_props(gchar(50) + gchar(0))


def test_joinleave_header_before_an_ascending_blob_still_parses():
    data = (gchar(0) + gchar(7) + gchar(50) + gchar(1)
            + gchar(0) + gstring("Bob") + gchar(20) + gstring("start.nw"))
    props = parse_other_player(data)
    assert (props['joinleave'], props['nickname'], props['level']) == (
        1, "Bob", "start.nw")


# =============================================================================
# Shared wire facts
# =============================================================================

def test_sword_power_image_only_when_one_is_on_the_wire():
    bare = gchar(8) + gchar(3)
    custom = gchar(8) + gchar(33) + gstring("blade.png")
    for parse, prefix in ((parse_player_props, ''),
                          (lambda d: parse_other_player(gchar(0) + gchar(7) + d), '')):
        assert parse(bare)['sword_power'] == 3
        assert 'sword_image' not in parse(bare)
        assert parse(custom)['sword_power'] == 3
        assert parse(custom)['sword_image'] == "blade.png"


def test_mid_range_bare_power_does_not_swallow_the_next_prop():
    data = gchar(8) + gchar(7) + gchar(20) + gstring("start.nw")
    props = parse_player_props(data)
    assert props['sword_power'] == 7
    assert props['level'] == "start.nw"


def test_colors_width_retry_still_self_corrects():
    """A classic five-byte COLORS payload parsed by a v6-preferring caller."""
    data = (gchar(13) + b"".join(gchar(i) for i in range(5))
            + gchar(15) + gchar(20) + gchar(16) + gchar(22))
    props = parse_player_props(data, colors_len=8)
    assert props['colors'] == [0, 1, 2, 3, 4]
    assert (props['x'], props['y']) == (10.0, 11.0)


def test_effect_colors_stop_if_first_zero_keeps_alignment():
    """EFFECTCOLORS is 1 byte when the first value is 0, otherwise 5."""
    short = gchar(23) + gchar(0) + gchar(34) + gstring("bob")
    long = (gchar(23) + b"".join(gchar(i) for i in (1, 2, 3, 4, 5))
            + gchar(34) + gstring("bob"))
    assert parse_player_props(short)['account'] == "bob"
    assert parse_player_props(long)['account'] == "bob"


def test_high_precision_position_overrides_half_tiles():
    data = gchar(15) + gchar(60) + gchar(78) + gchar(3) + gchar(96)
    # X2 encodes pixels << 1: (3 << 7 | 96) >> 1 = 240 pixels = 15.0 tiles.
    assert parse_player_props(data)['x'] == 15.0


# =============================================================================
# NPC props (a different prop enum over the same walker)
# =============================================================================

def test_npc_gattrib_range_does_not_swallow_gmap_attribution():
    """GMAPLEVELX/GMAPLEVELY/Z (41-43) sit between GATTRIB5 and GATTRIB6."""
    data = (gint3(5)
            + gchar(40) + gstring("attr5")
            + gchar(41) + gchar(2)
            + gchar(42) + gchar(3)
            + gchar(43) + gchar(50)
            + gchar(75) + gchar(3) + gchar(96)
            + gchar(76) + gchar(3) + gchar(96))
    props = parse_npc_props(data)
    assert props['id'] == 5
    assert (props['gmaplevelx'], props['gmaplevely']) == (2, 3)
    assert (props['x'], props['y']) == (15.0, 15.0)


def test_npc_sword_and_shield_images_do_not_desync_the_stream():
    """NPCProp SWORDIMAGE/SHIELDIMAGE are PropertySwordPower, not plain
    strings: a bare power carries no image."""
    data = (gint3(5)
            + gchar(10) + gchar(2)
            + gchar(11) + gchar(1)
            + gchar(20) + gstring("Guard"))
    assert parse_npc_props(data)['nickname'] == "Guard"

    with_images = (gint3(5)
                   + gchar(10) + gchar(31) + gstring("blade.png")
                   + gchar(20) + gstring("Guard"))
    assert parse_npc_props(with_images)['nickname'] == "Guard"


def test_npc_name_property_is_retained_for_getnpc():
    data = gint3(5) + gchar(50) + gstring("Lamp")
    assert parse_npc_props(data)["name"] == "Lamp"


def test_npc_script_is_a_gshort_length_string():
    script = "if (playerenters) { }"
    data = (gint3(5)
            + gchar(1) + gchar(len(script) >> 7) + gchar(len(script) & 0x7F)
            + script.encode('latin-1')
            + gchar(20) + gstring("Guard"))
    props = parse_npc_props(data)
    assert props['script'] == script
    assert props['nickname'] == "Guard"


def test_npc_imagepart_and_headimage_preset():
    data = (gint3(5)
            + gchar(22) + gchar(7)
            + gchar(34) + gchar(1) + gchar(0) + gchar(2) + gchar(0)
            + gchar(32) + gchar(48))
    props = parse_npc_props(data)
    assert props['headimage'] == 7          # preset id, unlike the player parser
    assert props['imagepart'] == (128, 256, 32, 48)


def test_npc_empty_string_is_surfaced_as_empty():
    """Clearing an NPC's message is a real update, so '' reaches the caller."""
    data = gint3(5) + gchar(15) + gchar(0)
    assert parse_npc_props(data)['message'] == ''


# =============================================================================
# Baddy props
# =============================================================================

def test_baddy_props_round_trip():
    data = (gchar(3)                                   # baddy id
            + gchar(1) + gchar(61)
            + gchar(2) + gchar(20)
            + gchar(3) + gchar(2)
            + gchar(4) + gchar(3) + gstring("baddy.png")
            + gchar(5) + gchar(1)
            + gchar(6) + gchar(4)
            + gchar(7) + gchar(0b1001)
            + gchar(8) + gstring("Halt!"))
    props = parse_baddy_props(data)
    assert props['id'] == 3
    assert (props['x'], props['y']) == (30.5, 10.0)
    assert props['type'] == 2
    assert (props['power'], props['image']) == (3, "baddy.png")
    assert props['mode'] == 1
    assert props['animation'] == 4
    assert props['direction'] == 1          # headDir << 2 | direction
    assert props['verse_sight'] == "Halt!"


def test_baddy_empty_verse_is_not_surfaced():
    data = gchar(3) + gchar(9) + gchar(0) + gchar(5) + gchar(2)
    props = parse_baddy_props(data)
    assert 'verse_hurt' not in props
    assert props['mode'] == 2
