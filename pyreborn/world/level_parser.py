"""
Level file parser for GLEVNW01 format
Parses board data, links, NPCs, signs, and other level elements
"""

from typing import Dict, List, Tuple, Optional, Union
from dataclasses import dataclass


@dataclass
class LevelLink:
    """Represents a level link/warp"""
    x: int
    y: int
    width: int
    height: int
    target_level: str
    target_x: Union[float, str]  # Can be numeric or "playerx"
    target_y: Union[float, str]  # Can be numeric or "playery"
    
    # Alias properties for compatibility
    @property
    def destination(self) -> str:
        """Alias for target_level for compatibility with rendering code"""
        return self.target_level
    
    @property
    def dest_level(self) -> str:
        return self.target_level
    
    @property
    def dest_x(self) -> Union[float, str, None]:
        # Convert special values to None
        if isinstance(self.target_x, str) and self.target_x in ('playerx', '-1'):
            return None
        return self.target_x
    
    @property 
    def dest_y(self) -> Union[float, str, None]:
        # Convert special values to None
        if isinstance(self.target_y, str) and self.target_y in ('playery', '-1'):
            return None
        return self.target_y
    
    def contains(self, px: float, py: float) -> bool:
        """Check if position is within link area"""
        return (self.x <= px < self.x + self.width and 
                self.y <= py < self.y + self.height)
    

@dataclass
class LevelNPC:
    """Represents an NPC in the level"""
    x: float
    y: float
    image: str
    script: str
    

@dataclass
class LevelSign:
    """Represents a sign in the level"""
    x: int
    y: int
    text: str


