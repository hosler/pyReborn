"""
Tests for new GServer-V2 features
"""

import pytest
from pyreborn.protocol.enums import PlayerProp, PlayerToServer, ServerToPlayer, PlayerListCategory
from pyreborn.protocol.packets import (
    RequestUpdateBoardPacket, RequestTextPacket, SendTextPacket,
    PlayerPropsPacket
)
from pyreborn.models.player import Player
from pyreborn.handlers.packet_handler import PacketReader, PacketHandler
from pyreborn.events import EventType


class TestNewPacketTypes:
    """Test new packet implementations"""
    
    def test_request_update_board_packet(self):
        """Test REQUESTUPDATEBOARD packet creation"""
        packet = RequestUpdateBoardPacket(
            level="level1.nw",
            mod_time=12345,
            x=10,
            y=20,
            width=32,
            height=32
        )
        
        data = packet.to_bytes()
        assert len(data) > 0
        assert data[0] == PlayerToServer.PLI_REQUESTUPDATEBOARD + 32
        
    def test_request_text_packet(self):
        """Test REQUESTTEXT packet creation"""
        packet = RequestTextPacket("serveroption.startlevel")
        data = packet.to_bytes()
        
        assert len(data) > 0
        assert data[0] == PlayerToServer.PLI_REQUESTTEXT + 32
        assert b"serveroption.startlevel" in data
        
    def test_send_text_packet(self):
        """Test SENDTEXT packet creation"""
        packet = SendTextPacket("playersetting.group", "admins")
        data = packet.to_bytes()
        
        assert len(data) > 0
        assert data[0] == PlayerToServer.PLI_SENDTEXT + 32
        assert b"playersetting.group" in data
        assert b"admins" in data


class TestHighPrecisionCoordinates:
    """Test high-precision coordinate support"""
    
    def test_player_high_precision_props(self):
        """Test setting high-precision coordinates on player"""
        player = Player()
        
        # Test X2 property
        player.set_property(PlayerProp.PLPROP_X2, 512)  # 512 pixels = 32 tiles
        assert player.x == 32.0
        
        # Test Y2 property
        player.set_property(PlayerProp.PLPROP_Y2, 256)  # 256 pixels = 16 tiles
        assert player.y == 16.0
        
        # Test Z2 property
        player.set_property(PlayerProp.PLPROP_Z2, 50)
        assert player.z == 50
        
    def test_high_precision_movement_packet(self):
        """Test high-precision movement packet"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_X2, 800)  # 50 tiles
        packet.add_property(PlayerProp.PLPROP_Y2, 480)  # 30 tiles
        packet.add_property(PlayerProp.PLPROP_Z2, 25)
        
        data = packet.to_bytes()
        assert len(data) > 0
        
        # Verify packet contains X2, Y2, Z2 props
        assert PlayerProp.PLPROP_X2 + 32 in data
        assert PlayerProp.PLPROP_Y2 + 32 in data
        assert PlayerProp.PLPROP_Z2 + 32 in data


class TestGhostModePackets:
    """Test ghost mode packet handling"""
    
    def test_ghost_text_handler(self):
        """Test ghost text packet parsing"""
        handler = PacketHandler()
        
        # Create ghost text packet data
        text = "Debug Mode Active"
        data = text.encode('ascii') + b'\n'
        reader = PacketReader(data)
        
        result = handler._handle_ghost_text(reader)
        assert result["type"] == "ghost_text"
        assert result["text"] == text
        
    def test_ghost_icon_handler(self):
        """Test ghost icon packet parsing"""
        handler = PacketHandler()
        
        # Ghost icon enabled
        data = bytes([1 + 32])
        reader = PacketReader(data)
        result = handler._handle_ghost_icon(reader)
        assert result["type"] == "ghost_icon"
        assert result["enabled"] is True
        
        # Ghost icon disabled
        data = bytes([0 + 32])
        reader = PacketReader(data)
        result = handler._handle_ghost_icon(reader)
        assert result["enabled"] is False


class TestTriggerActionHandler:
    """Test triggeraction packet handling"""
    
    def test_triggeraction_parsing(self):
        """Test parsing triggeraction packets"""
        handler = PacketHandler()
        
        # Test gr.setgroup action
        data = b"gr.setgroup,admins\n"
        reader = PacketReader(data)
        result = handler._handle_trigger_action(reader)
        
        assert result["type"] == "trigger_action"
        assert result["action"] == "gr.setgroup"
        assert result["params"] == ["admins"]
        
    def test_triggeraction_with_multiple_params(self):
        """Test triggeraction with multiple parameters"""
        handler = PacketHandler()
        
        data = b"gr.npc.setpos,100,200,level1.nw\n"
        reader = PacketReader(data)
        result = handler._handle_trigger_action(reader)
        
        assert result["action"] == "gr.npc.setpos"
        assert result["params"] == ["100", "200", "level1.nw"]


class TestPlayerProperties:
    """Test new player properties"""
    
    def test_community_name_property(self):
        """Test community name property"""
        player = Player()
        player.set_property(PlayerProp.PLPROP_COMMUNITYNAME, "CoolPlayer123")
        assert player.community_name == "CoolPlayer123"
        
    def test_playerlist_category_property(self):
        """Test player list category property"""
        player = Player()
        player.set_property(PlayerProp.PLPROP_PLAYERLISTCATEGORY, PlayerListCategory.CHANNEL)
        assert player.playerlist_category == PlayerListCategory.CHANNEL
        
    def test_group_property(self):
        """Test group property (custom)"""
        player = Player()
        player.group = "moderators"
        assert player.group == "moderators"


class TestMinimapHandler:
    """Test minimap packet handling"""
    
    def test_minimap_parsing(self):
        """Test minimap packet parsing"""
        handler = PacketHandler()
        
        data = b"minimap.txt,minimap.png,10,20\n"
        reader = PacketReader(data)
        result = handler._handle_minimap(reader)
        
        assert result["type"] == "minimap"
        assert result["text_file"] == "minimap.txt"
        assert result["image_file"] == "minimap.png"
        assert result["x"] == 10
        assert result["y"] == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])