"""Client._handle_packet dispatch table and the state-component façade.

The 90-branch if/elif chain in Client._handle_packet became a registry of
per-domain handler functions (pyreborn/handlers/), and the 156 flat attributes
its branches mutated moved onto state components (pyreborn/client_state.py).
Both refactors had to be invisible from the outside, so:

- HANDLED_IDS_BEFORE_REGISTRY below is a frozen snapshot of every packet id the
  old chain had a branch for (extracted from `git show HEAD:pyreborn/client.py`
  at the time of the refactor). No id may silently drop out of the table.
- FLAT_ATTRIBUTES_USED_OUTSIDE_CLIENT is the set of moved attributes that the
  game/ layer, game_tester and the rest of the suite touch on a Client. Each
  must still read and write through the façade.
"""

import pytest

import pyreborn.client as client_module
from pyreborn import Client
from pyreborn.handlers import PACKET_HANDLERS, handles
from pyreborn.packets import PacketID

# Every branch of the pre-registry if/elif chain, in chain order. PLO_NPCDEL is
# not in PacketID (packet 29 is only named in client-side code), so it is
# resolved separately below.
HANDLED_IDS_BEFORE_REGISTRY = [
    "PLO_LEVELNAME", "PLO_WARPFAILED", "PLO_PLAYERPROPS", "PLO_TOALL",
    "PLO_SHOWIMG", "PLO_NPCWEAPONADD", "PLO_SHOOT", "PLO_SHOOT2",
    "PLO_HURTPLAYER", "PLO_ITEMADD", "PLO_ITEMDEL", "PLO_PRIVATEMESSAGE",
    "PLO_ADDPLAYER", "PLO_DELPLAYER", "PLO_BADDYPROPS", "PLO_BOARDPACKET",
    "PLO_RAWDATA", "PLO_FILE", "PLO_FILESENDFAILED", "PLO_LARGEFILESTART",
    "PLO_LARGEFILESIZE", "PLO_LARGEFILEEND", "PLO_FILEUPTODATE",
    "PLO_NEWWORLDTIME", "PLO_PLAYERWARP", "PLO_PLAYERWARP2",
    "PLO_LEVELLINK", "PLO_NPCPROPS", "PLO_SHOWIMGNPC", "PLO_NPCDEL",
    "PLO_NPCDEL2", "PLO_OTHERPLPROPS", "PLO_LEVELCHEST", "PLO_DISCMESSAGE",
    "PLO_LISTPROCESSES", "PLO_LEVELSIGN", "PLO_EXPLOSION", "PLO_HITOBJECTS",
    "PLO_MINIMAP", "PLO_BIGMAP", "PLO_BOARDLAYER", "PLO_GHOSTMODE",
    "PLO_BOARDMODIFY", "PLO_BOARDMODIFY2", "PLO_BOARDHEIGHTS",
    "PLO_LEVELBOARD", "PLO_ISLEADER", "PLO_SIGNATURE", "PLO_BADDYHURT",
    "PLO_FLAGSET", "PLO_FLAGDEL", "PLO_BOMBADD", "PLO_BOMBDEL",
    "PLO_ARROWADD", "PLO_HORSEADD", "PLO_HORSEDEL", "PLO_FIRESPY",
    "PLO_THROWCARRIED", "PLO_PUSHAWAY", "PLO_NPCMOVED", "PLO_MOVE2",
    "PLO_MOVE", "PLO_FREEZEPLAYER2", "PLO_UNFREEZEPLAYER", "PLO_SAY2",
    "PLO_HIDENPCS", "PLO_SERVERWARP", "PLO_TRIGGERACTION",
    "PLO_DISABLECLASSICMODE", "PLO_FULLSTOP2", "PLO_PROFILE",
    "PLO_NPCSERVERADDR", "PLO_SETNETCOOKIE", "PLO_NPCBYTECODE",
    "PLO_GANISCRIPT", "PLO_NPCWEAPONSCRIPT", "PLO_LOADGANI",
    "PLO_LOADSCRIPT", "PLO_NPCWEAPONDEL", "PLO_LEVELMODTIME",
    "PLO_STARTMESSAGE", "PLO_DEFAULTWEAPON", "PLO_STAFFGUILDS",
    "PLO_SERVERTEXT", "PLO_SETACTIVELEVEL", "PLO_UNKNOWN168",
    "PLO_GHOSTICON", "PLO_RPGWINDOW", "PLO_STATUSLIST", "PLO_UNKNOWN190",
    "PLO_CLEARWEAPONS", "PLO_HASNPCSERVER",
]