class LevelParser:
    """Parser for GLEVNW01 level files"""
    
    def __init__(self):
        self.board_data = bytearray()
        self.links: List[LevelLink] = []
        self.npcs: List[LevelNPC] = []
        self.signs: List[LevelSign] = []
        self.chest_items: Dict[Tuple[int, int], int] = {}
        self.is_gmap = False  # Track if this is a GMAP file
        
    def parse(self, file_data: bytes) -> Dict:
        """Parse a complete level file
        
        Returns:
            Dict containing all parsed level data
        """
        try:
            # Decode with latin-1 to handle special characters
            text = file_data.decode('latin-1', errors='replace')
            lines = text.split('\n')
            
            # Track parsing state
            i = 0
            in_npc = False
            current_npc = None
            npc_script_lines = []
            
            # Check for GLEVNW01 header
            if lines[0].strip() == 'GLEVNW01':
                i = 1  # Skip header
                self.is_gmap = True  # GLEVNW01 files use different encoding
                
            # Parse content
            while i < len(lines):
                line = lines[i].strip()
                
                # Skip empty lines
                if not line:
                    i += 1
                    continue
                    
                # Board data
                if line.startswith('BOARD '):
                    self._parse_board_line(line)
                    
                # Level links
                elif line.startswith('LINK '):
                    self._parse_link(line)
                    
                # Signs
                elif line.startswith('SIGN '):
                    self._parse_sign(line)
                    
                # Chests
                elif line.startswith('CHEST '):
                    self._parse_chest(line)
                    
                # NPCs
                elif line.startswith('NPC '):
                    # Start new NPC
                    if in_npc and current_npc:
                        # Save previous NPC
                        current_npc.script = '\n'.join(npc_script_lines)
                        self.npcs.append(current_npc)
                        
                    parts = line.split(' - ')
                    if len(parts) >= 2:
                        coords = parts[1].split()
                        if len(coords) >= 2:
                            x = float(coords[0])
                            y = float(coords[1])
                            current_npc = LevelNPC(x=x, y=y, image='', script='')
                            in_npc = True
                            npc_script_lines = []
                            
                elif line == 'NPCEND' and in_npc:
                    # End current NPC
                    if current_npc:
                        current_npc.script = '\n'.join(npc_script_lines)
                        self.npcs.append(current_npc)
                    in_npc = False
                    current_npc = None
                    npc_script_lines = []
                    
                elif in_npc:
                    # Accumulate NPC script lines
                    npc_script_lines.append(line)
                    
                i += 1
                
            # Save final NPC if still parsing one
            if in_npc and current_npc:
                current_npc.script = '\n'.join(npc_script_lines)
                self.npcs.append(current_npc)
                
            # Return parsed data
            return {
                'board_data': bytes(self.board_data),
                'links': self.links,
                'npcs': self.npcs,
                'signs': self.signs,
                'chests': self.chest_items
            }
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error parsing level file: {e}")
            return {
                'board_data': bytes(self.board_data),
                'links': [],
                'npcs': [],
                'signs': [],
                'chests': {}
            }
            
    def _parse_board_line(self, line: str):
        """Parse a BOARD line"""
        # Format: BOARD x y width height tile_data
        parts = line.split(None, 5)  # Split into max 6 parts
        if len(parts) >= 6:
            x = int(parts[1])
            y = int(parts[2])
            width = int(parts[3])
            height = int(parts[4])
            tile_str = parts[5]
            
            # For GLEVNW01 format, handle 64 BOARD lines with height=0
            if height == 0 and width == 64 and y < 64:
                # Decode this row
                row_bytes = self._decode_board_string(tile_str)
                # Insert at correct position
                start_pos = y * 64 * 2  # Each tile is 2 bytes
                if start_pos == len(self.board_data):
                    self.board_data.extend(row_bytes)
                    
    def _decode_board_string(self, board_str: str) -> bytes:
        """Decode BOARD string to tile data"""
        result = bytearray()
        
        # Reborn's base64 character set
        base64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        
        i = 0
        while i < len(board_str):
            # Each tile is encoded as 2 characters
            if i + 1 < len(board_str):
                char1 = board_str[i]
                char2 = board_str[i + 1]
                
                # Find positions in base64 character set
                idx1 = base64_chars.find(char1)
                idx2 = base64_chars.find(char2)
                
                if idx1 >= 0 and idx2 >= 0:
                    # Reborn tile ID format: first_char * 64 + second_char
                    tile_id = idx1 * 64 + idx2
                    # Tile IDs can go up to 4095 (12 bits)
                    # No modulo needed - the formula gives us the correct range
                else:
                    # Invalid characters, use tile 0
                    tile_id = 0
                
                # Store as little-endian 16-bit
                result.extend(tile_id.to_bytes(2, 'little'))
                i += 2
            else:
                break
                
        return bytes(result)
        
    def _parse_link(self, line: str):
        """Parse a LINK line"""
        # Format: LINK target_level x y width height target_x target_y
        parts = line.split()
        if len(parts) >= 8:
            try:
                # Handle special values for destination coordinates
                dest_x = parts[6]
                dest_y = parts[7]
                
                # Convert to float if numeric, otherwise keep as string
                try:
                    dest_x_val = float(dest_x) if dest_x not in ('playerx', '-1') else dest_x
                except ValueError:
                    dest_x_val = dest_x
                    
                try:
                    dest_y_val = float(dest_y) if dest_y not in ('playery', '-1') else dest_y
                except ValueError:
                    dest_y_val = dest_y
                
                link = LevelLink(
                    target_level=parts[1],
                    x=int(parts[2]),
                    y=int(parts[3]),
                    width=int(parts[4]),
                    height=int(parts[5]),
                    target_x=dest_x_val,
                    target_y=dest_y_val
                )
                self.links.append(link)
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Found link at ({link.x},{link.y}) -> {link.target_level} ({link.target_x},{link.target_y})")
            except ValueError as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to parse link: {line} - {e}")
                
    def _parse_sign(self, line: str):
        """Parse a SIGN line"""
        # Format: SIGN x y
        # Text follows on next lines
        parts = line.split()
        if len(parts) >= 3:
            try:
                sign = LevelSign(
                    x=int(parts[1]),
                    y=int(parts[2]),
                    text=""  # Will be filled from following lines
                )
                self.signs.append(sign)
            except ValueError:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to parse sign: {line}")
                
    def _parse_chest(self, line: str):
        """Parse a CHEST line"""
        # Format: CHEST x y item_id dir
        parts = line.split()
        if len(parts) >= 4:
            try:
                x = int(parts[1])
                y = int(parts[2])
                item_id = int(parts[3])
                self.chest_items[(x, y)] = item_id
            except ValueError:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to parse chest: {line}")


# Module-level function for compatibility
def parse_level_data(level_name: str, level_data: bytes) -> Optional[Dict]:
    """Parse level data from bytes (compatibility function)"""
    parser = LevelParser()
    return parser.parse(level_data)