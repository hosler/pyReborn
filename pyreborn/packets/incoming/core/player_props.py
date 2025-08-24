#!/usr/bin/env python3
"""
PLO_PLAYERPROPS (Packet 9) - Parser based on Preagonal's C# implementation

This parser follows the approach used in Preagonal's C# codebase:
- Parse properties sequentially through entire packet
- Each property ID determines how to parse its value
- No separation between "numeric" and "string" sections
"""

from ...base import PacketStructure, PacketField, PacketFieldType, variable_data_field, PacketReader, parse_field
from typing import Dict, Any, Tuple, List
import logging

# Import GMAP resolution functionality (with fallback for circular imports)
try:
    from ...world.gmap_resolver import GMapResolver
    from ...world.coordinate_helpers import CoordinateHelpers
    GMAP_RESOLUTION_AVAILABLE = True
except ImportError:
    GMAP_RESOLUTION_AVAILABLE = False

logger = logging.getLogger(__name__)

# Module-level resolver for GMAP level name resolution
_gmap_resolver = None

def get_gmap_resolver():
    """Get or create module-level GMAP resolver instance"""
    global _gmap_resolver
    if _gmap_resolver is None and GMAP_RESOLUTION_AVAILABLE:
        _gmap_resolver = GMapResolver()
    return _gmap_resolver


PLO_PLAYERPROPS = PacketStructure(
    packet_id=9,
    name="PLO_PLAYERPROPS",
    fields=[
        variable_data_field("properties", "Encoded player properties")
    ],
    description="Player properties blob",
    variable_length=True
)


