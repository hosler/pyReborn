import pytest

from game_tester.game_bot import chat_nonce


@pytest.mark.parametrize("prefix", ["gmapchat_", "Test_", "ChatTest_"])
def test_chat_nonce_avoids_its_decimal_length(prefix):
    messages = [chat_nonce(prefix) for _ in range(1000)]
    assert len(set(messages)) == len(messages)
    for message in messages:
        assert message.startswith(prefix)
        assert message[len(prefix):].isalpha()
        assert str(len(message)) not in message


def test_chat_nonce_rejects_a_prefix_containing_its_length():
    with pytest.raises(ValueError, match="prefix contains the message length"):
        chat_nonce("15_")


def test_chat_nonce_allows_other_digits_in_the_prefix():
    message = chat_nonce("room2_")
    assert message.startswith("room2_")
    assert str(len(message)) not in message
