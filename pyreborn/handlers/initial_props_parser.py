#!/usr/bin/env python3
"""
Comprehensive parser for initial login properties packet
"""

from typing import Dict, Any, Tuple, Optional
import struct
import logging
from ..protocol.enums import PlayerProp

logger = logging.getLogger(__name__)


class InitialPropsParser:
    """Parser for the complex initial login properties packet"""
    
    def __init__(self):
        self.data = b''
        self.pos = 0
        self.props = {}
        
    def parse(self, data: bytes) -> Dict[PlayerProp, Any]:
        """Parse the initial login properties packet
        
        The packet contains data for multiple players:
        1. OUR player's numeric properties at the beginning
        2. String data (may include other players' data)
        3. GATTRIB flags and other properties
        4. Account names and additional data
        """
        self.data = data
        self.pos = 0
        self.props = {}
        
        logger.debug(f"[INITIAL_PROPS] Parsing {len(data)} bytes")
        
        # Phase 1: Parse OUR numeric properties from the beginning
        self._parse_our_numeric_properties()
        
        # Phase 2: Parse OUR equipment strings (sword, shield, etc)
        self._parse_our_equipment()
        
        # Phase 3: Parse GATTRIB flags (these appear to be ours)
        self._parse_gattrib_flags()
        
        # Phase 4: Try to find our account name
        self._find_our_account_name()
        
        logger.info(f"[INITIAL_PROPS] Extracted {len(self.props)} properties")
        return self.props
    
    def _parse_our_numeric_properties(self):
        """Parse the initial numeric properties section"""
        logger.debug("[INITIAL_PROPS] Phase 1: Numeric properties")
        
        # The first section contains prop/value pairs with +32 encoding
        # We need to be careful not to read into string data
        numeric_props_found = 0
        
        while self.pos < len(self.data) - 1:
            # Check if we've hit string data
            if self._looks_like_string_start():
                logger.debug(f"  String data detected at position {self.pos}")
                break
                
            prop_encoded = self.data[self.pos]
            value_encoded = self.data[self.pos + 1]
            
            prop_id = prop_encoded - 32
            value = value_encoded - 32
            
            logger.debug(f"  -> Position {self.pos}: bytes {prop_encoded:02x} {value_encoded:02x} = prop {prop_id}, value {value}")
            
            # Validate property ID
            if prop_id < 0 or prop_id > 100:
                # Not a valid property, might be string data
                logger.debug(f"  Invalid prop ID {prop_id}, stopping numeric parse")
                break
                
            try:
                prop = PlayerProp(prop_id)
                
                # Special handling for different property types
                if prop in [PlayerProp.PLPROP_SWORDPOWER, PlayerProp.PLPROP_SHIELDPOWER]:
                    # Power properties need additional -30 decoding
                    power = value - 30 if value >= 30 else value
                    # For initial packet, we'll get the image later
                    self.props[prop] = power
                    logger.debug(f"  {prop.name} = {power} (encoded: {value})")
                    
                elif prop in [PlayerProp.PLPROP_MAXPOWER, PlayerProp.PLPROP_CURPOWER,
                             PlayerProp.PLPROP_RUPEESCOUNT, PlayerProp.PLPROP_ARROWSCOUNT,
                             PlayerProp.PLPROP_BOMBSCOUNT, PlayerProp.PLPROP_GLOVEPOWER,
                             PlayerProp.PLPROP_BOMBPOWER, PlayerProp.PLPROP_SPRITE,
                             PlayerProp.PLPROP_STATUS]:
                    # Simple numeric properties
                    self.props[prop] = value
                    logger.debug(f"  {prop.name} = {value}")
                    
                elif prop in [PlayerProp.PLPROP_NICKNAME, PlayerProp.PLPROP_GANI,
                           PlayerProp.PLPROP_HEADGIF, PlayerProp.PLPROP_BODYIMG]:
                    # These will be parsed later from string section
                    # NICKNAME with value 0 is common and means empty nickname
                    if prop == PlayerProp.PLPROP_NICKNAME and value == 0:
                        # Empty nickname, this is valid
                        logger.debug(f"  {prop.name} = <empty>")
                    self.pos += 2
                    continue
                    
                else:
                    # Unknown or unhandled numeric property - still record it
                    # But skip GMAPLEVELX/Y as they should have actual coordinate values
                    if prop not in [PlayerProp.PLPROP_GMAPLEVELX, PlayerProp.PLPROP_GMAPLEVELY]:
                        self.props[prop] = value
                        logger.debug(f"  {prop.name} = {value}")
                    else:
                        # Skip GMAP coordinates in initial packet
                        logger.debug(f"  Skipping {prop.name} in initial packet")
                    
                self.pos += 2
                numeric_props_found += 1
                
            except ValueError:
                # Unknown property ID, might be string data
                # But let's continue scanning in case there are more props
                self.pos += 1
                continue
        
        logger.debug(f"  Found {numeric_props_found} numeric properties")
    
    def _looks_like_string_start(self) -> bool:
        """Check if current position looks like start of string data"""
        if self.pos + 4 >= len(self.data):
            return False
            
        # String properties start when we see a length byte followed by text
        # The pattern is usually: prop_id, length, string_data...
        
        # Check if next bytes look like a length-prefixed string
        prop_id = self.data[self.pos] - 32
        next_byte = self.data[self.pos + 1]
        
        # If prop_id is valid but next byte is a printable character or high value,
        # we might be at the string section
        if prop_id > 20 and next_byte > 0x40:
            # Look ahead to confirm we see text
            chunk = self.data[self.pos:self.pos + 10]
            if b'sword' in chunk or b'shield' in chunk or b'idle' in chunk:
                return True
                
        return False
    
    def _parse_our_equipment(self):
        """Parse string properties from the packet"""
        logger.debug("[INITIAL_PROPS] Phase 2: String properties")
        
        # Known string patterns to find
        string_patterns = [
            (b'sword1.png', 'sword_image'),
            (b'sword2.png', 'sword_image'),
            (b'sword3.png', 'sword_image'),
            (b'sword4.png', 'sword_image'),
            (b'shield1.png', 'shield_image'),
            (b'shield2.png', 'shield_image'),
            (b'shield3.png', 'shield_image'),
            (b'idle', 'gani'),
            (b'walk', 'gani'),
            (b'sword', 'gani'),
            (b'head0.png', 'head_image'),
            (b'head1.png', 'head_image'),
            (b'head2.png', 'head_image'),
            (b'head3.png', 'head_image'),
            (b'head4.png', 'head_image'),
            (b'head5.png', 'head_image'),
            (b'head6.png', 'head_image'),
            (b'head7.png', 'head_image'),
            (b'head8.png', 'head_image'),
            (b'head9.png', 'head_image'),
            (b'head10.png', 'head_image'),
            (b'head11.png', 'head_image'),
            (b'head12.png', 'head_image'),
            (b'head13.png', 'head_image'),
            (b'head14.png', 'head_image'),
            (b'head15.png', 'head_image'),
            (b'body.png', 'body_image'),
            (b'body2.png', 'body_image'),
            (b'body3.png', 'body_image'),
        ]
        
        # Also look for player nickname (after a known position marker)
        # The nickname appears to be preceded by certain bytes
        
        for pattern, prop_type in string_patterns:
            if pattern in self.data:
                pos = self.data.find(pattern)
                value = pattern.decode('ascii', errors='ignore')
                
                if prop_type == 'sword_image':
                    # Update sword power tuple
                    if PlayerProp.PLPROP_SWORDPOWER in self.props:
                        power = self.props[PlayerProp.PLPROP_SWORDPOWER]
                        self.props[PlayerProp.PLPROP_SWORDPOWER] = (power, value)
                    else:
                        self.props[PlayerProp.PLPROP_SWORDPOWER] = (1, value)
                    logger.debug(f"  Found sword image: {value}")
                    
                elif prop_type == 'shield_image':
                    # Update shield power tuple
                    if PlayerProp.PLPROP_SHIELDPOWER in self.props:
                        power = self.props[PlayerProp.PLPROP_SHIELDPOWER]
                        self.props[PlayerProp.PLPROP_SHIELDPOWER] = (power, value)
                    else:
                        self.props[PlayerProp.PLPROP_SHIELDPOWER] = (1, value)
                    logger.debug(f"  Found shield image: {value}")
                    
                elif prop_type == 'gani':
                    if PlayerProp.PLPROP_GANI not in self.props:
                        self.props[PlayerProp.PLPROP_GANI] = value
                        logger.debug(f"  Found GANI: {value}")
                        
                elif prop_type == 'head_image':
                    self.props[PlayerProp.PLPROP_HEADGIF] = value
                    logger.debug(f"  Found head image: {value}")
                    
                elif prop_type == 'body_image':
                    self.props[PlayerProp.PLPROP_BODYIMG] = value
                    logger.debug(f"  Found body image: {value}")
        
        # Nickname might not be in the initial packet
        # Account name "hosler" is different from nickname "me"
        
    def _find_nickname(self):
        """Find player nickname in the packet"""
        # Account name is "hosler" but nickname is "me" 
        # Look for the actual nickname
        
        # First check for known nicknames - prioritize shorter ones like "me"
        known_nicks = [b'me', b'*SpaceManSpiff']
        for nick in known_nicks:
            if nick in self.data:
                pos = self.data.find(nick)
                # For short nicknames like "me", need to be more careful
                if len(nick) <= 3:
                    # Check it's not part of another word
                    before_ok = pos == 0 or self.data[pos-1] < 0x20 or self.data[pos-1] > 0x7E
                    after_ok = pos + len(nick) >= len(self.data) or self.data[pos+len(nick)] < 0x20 or self.data[pos+len(nick)] > 0x7E
                    if before_ok and after_ok:
                        nickname = nick.decode('ascii')
                        if PlayerProp.PLPROP_NICKNAME not in self.props:
                            self.props[PlayerProp.PLPROP_NICKNAME] = nickname
                            logger.debug(f"  Found nickname: {nickname}")
                            return
                else:
                    # Longer nicknames are less ambiguous
                    nickname = nick.decode('ascii')
                    if PlayerProp.PLPROP_NICKNAME not in self.props:
                        self.props[PlayerProp.PLPROP_NICKNAME] = nickname
                        logger.debug(f"  Found nickname: {nickname}")
                        return
        
        # If not found, try generic search but be more careful
        for i in range(50, len(self.data) - 3):  # Start after initial props
            # Look for length-prefixed strings
            if i > 0 and self.data[i-1] < 20:  # Possible length byte
                length = self.data[i-1]
                if 3 <= length <= 20 and i + length <= len(self.data):
                    # Try to read the string
                    try:
                        nickname = self.data[i:i+length].decode('ascii')
                        # Validate it's a reasonable nickname
                        if (nickname.replace('*', '').replace('_', '').isalnum() and
                            not any(x in nickname.lower() for x in ['.png', 'idle', 'walk', 'sword', 'shield', 'body', 'head'])):
                            if PlayerProp.PLPROP_NICKNAME not in self.props:
                                self.props[PlayerProp.PLPROP_NICKNAME] = nickname
                                logger.debug(f"  Found nickname: {nickname}")
                                return
                    except:
                        pass
    
    def _parse_gattrib_flags(self):
        """Parse GATTRIB flag properties"""
        logger.debug("[INITIAL_PROPS] Phase 3: GATTRIB flags")
        
        # GATTRIB flags appear to be encoded as 0x20 (space) bytes
        # They typically start around position 0x70
        gattrib_count = 0
        
        # Look for sequences of 0x20 bytes
        for i in range(0x70, min(0xA0, len(self.data))):
            if i < len(self.data) and self.data[i] == 0x20:
                # This could be a GATTRIB flag
                # Calculate which GATTRIB based on position
                gattrib_num = gattrib_count + 1
                if 1 <= gattrib_num <= 30:
                    prop_id = PlayerProp.PLPROP_GATTRIB1 + gattrib_num - 1
                    try:
                        prop = PlayerProp(prop_id)
                        self.props[prop] = True
                        logger.debug(f"  GATTRIB{gattrib_num} = True")
                    except ValueError:
                        pass
                gattrib_count += 1
    
    def _find_our_account_name(self):
        """Parse any remaining data in the packet"""
        logger.debug("[INITIAL_PROPS] Phase 4: Remaining data")
        
        # Look for our account name (hosler)
        # This is different from nickname (me)
        if b'hosler' in self.data:
            self.props[PlayerProp.PLPROP_ACCOUNTNAME] = 'hosler'
            self.props[PlayerProp.PLPROP_COMMUNITYNAME] = 'hosler'
            logger.debug("  Found account name: hosler")
            
        # Note: Nickname "me" doesn't appear to be in the initial packet
        # It might be set later or sent in a different packet
        
        # Look for colors pattern (comma-separated numbers)
        for i in range(len(self.data) - 10):
            chunk = self.data[i:i+11]
            try:
                text = chunk.decode('ascii', errors='ignore')
                if ',' in text and text.count(',') == 4:
                    parts = text.split(',')
                    if all(p.isdigit() for p in parts):
                        colors = [int(p) for p in parts]
                        self.props[PlayerProp.PLPROP_EFFECTCOLORS] = colors
                        logger.debug(f"  Found colors: {colors}")
                        break
            except:
                pass
        
        # Status and sprite might be in the remaining numeric data
        # Let's check for reasonable values
        for i in range(0x40, min(0x60, len(self.data) - 1)):
            byte1 = self.data[i]
            byte2 = self.data[i + 1] if i + 1 < len(self.data) else 0
            
            # Check for SPRITE (should be 2)
            if byte1 - 32 == 17 and 0 <= byte2 - 32 <= 10:
                self.props[PlayerProp.PLPROP_SPRITE] = byte2 - 32
                logger.debug(f"  Found SPRITE: {byte2 - 32}")
                
            # Check for STATUS (should be 20)
            elif byte1 - 32 == 18 and 0 <= byte2 - 32 <= 100:
                self.props[PlayerProp.PLPROP_STATUS] = byte2 - 32
                logger.debug(f"  Found STATUS: {byte2 - 32}")


def parse_initial_login_props(data: bytes) -> Dict[PlayerProp, Any]:
    """Parse initial login properties packet"""
    parser = InitialPropsParser()
    return parser.parse(data)