# A packet id nothing has ever handled: PLO_NPCACTION and PLO_GHOSTTEXT are
# already asserted unhandled by test_npc_move_del2_login.py, so use one of
# them rather than inventing a number that could later gain a handler.
UNHANDLED_PACKET_ID = int(PacketID.PLO_NPCACTION)

# Moved attributes that code outside client.py reads or writes on a Client.
FLAT_ATTRIBUTES_USED_OUTSIDE_CLIENT = [
    # level / board
    "tiles", "_tiles_level_name", "levels", "_current_level_name",
    "_pending_level_name", "active_level", "links", "chests", "chest_items",
    "signs", "board_layers", "is_leader",
    # gmap
    "gmap_grid", "gmap_width", "gmap_height", "gmap_name", "bigmap_info",
    "_gmap_offset_x", "_gmap_offset_y",
    # warp / transition
    "_awaiting_warp_confirm", "_warp_fallback", "_local_level_transition",
    "_local_level_transition_epoch", "_local_level_transition_direction",
    "_plain_level_change_epoch", "_local_level_transition_started",
    "_known_gmap_segments",
    # entities
    "npcs", "_npc_cache", "npc_moves", "players", "player_list", "items",
    "baddies", "weapons", "bombs", "arrows", "horses", "active_explosions",
    # combat
    "_arrow_sims", "_pending_arrow_hits", "auto_respond_hurt",
    # files
    "_pending_files", "_received_files", "_failed_files",
    "_large_file_transfers",
    # scripts
    "gs1_host", "gs2_host", "gs2_bytecode", "gs2_script_headers",
    "gani_setbackto",
    # session
    "_authenticated", "ghost_mode", "ghost_icon", "frozen", "input_frozen",
    "login_complete", "server_warp_info", "global_flags", "status_list",
    "has_npc_server", "disconnect_reason",
    # instrumentation
    "packet_stats", "_handled_plo_ids", "prop_parse_diagnostics",
    # callbacks
    "on_packet", "on_chat", "on_hurt", "on_item", "on_pm", "on_weapon_add",
    "on_projectile", "on_file", "on_board_modify", "on_bomb_add",
    "on_bomb_del", "on_arrow_add", "on_npc_del", "on_sword_hit_npc",
    "on_freeze", "on_fullstop", "on_say2", "on_triggeraction",
    "on_login_complete", "on_disconnect", "on_gs2_bytecode",
    "on_server_text", "on_rpg_window", "on_flag", "on_flag_del",
]


# Packet ids the registry gained AFTER the refactor. The frozen list above is a
# record of what the old if/elif chain handled, so it must never shrink - but it
# is not a ceiling, and a genuinely new handler is not a regression. Adding an
# id here is a deliberate act; forgetting to is what the assertion below catches.
HANDLED_IDS_ADDED_SINCE_REGISTRY = [
    # PLO_UPDATEPACKAGEISUPDATED (187). GServer-v2 (server/src/Server.cpp)
    # pushes this to every client that has seen a file when that file changes
    # on disk. Handled now so the on-disk asset cache drops its stale copy and
    # re-fetches; before, mid-session content updates were never picked up.
    187,
]


def _expected_ids():
    ids = set()
    for name in HANDLED_IDS_BEFORE_REGISTRY:
        if name == "PLO_NPCDEL":
            from pyreborn.handlers.entities import PLO_NPCDEL
            ids.add(int(PLO_NPCDEL))
        else:
            ids.add(int(getattr(PacketID, name)))
    return ids


class _NoopProtocol:
    """Stand-in transport: never sends, reports connected."""

    connected = True

    def send_packet(self, _packet_id, _data=b""):
        return True

    def disconnect(self):
        self.connected = False


def _client():
    client = Client("localhost", 14900)
    client._protocol = _NoopProtocol()
    return client


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

def test_registry_routes_every_previously_handled_packet_id():
    # Directional on purpose: no previously-handled id may silently drop out,
    # and any id present but unaccounted for has to be declared above rather
    # than appearing by accident.
    missing = _expected_ids() - set(PACKET_HANDLERS)
    assert not missing, f"handler(s) dropped out of the registry: {sorted(missing)}"
    undeclared = set(PACKET_HANDLERS) - _expected_ids() - set(HANDLED_IDS_ADDED_SINCE_REGISTRY)
    assert not undeclared, (
        "new handler(s) not declared in HANDLED_IDS_ADDED_SINCE_REGISTRY: "
        f"{sorted(undeclared)}")


def test_handled_plo_ids_is_the_registry():
    assert client_module.HANDLED_PLO_IDS == set(PACKET_HANDLERS)
    # The coverage harness reads the per-instance copy (subclasses extend it).
    assert _client()._handled_plo_ids == set(PACKET_HANDLERS)


