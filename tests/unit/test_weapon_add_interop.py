"""Weapon-add compatibility across the Python server and client."""

import sys
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[3] / "pygserver"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from pygserver.protocol.packets import build_npc_weapon_add  # noqa: E402
from pyreborn.client import Client  # noqa: E402
from pyreborn.packets import PacketID, parse_weapon_add  # noqa: E402


def _payload(name, image, script):
    packet = build_npc_weapon_add(name, image, script)
    return packet[1:-1]


def test_server_builder_round_trips_named_weapon_with_script():
    assert parse_weapon_add(_payload("Staff", "", "if (playerenters) {}")) == {
        "name": "Staff",
        "image": "",
        "script": "if (playerenters) {}",
    }


def test_server_builder_round_trips_scriptless_weapon():
    assert parse_weapon_add(_payload("Beer", "", "")) == {
        "name": "Beer",
        "image": "",
        "script": "",
    }


def test_server_builder_round_trips_image_bearing_weapon():
    assert parse_weapon_add(_payload("Bow", "bow.png", "")) == {
        "name": "Bow",
        "image": "bow.png",
        "script": "",
    }


def test_observed_unlabeled_scriptless_payload_is_accepted():
    assert parse_weapon_add(b"$Beer   ") == {
        "name": "Beer",
        "image": "",
        "script": "",
    }


def test_modern_class_header_weapon_is_accepted():
    assert parse_weapon_add(b"%Blade  j $base") == {
        "name": "Blade",
        "image": "",
        "script": "",
        "classes": "base",
    }


def test_observed_payload_reaches_client_weapon_inventory():
    client = Client()
    client._handle_packet(PacketID.PLO_NPCWEAPONADD, b"$Beer   ")
    assert client.weapons["Beer"] == {"name": "Beer", "image": "", "script": ""}