def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse player properties following Preagonal's approach.
    
    Each property is parsed based on its ID:
    - Most numeric properties: single byte with -32
    - String properties: length byte (-32) + string data  
    - PixelX/PixelY: 2-byte special encoding
    - Special cases like HeadImage with length-100
    """
    try:
        prop_data = data.get('properties', b'')
        
        if not prop_data:
            return {'error': 'No property data', 'properties': {}, 'events': []}
        
        # WORKAROUND: Server sometimes sends a leading backslash (0x5c) that corrupts the data
        # This is a bug in the server or packet extraction, but we can work around it
        if len(prop_data) > 0 and prop_data[0] == 0x5c:  # backslash
            logger.warning(f"Stripping leading backslash from PLO_PLAYERPROPS data")
            prop_data = prop_data[1:]
        
        from pyreborn.protocol.enums import PlayerProp
        
        properties = {}
        events_to_emit = []
        pos = 0
        
        logger.info(f"📦 Parsing PLO_PLAYERPROPS: {len(prop_data)} bytes")
        if len(prop_data) > 0:
            first_bytes = ' '.join(f'{b:02x}' for b in prop_data[:min(20, len(prop_data))])
            logger.info(f"   First bytes: {first_bytes}")  # Changed to INFO level
        
        # Track what changed
        position_changed = False
        nickname_changed = False
        health_changed = False
        sprite_changed = False
        
        # Parse properties sequentially through entire packet
        prop_count = 0
        while pos < len(prop_data):
            # Read property ID
            prop_id = prop_data[pos] - 32
            pos += 1
            
            # Validate property ID
            if prop_id < 0 or prop_id > 125:
                logger.debug(f"Invalid property ID {prop_id} at position {pos-1}, stopping")
                break
            
            # WORKAROUND: Check if we're in the empty properties section
            # This section has many properties with length 0 (0x20)
            # If we see property 0 followed by a large length that would read past the end,
            # we're probably misinterpreting the empty properties section
            if prop_id == 0 and pos < len(prop_data):
                potential_len = prop_data[pos] - 32
                # If the "nickname" would be suspiciously long or contain property IDs
                if potential_len > 30 and pos + 1 + potential_len <= len(prop_data):
                    # Check if the "string" contains what looks like property IDs
                    preview = prop_data[pos + 1:pos + 1 + min(10, potential_len)]
                    # If we see patterns like 0x20 0xXX 0x20 (property, length 0, property)
                    if preview.count(0x20) > 2:
                        logger.debug(f"Detected misaligned property 0 in empty section at {pos-1}, skipping")
                        # Skip this byte and continue
                        continue
            
            try:
                prop = PlayerProp(prop_id)
                prop_name = prop.name.lower().replace('plprop_', '')
            except ValueError:
                prop = None
                prop_name = f'prop_{prop_id}'
            
            logger.debug(f"Property {prop_id} ({prop_name}) at position {pos-1}")
            
            # Parse based on property type (following Preagonal's logic)
            
            # String properties with length prefix  
            # Note: Properties 8 and 9 (sword/shield) have special encoding, handled separately
            # IMPORTANT: Property 0 (nickname) can appear as 0x20 which is also a space character
            # Be careful to not misinterpret empty property sections
            # Properties 83-125: Unknown properties that may contain nested account data
            # Property 21 is HorseImage (string property, not special encoding)
            if prop_id in [0, 10, 12, 20, 21, 34, 35, 37, 38, 39, 40, 41, 46, 47, 48, 49, 
                          52, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 
                          69, 70, 71, 72, 73, 74, 75, 82] or (prop_id >= 83 and prop_id <= 125):
                # These are string properties - read length then string
                if pos < len(prop_data):
                    str_len = prop_data[pos] - 32
                    pos += 1
                    if str_len > 0 and pos + str_len <= len(prop_data):
                        string_val = prop_data[pos:pos + str_len].decode('latin-1', errors='replace')
                        # For nickname, only update if it looks valid
                        if prop_id == 0:  # Nickname
                            # Check if this looks like a valid nickname (not garbled data)
                            # Garbled nicknames often have patterns like " G H I" from empty properties
                            if string_val and not string_val.startswith(' G H') and not string_val.startswith(' H I'):
                                # Additional check: valid nicknames shouldn't have this many single letters
                                single_letter_count = sum(1 for word in string_val.split() if len(word) == 1)
                                if single_letter_count < 10:  # Arbitrary threshold
                                    properties[prop_name] = string_val
                                    nickname_changed = True
                                    logger.info(f"   Nickname: {string_val}")
                                else:
                                    logger.debug(f"   Skipping garbled nickname: {repr(string_val[:30])}")
                            else:
                                logger.debug(f"   Skipping empty/garbled nickname")
                        elif prop_id == 34:  # Original AccountName property
                            properties['account'] = string_val
                            logger.info(f"   Account name (prop 34): {string_val}")
                        else:
                            properties[prop_name] = string_val
                            if prop_id == 10:  # Animation/GANI
                                logger.debug(f"   Animation: {string_val}")
                            
                            # Check string properties > 82 for nested community name
                            # These high-numbered properties contain the community name with nested encoding
                            if prop_id > 82 and len(string_val) > 4 and '\x42' in string_val:
                                # Found potential nested property 34 (community name in v6+)
                                nested_pos = string_val.find('\x42')
                                if nested_pos >= 0 and nested_pos + 1 < len(string_val):
                                    # Read the length of the nested property
                                    nested_len = ord(string_val[nested_pos + 1]) - 32
                                    if nested_len > 0 and nested_pos + 2 + nested_len <= len(string_val):
                                        # Extract the community name from the nested property
                                        community_name = string_val[nested_pos + 2:nested_pos + 2 + nested_len]
                                        if community_name and community_name.isprintable():
                                            properties['communityname'] = community_name
                                            # Store as account name since it's the login account
                                            properties['account'] = community_name
                                            logger.info(f"   Community name extracted from prop {prop_id}: '{community_name}'")
                        pos += str_len
                    elif str_len == 0:
                        # Don't overwrite nickname with empty value
                        if prop_id != 0:  # Not nickname
                            properties[prop_name] = ""
                        else:
                            logger.debug(f"   Skipping empty nickname")
                        
            # HeadImage (special encoding with length-100)
            elif prop_id == 11:
                if pos < len(prop_data):
                    len_val = prop_data[pos] - 32
                    pos += 1
                    if len_val < 100:
                        # Standard head image
                        properties['headimg'] = f"head{len_val}.png"
                        logger.debug(f"   Head image: head{len_val}.png")
                    else:
                        # Custom head image
                        actual_len = len_val - 100
                        if actual_len > 0 and pos + actual_len <= len(prop_data):
                            headimg = prop_data[pos:pos + actual_len].decode('latin-1', errors='replace')
                            properties['headimg'] = headimg
                            logger.debug(f"   Head image: {headimg}")
                            pos += actual_len
                            
            # X and Y coordinates (obsolete, single byte)
            elif prop_id == 15:  # X
                if pos < len(prop_data):
                    value = prop_data[pos] - 32
                    coord_tiles = value / 2.0  # Half-tiles to tiles
                    properties['x'] = coord_tiles
                    position_changed = True
                    logger.info(f"   X: {coord_tiles:.1f} tiles")
                    pos += 1
                    
            elif prop_id == 16:  # Y
                if pos < len(prop_data):
                    value = prop_data[pos] - 32
                    coord_tiles = value / 2.0  # Half-tiles to tiles
                    properties['y'] = coord_tiles
                    position_changed = True
                    logger.info(f"   Y: {coord_tiles:.1f} tiles")
                    pos += 1
                    
            # PixelX (property 78) - 2-byte special encoding
            elif prop_id == 78:
                if pos + 1 < len(prop_data):
                    # Read 2-byte value
                    b1 = prop_data[pos] - 32
                    b2 = prop_data[pos + 1] - 32
                    value = (b1 << 7) | b2
                    
                    # Extract pixel value and sign
                    pixels = value >> 1
                    if value & 0x0001:
                        pixels = -pixels
                    
                    # Convert to tiles
                    coord_tiles = pixels / 16.0
                    properties['pixelx'] = coord_tiles
                    properties['x2'] = coord_tiles  # Also store as x2 for compatibility
                    position_changed = True
                    logger.info(f"   PixelX: {coord_tiles:.4f} tiles ({pixels} pixels)")
                    pos += 2
                    
            # PixelY (property 79) - 2-byte special encoding
            elif prop_id == 79:
                if pos + 1 < len(prop_data):
                    # Read 2-byte value
                    b1 = prop_data[pos] - 32
                    b2 = prop_data[pos + 1] - 32
                    value = (b1 << 7) | b2
                    
                    # Extract pixel value and sign
                    pixels = value >> 1
                    if value & 0x0001:
                        pixels = -pixels
                    
                    # Convert to tiles
                    coord_tiles = pixels / 16.0
                    properties['pixely'] = coord_tiles
                    properties['y2'] = coord_tiles  # Also store as y2 for compatibility
                    position_changed = True
                    logger.info(f"   PixelY: {coord_tiles:.4f} tiles ({pixels} pixels)")
                    pos += 2
                    
            # PixelZ (property 80) - 2-byte
            elif prop_id == 80:
                if pos + 1 < len(prop_data):
                    b1 = prop_data[pos] - 32
                    b2 = prop_data[pos + 1] - 32
                    value = (b1 << 7) | b2
                    properties['pixelz'] = value >> 1
                    pos += 2
                    
            # Rupees (3-byte value)
            elif prop_id == 3:
                if pos + 2 < len(prop_data):
                    b1 = prop_data[pos] - 32
                    b2 = prop_data[pos + 1] - 32
                    b3 = prop_data[pos + 2] - 32
                    value = (b1 << 14) | (b2 << 7) | b3
                    properties['rupees'] = value
                    logger.debug(f"   Rupees: {value}")
                    pos += 3
                    
            # Colors (5 single bytes)
            elif prop_id == 13:
                if pos + 4 < len(prop_data):
                    colors = []
                    for i in range(5):
                        colors.append(prop_data[pos + i] - 32)
                    properties['colors'] = colors
                    logger.debug(f"   Colors: {colors}")
                    pos += 5
                    
            # SwordPower (special encoding) - DISABLED, property 8 seems to be animation
            elif prop_id == 8:
                if pos < len(prop_data):
                    sp = prop_data[pos] - 32
                    pos += 1
                    if sp > 4:
                        # Custom sword image
                        sp -= 30
                        if pos < len(prop_data):
                            img_len = prop_data[pos] - 32
                            pos += 1
                            if img_len > 0 and pos + img_len <= len(prop_data):
                                swordimg = prop_data[pos:pos + img_len].decode('latin-1', errors='replace')
                                properties['swordimg'] = swordimg
                                pos += img_len
                    else:
                        properties['swordimg'] = f"sword{sp}.png"
                    properties['swordpower'] = sp
                    logger.debug(f"   Sword power: {sp}")
                    
            # ShieldPower (special encoding)
            elif prop_id == 9:
                if pos < len(prop_data):
                    sp = prop_data[pos] - 32
                    pos += 1
                    if sp > 3:
                        # Custom shield image
                        sp -= 10
                        # IMPORTANT: Check if sp is negative (fixes odd bug with 1.41 client per GServer)
                        if sp < 0:
                            logger.debug(f"   Shield power negative after -10: {sp}, stopping parse")
                            break  # Stop parsing entirely (matches GServer line 492)
                        
                        if pos < len(prop_data):
                            img_len = prop_data[pos] - 32
                            pos += 1
                            if img_len > 0 and pos + img_len <= len(prop_data):
                                shieldimg = prop_data[pos:pos + img_len].decode('latin-1', errors='replace')
                                properties['shieldimg'] = shieldimg
                                pos += img_len
                    else:
                        properties['shieldimg'] = f"shield{sp}.png"
                    properties['shieldpower'] = sp
                    logger.debug(f"   Shield power: {sp}")
                    
            # Single-byte numeric properties
            else:
                if pos < len(prop_data):
                    value = prop_data[pos] - 32
                    properties[prop_name] = value
                    pos += 1
                    
                    # Track specific changes
                    if prop_id == 1:  # MaxPower
                        logger.debug(f"   Max power: {value}")
                    elif prop_id == 2:  # CurrentPower
                        properties['curpower'] = value / 2.0  # Half-hearts to hearts
                        health_changed = True
                        logger.debug(f"   Current power: {value/2.0}")
                    elif prop_id == 14:  # Player ID
                        properties['id'] = value
                        logger.info(f"   Player ID: {value}")
                    elif prop_id == 17:  # Sprite/direction
                        properties['sprite'] = value % 4
                        sprite_changed = True
                        logger.debug(f"   Direction: {value % 4}")
                    elif prop_id == 25:  # AP Count (Achievement Points)
                        properties['apcount'] = value
                        logger.info(f"   AP Count: {value}")
                    elif prop_id == 43:  # GmapLevelX
                        properties['gmaplevelx'] = value
                        logger.info(f"   GMAP X segment: {value}")
                    elif prop_id == 44:  # GmapLevelY
                        properties['gmaplevely'] = value
                        logger.info(f"   GMAP Y segment: {value}")
            
            # Check for undocumented high-number properties (81, 82)
            if prop_id == 81:  # Guild tag / prefix
                if pos < len(prop_data):
                    str_len = prop_data[pos] - 32
                    pos += 1
                    if str_len > 0 and pos + str_len <= len(prop_data):
                        guild_tag = prop_data[pos:pos+str_len].decode('ascii', errors='replace')
                        properties['guild_tag'] = guild_tag
                        logger.info(f"   Guild tag: {guild_tag}")
                        pos += str_len
                        
            elif prop_id == 82:  # Actual nickname (v6+ clients)
                if pos < len(prop_data):
                    str_len = prop_data[pos] - 32
                    pos += 1
                    if str_len > 0 and pos + str_len <= len(prop_data):
                        nickname = prop_data[pos:pos+str_len].decode('ascii', errors='replace')
                        properties['nickname'] = nickname
                        nickname_changed = True
                        logger.info(f"   Nickname (prop 82): {nickname}")
                        pos += str_len
            
            prop_count += 1
            
            # Safety limit
            if prop_count > 100:
                logger.warning("Parsed over 100 properties, stopping to prevent infinite loop")
                break
        
        logger.info(f"   Parsed {prop_count} properties total")
        
        # If no coordinates were found, use defaults
        # Note: Properties 15/16 (X/Y) are obsolete, server uses X2/Y2 (75/76)
        if 'x' not in properties and 'pixelx' not in properties:
            # This is expected for initial props which don't include position
            logger.debug("   No X coordinate in this packet (expected for some packet types)")
            
        if 'y' not in properties and 'pixely' not in properties:
            # This is expected for initial props which don't include position
            logger.debug("   No Y coordinate in this packet (expected for some packet types)")
        
        # Calculate coordinate info and resolve GMAP level names
        coordinate_info = {}
        resolved_level_name = None
        
        if 'gmaplevelx' in properties and 'gmaplevely' in properties:
            # GMAP mode
            gmaplevelx = properties['gmaplevelx']
            gmaplevely = properties['gmaplevely']
            
            # Get world coordinates (x2/y2 are authoritative if available)
            world_x = properties.get('x2')  # x2/y2 are already in tiles
            world_y = properties.get('y2')
            
            # Fallback to pixel coordinates (already converted to tiles in parsing)
            if world_x is None:
                world_x = properties.get('pixelx', properties.get('x', 30.0))
            if world_y is None:
                world_y = properties.get('pixely', properties.get('y', 30.0))
                
            # Calculate local coordinates for this segment
            local_x = world_x % 64  # Local position within segment
            local_y = world_y % 64
            
            # Try to resolve actual level name using world coordinates
            # Note: GMAP name will be provided by session manager context
            # For now, we'll store the coordinate data for later resolution
            resolver = get_gmap_resolver() if GMAP_RESOLUTION_AVAILABLE else None
            if resolver:
                # We'll try resolution with a default GMAP name pattern
                # This will be enhanced when session manager provides the GMAP context
                logger.debug(f"🔍 GMAP coordinates ready for resolution: world({world_x:.2f},{world_y:.2f}), segment({gmaplevelx},{gmaplevely})")
            
            coordinate_info = {
                'in_gmap': True,
                'gmap_segment': (gmaplevelx, gmaplevely),
                'local_position': (local_x, local_y),
                'world_position': (world_x, world_y),
                'resolved_level_name': resolved_level_name,
                'resolver_available': resolver is not None
            }
        else:
            # Single level mode
            coordinate_info = {
                'in_gmap': False,
                'local_position': (
                    properties.get('pixelx', properties.get('x', 30.0)),
                    properties.get('pixely', properties.get('y', 30.0))
                )
            }
        
        # Build events  
        # Check if position properties are in this packet (for event triggering)
        if not position_changed:
            position_changed = ('x' in properties or 'pixelx' in properties or 
                              'y' in properties or 'pixely' in properties)
        
        if position_changed:
            events_to_emit.append({
                'type': 'PLAYER_MOVED',
                'data': {
                    'x': properties.get('pixelx', properties.get('x', 30.0)),
                    'y': properties.get('pixely', properties.get('y', 30.0)),
                    'coordinate_info': coordinate_info
                }
            })
        
        # Always emit update event
        update_data = {'properties': properties}
        
        if nickname_changed:
            update_data['nickname_changed'] = True
            update_data['nickname'] = properties.get('nickname', '')
        
        if health_changed:
            update_data['health_changed'] = True
            update_data['current_health'] = properties.get('curpower', 0)
            update_data['max_health'] = properties.get('maxpower', 3)
        
        if sprite_changed:
            update_data['direction_changed'] = True
            update_data['direction'] = properties.get('sprite', 2)
        
        events_to_emit.append({
            'type': 'PLAYER_UPDATE',
            'data': update_data
        })
        
        # Log summary
        logger.info(f"✅ PLO_PLAYERPROPS parsed: {len(properties)} properties")
        if 'x' in properties or 'pixelx' in properties:
            x_val = properties.get('pixelx', properties.get('x', '?'))
            logger.info(f"   X coordinate: {x_val}")
        if 'y' in properties or 'pixely' in properties:
            y_val = properties.get('pixely', properties.get('y', '?'))
            logger.info(f"   Y coordinate: {y_val}")
        if 'nickname' in properties:
            logger.info(f"   Nickname: {properties['nickname']}")
        
        return {
            'properties': properties,
            'events': events_to_emit,
            'coordinate_info': coordinate_info,
            'raw_size': len(prop_data)
        }
        
    except Exception as e:
        logger.error(f"Error parsing player props: {e}")
        import traceback
        traceback.print_exc()
        return {
            'error': str(e),
            'properties': {},
            'events': []
        }


def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PLAYERPROPS packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PLAYERPROPS.packet_id,
        'packet_name': PLO_PLAYERPROPS.name,
        'fields': {}
    }
    
    # Parse the raw fields first
    for field in PLO_PLAYERPROPS.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    # Apply full business logic parsing
    parsed_data = parse(result['fields'])
    if parsed_data:
        result['parsed_data'] = parsed_data
    
    return result