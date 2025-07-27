"""
Level Manager for handling level data, tiles, and assets
"""

import os
import gzip
import zlib
import logging
import time
from typing import Dict, List, Optional, Tuple, Any, Callable
from ..models.level import Level, Sign, Chest, LevelLink, NPC, Baddy
from ..protocol.enums import ServerToPlayer
from ..parsers.gmap_parser import GmapParser

from ..utils.logging_config import ModuleLogger
logger = ModuleLogger.get_logger(__name__)


class LevelManager:
    """Manages level data, tiles, and asset requests"""
    
    def __init__(self, client):
        self.client = client
        self.current_level: Optional[Level] = None
        self.levels: Dict[str, Level] = {}  # Cache of loaded levels
        self.assets: Dict[str, bytes] = {}  # Downloaded assets
        self.pending_requests: Dict[str, List[Callable]] = {}  # File request callbacks
        
        # Asset cache directory (optional)
        self.cache_dir = None
        
        # Level file queue for requests
        self.requested_files = set()
        self.request_timestamps = {}  # Track when files were requested
        self.request_timeout = 30.0  # 30 second timeout for file requests
        self.last_request_time = 0
        self.request_rate_limit = 0.1  # Minimum time between requests (100ms)
        self.last_adjacent_request_time = 0
        # No cooldown - request files as fast as possible
        self.pending_file_requests = []  # Queue of files to request
        self.last_file_request_time = 0.0
        self.file_request_delay = 0.5  # 500ms between file requests for server compatibility to prevent disconnects
        self.max_concurrent_requests = 5  # Limit concurrent file requests
        self.active_requests = 0  # Track active file requests
        
        # Tile mapping for collision detection
        self.tile_mapping = None
        
        # Tileset management
        self.default_tileset = "pics1.png"
        self.current_tileset = self.default_tileset
        self.tileset_requested = False  # Track if we've requested the tileset
        
        # No longer need row-by-row board data collection
        # Board data now comes all at once via PLO_BOARDPACKET
        
        # GMAP tracking
        self.current_gmap = None  # Name of current gmap (e.g., "zlttp.gmap")
        self.is_on_gmap = False  # Whether we're on a gmap
        self.gmap_data = {}  # Dict of gmap_name -> GmapParser
        self.gmap_segments = set()  # Set of level names that are gmap segments
        self.last_level_entered = None  # Track last level to prevent duplicate adjacent requests
        self.adjacent_request_cooldown = 0.5  # 0.5 second cooldown between adjacent requests
        self.max_adjacent_requests = 8  # Max adjacent requests per cooldown period
        
        # Enhanced GMAP management
        self.gmap_width = 1
        self.gmap_height = 1
        self.level_adjacency = {}  # Dict[str, Dict[str, str]] - level_name -> {direction: adjacent_level}
        self.loaded_levels = set()  # Set[str] - track which levels have been loaded
        
        # Active level for packet processing (set by PLO_SETACTIVELEVEL)
        self.active_level_for_packets = None  # The level that incoming packets will modify
        
        # Transition tracking to avoid loops
        self.is_transitioning = False  # Track when we're in middle of edge transition
        self.transition_expected_level = None  # Expected level after transition
        self.transition_timeout = 0  # Timeout for transition completion
        
        # Pending adjacent request tracking
        self._pending_adjacent_request = False  # Flag to request adjacent levels when GMAP data loads
        
    def set_cache_directory(self, cache_dir: str):
        """Set directory for caching downloaded assets"""
        self.cache_dir = cache_dir
        if cache_dir and not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
    
    def start_edge_transition(self, expected_level: str = None):
        """Mark that we're starting an edge transition"""
        self.is_transitioning = True
        self.transition_expected_level = expected_level
        logger.info(f"Starting edge transition, expecting level: {expected_level}")
    
    def end_edge_transition(self):
        """Mark that edge transition is complete"""
        self.is_transitioning = False
        self.transition_expected_level = None
        self.transition_timeout = 0
        logger.info("Edge transition complete")
    
    def check_transition_timeout(self):
        """Check if transition has timed out and end it if necessary"""
        if self.is_transitioning and self.transition_timeout > 0:
            import time
            if time.time() > self.transition_timeout:
                logger.warning(f"Transition timed out after 2 seconds - ending transition")
                self.end_edge_transition()
                return True
        return False
    
    def has_level_data(self, level_name: str) -> bool:
        """Check if we have level data loaded"""
        # Check if we have the level file in assets
        if level_name.endswith('.nw'):
            return level_name in self.assets
        else:
            return f"{level_name}.nw" in self.assets
    
    def set_current_level(self, level_name: str):
        """Set the current level by name"""
        if level_name not in self.levels:
            self.levels[level_name] = Level(level_name)
            self.loaded_levels.add(level_name)
        
        old_level = self.current_level
        self.current_level = self.levels[level_name]
        self.current_level_name = level_name
        
        # Update player's level reference
        if self.client.local_player:
            self.client.local_player.level = level_name
            
            # Add player to new level
            self.current_level.add_player(self.client.local_player)
            
            # Remove from old level
            if old_level and self.client.local_player.id in old_level.players:
                old_level.remove_player(self.client.local_player.id)
        
        logger.info(f"Current level set to: {level_name}")
    
    def handle_player_warp(self, x: float, y: float, level_name: str):
        """Handle player warping to a new level"""
        logger.info(f"Warping to level: {level_name} at ({x}, {y})")
        
        # Create or get level
        if level_name not in self.levels:
            self.levels[level_name] = Level(level_name)
            self.loaded_levels.add(level_name)
        
        old_level = self.current_level
        self.current_level = self.levels[level_name]
        
        # Update player position in new level
        if self.client.local_player:
            self.client.local_player.x = x
            self.client.local_player.y = y
            self.client.local_player.level = level_name
            
            # Add player to level
            self.current_level.add_player(self.client.local_player)
            
            # Remove from old level
            if old_level and self.client.local_player.id in old_level.players:
                old_level.remove_player(self.client.local_player.id)
        
        # Request level file if we don't have it
        # Don't add .nw if it already has it
        if level_name.endswith('.nw'):
            level_file = level_name
        else:
            level_file = f"{level_name}.nw"
            
        if level_file not in self.assets and level_file not in self.requested_files:
            self.request_file(level_file)
        
        # Update session manager
        if hasattr(self.client, 'session'):
            self.client.session.enter_level(self.current_level)
        
        # Emit level change event
        if hasattr(self.client, 'events'):
            from ..core.events import EventType
            self.client.events.emit(EventType.LEVEL_ENTERED, level=self.current_level)
        
        # If we're on a GMAP and entered a new level, request adjacent levels
        # But only if GMAP mode is enabled
        if self.is_on_gmap and (not old_level or old_level.name != level_name):
            if hasattr(self.client, '_gmap_enabled') and not self.client._gmap_enabled:
                logger.info(f"Warped to new GMAP segment but GMAP mode disabled - not requesting adjacent levels")
            else:
                logger.info(f"Warped to new GMAP segment - requesting adjacent levels")
                self.request_adjacent_levels()
    
    def handle_level_name(self, name: str):
        """Handle level name packet - sets the current level (where the player is)"""
        # Check if this is a GMAP first
        if name.endswith('.gmap'):
            # Check if GMAP mode is disabled
            if hasattr(self.client, '_gmap_enabled') and not self.client._gmap_enabled:
                logger.info(f"Ignoring GMAP '{name}' - GMAP mode is disabled")
                # Don't process GMAP names when GMAP mode is disabled
                # The server will send the actual level name next
                return
                
            was_on_gmap = self.is_on_gmap
            self.current_gmap = name
            # Only set is_on_gmap if GMAP mode is enabled
            if hasattr(self.client, '_gmap_enabled') and self.client._gmap_enabled:
                self.is_on_gmap = True
            else:
                self.is_on_gmap = False
            logger.info(f"Entered GMAP: {name} (is_on_gmap={self.is_on_gmap})")
            
            # Extract GMAP name and check if we have the data
            gmap_name = name[:-5]  # Remove .gmap extension
            if gmap_name not in self.gmap_data:
                # Try to load from cache first (if cache is configured)
                cache_loaded = False
                if self.cache_dir:
                    import os
                    cache_path = os.path.join(self.cache_dir, name)
                    if os.path.exists(cache_path):
                        logger.info(f"[GMAP] Loading {name} from cache: {cache_path}")
                        try:
                            with open(cache_path, 'rb') as f:
                                gmap_data = f.read()
                            # Process the cached GMAP file
                            self.handle_file_data(name, gmap_data)
                            logger.info(f"[GMAP] Successfully loaded {name} from cache")
                            cache_loaded = True
                        except Exception as e:
                            logger.error(f"[GMAP] Failed to load from cache: {e}")
                    else:
                        logger.debug(f"[GMAP] No cache file found at: {cache_path}")
                else:
                    logger.debug(f"[GMAP] No cache directory configured")
                
                if not cache_loaded:
                    # Request the GMAP file from server
                    logger.info(f"[GMAP] Requesting GMAP file from server: {name}")
                    self.request_file(name)
            
            # When first entering a GMAP, we should request adjacent levels
            # but only after GMAP data is fully loaded
            if not was_on_gmap:
                logger.info(f"Entered GMAP - will request adjacent levels after GMAP data loads")
                # Mark that we need to request adjacent levels once GMAP is ready
                self._pending_adjacent_request = True
            
            # Don't change current_level for gmaps - they're not actual levels
            return
        
        # For actual levels (including gmap segments)
        # Create level if it doesn't exist
        if name not in self.levels:
            self.levels[name] = Level(name)
            self.loaded_levels.add(name)
            
            # Set up GMAP adjacency if this is a GMAP segment
            if self.is_on_gmap:
                self._setup_gmap_adjacency(name)
        
        # Check if we're leaving GMAP mode
        if self.is_on_gmap and self.current_gmap:
            # Check if this level is part of the current GMAP
            gmap_name = self.current_gmap.replace('.gmap', '')
            if gmap_name in self.gmap_data:
                gmap_parser = self.gmap_data[gmap_name]
                # Check if the level is in the GMAP segments
                is_in_gmap = False
                for row in range(gmap_parser.height):
                    for col in range(gmap_parser.width):
                        if gmap_parser.get_segment_at(col, row) == name:
                            is_in_gmap = True
                            break
                    if is_in_gmap:
                        break
                
                if not is_in_gmap:
                    # We're entering a level that's NOT part of the GMAP (e.g., a house)
                    logger.info(f"Leaving GMAP mode - entering non-GMAP level: {name}")
                    self.is_on_gmap = False
                    self.current_gmap = None
                    # Also notify the gmap_manager
                    if hasattr(self.client, 'gmap_manager'):
                        self.client.gmap_manager.exit_gmap()
        
        # Update current level (where the player is)
        # During transitions, only accept the expected level or unknown levels
        old_level = self.current_level
        should_update_level = True
        
        if self.is_transitioning and self.transition_expected_level:
            if name != self.transition_expected_level:
                logger.warning(f"Ignoring level change to '{name}' during transition (expecting '{self.transition_expected_level}')")
                should_update_level = False
        
        if should_update_level:
            self.current_level = self.levels[name]
        else:
            # Don't update current level, but continue processing for adjacency, etc.
            pass
        
        # If we're on a GMAP, this is a segment
        if self.is_on_gmap:
            self.gmap_segments.add(name)
            logger.info(f"Current level (GMAP segment): {name}")
            
            # Only request adjacent levels if this is actually a new level
            if self.last_level_entered != name:
                self.last_level_entered = name
                
                # Check if we're in a transition - if so, this is an acknowledgment
                if self.is_transitioning:
                    logger.info(f"Level change during transition - treating as acknowledgment")
                    
                    # Check if this matches our expected level
                    if self.transition_expected_level:
                        if name == self.transition_expected_level:
                            logger.info(f"Received expected level '{name}' - transition on track")
                            # Don't end transition immediately - wait for server to settle
                            # Set a shorter timeout since we got the expected level
                            import time
                            self.transition_timeout = time.time() + 1.0  # 1 second timeout
                        else:
                            logger.warning(f"Received '{name}' but expected '{self.transition_expected_level}' - server may be correcting our position")
                            # Set a longer timeout to see if server sends the correct level
                            import time
                            self.transition_timeout = time.time() + 2.0  # 2 second timeout
                    else:
                        # No expected level specified, assume any level change ends transition
                        logger.info(f"Transition without expected level - ending transition")
                        self.end_edge_transition()
                else:
                    # Check if we have GMAP data before requesting adjacent levels
                    gmap_name = self.current_gmap.replace('.gmap', '') if self.current_gmap else None
                    if gmap_name and gmap_name in self.gmap_data:
                        # We have GMAP data, request adjacent levels (if GMAP mode is enabled)
                        if hasattr(self.client, '_gmap_enabled') and not self.client._gmap_enabled:
                            logger.info(f"Entered new GMAP segment but GMAP mode disabled - not requesting adjacent levels")
                        else:
                            logger.info(f"Entered new GMAP segment - requesting adjacent levels")
                            self.request_adjacent_levels()
                    else:
                        logger.info(f"Entered new GMAP segment but no GMAP data yet - deferring adjacent requests")
        else:
            logger.info(f"Current level: {name}")
    
    def set_active_level_for_packets(self, name: str):
        """Set the active level for incoming packets (PLO_SETACTIVELEVEL)
        
        This is different from current_level - this determines which level
        will receive board updates, NPCs, items, signs, etc.
        """
        if name.endswith('.gmap'):
            # GMAPs aren't real levels, they're just metadata
            logger.info(f"Active level for packets: {name} (GMAP - no direct modifications)")
            self.active_level_for_packets = None
            return
            
        # Create level if it doesn't exist
        if name not in self.levels:
            self.levels[name] = Level(name)
            
        self.active_level_for_packets = self.levels[name]
        logger.info(f"Active level for packets: {name}")
    
    def handle_board_packet(self, board_data: bytes):
        """Handle full board data from PLO_BOARDPACKET (ID 101)"""
        # Use the active level for packets if set, otherwise use current level
        target_level = self.active_level_for_packets or self.current_level
        
        if not target_level:
            logger.warning("Received board packet but no active level!")
            return
        
        logger.info(f"Applying {len(board_data)} bytes of board data to level: {target_level.name}")
        
        # Apply the board data directly
        target_level.set_board_data(board_data)
        
        # Emit level board loaded event
        if hasattr(self.client, 'events'):
            from ..core.events import EventType
            self.client.events.emit(EventType.LEVEL_BOARD_LOADED, 
                                  level=target_level, 
                                  width=64, height=64)
    
    def handle_board_complete(self, level_name: str, width: int, height: int, tiles: List[int]):
        """Handle complete board data assembled from text rows"""
        # Find the target level
        target_level = self.levels.get(level_name)
        if not target_level:
            logger.warning(f"Received board data for unknown level: {level_name}")
            return
            
        logger.info(f"Applying {len(tiles)} tiles to level: {level_name} ({width}x{height})")
        
        # Convert tile list to board data bytes
        board_data = bytearray()
        for tile_id in tiles:
            # Each tile is 2 bytes in little-endian format
            board_data.extend(tile_id.to_bytes(2, 'little'))
            
        # Apply the board data
        target_level.set_board_data(bytes(board_data))
        
        # Emit level board loaded event
        if hasattr(self.client, 'events'):
            from ..core.events import EventType
            self.client.events.emit(EventType.LEVEL_BOARD_LOADED, 
                                  level=target_level, 
                                  width=width, height=height)
    
    
    def handle_level_board(self, data: bytes):
        """Handle level board data (tile data)"""
        if not self.current_level:
            logger.warning("Received level board data but no current level!")
            return
        
        try:
            # Parse level board format
            # Format varies but typically: [width][height][tile data...]
            if len(data) < 2:
                return
                
            width = data[0] - 32 if data[0] >= 32 else data[0]
            height = data[1] - 32 if data[1] >= 32 else data[1]
            
            # Sanity check
            if width <= 0 or height <= 0 or width > 1024 or height > 1024:
                logger.warning(f"Invalid level dimensions: {width}x{height}")
                return
            
            self.current_level.width = width
            self.current_level.height = height
            
            # Initialize tiles array
            self.current_level.tiles = [[0] * width for _ in range(height)]
            
            # Parse tile data
            pos = 2
            for y in range(height):
                for x in range(width):
                    if pos + 1 < len(data):
                        # Tiles are typically 2 bytes each
                        tile_low = data[pos] - 32 if data[pos] >= 32 else data[pos]
                        tile_high = data[pos + 1] - 32 if data[pos + 1] >= 32 else data[pos + 1]
                        tile = tile_low | (tile_high << 8)
                        self.current_level.tiles[y][x] = tile
                        pos += 2
                    else:
                        break
            
            logger.info(f"Loaded level board: {width}x{height} tiles")
            
            # Emit level board loaded event
            if hasattr(self.client, 'events'):
                from ..core.events import EventType
                self.client.events.emit(EventType.LEVEL_BOARD_LOADED, 
                                      level=self.current_level, 
                                      width=width, height=height)
            
        except Exception as e:
            logger.error(f"Error parsing level board: {e}")
    
    def handle_board_modify(self, x: int, y: int, width: int, height: int, tiles: List[int]):
        """Handle tile modification"""
        # Use the active level for packets if set, otherwise use current level
        target_level = self.active_level_for_packets or self.current_level
        if not target_level:
            return
        
        # Apply tile changes
        tile_idx = 0
        for dy in range(height):
            for dx in range(width):
                if tile_idx < len(tiles):
                    new_x = x + dx
                    new_y = y + dy
                    if (0 <= new_x < target_level.width and 
                        0 <= new_y < target_level.height):
                        target_level.set_tile(new_x, new_y, tiles[tile_idx])
                    tile_idx += 1
        
        logger.debug(f"Modified tiles at ({x}, {y}) size {width}x{height}")
        
        # Log to session manager
        if hasattr(self.client, 'session'):
            self.client.session.log_tile_update(target_level.name, x, y, width, height)
        
        # Emit tile update event
        if hasattr(self.client, 'events'):
            from ..core.events import EventType
            self.client.events.emit(EventType.TILES_UPDATED,
                                  level=target_level.name,
                                  x=x, y=y, width=width, height=height,
                                  tiles=tiles)
    
    def handle_level_sign(self, x: int, y: int, text: str):
        """Handle level sign"""
        # Use the active level for packets if set, otherwise use current level
        target_level = self.active_level_for_packets or self.current_level
        if not target_level:
            return
        
        sign = Sign(x, y, text)
        target_level.signs.append(sign)
        logger.debug(f"Added sign at ({x}, {y}): {text[:50]}...")
        
        # Log to session manager
        if hasattr(self.client, 'session'):
            self.client.session.log_level_object_added(
                target_level.name, "Sign", x, y, text
            )
        
        # Emit sign added event
        if hasattr(self.client, 'events'):
            from ..core.events import EventType
            self.client.events.emit(EventType.LEVEL_SIGN_ADDED, 
                                  level=target_level.name,
                                  sign=sign, x=x, y=y, text=text)
    
    def handle_level_chest(self, x: int, y: int, item: int, sign_text: str):
        """Handle level chest"""
        # Use the active level for packets if set, otherwise use current level
        target_level = self.active_level_for_packets or self.current_level
        if not target_level:
            return
        
        # Ensure chests is a list (defensive programming)
        if not hasattr(target_level, 'chests'):
            logger.warning(f"Level {target_level.name} missing chests attribute, creating empty list")
            target_level.chests = []
        elif not isinstance(target_level.chests, list):
            logger.warning(f"Level {target_level.name} has chests as {type(target_level.chests).__name__}, converting to list")
            # If it's a dict, try to preserve any existing data
            if isinstance(target_level.chests, dict):
                # Convert dict values to list if they look like chest objects
                existing_chests = []
                for key, value in target_level.chests.items():
                    if hasattr(value, 'x') and hasattr(value, 'y'):
                        existing_chests.append(value)
                target_level.chests = existing_chests
            else:
                target_level.chests = []
        
        chest = Chest(x, y, item, sign_text)
        target_level.chests.append(chest)
        logger.debug(f"Added chest at ({x}, {y}) with item {item}")
        
        # Log to session manager
        if hasattr(self.client, 'session'):
            self.client.session.log_level_object_added(
                target_level.name, "Chest", x, y, f"item {item}"
            )
        
        # Emit chest added event
        if hasattr(self.client, 'events'):
            from ..core.events import EventType
            self.client.events.emit(EventType.LEVEL_CHEST_ADDED,
                                  level=target_level.name,
                                  chest=chest, x=x, y=y, item=item, sign_text=sign_text)
    
    def handle_level_link(self, data):
        """Handle level link - updated to accept parsed data dict"""
        # Use the active level for packets if set, otherwise use current level
        target_level = self.active_level_for_packets or self.current_level
        if not target_level:
            return
        
        try:
            # Check if we got parsed data or raw bytes
            if isinstance(data, dict):
                # New parsed format
                x = data.get('x', 0)
                y = data.get('y', 0)
                width = data.get('width', 1)
                height = data.get('height', 1)
                dest_level = data.get('level_name', 'unknown')
                dest_x = data.get('new_x', 30.0)
                dest_y = data.get('new_y', 30.0)
            else:
                # Legacy raw bytes format
                if len(data) < 10:
                    return
                x = data[0] - 32 if data[0] >= 32 else data[0]
                y = data[1] - 32 if data[1] >= 32 else data[1]
                width = data[2] - 32 if data[2] >= 32 else data[2]
                height = data[3] - 32 if data[3] >= 32 else data[3]
                dest_level = "unknown"
                dest_x = 30.0
                dest_y = 30.0
            
            link = LevelLink(x, y, width, height, dest_level, dest_x, dest_y)
            target_level.links.append(link)
            logger.debug(f"Added level link at ({x}, {y}) size {width}x{height} -> {dest_level} at ({dest_x}, {dest_y})")
            
            # Log to session manager
            if hasattr(self.client, 'session'):
                self.client.session.log_level_object_added(
                    target_level.name, "Link", x, y, f"to {dest_level}"
                )
            
            # Emit link added event
            if hasattr(self.client, 'events'):
                from ..core.events import EventType
                self.client.events.emit(EventType.LEVEL_LINK_ADDED,
                                      level=target_level.name,
                                      link=link, x=x, y=y, width=width, height=height,
                                      dest_level=dest_level, dest_x=dest_x, dest_y=dest_y)
            
        except Exception as e:
            logger.error(f"Error parsing level link: {e}")
    
    def handle_file_data(self, filename: str, data: bytes):
        """Handle received file data"""
        logger.info(f"Received file: {filename} ({len(data)} bytes)")
        
        # Store in assets
        self.assets[filename] = data
        self.requested_files.discard(filename)
        self.request_timestamps.pop(filename, None)
        
        # Decrement active requests counter
        if self.active_requests > 0:
            self.active_requests -= 1
            logger.debug(f"File received, active requests now: {self.active_requests}")
        
        # Save to cache if enabled
        if self.cache_dir:
            cache_path = os.path.join(self.cache_dir, filename)
            try:
                with open(cache_path, 'wb') as f:
                    f.write(data)
                logger.debug(f"Cached file: {cache_path}")
            except Exception as e:
                logger.error(f"Failed to cache file: {e}")
        
        # Process GMAP files
        if filename.endswith('.gmap'):
            gmap_name = filename[:-5]  # Remove .gmap extension
            
            # Check if we already have this GMAP data
            if gmap_name in self.gmap_data:
                logger.info(f"[GMAP] Already have {filename} data, skipping re-parse")
                return
                
            logger.info(f"[GMAP] Received GMAP file: {filename} ({len(data)} bytes)")
            parser = GmapParser()
            if parser.parse(data):
                self.gmap_data[gmap_name] = parser
                self.gmap_width = parser.width
                self.gmap_height = parser.height
                logger.info(f"[GMAP] Parsed {gmap_name}: {parser.width}x{parser.height} grid, {len(parser.segments)} segments")
                
                # Also load into GMap manager for consistency
                logger.debug(f"[GMAP] Checking sync to GMap manager: hasattr(self,'client')={hasattr(self, 'client')}, hasattr(client,'gmap_manager')={hasattr(self.client, 'gmap_manager') if hasattr(self, 'client') else 'NO CLIENT'}")
                if hasattr(self, 'client') and hasattr(self.client, 'gmap_manager'):
                    logger.debug(f"[GMAP] Calling gmap_manager.handle_gmap_file({filename}, {len(data)} bytes)")
                    self.client.gmap_manager.handle_gmap_file(filename, data)
                    logger.info(f"[GMAP] Synced GMAP data to GMap manager")
                else:
                    logger.warning(f"[GMAP] Cannot sync to GMap manager - client or gmap_manager not available")
                
                # Check if GMAP specifies a tileset
                if parser.tileset:
                    logger.info(f"[GMAP] Tileset specified: {parser.tileset}")
                    self.set_tileset(parser.tileset)
                else:
                    logger.info(f"[GMAP] No tileset specified, using default: {self.default_tileset}")
                    self.set_tileset(self.default_tileset)
                
                # Log ALL segments for debugging
                if parser.segments:
                    logger.info(f"[GMAP] ALL segments ({len(parser.segments)} total):")
                    for i, seg in enumerate(parser.segments):
                        x = i % parser.width
                        y = i // parser.width
                        logger.info(f"[GMAP]   Position ({x},{y}): {seg}")
                
                # Mark all segments as GMAP segments
                for segment in parser.segments:
                    self.gmap_segments.add(segment)
                
                # Set up adjacency for already loaded levels
                for level_name in list(self.loaded_levels):
                    if level_name in parser.segments:
                        self._setup_gmap_adjacency(level_name)
                
                # If this is our current GMAP, we can now request adjacent segments
                if self.current_gmap == filename:
                    logger.info(f"Current GMAP data loaded, can now determine adjacent segments")
                    # Emit event for GMAP data loaded
                    if hasattr(self.client, 'events'):
                        from ..core.events import EventType
                        self.client.events.emit(EventType.GMAP_DATA_LOADED, {
                            'gmap_name': gmap_name,
                            'parser': parser
                        })
                    
                    # Check if we have a pending adjacent request
                    if hasattr(self, '_pending_adjacent_request') and self._pending_adjacent_request:
                        logger.info(f"GMAP data loaded - processing pending adjacent request")
                        self._pending_adjacent_request = False  # Clear the flag
                        if hasattr(self.client, '_gmap_enabled') and not self.client._gmap_enabled:
                            logger.info(f"GMAP data loaded but GMAP mode disabled - not requesting adjacent levels")
                        else:
                            logger.info(f"GMAP data loaded, requesting adjacent levels for pending request")
                            self.request_adjacent_levels()
                    
                    # GMAP data is now available - request adjacent levels if we have a current level
                    elif self.current_level and self.is_on_gmap:
                        logger.info(f"GMAP data loaded - checking if adjacent levels needed")
                        if hasattr(self.client, '_gmap_enabled') and not self.client._gmap_enabled:
                            logger.info(f"GMAP data loaded but GMAP mode disabled - not requesting adjacent levels")
                        else:
                            logger.info(f"GMAP data loaded, requesting adjacent levels for current segment")
                            self.request_adjacent_levels()
        
        # Process level files
        if filename.endswith('.nw'):
            # For GMAP chunks, the file often just contains the header
            # Board data comes separately via BOARD text packets or PLO_BOARDPACKET
            if len(data) == 9 and data.startswith(b'GLEVNW01'):
                logger.debug(f"GMAP chunk file (header only): {filename}")
                
                # Keep the full filename as level name (including .nw extension)
                level_name = filename
                
                # Create level if it doesn't exist
                if level_name not in self.levels:
                    self.levels[level_name] = Level(level_name)
                
                # Mark as GMAP segment
                if self.is_on_gmap:
                    self.gmap_segments.add(level_name)
                
                # Set this level as active for board packets
                old_active = self.active_level_for_packets
                self.active_level_for_packets = self.levels[level_name]
                logger.debug(f"Set active level for board data: {level_name}")
                
                # Board data will come via separate packets
                # Note: We restore active level after a short delay or when next file arrives
                
            elif len(data) > 9 and data.startswith(b'GLEVNW01'):
                logger.debug(f"Processing GLEVNW01 file: {filename}")
                
                # Keep the full filename as level name (including .nw extension)
                level_name = filename
                
                # Create level if it doesn't exist
                if level_name not in self.levels:
                    self.levels[level_name] = Level(level_name)
                
                # Mark as GMAP segment
                if self.is_on_gmap:
                    self.gmap_segments.add(level_name)
                
                # Parse using level parser (handles GLEVNW01 text format)
                from pyreborn.parsers.level_parser import LevelParser
                parser = LevelParser()
                try:
                    parsed_data = parser.parse(data)
                    
                    # Apply parsed data to the level
                    level = self.levels[level_name]
                    if 'board_data' in parsed_data and parsed_data['board_data']:
                        level.set_board_data(parsed_data['board_data'])
                        logger.debug(f"   Applied board data from GLEVNW01 file")
                        
                        # Emit board loaded event
                        if hasattr(self.client, 'events'):
                            from ..core.events import EventType
                            self.client.events.emit(EventType.LEVEL_BOARD_LOADED,
                                                  level=level,
                                                  width=64, height=64)
                    
                    # Apply other parsed data (links, npcs, signs, etc.)
                    if 'links' in parsed_data:
                        level.links = parsed_data['links']
                    if 'npcs' in parsed_data:
                        level.npcs = parsed_data['npcs']
                    if 'signs' in parsed_data:
                        level.signs = parsed_data['signs']
                        
                except Exception as e:
                    logger.error(f"   Error parsing GLEVNW01 file: {e}")
            else:
                # Regular level file parsing
                self.parse_level_file(filename, data)
        
        # Execute callbacks for this file
        if filename in self.pending_requests:
            for callback in self.pending_requests[filename]:
                try:
                    callback(filename, data)
                except Exception as e:
                    logger.error(f"Error in file callback: {e}")
            del self.pending_requests[filename]
    
    def _process_level_packet_stream(self, data: bytes, level_name: str):
        """Process packet stream from level file data"""
        try:
            pos = 0
            while pos < len(data):
                # Check for PLO_RAWDATA (ID 100)
                if pos + 4 <= len(data) and data[pos] == 132:  # 100 + 32
                    logger.debug(f"   Found PLO_RAWDATA at position {pos}")
                    
                    # Read the announced size (3 bytes, GINT3 encoded)
                    size_bytes = data[pos+1:pos+4]
                    size = (size_bytes[0] - 32) | ((size_bytes[1] - 32) << 6) | ((size_bytes[2] - 32) << 12)
                    logger.debug(f"      Announced size: {size} bytes")
                    
                    # Skip PLO_RAWDATA header and newline
                    pos += 4
                    if pos < len(data) and data[pos] == ord('\n'):
                        pos += 1
                    
                    # Check for PLO_BOARDPACKET to confirm board data
                    if size == 8194 and pos < len(data) and data[pos] == 133:  # 101 + 32
                        logger.debug(f"   Found PLO_BOARDPACKET at position {pos}")
                        
                        # Skip PLO_BOARDPACKET header and newline
                        pos += 1
                        newline_pos = data.find(b'\n', pos)
                        if newline_pos >= 0:
                            pos = newline_pos + 1
                        
                        # Read the board data (8192 bytes)
                        if pos + 8192 <= len(data):
                            board_data = data[pos:pos+8192]
                            logger.debug(f"   Got complete board data: {len(board_data)} bytes")
                            
                            # Apply board data to the level
                            if level_name in self.levels:
                                self.levels[level_name].set_board_data(board_data)
                                
                                # Emit event
                                if hasattr(self.client, 'events'):
                                    from ..core.events import EventType
                                    self.client.events.emit(EventType.LEVEL_BOARD_LOADED, 
                                                          level=self.levels[level_name], 
                                                          width=64, height=64)
                            
                            pos += 8192
                        else:
                            logger.warning(f"   Not enough data for board (need 8192, have {len(data) - pos})")
                            break
                    else:
                        # Skip the announced data
                        pos += size
                else:
                    # Skip unknown packet
                    pos += 1
                    
        except Exception as e:
            logger.error(f"   Error processing level packet stream: {e}")
    
    def parse_level_file(self, filename: str, data: bytes):
        """Parse a .nw level file"""
        try:
            # Level files can be compressed
            level_data = data
            
            # Try to decompress if it looks compressed
            if data.startswith(b'\\x1f\\x8b'):  # gzip magic
                level_data = gzip.decompress(data)
            elif data.startswith(b'BZ'):  # bzip2 magic
                import bz2
                level_data = bz2.decompress(data)
            
            # Parse level file format
            level_name = filename[:-3]  # Remove .nw extension
            if level_name not in self.levels:
                self.levels[level_name] = Level(level_name)
            
            level = self.levels[level_name]
            
            # Basic parsing - level file format is complex
            # This is a simplified version
            pos = 0
            if len(level_data) > 8:
                # Level files typically start with header
                # Format varies significantly between versions
                logger.debug(f"Parsing level file: {filename}")
                
                # Try to extract basic info
                if level_data[0:4] == b'GRLV':  # Reborn level magic
                    # Version info would be next
                    pos = 8
                
                # Would parse tiles, objects, NPCs, etc. here
                # This is very complex and version-dependent
                
            level.mod_time = os.path.getmtime(filename) if os.path.exists(filename) else 0
            logger.debug(f"Parsed level file: {level_name}")
            
        except Exception as e:
            logger.error(f"Error parsing level file {filename}: {e}")
    
    def request_file(self, filename: str, callback: Optional[Callable] = None):
        """Request a file from the server"""
        # Check if already loaded as a level (with actual data)
        if filename in self.loaded_levels:
            logger.info(f"File already loaded as level, skipping: {filename}")
            if callback:
                # Call callback immediately with existing data
                level = self.levels[filename]
                if hasattr(level, 'board_data') and level.board_data:
                    # Simulate file data from level
                    callback(filename, b'')  # Empty data since it's already loaded
            return
            
        if filename in self.requested_files:
            # Check if request has timed out
            current_time = time.time()
            if filename in self.request_timestamps:
                time_since_request = current_time - self.request_timestamps[filename]
                if time_since_request > self.request_timeout:
                    logger.warning(f"File request for {filename} timed out after {time_since_request:.1f}s, re-requesting")
                    self.requested_files.discard(filename)
                    self.request_timestamps.pop(filename, None)
                else:
                    # Already requested and not timed out, just add callback
                    logger.info(f"File already requested {time_since_request:.1f}s ago, skipping duplicate: {filename}")
                    if callback:
                        if filename not in self.pending_requests:
                            self.pending_requests[filename] = []
                        self.pending_requests[filename].append(callback)
                    return
            else:
                # Already requested but no timestamp, just add callback
                logger.info(f"File already requested, skipping duplicate: {filename}")
                if callback:
                    if filename not in self.pending_requests:
                        self.pending_requests[filename] = []
                    self.pending_requests[filename].append(callback)
                return
        
        # No rate limiting - request files as fast as possible
        
        # Check cache first
        if self.cache_dir:
            cache_path = os.path.join(self.cache_dir, filename)
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, 'rb') as f:
                        data = f.read()
                    logger.debug(f"Loaded from cache: {filename}")
                    # Process cached file through normal pipeline
                    self.handle_file_data(filename, data)
                    if callback:
                        callback(filename, data)
                    return
                except Exception as e:
                    logger.error(f"Failed to load from cache: {e}")
        
        # Add callback
        if callback:
            if filename not in self.pending_requests:
                self.pending_requests[filename] = []
            self.pending_requests[filename].append(callback)
        
        # No queueing - send requests immediately
        
        # Send request to server
        from ..protocol.packets import WantFilePacket
        packet = WantFilePacket(filename)
        self.client.queue_packet(packet.to_bytes())
        self.requested_files.add(filename)
        self.request_timestamps[filename] = time.time()
        self.last_request_time = time.time()
        self.last_file_request_time = time.time()
        self.active_requests += 1
        logger.debug(f"Requested file: {filename} (active requests: {self.active_requests})")
    
    def get_current_level(self) -> Optional[Level]:
        """Get the current level"""
        return self.current_level
    
    def get_level(self, name: str) -> Optional[Level]:
        """Get a level by name"""
        return self.levels.get(name)
        
    def get_or_create_level(self, name: str) -> Level:
        """Get or create a level by name"""
        if name not in self.levels:
            self.levels[name] = Level(name)
        return self.levels[name]
    
    def get_tile(self, x: int, y: int, layer: int = 0) -> int:
        """Get tile at position in current level"""
        if self.current_level:
            return self.current_level.get_tile(x, y, layer)
        return 0
    
    def is_position_blocked(self, x: float, y: float) -> bool:
        """Check if a position is blocked by tiles"""
        if not self.current_level:
            return False
        
        # Get tile at position
        tile_x = int(x)
        tile_y = int(y)
        tile = self.get_tile(tile_x, tile_y)
        
        # Basic blocking logic - would need tile attribute data
        # Tiles 0-15 are typically passable, others may block
        return tile > 15  # Simplified logic
    
    def find_level_links_at(self, x: float, y: float) -> List[LevelLink]:
        """Find level links at a position"""
        if not self.current_level:
            return []
        
        links = []
        for link in self.current_level.links:
            if link.contains(x, y):
                links.append(link)
        return links
    
    def _delayed_initial_adjacent_request(self):
        """Handle delayed adjacent level request when first entering GMAP"""
        # Check if GMAP mode is disabled on the client
        if hasattr(self.client, '_gmap_enabled') and not self.client._gmap_enabled:
            logger.debug("GMAP mode disabled - not making initial adjacent request")
            return
            
        if self.is_on_gmap and self.current_level:
            logger.info(f"Initial GMAP adjacent request for: {self.current_level.name}")
            # Bypass the cooldown check for the initial request
            old_last_time = self.last_adjacent_request_time
            self.last_adjacent_request_time = 0  # Reset to allow immediate request
            self.request_adjacent_levels()
            # Don't restore the old time - let the new request set it
        else:
            logger.debug("No longer on GMAP or no current level for delayed request")
    
    def request_adjacent_levels(self):
        """Request adjacent level data when on a GMAP"""
        # Check if GMAP mode is disabled on the client
        if hasattr(self.client, '_gmap_enabled') and not self.client._gmap_enabled:
            logger.debug("GMAP mode disabled - not requesting adjacent levels")
            return
            
        if not self.is_on_gmap or not self.current_level:
            return
        
        # Don't request new levels if we still have pending requests to avoid race conditions
        if self.active_requests > 0:
            logger.debug(f"Skipping adjacent level request - {self.active_requests} requests still pending")
            return
            
        # Don't request if we have pending queued requests either
        if self.pending_file_requests:
            logger.debug(f"Skipping adjacent level request - {len(self.pending_file_requests)} requests still queued")
            return
        
        logger.info(f"Requesting adjacent levels for GMAP segment: {self.current_level.name}")
        
        # First check if we have GMAP data to determine adjacent segments
        level_name = self.current_level.name
        gmap_name = None
        gmap_parser = None
        
        # Use the current GMAP name if we have one
        if self.current_gmap and self.current_gmap.endswith('.gmap'):
            gmap_name = self.current_gmap[:-5]  # Remove .gmap extension
            gmap_parser = self.gmap_data.get(gmap_name)
            logger.info(f"Using current GMAP: {gmap_name}, has parser: {gmap_parser is not None}")
        
        if gmap_parser and gmap_parser.segments:
            # We have GMAP data! Use it to determine adjacent segments
            logger.info(f"Using GMAP data for {gmap_name} to determine adjacent segments")
            logger.info(f"GMAP dimensions: {gmap_parser.width}x{gmap_parser.height}")
            logger.info(f"Current level: {level_name}")
            
            # Find current segment position in the GMAP
            x, y = None, None
            
            # First try to find the segment in the GMAP data
            if level_name in gmap_parser.segments:
                index = gmap_parser.segments.index(level_name)
                # Calculate x,y from index (segments are stored in row-major order)
                x = index % gmap_parser.width
                y = index // gmap_parser.width
                logger.info(f"Found {level_name} at position ({x}, {y}) in GMAP")
                
                # Update player's GMAP coordinates using actual GMAP file position
                # BUT NOT during transitions - let the transition logic handle coordinates
                if (hasattr(self, 'client') and self.client and hasattr(self.client, 'local_player') and 
                    self.client.local_player and not self.is_transitioning):
                    old_x = getattr(self.client.local_player, 'gmaplevelx', None)
                    old_y = getattr(self.client.local_player, 'gmaplevely', None)
                    self.client.local_player.gmaplevelx = x
                    self.client.local_player.gmaplevely = y
                    
                    # Update world coordinates using GMAP file position
                    if hasattr(self.client.local_player, '_x') and hasattr(self.client.local_player, '_y'):
                        self.client.local_player._x2 = x * 64 + self.client.local_player._x
                        self.client.local_player._y2 = y * 64 + self.client.local_player._y
                        logger.info(f"Updated player GMAP position: ({old_x}, {old_y}) -> ({x}, {y})")
                        logger.info(f"Updated world coordinates: ({self.client.local_player._x2}, {self.client.local_player._y2})")
                    
                    # Don't send GMAP coordinates here - this is called when the server
                    # tells us we're in a different level, not when we actually move.
                    # Sending coordinates here causes the server to bounce us between levels.
                    # GMAP coordinates should only be sent when the player actually moves.
                    if old_x != x or old_y != y:
                        logger.info(f"GMAP position changed from ({old_x}, {old_y}) to ({x}, {y}) but NOT sending to server")
                        logger.info(f"Coordinates should only be sent during actual player movement")
            else:
                # Try parsing from level name if it has coordinates
                if '-' in level_name:
                    parts = level_name.split('-')
                    if len(parts) >= 2:
                        seg_part = parts[1].replace('.nw', '')
                        x, y = self._parse_segment_coords(seg_part)
                
            if x is not None and y is not None:
                # Get adjacent segments from GMAP data
                adjacent = gmap_parser.get_adjacent_segments(x, y)
                logger.info(f"Current segment at ({x}, {y}), found {len(adjacent)} adjacent segments")
                
                # Request adjacent segments with limits to prevent spam
                request_count = 0
                for direction, segment_name in adjacent.items():
                    if request_count >= self.max_adjacent_requests:
                        logger.info(f"   Reached max adjacent requests ({self.max_adjacent_requests}), stopping")
                        break
                        
                    # Check if level is actually loaded (not just an empty entry)
                    if segment_name not in self.loaded_levels:
                        # Also check if already requested to avoid duplicate requests
                        if segment_name in self.requested_files:
                            logger.debug(f"   {direction}: {segment_name} (already requested)")
                            continue
                            
                        logger.info(f"   Requesting {direction}: {segment_name}")
                        self.request_file(segment_name)
                        request_count += 1
                    else:
                        logger.debug(f"   {direction}: {segment_name} (already loaded)")
                
                return
            else:
                logger.warning(f"Could not determine position of {level_name} in GMAP")
        
        # Fallback to old parsing method if no GMAP data
        logger.info(f"No GMAP data available, using fallback method")
        
        # Parse current segment position from level name (e.g., zlttp-d8.nw)
        if '-' not in level_name:
            logger.warning(f"   Cannot parse segment position from: {level_name}")
            return
            
        try:
            # Extract base name and segment code
            base_name = level_name.split('-')[0]  # zlttp
            segment_code = level_name.split('-')[1].replace('.nw', '')  # d8
            
            if len(segment_code) >= 2:
                col_char = segment_code[0]  # d
                row_str = segment_code[1:]  # 8
                
                # Convert column letter to number (a=0, b=1, c=2, etc.)
                col_num = ord(col_char.lower()) - ord('a')
                row_num = int(row_str)
                
                logger.debug(f"   Current segment: column {col_char}({col_num}), row {row_num}")
                
                # Request all 8 adjacent segments immediately
                
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        if dx == 0 and dy == 0:
                            continue  # Skip current segment
                            
                        new_col = col_num + dx
                        new_row = row_num + dy
                        
                        # Skip invalid positions - check bounds based on GMAP data if available
                        # Get GMAP dimensions if we have them
                        max_col = 9  # Default to 10x10
                        max_row = 9
                        
                        # Try to get actual dimensions from GMAP data
                        if base_name in self.gmap_data:
                            gmap_parser = self.gmap_data[base_name]
                            max_col = gmap_parser.width - 1
                            max_row = gmap_parser.height - 1
                        
                        if new_col < 0 or new_row < 0 or new_col > max_col or new_row > max_row:
                            continue
                            
                        # Convert back to letter
                        new_col_char = chr(ord('a') + new_col)
                        segment_name = f"{base_name}-{new_col_char}{new_row}.nw"
                        
                        # Request the file if we haven't already
                        if segment_name not in self.levels and segment_name not in self.assets and segment_name not in self.requested_files:
                            logger.info(f"   Requesting adjacent segment: {segment_name}")
                            self.request_file(segment_name)
                
        except Exception as e:
            logger.error(f"   Error parsing segment position: {e}")
    
    def set_tileset(self, tileset_name: str):
        """Set the current tileset and request it if needed
        
        Args:
            tileset_name: Name of the tileset file (e.g., 'pics1.png')
        """
        if tileset_name != self.current_tileset:
            logger.info(f"Changing tileset from {self.current_tileset} to {tileset_name}")
            self.current_tileset = tileset_name
            self.tileset_requested = False
        
        # Only request non-default tilesets (default is bundled with client)
        if (tileset_name != self.default_tileset and 
            tileset_name not in self.assets and 
            tileset_name not in self.requested_files and 
            not self.tileset_requested):
            logger.info(f"Requesting custom tileset: {tileset_name}")
            self.request_file(tileset_name)
            self.tileset_requested = True
    
    def load_tile_mapping(self, tileset_dir: str) -> bool:
        """Load tile mapping for collision detection"""
        try:
            from .tile_mapping import load_reborn_tiles
            self.tile_mapping = load_reborn_tiles(tileset_dir)
            if self.tile_mapping:
                logger.info(f"Loaded tile mapping from: {tileset_dir}")
                return True
            else:
                logger.error(f"Failed to load tile mapping")
                return False
        except Exception as e:
            logger.error(f"Error loading tile mapping: {e}")
            return False
    
    def update(self):
        """Periodic update to handle delayed requests"""
        # Process any pending file requests immediately
        if self.pending_file_requests:
            while self.pending_file_requests and self.active_requests < self.max_concurrent_requests:
                # Process next pending request
                filename, callback = self.pending_file_requests.pop(0)
                logger.debug(f"Processing pending file request: {filename}")
                
                # Send request directly
                from ..protocol.packets import WantFilePacket
                packet = WantFilePacket(filename)
                self.client.queue_packet(packet.to_bytes())
                self.requested_files.add(filename)
                self.request_timestamps[filename] = time.time()
                self.last_request_time = time.time()
                self.last_file_request_time = time.time()
                self.active_requests += 1
                logger.debug(f"Sent queued file request: {filename} (active requests: {self.active_requests})")
    
    
    def _parse_segment_coords(self, seg_part: str) -> Tuple[Optional[int], Optional[int]]:
        """Parse segment coordinates from segment part (e.g., 'd8' -> (3, 8))"""
        if not seg_part:
            return None, None
            
        # Column letter format (e.g., d8)
        if seg_part[0].isalpha():
            col_letter = seg_part[0]
            row_str = seg_part[1:]
            
            if row_str.isdigit():
                x = ord(col_letter) - ord('a')  # a=0, b=1, c=2, d=3, etc.
                y = int(row_str)
                return x, y
        
        # Numeric format (e.g., 03-08)
        elif '-' in seg_part:
            parts = seg_part.split('-')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return int(parts[0]), int(parts[1])
        
        return None, None
    
    def is_position_blocked_by_tiles(self, x: float, y: float) -> bool:
        """Check if position is blocked using tile mapping data"""
        if not self.current_level or not self.tile_mapping:
            return self.is_position_blocked(x, y)  # Fallback to basic logic
        
        # Get tile at position
        tile_x = int(x)
        tile_y = int(y)
        
        if (0 <= tile_x < self.current_level.width and 
            0 <= tile_y < self.current_level.height and
            self.current_level.tiles):
            
            tile_id = self.current_level.tiles[tile_y][tile_x]
            if isinstance(tile_id, int):
                # Convert numeric tile ID to string format if needed
                tile_id = self._convert_numeric_to_tile_id(tile_id)
            
            # Check with tile mapping
            return self.tile_mapping.is_tile_blocking(str(tile_id))
        
        return False
    
    def _process_request_queue(self):
        """Process file request queue with rate limiting"""
        from ..protocol.packets import WantFilePacket
        
        while True:
            try:
                if self.request_queue and hasattr(self, 'client') and self.client:
                    # Check rate limit
                    current_time = time.time()
                    time_since_last = current_time - self.last_request_time
                    if time_since_last < self.request_rate_limit:
                        time.sleep(self.request_rate_limit - time_since_last)
                    
                    # Process next request
                    filename = self.request_queue.pop(0)
                    packet = WantFilePacket(filename)
                    self.client.queue_packet(packet.to_bytes())
                    self.requested_files.add(filename)
                    self.last_request_time = time.time()
                    logger.debug(f"Sent file request: {filename} (queue remaining: {len(self.request_queue)})")
                else:
                    # No requests, sleep briefly
                    time.sleep(0.1)
            except Exception as e:
                logger.error(f"Error in request queue processor: {e}")
                time.sleep(1)
    
    def analyze_current_level_tiles(self) -> Dict[str, Any]:
        """Analyze tiles in current level"""
        if not self.current_level or not self.current_level.tiles or not self.tile_mapping:
            return {"error": "No level data or tile mapping"}
        
        # Convert tiles to string format if needed
        tile_array = []
        for row in self.current_level.tiles:
            string_row = []
            for tile in row:
                if isinstance(tile, int):
                    tile_id = self._convert_numeric_to_tile_id(tile)
                    string_row.append(tile_id)
                else:
                    string_row.append(str(tile))
            tile_array.append(string_row)
        
        # Use tile mapping to analyze
        analysis = self.tile_mapping.analyze_tiles(tile_array)
        analysis["level_name"] = self.current_level.name
        
        return analysis
    
    def _convert_numeric_to_tile_id(self, tile_num: int) -> str:
        """Convert numeric tile ID to 2-character string format"""
        # This is a simplified conversion - the real Reborn encoding is more complex
        # For now, use a basic mapping
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        if tile_num < len(chars) * len(chars):
            first_char = chars[tile_num // len(chars)]
            second_char = chars[tile_num % len(chars)]
            return first_char + second_char
        return "AA"  # Default fallback
    
    def get_level_summary(self) -> Dict[str, Any]:
        """Get summary of level manager state"""
        summary = {
            "current_level": self.current_level.name if self.current_level else None,
            "loaded_levels": len(self.levels),
            "cached_assets": len(self.assets),
            "pending_requests": len(self.pending_requests),
            "tile_mapping_loaded": self.tile_mapping is not None,
            "level_details": {
                name: {
                    "size": f"{level.width}x{level.height}",
                    "players": len(level.players),
                    "npcs": len(level.npcs),
                    "signs": len(level.signs),
                    "chests": len(level.chests),
                    "links": len(level.links)
                }
                for name, level in self.levels.items()
            }
        }
        
        # Add tile mapping info if available
        if self.tile_mapping:
            summary["tile_mapping_tiles"] = len(self.tile_mapping.tiles)
        
        return summary
    
    # GMAP and Level Data Access Methods (for client/bot developers)
    
    def is_gmap_level(self, level_name: str) -> bool:
        """Check if a level name indicates a gmap segment or gmap file"""
        # Check for .gmap files
        if level_name.endswith('.gmap'):
            return True
        
        # Check if we have connection GMAP data
        if self.gmap_data:
            # Look through all GMAP data to see if this level name is in any segments
            for gmap_key, gmap_parser in self.gmap_data.items():
                if level_name in gmap_parser.segments:
                    return True
        
        # Fallback to naming conventions for backwards compatibility
        return ('-' in level_name and level_name.count('-') == 1 and level_name.endswith('.nw'))
    
    def parse_segment_name(self, level_name: str) -> Optional[Tuple[str, int, int]]:
        """Parse a segment name like 'world-a0.nw' or 'world_01-02.nw' -> ('world', x, y)
        
        This method looks up the actual position in the GMAP data rather than
        making assumptions about naming conventions.
        """
        # Try to find this level in our GMAP data
        for gmap_name, gmap_parser in self.gmap_data.items():
            # Search through all segments in this GMAP
            for y in range(gmap_parser.height):
                for x in range(gmap_parser.width):
                    segment = gmap_parser.get_segment_at(x, y)
                    if segment == level_name:
                        return (gmap_name, x, y)
        
        # Not found in any GMAP
        return None
    
    def get_segment_name(self, base_name: str, seg_x: int, seg_y: int) -> str:
        """Build a segment name from gmap name and coordinates
        
        This method looks up the actual segment name from GMAP data.
        """
        # Look up in GMAP data
        gmap_parser = self.gmap_data.get(base_name)
        if gmap_parser:
            segment = gmap_parser.get_segment_at(seg_x, seg_y)
            if segment:
                return segment
        
        # Fallback - this shouldn't happen if GMAP data is loaded
        return f"{base_name}-unknown{seg_x}-{seg_y}.nw"
    
    def _setup_gmap_adjacency(self, level_name: str):
        """Set up adjacency relationships for a GMAP level"""
        segment_info = self.parse_segment_name(level_name)
        if not segment_info:
            return
            
        base_name, x, y = segment_info
        
        # Initialize adjacency entry for this level
        if level_name not in self.level_adjacency:
            self.level_adjacency[level_name] = {}
        
        # Get GMAP parser if available
        gmap_parser = self.gmap_data.get(base_name)
        if gmap_parser:
            # Use GMAP data to determine adjacent segments
            adjacent = gmap_parser.get_adjacent_segments(x, y)
            for direction, segment_name in adjacent.items():
                self.level_adjacency[level_name][direction] = segment_name
                
                # Set up reverse adjacency if the adjacent level is already loaded
                if segment_name in self.loaded_levels:
                    if segment_name not in self.level_adjacency:
                        self.level_adjacency[segment_name] = {}
                    reverse_direction = self._get_reverse_direction(direction)
                    self.level_adjacency[segment_name][reverse_direction] = level_name
        else:
            # Fallback to coordinate-based adjacency
            directions = {
                'north': (x, y - 1),
                'south': (x, y + 1),
                'east': (x + 1, y),
                'west': (x - 1, y),
                'northeast': (x + 1, y - 1),
                'northwest': (x - 1, y - 1),
                'southeast': (x + 1, y + 1),
                'southwest': (x - 1, y + 1)
            }
            
            for direction, (adj_x, adj_y) in directions.items():
                if adj_x >= 0 and adj_y >= 0:  # Only valid coordinates
                    adj_name = self.get_segment_name(base_name, adj_x, adj_y)
                    self.level_adjacency[level_name][direction] = adj_name
    
    def _get_reverse_direction(self, direction: str) -> str:
        """Get the reverse direction"""
        reverse_map = {
            'north': 'south',
            'south': 'north',
            'east': 'west',
            'west': 'east',
            'northeast': 'southwest',
            'southwest': 'northeast',
            'northwest': 'southeast',
            'southeast': 'northwest'
        }
        return reverse_map.get(direction, direction)
    
    def get_adjacent_level(self, level_name: str, direction: str) -> Optional[str]:
        """Get the adjacent level in a specific direction"""
        return self.level_adjacency.get(level_name, {}).get(direction)
    
    def get_adjacent_segments(self, level_name: str) -> Dict[str, str]:
        """Get all adjacent segments for a level"""
        return self.level_adjacency.get(level_name, {}).copy()
    
    def get_gmap_info(self) -> Dict:
        """Get current gmap information for display"""
        if not self.current_gmap:
            return {}
            
        gmap_name = self.current_gmap.replace('.gmap', '') if self.current_gmap.endswith('.gmap') else self.current_gmap
        gmap_parser = self.gmap_data.get(gmap_name)
        
        return {
            'gmap_name': gmap_name,
            'gmap_width': gmap_parser.width if gmap_parser else self.gmap_width,
            'gmap_height': gmap_parser.height if gmap_parser else self.gmap_height,
            'current_level': self.current_level.name if self.current_level else None,
            'requested_count': len(self.requested_files),
            'loaded_count': len(self.loaded_levels),
            'total_segments': len(gmap_parser.segments) if gmap_parser else 0
        }
        
    def get_gmap_position_for_level(self, level_name: str) -> Optional[Tuple[int, int]]:
        """Get GMAP grid position for a level
        
        Returns (x, y) tuple if found in current GMAP, None otherwise
        """
        if not self.current_gmap or not level_name:
            return None
            
        gmap_name = self.current_gmap.replace('.gmap', '')
        if gmap_name not in self.gmap_data:
            return None
            
        gmap = self.gmap_data[gmap_name]
        
        # Search for the level in the GMAP grid
        for y in range(gmap.height):
            for x in range(gmap.width):
                idx = y * gmap.width + x
                if idx < len(gmap.levels) and gmap.levels[idx] == level_name:
                    return (x, y)
                    
        return None
    
    def get_level_at_gmap_position(self, gmap_name: str, seg_x: int, seg_y: int) -> Optional[Level]:
        """Get level at specific GMAP position (for client developers)
        
        Args:
            gmap_name: GMAP name (e.g., "zlttp")
            seg_x: Segment X coordinate
            seg_y: Segment Y coordinate
            
        Returns:
            Level object if loaded, None otherwise
        """
        gmap_parser = self.gmap_data.get(gmap_name)
        if gmap_parser:
            segment_name = gmap_parser.get_segment_at(seg_x, seg_y)
            if segment_name:
                return self.levels.get(segment_name)
        
        # Fallback to coordinate-based naming
        segment_name = self.get_segment_name(gmap_name, seg_x, seg_y)
        return self.levels.get(segment_name)
        
    def get_gmap_segment_coords(self, level_name: str) -> Optional[Tuple[str, int, int]]:
        """Get GMAP coordinates for a level (for client developers)
        
        Args:
            level_name: Level name
            
        Returns:
            Tuple of (gmap_name, seg_x, seg_y) or None
        """
        return self.parse_segment_name(level_name)
    
