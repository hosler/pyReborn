"""Cross-host conformance checks for the shared A-class GS1 surface."""

import asyncio
import os
import sys
from collections import deque
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../pygserver"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../reborn-protocol"))

import pytest

from pyreborn.gs1_client import ClientGS1
from pygserver import npc_motion
from pygserver.config import ServerConfig
from pygserver.gs1.host import GS1Host
from pygserver.level import Level
from pygserver.server import GameServer
from reborn_protocol.gs1 import Context, VarStore, run
from reborn_protocol.gs1.host_shared import (
    A_CLASS_NPC_ATTR,
    A_CLASS_PLAYER_ATTR,
)


_PLAYER_VALUES = {
    "direction": 3,
    "sprite": 4,
    "rupees": 125,
    "hearts": 4.5,
    "max_hearts": 8,
    "arrows": 12,
    "bombs": 7,
    "sword_power": 3,
    "shield_power": 2,
    "nickname": "Tester",
    "head_image": "head.png",
    "body_image": "body.png",
    "sword_image": "sword.png",
    "shield_image": "shield.png",
}

_NPC_VALUES = {
    "x": 10.5,
    "y": 20.25,
    "direction": 2,
    "image": "npc.png",
    "gani": "idle",
    "nickname": "Guide",
    "message": "Hello",
    "glove_power": 1,
}


class _ServerNpc(SimpleNamespace):
    """Server NPC stand-in with the move-queue state pygserver's NPC carries.

    It sits on a real plain level, so the server's position rules (the clamp in
    NPCManager.confine_position) apply to it when a test runs them."""

    def __init__(self, **values):
        super().__init__(**values)
        self.level = Level("conformance.nw")
        self.move_queue = deque()
        self._move_events = 0
        self._position_check = False

    def mark_dirty(self):
        self.dirty = True


def _run_pair(source):
    client_player = SimpleNamespace(**_PLAYER_VALUES, account="account")
    client_npc = dict(_NPC_VALUES)
    client_runtime = ClientGS1(SimpleNamespace(player=client_player))
    client_vars = VarStore()
    client_context = Context(
        client_runtime._host, client_vars, this_obj=client_npc,
        player=client_player,
    )

    server_player = SimpleNamespace(
        **_PLAYER_VALUES, account_name="account", weapons_disabled=False,
    )
    server_npc = _ServerNpc(**_NPC_VALUES)
    server_vars = VarStore()
    server_context = Context(
        GS1Host(), server_vars, this_obj=server_npc, player=server_player,
    )

    run(source, ctx=client_context)
    run(source, ctx=server_context)
    return (
        client_context, client_npc, client_player,
        server_context, server_npc, server_player,
    )


@pytest.mark.parametrize(
    "name",
    [
        *A_CLASS_PLAYER_ATTR,
        "playeraccount",
        *(name for name in A_CLASS_NPC_ATTR if name != "message"),
    ],
)
def test_accessors_match_through_the_real_interpreter(name):
    client_context, _, _, server_context, _, _ = _run_pair(
        f"this.result = {name};"
    )
    client_value = client_context.vars.scopes["this"]["result"]
    server_value = server_context.vars.scopes["this"]["result"]
    assert client_value == server_value
    assert type(client_value) is type(server_value)


def test_tokenscount_matches_through_the_real_interpreter():
    client_context, _, _, server_context, _, _ = _run_pair(
        "tokenize alpha beta gamma; this.result = tokenscount;"
    )
    client_value = client_context.vars.scopes["this"]["result"]
    server_value = server_context.vars.scopes["this"]["result"]
    assert client_value == server_value == 3.0
    assert type(client_value) is type(server_value) is float


@pytest.mark.parametrize(
    ("script", "fields"),
    [
        ("move 1.5,-2; hide; show;", ("x", "y", "visible")),
        ("setani walk; setcharani idle;", ("gani",)),
        ("setimgpart sheet.png,1,2,3,4;", ("image", "imagepart")),
        ("message hello;", ("message",)),
    ],
)
def test_npc_command_contracts_match_through_the_real_interpreter(script, fields):
    _, client_npc, _, _, server_npc, _ = _run_pair(script)
    # The server queues `move` (50 ms slices, announced with PLO_MOVE2) where
    # the client applies it at once, so compare the end state once the server's
    # queue has run dry.
    npc_motion.process_queue(server_npc, None, 10_000)
    assert not server_npc.move_queue
    for field in fields:
        assert client_npc.get(field) == getattr(server_npc, field, None)
        assert type(client_npc.get(field)) is type(getattr(server_npc, field, None))


