"""End-to-end serverlist chat: two pyReborn clients + the REAL Login
-Serverlist_Chat weapon bytecode against the throwaway pygserver (whose
in-process IRC leg implements the combined gserver+lister behavior).

Exercises the full loop the specs describe (gs2-login-irc-spec.md section 5
steps 1-3): irc login -> channel pseudo-player (prop 81 flags), join
confirms, member pseudo-players in the chatters pane, sender-echo +
cross-client privmsg relay, and part.

Marked `integration`: needs the conftest pygserver fixture, plus the
third-party Preagonal bytecode corpus for the official weapon.
"""

import time
from pathlib import Path

import pytest

from game_tester.login import login_session
from pyreborn.gs2_client import ClientGS2

_CORPUS = Path(__file__).resolve().parents[2] / \
    "Preagonal" / "gbf" / "bytecode" / "login"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (_CORPUS / "_Serverlist_Chat.gs2bc").is_file(),
                       reason="Preagonal login bytecode corpus not checked out"),
]


def _attach_chat(client):
    rt2 = ClientGS2(client, None).attach()
    rt2.load_bytecode("weapon", "-Serverlist_Chat",
                      (_CORPUS / "_Serverlist_Chat.gs2bc").read_bytes())
    return rt2


def _pump(pairs, seconds):
    end = time.time() + seconds
    while time.time() < end:
        for client, _rt2 in pairs:
            client.update(timeout=0.03)
        time.sleep(0.01)


def test_two_client_channel_chat(pygserver):
    with login_session(pygserver.host, pygserver.port, "chat_a", "test",
                       version="6.037", settle=False) as a_out:
        assert a_out.ok, a_out.rejection
        a = a_out.client
        with login_session(pygserver.host, pygserver.port, "chat_b", "test",
                           version="6.037", settle=False) as b_out:
            assert b_out.ok, b_out.rejection
            b = b_out.client
            ra, rb = _attach_chat(a), _attach_chat(b)
            pairs = [(a, ra), (b, rb)]
            _pump(pairs, 0.8)

            va = ra.vms["weapon"]["-serverlist_chat"]
            vb = rb.vms["weapon"]["-serverlist_chat"]
            va.call("openChat")
            vb.call("openChat")

            # the user path: /join typed into the chat field's parser
            va.call("parseChat", "/join reborn")
            _pump(pairs, 0.8)
            vb.call("parseChat", "/join reborn")
            _pump(pairs, 0.8)

            # A's channel pane confirms the join
            pane_a = ra.gui._named.get("globalchat_chatlist_#reborn")
            assert pane_a is not None, "A's channel pane never built"
            assert "You join #reborn" in pane_a.text

            # chatters pane: the channel pseudo-player (prop-81 ischannel)
            # plus both member pseudo-players
            ch = rb.gui._named.get("globalchat_channels")
            texts = [str(r.get("text")) for r in ch.list_rows]
            assert any(t.startswith("#reborn") for t in texts), texts
            assert any("chat_a" in t for t in texts), texts
            assert any("chat_b" in t for t in texts), texts

            # the roster surface behind it: channel flagged ischannel via
            # prop 81, members present in allplayers
            channels = [p for p in ra.all_player_objects()
                        if p.get("ischannel") == 1.0]
            assert channels and any(
                str(c.get("account")).lower() == "irc:#reborn"
                for c in channels)

            # privmsg: sender echo on A, relay to B
            va.call("parseChat", "hello over the wire")
            _pump(pairs, 1.2)
            pane_b = rb.gui._named.get("globalchat_chatlist_#reborn")
            assert pane_b is not None, "B's channel pane never built"
            assert "hello over the wire" in pane_b.text, pane_b.text[-400:]
            assert "hello over the wire" in pane_a.text   # sender echo

            # part: B leaves, further messages must not reach it
            vb.call("parseChat", "/part reborn")
            _pump(pairs, 0.8)
            before = pane_b.text
            va.call("parseChat", "after the part")
            _pump(pairs, 1.0)
            assert "after the part" in pane_a.text
            assert pane_b.text == before
