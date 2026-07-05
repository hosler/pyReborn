"""Unit tests for pyreborn gani module (animation parsing)."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn.gani import GaniParser, Gani, GaniFrame, GaniSprite


class TestGaniParser:
    """Tests for GANI file parsing."""

    def test_parser_creation(self):
        """Test creating a GaniParser."""
        parser = GaniParser()
        assert parser is not None

    def test_gani_class_exists(self):
        """Test Gani class exists and can be instantiated."""
        # Just verify the class exists
        assert Gani is not None


class TestGaniFrame:
    """Tests for GaniFrame dataclass."""

    def test_frame_creation(self):
        """Test GaniFrame creation."""
        frame = GaniFrame(sprites=[])
        assert frame is not None

    def test_frame_has_sound_field(self):
        """Test GaniFrame has sound field."""
        frame = GaniFrame(sprites=[])
        assert hasattr(frame, 'sound')


class TestGaniSprite:
    """Tests for GaniSprite dataclass."""

    def test_sprite_creation(self):
        """Test GaniSprite creation."""
        sprite = GaniSprite(id=0, layer=0, x=0, y=0, width=32, height=32)
        assert sprite is not None

    def test_sprite_has_description(self):
        """Test GaniSprite has description field."""
        sprite = GaniSprite(id=0, layer=0, x=0, y=0, width=32, height=32)
        assert hasattr(sprite, 'description')


class TestDirectionConversion:
    """Tests for direction helper functions."""

    def test_direction_from_delta(self):
        """Test converting movement delta to direction."""
        from pyreborn.gani import direction_from_delta

        # Right
        assert direction_from_delta(1, 0) == 3
        # Left
        assert direction_from_delta(-1, 0) == 1
        # Down
        assert direction_from_delta(0, 1) == 2
        # Up
        assert direction_from_delta(0, -1) == 0

    def test_direction_name(self):
        """Test getting direction name."""
        from pyreborn.gani import direction_name

        assert direction_name(0) == "up"
        assert direction_name(1) == "left"
        assert direction_name(2) == "down"
        assert direction_name(3) == "right"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
