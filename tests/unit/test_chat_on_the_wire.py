"""A chat message goes out whole, whatever else the tick sends.

Both chat paths (`say`: PLI_TOALL; `send_level_chat`: a CURCHAT prop in
PLI_PLAYERPROPS) are exercised for every length 1..223, sent from inside a
tick (between the tick's position sends, i.e. inside `movement_batch`) and
from outside one, in ticks that also hold movement, direction changes, a sword
swing and a door warp. The recorded bytes are decoded and compared to the text.
"""
import pygame
import pytest
from reborn_protocol.props import PLAYER_PROPS, decode_value

import offline_game
from offline_game import key_event
from pyreborn.packets import PacketID

R, L, U, D = pygame.K_RIGHT, pygame.K_LEFT, pygame.K_UP, pygame.K_DOWN
SPACE = pygame.K_SPACE
LINK = "fixture_d.nw 32 28 2 4 10 12"
CURCHAT = 12


def _text(length: int) -> str:
    base = "Test_%d_" % length
    return (base + "abcdefghijklmnopqrstuvwxyz0123456789" * 7)[:length]


def _chat_on_wire(sent):
    """Every chat string the packets carry, in order: ("toall", text) and
    ("curchat", text)."""
    out = []
    for pid, data in sent:
        if pid == PacketID.PLI_TOALL:
            n = data[0] - 32
            assert len(data) == 1 + n, "toall length byte disagrees with the body"
            out.append(("toall", data[1:].decode("latin-1")))
        elif pid == PacketID.PLI_PLAYERPROPS:
            pos = 0
            while pos < len(data):
                prop = data[pos] - 32
                value, pos = decode_value(PLAYER_PROPS[prop], data, pos + 1)
                if prop == CURCHAT:
                    out.append(("curchat", value))
    return out


@pytest.fixture
def held(monkeypatch):
    class _Held(dict):
        def __missing__(self, key):
            return False
    keys = _Held()
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: keys)
    return keys


def _plan():
    """(held keys, events) per tick: walking, turning, a sword swing, then the
    step onto the door link."""
    return [((R,), None), ((U,), None), ((D,), None), ((R, SPACE), [SPACE]),
            ((L,), None)]


@pytest.mark.parametrize("inside_tick", [False, True])
def test_every_chat_length_goes_out_whole(make_game, held, inside_tick):
    game = make_game(player_xy=(30.0, 30.0), gmap=True, tiles=lambda tx, ty: 0,
                     links=[LINK])
    game.frames(1, dt=0.0)
    client = game.client
    loop = client._protocol
    mark = len(loop.sent)
    expected = []
    plan = _plan()
    sent_so_far = 0
    for length in range(1, 224):
        keys, events = plan[(length - 1) % len(plan)]
        held.clear()
        held.update({k: True for k in keys})
        text = _text(length)
        sender = client.say if length % 2 else client.send_level_chat
        kind = "toall" if length % 2 else "curchat"
        expected.append((kind, text))
        if inside_tick:
            original = game.gs2.process_coroutines
            done = []

            def process_coroutines(dt, original=original, sender=sender,
                                   text=text, done=done):
                if not done:
                    done.append(True)
                    sender(text)
                return original(dt)
            game.gs2.process_coroutines = process_coroutines
        else:
            sender(text)
        evs = [key_event(e) for e in (events or ())]
        game.ticks(1, events=evs)
        if inside_tick:
            game.gs2.process_coroutines = original
    got = _chat_on_wire(loop.sent[mark:])
    assert got == expected
    pids = {pid for pid, _ in loop.sent[mark:]}
    assert PacketID.PLI_LEVELWARP in pids, "the walk never reached the door"
