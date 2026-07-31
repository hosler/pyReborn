"""Unit tests for pyreborn protocol module."""

import pytest
import sys
import os

# Add paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../reborn-protocol'))

from reborn_protocol import RebornEncryption, PacketBuilder, PacketReader


class TestRebornEncryption:
    """These tests cover ENCRYPT_GEN_5 encryption."""

    def test_create_encryption(self):
        """The test creates an encryption object."""
        enc = RebornEncryption(12345)  # Key should be int
        assert enc is not None

    def test_encrypt_decrypt_roundtrip(self):
        """The test checks that decryption returns the data before encryption."""
        enc = RebornEncryption(12345)
        original = b"Hello, World!"
        encrypted = enc.encrypt(original)
        # Reset position for decrypt
        enc2 = RebornEncryption(12345)
        decrypted = enc2.decrypt(encrypted)
        assert decrypted == original

    def test_different_keys_different_output(self):
        """The test checks that different keys produce different ciphertext."""
        enc1 = RebornEncryption(11111)
        enc2 = RebornEncryption(22222)
        data = b"same data"
        encrypted1 = enc1.encrypt(data)
        encrypted2 = enc2.encrypt(data)
        assert encrypted1 != encrypted2


class TestPacketBuilder:
    """These tests cover PacketBuilder."""

    def test_write_byte(self):
        """The test writes one byte."""
        builder = PacketBuilder()
        builder.write_byte(65)
        assert builder.build() == b'A'

    def test_write_gchar(self):
        """The test writes a gchar (value + 32)."""
        builder = PacketBuilder()
        builder.write_gchar(0)
        assert builder.build() == b' '  # 0 + 32 = 32 = space

        builder = PacketBuilder()
        builder.write_gchar(33)
        assert builder.build() == b'A'  # 33 + 32 = 65 = 'A'

    def test_chain_writes(self):
        """The test chains multiple writes."""
        builder = PacketBuilder()
        result = (builder
                  .write_gchar(1)
                  .write_gchar(2)
                  .write_gchar(3)
                  .build())
        assert result == bytes([33, 34, 35])  # 1+32, 2+32, 3+32


class TestPacketReader:
    """These tests cover PacketReader."""

    def test_read_byte(self):
        """The test reads one byte."""
        reader = PacketReader(b'\x41\x42\x43')
        assert reader.read_byte() == 65
        assert reader.read_byte() == 66
        assert reader.read_byte() == 67

    def test_read_gchar(self):
        """The test reads a gchar (value - 32)."""
        reader = PacketReader(b' ')  # 32 - 32 = 0
        assert reader.read_gchar() == 0

        reader = PacketReader(b'A')  # 65 - 32 = 33
        assert reader.read_gchar() == 33

    def test_remaining(self):
        """The test gets the remaining bytes."""
        reader = PacketReader(b'ABCDE')
        reader.read_byte()
        reader.read_byte()
        assert reader.remaining() == b'CDE'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
