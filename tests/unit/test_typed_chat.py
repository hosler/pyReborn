"""Typed-chat routing and local CURCHAT echo behavior."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pygame

from pyreborn.game.input import InputMixin
from pyreborn.game.render_entities import EntityRenderMixin
from pyreborn.player import Player


class ChatInputHarness(InputMixin):
    def __init__(self, message):
        self.chat_input = message
        self.typing = True
        self.local_chat_text = ""
        self.local_chat_time = 0.0
        self.chat_messages = []
        self.chat_seq = 0
        self.client = SimpleNamespace(
            say=Mock(),
            send_level_chat=Mock(),
            player=Player(),
        )

    def _append_chat(self, message):
        self.chat_messages.append(message)
        self.chat_seq += 1


def enter_event():
    return SimpleNamespace(key=pygame.K_RETURN)


def test_enter_routes_normal_typed_chat_to_curchat_once():
    game = ChatInputHarness("hello nearby")

    with patch("pyreborn.game.input.time.time", return_value=12.5):
        game._handle_chat_input(enter_event())

    game.client.send_level_chat.assert_called_once_with("hello nearby")
    game.client.say.assert_not_called()
    assert game.local_chat_text == "hello nearby"
    assert game.local_chat_time == 12.5
    assert game.chat_messages == ["[You] hello nearby"]
    assert game.chat_seq == 1


def test_toall_prefix_routes_stripped_message_to_global_chat():
    game = ChatInputHarness("toall hello everyone")

    game._handle_chat_input(enter_event())

    game.client.say.assert_called_once_with("hello everyone")
    game.client.send_level_chat.assert_not_called()
    assert game.local_chat_text == ""
    assert game.chat_messages == ["[You] hello everyone"]


def test_local_bubble_replaces_old_chat_and_clears_on_expiry():
    game = ChatInputHarness("new chat")
    game.local_chat_text = "old chat"
    game.client.player.chat = "old chat"

    with patch("pyreborn.game.input.time.time", return_value=20.0):
        game._handle_chat_input(enter_event())

    # Client.send_level_chat supplies its optimistic Player.chat echo in the
    # real client; model that state before exercising the render-time clear.
    game.client.player.chat = "new chat"
    game.chat_bubble_duration = 4.0
    game._render_speech_bubble = Mock()

    with patch("pyreborn.game.render_entities.time.time", return_value=23.9):
        EntityRenderMixin._render_player_chat(game, 10, 20)
    game._render_speech_bubble.assert_called_once_with(10, 20, "new chat")

    with patch("pyreborn.game.render_entities.time.time", return_value=24.0):
        EntityRenderMixin._render_player_chat(game, 10, 20)
    assert game.local_chat_text == ""
    assert game.client.player.chat == ""


def _event_game(message=""):
    game = ChatInputHarness(message)
    game.running = True
    game.key_just_pressed = {}
    game.pm_target_id = None
    game.show_player_list = False
    game.show_server_list = False
    game.big_map_visible = False
    game.dialogue_text = "Still talking"
    game.inventory_ui = SimpleNamespace(visible=False)
    game.settings_ui = SimpleNamespace(visible=False)
    game._ensure_settings_ui = lambda: game.settings_ui
    game._gs2_gui_event = lambda event: False
    game._gs1_keypress_queue = []
    return game


def test_typed_chat_takes_priority_over_open_dialogue(monkeypatch):
    game = _event_game()
    game._advance_dialogue = Mock()
    monkeypatch.setattr(pygame.event, "get", lambda: [
        pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_a, "unicode": "a"}),
    ])

    game._handle_events()

    assert game.chat_input == "a"
    assert game.dialogue_text == "Still talking"
    game._advance_dialogue.assert_not_called()


def test_dead_player_can_send_typed_chat(monkeypatch):
    game = _event_game("still here")
    game.client.player.hearts = 0
    monkeypatch.setattr(pygame.event, "get", lambda: [
        pygame.event.Event(pygame.KEYDOWN,
                           {"key": pygame.K_RETURN, "unicode": "\r"}),
    ])

    game._handle_events()

    game.client.send_level_chat.assert_called_once_with("still here")
    assert game.typing is False
