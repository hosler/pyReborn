"""
Initialization Tracker
======================

Tracks what initial data we've received from the server after login.
The game should only transition from LOADING to PLAYING once all
required data has been received.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class InitializationTracker:
    """Tracks initialization state after login"""
    
    def __init__(self):
        """Initialize the tracker"""
        self.reset()
        
    def reset(self):
        """Reset all tracking flags"""
        # Required data
        self.has_player_props = False  # PLO_PLAYERPROPS received
        self.has_initial_level = False  # PLO_LEVELBOARD received
        
        # Optional data
        self.has_appearance = False  # Character appearance data
        self.has_gmap_data = False  # GMAP data if entering a GMAP world
        
        # Timing
        self.login_time = None
        self.ready_time = None
        
        # Data storage
        self.player_data = None
        self.level_name = None
        
        logger.info("Initialization tracker reset")
    
    def mark_login(self):
        """Mark that login has occurred"""
        self.login_time = time.time()
        logger.info("Login marked - waiting for initial data")
    
    def mark_player_props_received(self, player_data: dict):
        """Mark that we've received initial player properties
        
        Args:
            player_data: Dictionary containing player properties
        """
        self.has_player_props = True
        self.player_data = player_data
        
        # Log what we received
        if player_data:
            # Server might send x/y OR x2/y2 OR both
            x = player_data.get('x', player_data.get('x2', 'None'))
            y = player_data.get('y', player_data.get('y2', 'None'))
            nickname = player_data.get('nickname', 'Unknown')
            
            # Check for GMAP segment
            if 'gmaplevelx' in player_data and 'gmaplevely' in player_data:
                seg_x = player_data['gmaplevelx']
                seg_y = player_data['gmaplevely']
                logger.info(f"✓ Player props received: {nickname} at segment ({seg_x},{seg_y}), coords ({x}, {y})")
            else:
                logger.info(f"✓ Player props received: {nickname} at ({x}, {y})")
        else:
            logger.info("✓ Player props received (no position data)")
        
        self._check_ready()
    
    def mark_initial_level_received(self, level_name: str):
        """Mark that we've received the initial level data
        
        Args:
            level_name: Name of the initial level
        """
        self.has_initial_level = True
        self.level_name = level_name
        logger.info(f"✓ Initial level received: {level_name}")
        
        self._check_ready()
    
    def mark_appearance_received(self):
        """Mark that we've received character appearance data"""
        self.has_appearance = True
        logger.info("✓ Character appearance received")
        
        self._check_ready()
    
    def mark_gmap_received(self, gmap_name: str):
        """Mark that we've received GMAP data
        
        Args:
            gmap_name: Name of the GMAP file
        """
        self.has_gmap_data = True
        logger.info(f"✓ GMAP data received: {gmap_name}")
        
        self._check_ready()
    
    def is_ready(self) -> bool:
        """Check if we have all required data to start playing
        
        Returns:
            True if all required data has been received
        """
        # Required: player props and initial level
        return self.has_player_props and self.has_initial_level
    
    def _check_ready(self):
        """Check if we're ready and log the transition"""
        if self.is_ready() and self.ready_time is None:
            self.ready_time = time.time()
            load_time = self.ready_time - self.login_time if self.login_time else 0
            logger.info(f"✅ All required data received! Load time: {load_time:.2f}s")
    
    def get_missing_data(self) -> list:
        """Get a list of what data we're still waiting for
        
        Returns:
            List of missing data descriptions
        """
        missing = []
        
        if not self.has_player_props:
            missing.append("Player properties")
        if not self.has_initial_level:
            missing.append("Initial level")
        
        # Optional data (not included in missing for now)
        # if not self.has_appearance:
        #     missing.append("Character appearance")
        
        return missing
    
    def get_load_progress(self) -> float:
        """Get loading progress as a percentage
        
        Returns:
            Progress from 0.0 to 1.0
        """
        required_count = 2  # player_props and initial_level
        received_count = 0
        
        if self.has_player_props:
            received_count += 1
        if self.has_initial_level:
            received_count += 1
        
        return received_count / required_count
    
    def get_status_text(self) -> str:
        """Get a human-readable status text for display
        
        Returns:
            Status text describing what we're waiting for
        """
        if self.is_ready():
            return "Ready to play!"
        
        missing = self.get_missing_data()
        if missing:
            return f"Waiting for: {', '.join(missing)}"
        
        return "Initializing..."
    
    def has_valid_position(self) -> bool:
        """Check if we have valid player position data
        
        Returns:
            True if player position is available and not hardcoded
        """
        if not self.player_data:
            return False
        
        x = self.player_data.get('x')
        y = self.player_data.get('y')
        
        # Check if we have position data and it's not the hardcoded default
        if x is None or y is None:
            return False
        
        # Reject hardcoded 30,30 position
        if x == 30.0 and y == 30.0:
            logger.warning("⚠️ Received hardcoded position (30, 30) - waiting for real position")
            return False
        
        return True