"""
PLI_PLAYERPROPS - Player Properties Packet

This packet sets various player properties like position, appearance, stats, etc.
The most complex outgoing packet with custom encoding for different property types.

Property Encoding Rules (for GServer compatibility):

Fixed-size properties (no length prefix):
- PLPROP_X (15), PLPROP_Y (16): Half-tiles (value * 2), single byte, range 0-63.5 tiles
- PLPROP_SPRITE (17): Player facing direction (0=down, 1=left, 2=up, 3=right), single byte
  Note: Despite the name "SPRITE", this property controls direction, not the visual sprite
- PLPROP_Z (45): Height with +50 offset, single byte  
- PLPROP_GMAPLEVELX (43), PLPROP_GMAPLEVELY (44): GMAP segment coordinates, single byte

Variable-size string properties (with GCHAR length prefix):
- PLPROP_GANI (10): Animation name (e.g., "idle", "walk", "sword", "spin")
- PLPROP_NICKNAME (0): Player nickname
- PLPROP_CURCHAT (12): Chat message bubble
- PLPROP_BODYIMG (35): Body image filename
- PLPROP_CURLEVEL (20): Current level name

Special encoding properties:
- PLPROP_X2 (78), PLPROP_Y2 (79), PLPROP_Z2 (80): 2-byte pixel coordinates
  Format: (abs(pixels) << 1) | negative_flag, sent as big-endian
- PLPROP_HEADGIF (11): Length + 100, then string
- PLPROP_SWORDPOWER (8): Complex encoding with power level + image
- PLPROP_SHIELDPOWER (9): Complex encoding with power level + image

Note: All property IDs and values are offset by +32 for protocol encoding
"""

import logging
from typing import Dict, Any, List, Tuple, Union
from pyreborn.protocol.enums import PlayerProp
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class PlayerPropsBuilder:
    """Custom builder for PlayerProps packets with property-specific encoding"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build PlayerProps packet with custom property encoding"""
        from pyreborn.protocol.enums import PlayerToServer
        
        # Build packet directly without PacketBuilder
        data = bytearray()
        data.append(PlayerToServer.PLI_PLAYERPROPS + 32)  # Packet ID + 32
        
        # Get properties from packet fields
        properties = packet.get_field('properties') or []
        
        for prop, value in properties:
            prop_enum = PlayerProp(prop) if isinstance(prop, int) else prop
            data.append(int(prop_enum) + 32)  # Property ID + 32
            
            # Debug logging for direction and gani changes
            if prop_enum == PlayerProp.PLPROP_SPRITE:
                # Commented out to reduce log spam
                # logger.info(f"Sending direction update: {value} (0=down, 1=left, 2=up, 3=right)")
                pass
            elif prop_enum == PlayerProp.PLPROP_GANI:
                logger.info(f"Sending GANI update: {value}")
            
            # Handle different property types with custom encoding
            if prop_enum in [PlayerProp.PLPROP_X, PlayerProp.PLPROP_Y, PlayerProp.PLPROP_SPRITE]:
                # Fixed-size properties - NO length field
                if prop_enum in [PlayerProp.PLPROP_X, PlayerProp.PLPROP_Y]:
                    # Clamp negative values to 0, max to 255, coordinate encoding
                    clamped_value = max(0, min(255, int(value * 2)))
                    data.append(clamped_value + 32)
                else:
                    data.append(int(value) + 32)
            elif prop_enum in [PlayerProp.PLPROP_GMAPLEVELX, PlayerProp.PLPROP_GMAPLEVELY]:
                # GMAP level coordinates are sent as single bytes
                data.append(max(0, min(255, int(value))) + 32)
            elif prop_enum in [PlayerProp.PLPROP_X2, PlayerProp.PLPROP_Y2, PlayerProp.PLPROP_Z2]:
                # High precision coordinates (2 bytes with GSHORT encoding)
                # Server expects: (abs(pixels) << 1) | (negative ? 1 : 0)
                # Then encodes as GSHORT: value + 0x1020, split into 7-bit chunks
                pixel_value = int(value)
                abs_value = abs(pixel_value)
                is_negative = pixel_value < 0
                encoded_value = (abs_value << 1) | (1 if is_negative else 0)
                
                # Debug logging for X2/Y2 encoding
                if prop_enum in [PlayerProp.PLPROP_X2, PlayerProp.PLPROP_Y2]:
                    prop_name = "X2" if prop_enum == PlayerProp.PLPROP_X2 else "Y2"
                    logger.debug(f"[{prop_name}_ENCODE] Input: {value}, Pixels: {pixel_value}, Raw: {encoded_value}, GSHORT: {encoded_value + 0x1020:04X}")
                
                # GSHORT encoding: add offset, split into 7-bit values
                gshort_value = encoded_value + 0x1020
                b1 = (gshort_value >> 7) & 0xFF
                b2 = gshort_value & 0x7F
                
                # Add protocol offset to each byte
                data.append(b1 + 32)
                data.append(b2 + 32)
            elif prop_enum == PlayerProp.PLPROP_HEADGIF:
                # Head image uses length + 100
                data.append(len(str(value)) + 100)
                data.extend(str(value).encode('ascii', errors='replace'))
            elif prop_enum == PlayerProp.PLPROP_SWORDPOWER:
                # Sword power special encoding
                if isinstance(value, tuple):
                    sword_id, sword_image = value
                    data.append(len(sword_image) + 32)
                    data.append(sword_id + 30 + 32)  # +30 offset for sword power, +32 for protocol
                    data.extend(sword_image.encode('ascii', errors='replace'))
                else:
                    data.append(1 + 32)
                    data.append(int(value) + 30 + 32)
                    data.extend(str(value).encode('ascii', errors='replace'))
            elif isinstance(value, str):
                # String properties with length
                data.append(len(value) + 32)
                data.extend(value.encode('ascii', errors='replace'))
            else:
                # Numeric properties (single byte)
                data.append(int(value) + 32)
        
        # End packet with newline
        data.append(10)
        return bytes(data)