@pytest.mark.parametrize("name", HANDLED_IDS_BEFORE_REGISTRY)
def test_each_handled_id_maps_to_a_handler_in_the_handlers_package(name):
    if name == "PLO_NPCDEL":
        from pyreborn.handlers.entities import PLO_NPCDEL as resolved
    else:
        resolved = getattr(PacketID, name)
    handler = PACKET_HANDLERS[int(resolved)]
    assert handler.__module__.startswith("pyreborn.handlers.")


def test_registry_refuses_a_second_handler_for_the_same_id():
    before = dict(PACKET_HANDLERS)
    with pytest.raises(RuntimeError):
        @handles(PacketID.PLO_LEVELNAME)
        def _other_level_name_handler(client, data):  # pragma: no cover
            pass
    assert PACKET_HANDLERS == before


def test_unknown_packet_id_is_a_no_op_but_still_reaches_on_packet():
    client = _client()
    seen = []
    client.on_packet[UNHANDLED_PACKET_ID] = seen.append

    client._handle_packet(UNHANDLED_PACKET_ID, b"payload")

    assert seen == [b"payload"]
    assert UNHANDLED_PACKET_ID not in client._handled_plo_ids


def test_unknown_packet_id_without_a_custom_handler_does_nothing():
    client = _client()
    client._handle_packet(UNHANDLED_PACKET_ID, b"payload")
    assert client.packet_stats == {}


def test_handled_packet_also_reaches_on_packet():
    client = _client()
    seen = []
    client.on_packet[int(PacketID.PLO_ISLEADER)] = seen.append

    client._handle_packet(PacketID.PLO_ISLEADER, b"")

    assert client.is_leader is True
    assert seen == [b""]


def test_stop_from_a_handler_suppresses_on_packet():
    """A player leaving our level returned early in the old chain, skipping the
    custom-handler call at the bottom of _handle_packet - now expressed as the
    STOP sentinel."""
    client = _client()
    client.players[7] = {"id": 7}
    left = []
    client.on_player_left = left.append
    seen = []
    client.on_packet[int(PacketID.PLO_OTHERPLPROPS)] = seen.append

    # [gshort id][prop 50 = JOINLEAVELVL][value 0], gchar-encoded (+32).
    leave_packet = bytes([32, 7 + 32, 50 + 32, 32])
    client._handle_packet(PacketID.PLO_OTHERPLPROPS, leave_packet)

    assert 7 not in client.players
    assert left == [7]
    assert seen == []


def test_handler_exception_is_counted_not_raised_through_update(monkeypatch):
    client = _client()
    packet_id = int(PacketID.PLO_ISLEADER)

    def _boom(_client, _data):
        raise ValueError("handler blew up")

    monkeypatch.setitem(PACKET_HANDLERS, packet_id, _boom)
    monkeypatch.setattr(client._protocol, "recv_packets",
                        lambda _timeout=0.01: [(packet_id, b"")],
                        raising=False)

    client.update()

    stats = client.packet_stats[packet_id]
    assert stats["received"] == 1
    assert stats["errors"] == 1
    assert stats["handled"] == 0
    assert "ValueError" in stats["last_error"]


def test_update_counts_a_handled_packet(monkeypatch):
    client = _client()
    packet_id = int(PacketID.PLO_ISLEADER)
    monkeypatch.setattr(client._protocol, "recv_packets",
                        lambda _timeout=0.01: [(packet_id, b"")],
                        raising=False)

    client.update()

    assert client.packet_stats[packet_id]["handled"] == 1
    assert client.is_leader is True


# ---------------------------------------------------------------------------
# State-component façade
# ---------------------------------------------------------------------------

def test_every_alias_reads_and_writes_through_to_its_component():
    client = _client()
    sentinel = object()
    for name, (component, field) in client_module._STATE_ALIASES.items():
        holder = getattr(client, component)
        assert getattr(client, name) is getattr(holder, field), name
        setattr(client, name, sentinel)
        assert getattr(holder, field) is sentinel, name


@pytest.mark.parametrize("name", FLAT_ATTRIBUTES_USED_OUTSIDE_CLIENT)
def test_flat_attribute_still_works_on_the_client(name):
    client = _client()
    getattr(client, name)          # readable
    setattr(client, name, None)    # writable
    assert getattr(client, name) is None


def test_aliases_do_not_shadow_client_methods_or_properties():
    # client.py raises at import time if one does; assert the invariant here
    # too so the reason is visible when it trips.
    for name in client_module._STATE_ALIASES:
        attribute = getattr(Client, name)
        assert isinstance(attribute, property), name


def test_components_are_independent_between_clients():
    first, second = _client(), _client()
    first.npcs[1] = {"id": 1}
    first.tiles = [7] * 4096
    assert second.npcs == {}
    assert second.tiles == []
