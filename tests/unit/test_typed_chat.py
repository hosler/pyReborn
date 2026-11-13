"""Typed-chat routing and local CURCHAT echo behavior (real offline game)."""

import pygame
import pytest

from offline_game import key_event, spy
from pyreborn.game.render_entities import EntityRenderMixin


@pytest.fixture
def chat_game(make_game, monkeypatch):
    """``chat_game(message, **knobs)``: a game that is typing ``message``,
    with spies on the two chat senders (the real ones still run)."""
    def build(message, **knobs):
        game = make_game(**knobs)
        game.frames(1)
        game.chat.input = message
        game.chat.typing = True
        game.say_calls = spy(monkeypatch, game.client, "say")
        game.level_chat_calls = spy(monkeypatch, game.client,
                                    "send_level_chat")
        return game
    return build


def enter_event():
    return key_event(pygame.K_RETURN, "\r")


def test_enter_routes_normal_typed_chat_to_curchat_once(chat_game, sim_time):
    game = chat_game("hello nearby")

    sim_time(12.5)
    game._handle_chat_input(enter_event())

    assert game.level_chat_calls == [(("hello nearby",), {})]
    assert game.say_calls == []
    assert game.local_chat_text == "hello nearby"
    assert game.local_chat_time == 12.5
    assert game.chat.messages[-1:] == ["[You] hello nearby"]
    assert game.client.player.chat == "hello nearby"


def test_toall_prefix_routes_stripped_message_to_global_chat(chat_game):
    game = chat_game("toall hello everyone")

    game._handle_chat_input(enter_event())

    assert game.say_calls == [(("hello everyone",), {})]
    assert game.level_chat_calls == []
    assert game.local_chat_text == ""
    assert game.chat.messages[-1:] == ["[You] hello everyone"]


def test_local_bubble_replaces_old_chat_and_clears_on_expiry(chat_game,
                                                              sim_time):
    game = chat_game("new chat")
    game.local_chat_text = "old chat"
    game.client.player.chat = "old chat"

    sim_time(20.0)
    game._handle_chat_input(enter_event())

    # The real Client.send_level_chat supplied the optimistic Player.chat echo.
    assert game.client.player.chat == "new chat"
    game.chat_bubble_duration = 4.0
    bubbles = spy_bubbles(game)

    sim_time(23.9)
    EntityRenderMixin._render_player_chat(game, 10, 20)
    assert bubbles == [(10, 20, "new chat")]

    sim_time(24.0)
    EntityRenderMixin._render_player_chat(game, 10, 20)
    assert game.local_chat_text == ""
    assert game.client.player.chat == ""


def spy_bubbles(game):
    seen = []
    game._render_speech_bubble = lambda x, y, text: seen.append((x, y, text))
    return seen


def test_typed_chat_takes_priority_over_open_dialogue(chat_game, monkeypatch):
    game = chat_game("")
    game.dialogue_text = "Still talking"
    advances = spy(monkeypatch, game, "_advance_dialogue")

    game.frames(1, events=[key_event(pygame.K_a, "a")])

    assert game.chat.input == "a"
    assert game.dialogue_text == "Still talking"
    assert advances == []


def test_dead_player_can_send_typed_chat(chat_game):
    game = chat_game("still here", hearts=0)
    game.frames(2)
    assert game.client.player.hearts == 0
    game.chat.input = "still here"
    game.chat.typing = True

    game.frames(1, events=[key_event(pygame.K_RETURN, "\r")])

    assert game.level_chat_calls == [(("still here",), {})]
    assert game.chat.typing is False
