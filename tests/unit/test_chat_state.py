"""ChatState.append: the history cap and the monotonic sequence counter."""
from pyreborn.game.chat_state import ChatState
from pyreborn.game.constants import CHAT_HISTORY_CAP


def test_append_trims_to_cap_keeping_newest():
    chat = ChatState()
    for i in range(CHAT_HISTORY_CAP + 3):
        chat.append(f"m{i}")
    assert len(chat.messages) == CHAT_HISTORY_CAP
    assert chat.messages[0] == "m3"
    assert chat.messages[-1] == f"m{CHAT_HISTORY_CAP + 2}"


def test_append_at_exact_cap_drops_nothing():
    chat = ChatState()
    for i in range(CHAT_HISTORY_CAP):
        chat.append(f"m{i}")
    assert len(chat.messages) == CHAT_HISTORY_CAP
    assert chat.messages[0] == "m0"


def test_seq_advances_once_per_append_past_the_cap():
    chat = ChatState()
    for i in range(CHAT_HISTORY_CAP + 7):
        chat.append(f"m{i}")
    assert chat.seq == CHAT_HISTORY_CAP + 7
