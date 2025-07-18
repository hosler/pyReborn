"""
Player actions for PyReborn.
Encapsulates all player actions like movement, chat, appearance changes.
"""

from typing import Optional, TYPE_CHECKING
from .protocol.enums import PlayerProp, Direction
from .protocol.packets import (
    PlayerPropsPacket, ToAllPacket, BombAddPacket,
    ArrowAddPacket, FireSpyPacket, PrivateMessagePacket,
    RequestUpdateBoardPacket, RequestTextPacket, SendTextPacket
)

if TYPE_CHECKING:
    from .client import RebornClient

class PlayerActions:
    """Handles all player action methods"""
    
    def __init__(self, client: 'RebornClient'):
        self.client = client
        
    # Movement
    def move_to(self, x: float, y: float, direction: Optional[Direction] = None):
        """Move to position"""
        if direction is None:
            direction = self.client.local_player.direction
            
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_X, x)
        packet.add_property(PlayerProp.PLPROP_Y, y)
        packet.add_property(PlayerProp.PLPROP_SPRITE, direction)
        self.client._send_packet(packet)
        
        # Update local state
        self.client.local_player.x = x
        self.client.local_player.y = y
        self.client.local_player.direction = direction
        
        # Check for level link warps at the new position
        self._check_level_links(x, y)
        
    # Chat
    def set_chat(self, message: str):
        """Set chat bubble"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CURCHAT, message)
        self.client._send_packet(packet)
        self.client.local_player.chat = message
        
    def say(self, message: str):
        """Send chat message to all"""
        packet = ToAllPacket(message)
        self.client._send_packet(packet)
        
    def send_pm(self, player_id: int, message: str):
        """Send private message"""
        packet = PrivateMessagePacket(player_id, message)
        self.client._send_packet(packet)
        
    # Appearance
    def set_nickname(self, nickname: str):
        """Set nickname"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_NICKNAME, nickname)
        self.client._send_packet(packet)
        self.client.local_player.nickname = nickname
        
    def set_head_image(self, image: str):
        """Set head image"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_HEADGIF, image)
        self.client._send_packet(packet)
        self.client.local_player.head_image = image
        
    def set_body_image(self, image: str):
        """Set body image"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_BODYIMG, image)
        self.client._send_packet(packet)
        self.client.local_player.body_image = image
        
    def set_colors(self, colors: list):
        """Set player colors"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_COLORS, colors)
        self.client._send_packet(packet)
        self.client.local_player.colors = colors
        
    def set_gani(self, gani: str):
        """Set animation (gani)"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_GANI, gani)
        self.client._send_packet(packet)
        self.client.local_player.gani = gani
        
    def set_carry_sprite(self, sprite_id: int):
        """Set carry sprite (item being carried)
        
        Args:
            sprite_id: The sprite ID to carry (-1 for none)
        """
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CARRYSPRITE, sprite_id)
        self.client._send_packet(packet)
        self.client.local_player.carry_sprite = sprite_id
        
    # Combat
    def drop_bomb(self, x: Optional[float] = None, y: Optional[float] = None, power: int = 1):
        """Drop a bomb"""
        if x is None:
            x = self.client.local_player.x
        if y is None:
            y = self.client.local_player.y
        packet = BombAddPacket(x, y, power)
        self.client._send_packet(packet)
        
    def shoot_arrow(self):
        """Shoot an arrow"""
        packet = ArrowAddPacket()
        self.client._send_packet(packet)
        
    def fire_effect(self):
        """Fire effect"""
        packet = FireSpyPacket()
        self.client._send_packet(packet)
        
    # Items
    def set_arrows(self, count: int):
        """Set arrow count"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_ARROWSCOUNT, count)
        self.client._send_packet(packet)
        self.client.local_player.arrows = count
        
    def set_bombs(self, count: int):
        """Set bomb count"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_BOMBSCOUNT, count)
        self.client._send_packet(packet)
        self.client.local_player.bombs = count
        
    def set_rupees(self, count: int):
        """Set rupee count"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_RUPEESCOUNT, count)
        self.client._send_packet(packet)
        self.client.local_player.rupees = count
        
    def set_hearts(self, current: float, maximum: Optional[float] = None):
        """Set hearts"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CURPOWER, current)
        if maximum is not None:
            packet.add_property(PlayerProp.PLPROP_MAXPOWER, maximum)
        self.client._send_packet(packet)
        self.client.local_player.hearts = current
        if maximum is not None:
            self.client.local_player.max_hearts = maximum
            
    def warp_to_level(self, level_name: str, x: float = 30.0, y: float = 30.0):
        """Warp to a specific level"""
        from .protocol.enums import PlayerToServer
        
        # Ensure level name has .nw extension if not a gmap
        if not level_name.endswith('.nw') and not level_name.endswith('.gmap'):
            level_name = f"{level_name}.nw"
        
        # Build warp packet manually
        # Format: ID + x*2 + y*2 + level_name
        packet_data = bytearray()
        packet_data.append(PlayerToServer.PLI_LEVELWARP + 32)  # +32 for encoding
        packet_data.append(int(x * 2) + 32)  # x coordinate * 2 + 32
        packet_data.append(int(y * 2) + 32)  # y coordinate * 2 + 32
        
        # Add level name as gstring (length + string)
        level_bytes = level_name.encode('ascii')
        packet_data.append(len(level_bytes))  # Don't add 32 to length for gstring
        packet_data.extend(level_bytes)
        
        self.client.queue_packet(bytes(packet_data))
        print(f"Warping to level '{level_name}' at ({x}, {y})")
        
        # Also request the level file after warping
        if not level_name.endswith('.gmap'):  # Don't request file for gmaps
            self.client.request_file(level_name)
        
    def request_adjacent_level(self, x: int, y: int):
        """Request adjacent level data for gmap streaming
        
        Args:
            x: X offset (-1, 0, or 1)
            y: Y offset (-1, 0, or 1)
        """
        from .protocol.enums import PlayerToServer
        
        # Build adjacent level request packet
        packet_data = bytearray()
        packet_data.append(PlayerToServer.PLI_ADJACENTLEVEL + 32)
        packet_data.append(x + 32)  # X offset + 32
        packet_data.append(y + 32)  # Y offset + 32
        
        self.client.queue_packet(bytes(packet_data))
        print(f"Requesting adjacent level at offset ({x}, {y})")
        
    def get_gmap_position(self) -> tuple:
        """Get current GMAP segment position
        
        Returns:
            (gmaplevelx, gmaplevely, x2, y2) or None if not in a gmap
        """
        if not self.client.local_player:
            return None
            
        player = self.client.local_player
        gmaplevelx = getattr(player, 'gmaplevelx', None)
        gmaplevely = getattr(player, 'gmaplevely', None)
        x2 = getattr(player, 'x2', None)
        y2 = getattr(player, 'y2', None)
        
        if gmaplevelx is not None and gmaplevely is not None:
            return (gmaplevelx, gmaplevely, x2 or 0, y2 or 0)
        return None
    
    # New GServer-V2 features
    def request_board_update(self, level: str, x: int, y: int, width: int, height: int, mod_time: int = 0):
        """Request partial board update for a level region"""
        packet = RequestUpdateBoardPacket(level, mod_time, x, y, width, height)
        self.client._send_packet(packet)
    
    def request_text(self, key: str):
        """Request a text value from the server"""
        packet = RequestTextPacket(key)
        self.client._send_packet(packet)
    
    def send_text(self, key: str, value: str):
        """Send a text value to the server"""
        packet = SendTextPacket(key, value)
        self.client._send_packet(packet)
    
    def set_group(self, group: str):
        """Set player group (for group maps)"""
        # Store locally - server handles via triggeraction
        self.client.local_player.group = group
    
    def move_with_precision(self, x: float, y: float, z: float = 0.0, direction: Optional[Direction] = None):
        """Move using high-precision coordinates"""
        if direction is None:
            direction = self.client.local_player.direction
            
        packet = PlayerPropsPacket()
        # Use high-precision properties
        packet.add_property(PlayerProp.PLPROP_X2, int(x * 16))
        packet.add_property(PlayerProp.PLPROP_Y2, int(y * 16))
        packet.add_property(PlayerProp.PLPROP_Z2, int(z))
        packet.add_property(PlayerProp.PLPROP_SPRITE, direction)
        self.client._send_packet(packet)
        
        # Update local state
        self.client.local_player.x = x
        self.client.local_player.y = y
        self.client.local_player.z = z
        self.client.local_player.direction = direction
    
    def _check_level_links(self, x: float, y: float):
        """Check if player position triggers a level link warp"""
        # Only check if we have a level manager and current level
        if not hasattr(self.client, 'level_manager') or not self.client.level_manager.current_level:
            return
            
        level = self.client.level_manager.current_level
        
        # Check all links in the current level
        for link in level.links:
            # Check if player is within the link area
            if (x >= link.x and x < link.x + link.width and 
                y >= link.y and y < link.y + link.height):
                # Player is in a link area - warp them
                print(f"🔗 Player touched level link at ({x:.1f}, {y:.1f}) - warping to {link.dest_level}")
                self.warp_to_level(link.dest_level, link.dest_x, link.dest_y)
                break
                
    def check_edge_warp(self):
        """Check if player is at level edge and should warp
        
        In traditional Graal, levels are 64x64 tiles and players warp when
        moving beyond the edges.
        """
        if not self.client.local_player:
            return
            
        x = self.client.local_player.x
        y = self.client.local_player.y
        
        # Check if at edge (levels are 64 tiles, 0-63)
        edge_triggered = False
        new_x, new_y = x, y
        offset_x, offset_y = 0, 0
        
        if x < 0:
            # West edge
            offset_x = -1
            new_x = 63 + x  # Wrap to east side
            edge_triggered = True
        elif x >= 64:
            # East edge  
            offset_x = 1
            new_x = x - 64  # Wrap to west side
            edge_triggered = True
            
        if y < 0:
            # North edge
            offset_y = -1
            new_y = 63 + y  # Wrap to south side
            edge_triggered = True
        elif y >= 64:
            # South edge
            offset_y = 1 
            new_y = y - 64  # Wrap to north side
            edge_triggered = True
            
        if edge_triggered:
            # In a GMAP, request adjacent level
            if hasattr(self.client, 'level_manager'):
                if self.client.level_manager.is_on_gmap:
                    print(f"🗺️ Edge warp in GMAP: requesting adjacent level at offset ({offset_x}, {offset_y})")
                    self.request_adjacent_level(offset_x, offset_y)
                else:
                    # For regular levels, check for level links
                    level_name = self.client.level_manager.current_level.name if self.client.level_manager.current_level else "unknown"
                    print(f"🔍 At edge of level {level_name} - checking for level links")
                    # Links should handle the warp