def encode_properties_field(properties: List[Tuple[Union[PlayerProp, int], Any]]) -> List[Tuple[int, Any]]:
    """Encoder function to convert property list to internal format"""
    encoded = []
    for prop, value in properties:
        prop_id = int(prop) if isinstance(prop, (PlayerProp, int)) else prop
        encoded.append((prop_id, value))
    return encoded


# Define the PlayerProps packet structure
PLI_PLAYERPROPS = OutgoingPacketStructure(
    packet_id=2,
    name="PLI_PLAYERPROPS",
    description="Set player properties (position, appearance, stats, etc.)",
    fields=[
        OutgoingPacketField(
            name="properties",
            field_type=PacketFieldType.VARIABLE_DATA,
            description="List of (property_id, value) tuples to set",
            default=[],
            encoder=encode_properties_field
        )
    ],
    variable_length=True,
    builder_class=PlayerPropsBuilder
)


class PlayerPropsPacketHelper:
    """Helper class for easier PlayerProps packet construction"""
    
    @staticmethod
    def create() -> OutgoingPacket:
        """Create a new PlayerProps packet"""
        return PLI_PLAYERPROPS.create_packet()
    
    @staticmethod  
    def create_with_properties(**prop_kwargs) -> OutgoingPacket:
        """Create PlayerProps packet with properties as keyword arguments
        
        Example:
            packet = PlayerPropsPacketHelper.create_with_properties(
                x=30.5, y=25.0, nickname="TestPlayer"
            )
        """
        # Convert kwargs to property list
        properties = []
        prop_mapping = {
            'nickname': PlayerProp.PLPROP_NICKNAME,
            'x': PlayerProp.PLPROP_X,
            'y': PlayerProp.PLPROP_Y,
            'x2': PlayerProp.PLPROP_X2,
            'y2': PlayerProp.PLPROP_Y2,
            'z2': PlayerProp.PLPROP_Z2,
            'sprite': PlayerProp.PLPROP_SPRITE,
            'gani': PlayerProp.PLPROP_GANI,
            'headgif': PlayerProp.PLPROP_HEADGIF,
            'bodyimg': PlayerProp.PLPROP_BODYIMG,
            'colors': PlayerProp.PLPROP_COLORS,
            'curlevel': PlayerProp.PLPROP_CURLEVEL,
            'gmaplevelx': PlayerProp.PLPROP_GMAPLEVELX,
            'gmaplevely': PlayerProp.PLPROP_GMAPLEVELY,
            'chat': PlayerProp.PLPROP_CURCHAT,
            'arrows': PlayerProp.PLPROP_ARROWSCOUNT,
            'bombs': PlayerProp.PLPROP_BOMBSCOUNT,
            'rupees': PlayerProp.PLPROP_RUPEESCOUNT,
            'sword_power': PlayerProp.PLPROP_SWORDPOWER,
            'carry_sprite': PlayerProp.PLPROP_CARRYSPRITE,
        }
        
        for key, value in prop_kwargs.items():
            if key in prop_mapping:
                properties.append((prop_mapping[key], value))
            else:
                logger.warning(f"Unknown property: {key}")
        
        return PLI_PLAYERPROPS.create_packet(properties=properties)
    
    @staticmethod
    def add_property(packet: OutgoingPacket, prop: Union[PlayerProp, int], value: Any) -> OutgoingPacket:
        """Add a property to an existing packet (fluent interface)"""
        current_props = packet.get_field('properties') or []
        current_props.append((prop, value))
        return packet.set_field('properties', current_props)


# Export the helper for easier imports
PlayerPropsPacket = PlayerPropsPacketHelper