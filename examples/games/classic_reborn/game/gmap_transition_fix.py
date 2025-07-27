"""
Fix for GMAP boundary transition oscillation

The issue: When the player is exactly at a segment boundary (e.g., Y=0),
small movements can trigger rapid back-and-forth transitions between segments.

The fix:
1. Add a small dead zone at boundaries
2. Only transition when clearly crossing into the next segment
3. Track last transition to prevent rapid oscillation
"""

import time

class GMAPTransitionHandler:
    """Handles GMAP segment transitions with anti-oscillation logic"""
    
    def __init__(self):
        self.last_transition_time = 0
        self.transition_cooldown = 0.5  # seconds
        self.boundary_deadzone = 0.5  # tiles
        self.last_segment = None
        
    def should_transition(self, current_x, current_y, new_x, new_y):
        """
        Determine if we should transition to a new segment
        
        Returns: (should_transition, seg_change_x, seg_change_y, local_x, local_y)
        """
        # Check cooldown
        if time.time() - self.last_transition_time < self.transition_cooldown:
            return False, 0, 0, new_x, new_y
            
        seg_change_x = 0
        seg_change_y = 0
        local_x = new_x
        local_y = new_y
        
        # Only transition if we've moved significantly past the boundary
        # This prevents oscillation when hovering near boundaries
        
        # X boundary with deadzone
        if new_x < -self.boundary_deadzone:
            seg_change_x = -1
            local_x = new_x + 64
        elif new_x >= 64 + self.boundary_deadzone:
            seg_change_x = 1
            local_x = new_x - 64
            
        # Y boundary with deadzone  
        if new_y < -self.boundary_deadzone:
            seg_change_y = -1
            local_y = new_y + 64
        elif new_y >= 64 + self.boundary_deadzone:
            seg_change_y = 1
            local_y = new_y - 64
            
        # Only allow transition if we're clearly moving across
        should_transition = (seg_change_x != 0 or seg_change_y != 0)
        
        if should_transition:
            self.last_transition_time = time.time()
            
        return should_transition, seg_change_x, seg_change_y, local_x, local_y


def apply_boundary_fix(client_module):
    """
    Monkey patch the client to use the fixed transition logic
    """
    # Save original update method
    original_update = client_module.ClassicRebornClient.update
    
    # Create transition handler
    transition_handler = GMAPTransitionHandler()
    
    def patched_update(self, dt):
        """Patched update with fixed GMAP transitions"""
        # Call most of the original update
        original_update(self, dt)
        
        # But override the GMAP transition logic
        if hasattr(self, '_handle_player_movement'):
            original_handle = self._handle_player_movement
            
            def fixed_handle_movement(dx, dy, dt):
                # Get current position
                player = self.game_state.get_local_player()
                if not player:
                    return
                    
                current_x = player.x
                current_y = player.y
                
                # Calculate new position
                move_speed = 4.0
                new_x = current_x + dx * move_speed * dt
                new_y = current_y + dy * move_speed * dt
                
                # Check GMAP mode
                if hasattr(self.connection_manager, 'client') and self.connection_manager.client:
                    if getattr(self.connection_manager.client, 'is_gmap_mode', False):
                        # Use our fixed transition logic
                        should_transition, seg_change_x, seg_change_y, local_x, local_y = \
                            transition_handler.should_transition(current_x, current_y, new_x, new_y)
                        
                        if should_transition:
                            # Get current segment
                            current_gmapx = getattr(player, 'gmaplevelx', 0) or 0
                            current_gmapy = getattr(player, 'gmaplevely', 0) or 0
                            
                            # Calculate new segment
                            new_gmapx = current_gmapx + seg_change_x
                            new_gmapy = current_gmapy + seg_change_y
                            
                            # Update positions
                            player.x = local_x
                            player.y = local_y
                            player.gmaplevelx = new_gmapx
                            player.gmaplevely = new_gmapy
                            
                            # Update server
                            if hasattr(self.connection_manager.client, '_actions'):
                                self.connection_manager.client._actions.set_gmap_position(new_gmapx, new_gmapy)
                                self.connection_manager.client._actions.move(local_x, local_y, player.direction)
                        else:
                            # Normal movement within segment
                            player.x = new_x
                            player.y = new_y
                            self.connection_manager.move_player(new_x, new_y, player.direction)
                    else:
                        # Non-GMAP movement
                        player.x = new_x
                        player.y = new_y
                        self.connection_manager.move_player(new_x, new_y, player.direction)
                        
            self._handle_player_movement = fixed_handle_movement
            
    client_module.ClassicRebornClient.update = patched_update