def test_known_divergence_move_past_the_level_edge_server_clamps_client_does_not(tmp_path):
    """KNOWN DIVERGENCE (server vs client `move`), pinned on purpose.

    Server: the move is queued (nothing happens until the queue runs), and the
    position the queue leaves behind is then clamped to local pixels 0..976 on a
    plain level (GServer-v2 NPC.cpp:2038-2091 testForLinks, cc20c9d0), so
    `move 1.5,-2` from y=1 ends at y=0.
    Client: applies the move at once and has no level clamp, so it keeps y=-1.

    Both halves assert exact values: this goes red when either side changes,
    and the pair should then be reconciled (or the divergence re-documented)."""
    start = {"x": 1.0, "y": 1.0}
    source = "move 1.5,-2;"

    client_player = SimpleNamespace(**_PLAYER_VALUES, account="account")
    client_npc = {**_NPC_VALUES, **start}
    client_runtime = ClientGS1(SimpleNamespace(player=client_player))
    run(source, ctx=Context(client_runtime._host, VarStore(), this_obj=client_npc,
                            player=client_player))
    assert (client_npc["x"], client_npc["y"]) == (2.5, -1.0)      # instant, no clamp

    server_player = SimpleNamespace(**_PLAYER_VALUES, account_name="account",
                                    weapons_disabled=False)
    server_npc = _ServerNpc(**{**_NPC_VALUES, **start})
    run(source, ctx=Context(GS1Host(), VarStore(), this_obj=server_npc,
                            player=server_player))
    assert (server_npc.x, server_npc.y) == (1.0, 1.0)              # queued, not applied
    npc_motion.process_queue(server_npc, None, 10_000)
    assert (server_npc.x, server_npc.y) == (2.5, -1.0)             # the queue's result
    server = GameServer(ServerConfig(base_dir=str(tmp_path)))
    asyncio.run(server.npc_manager.confine_position(server_npc))
    assert (server_npc.x, server_npc.y) == (2.5, 0.0)              # the clamp


def test_say_is_a_sign_index_not_a_message_alias():
    """`say <n>` displays LEVEL SIGN n, it does not set the chat bubble -
    GServer-v2's own handler throws "invalid arguments: say signindex"
    (GS1Commands.cpp:2008-2016). The client now follows that contract
    (gs1_client._cmd_say -> sign_text_by_index). Pygserver's GS1 host still
    aliases say to message, so this is deliberately NOT in the cross-host
    parametrize above until pygserver catches up."""
    _, client_npc, _, _, _, _ = _run_pair("say 0;")
    # no sign store in this harness: nothing shown, bubble untouched
    assert client_npc.get("message") == _NPC_VALUES["message"]


def test_player_toggle_contract_matches_through_the_real_interpreter():
    _, _, _, _, _, server_player = _run_pair(
        "disableweapons; enableweapons;"
    )
    client_runtime = ClientGS1(SimpleNamespace(player=SimpleNamespace()))
    run(
        "disableweapons; enableweapons;",
        ctx=Context(client_runtime._host, player=client_runtime._host._player),
    )
    assert client_runtime.weapons_enabled is True
    assert server_player.weapons_disabled is False


def test_setlevel2_contract_matches_through_the_real_interpreter():
    client_warps = []
    client_runtime = ClientGS1(SimpleNamespace(player=SimpleNamespace()))
    client_runtime.on_warp = lambda *args: client_warps.append(args)
    run(
        "setlevel2 next.nw,12.5,8;",
        ctx=Context(client_runtime._host, this_obj={}, player=SimpleNamespace()),
    )

    class _WarpPlayer:
        def __init__(self):
            self.warps = []

        def warp(self, *args):
            self.warps.append(args)

            async def completed():
                return None

            return completed()

    server_player = _WarpPlayer()
    run(
        "setlevel2 next.nw,12.5,8;",
        ctx=Context(GS1Host(), this_obj=_ServerNpc(), player=server_player),
    )
    assert client_warps == server_player.warps == [("next.nw", 12.5, 8.0)]
