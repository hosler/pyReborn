"""
Input System
============

Modern input handling system that uses PyReborn's OutgoingPacketAPI
for sending player actions to the server.
"""

import pygame
import logging
import time
from typing import Dict, Set, Optional
from dataclasses import dataclass

# Import compatibility layer
from .packet_api_compat import OutgoingPacketAPI


logger = logging.getLogger(__name__)


@dataclass
class InputState:
    """Current input state"""
    keys_pressed: Set[int]
    mouse_pos: tuple
    mouse_buttons: tuple
    
    def __init__(self):
        self.keys_pressed = set()
        self.mouse_pos = (0, 0)
        self.mouse_buttons = (False, False, False)


class InputSystem:
    """Handles all player input and sends appropriate packets"""
    
    def __init__(self, packet_api: OutgoingPacketAPI, keybindings: Dict[str, int], physics_system=None):
        """Initialize input system
        
        Args:
            packet_api: API for sending packets to server
            keybindings: Action to key mappings
            physics_system: Optional physics system for collision detection
        """
        self.packet_api = packet_api
        self.keybindings = keybindings
        self.physics_system = physics_system
        
        # Input state
        self.state = InputState()
        self.previous_state = InputState()
        
        # Movement state
        self.movement_keys = {
            keybindings.get('move_up', pygame.K_w): (0, -1),
            keybindings.get('move_down', pygame.K_s): (0, 1),
            keybindings.get('move_left', pygame.K_a): (-1, 0),
            keybindings.get('move_right', pygame.K_d): (1, 0)
        }
        
        # Debug log keybindings
        logger.info(f"Movement keys configured:")
        for key, direction in self.movement_keys.items():
            key_name = pygame.key.name(key) if key else "None"
            logger.info(f"  {key} ({key_name}): {direction}")
        logger.info(f"Raw keybindings: {keybindings}")
        
        # Action keys
        self.action_keys = {
            keybindings.get('attack', pygame.K_SPACE): 'attack',
            keybindings.get('grab', pygame.K_LCTRL): 'grab',
            keybindings.get('chat', pygame.K_RETURN): 'chat'
        }
        
        # Rate limiting
        self.last_movement_send = 0
        self.movement_send_rate = 0.016  # 16ms between movement packets (60Hz) for instant response
        
        # Current movement direction
        self.current_direction = None
        self.last_direction = 2  # Remember last direction for idle sprite (default down)
        self.is_moving = False
        
        logger.info("Input system initialized")
    
    def handle_event(self, event: pygame.event.Event):
        """Handle pygame event"""
        if event.type == pygame.KEYDOWN:
            # Debug: log any keydown
            if event.key in self.movement_keys:
                logger.info(f"[INPUT] MOVEMENT KEY DOWN: {event.key} ({pygame.key.name(event.key)})")
            self.state.keys_pressed.add(event.key)
            self._handle_key_press(event.key)
            
        elif event.type == pygame.KEYUP:
            # Debug: log any keyup for movement keys
            if event.key in self.movement_keys:
                logger.info(f"[INPUT] MOVEMENT KEY UP: {event.key} ({pygame.key.name(event.key)})")
            self.state.keys_pressed.discard(event.key)
            self._handle_key_release(event.key)
            
        elif event.type == pygame.MOUSEMOTION:
            self.state.mouse_pos = event.pos
            
        elif event.type == pygame.MOUSEBUTTONDOWN:
            buttons = list(self.state.mouse_buttons)
            if event.button <= 3:
                buttons[event.button - 1] = True
            self.state.mouse_buttons = tuple(buttons)
            self._handle_mouse_press(event.button, event.pos)
            
        elif event.type == pygame.MOUSEBUTTONUP:
            buttons = list(self.state.mouse_buttons)
            if event.button <= 3:
                buttons[event.button - 1] = False
            self.state.mouse_buttons = tuple(buttons)
    
    def update(self, dt: float):
        """Update input system"""
        # Handle continuous movement
        self._update_movement()
        
        # Update previous state
        self.previous_state.keys_pressed = self.state.keys_pressed.copy()
        self.previous_state.mouse_pos = self.state.mouse_pos
        self.previous_state.mouse_buttons = self.state.mouse_buttons
    
    def _handle_key_press(self, key: int):
        """Handle key press"""
        # Debug log important key presses only
        if key in self.action_keys or key in self.movement_keys:
            key_name = pygame.key.name(key) if key else "Unknown"
            logger.debug(f"Key pressed: {key} ({key_name})")
        
        # Check for action keys
        if key in self.action_keys:
            action = self.action_keys[key]
            
            if action == 'attack':
                self._send_attack()
            elif action == 'grab':
                self._send_grab()
            elif action == 'chat':
                # Chat UI will handle this
                pass
        
        # Debug key: Print current level info  
        if key == pygame.K_l:  # 'L' key for level info
            try:
                session_manager = self.packet_api.client.session_manager
                if session_manager:
                    current_level = session_manager.get_current_level_name()
                    current_gmap = session_manager.get_current_gmap_name()
                    player = session_manager.get_player()
                    if player and hasattr(player, 'gmaplevelx'):
                        logger.info(f"🔍 LEVEL DEBUG: Current level='{current_level}', GMAP='{current_gmap}', Segment=({player.gmaplevelx},{player.gmaplevely})")
                    else:
                        logger.info(f"🔍 LEVEL DEBUG: Current level='{current_level}', GMAP='{current_gmap}', Player segment info not available")
                else:
                    logger.info("🔍 LEVEL DEBUG: Session manager not available")
            except Exception as e:
                logger.error(f"Debug level info failed: {e}")
    
    def _handle_key_release(self, key: int):
        """Handle key release"""
        # Check if movement key was released
        if key in self.movement_keys:
            self._update_movement_state()
    
    def _handle_mouse_press(self, button: int, pos: tuple):
        """Handle mouse button press"""
        if button == 1:  # Left click
            # TODO: Convert screen position to world position
            # and send appropriate action (attack, interact, etc)
            pass
    
    def _update_movement(self):
        """Update player movement based on pressed keys"""
        # Calculate movement vector
        move_x = 0
        move_y = 0
        
        # Debug: Log all pressed keys
        if self.state.keys_pressed and not hasattr(self, '_last_key_debug') or time.time() - getattr(self, '_last_key_debug', 0) > 1:
            logger.debug(f"[INPUT] All pressed keys: {self.state.keys_pressed}")
            self._last_key_debug = time.time()
        
        pressed_movement_keys = []
        for key, (dx, dy) in self.movement_keys.items():
            if key in self.state.keys_pressed:
                move_x += dx
                move_y += dy
                pressed_movement_keys.append(pygame.key.name(key))
        
        # Debug log movement if keys are pressed (reduce spam)
        if pressed_movement_keys and not hasattr(self, '_last_movement_debug') or time.time() - getattr(self, '_last_movement_debug', 0) > 1:
            logger.info(f"[INPUT] Movement keys pressed: {pressed_movement_keys}, vector: ({move_x}, {move_y})")
            self._last_movement_debug = time.time()
        
        # Normalize diagonal movement
        if move_x != 0 and move_y != 0:
            move_x *= 0.707  # 1/sqrt(2)
            move_y *= 0.707
        
        # Determine direction for sprite (prioritize vertical for diagonals)
        new_direction = None
        if move_y < 0:
            new_direction = 0  # Up
        elif move_y > 0:
            new_direction = 2  # Down
        elif move_x < 0:
            new_direction = 1  # Left
        elif move_x > 0:
            new_direction = 3  # Right
        
        # Store the actual movement vector for diagonal movement
        self.move_vector = (move_x, move_y)
        
        # Check if we should send movement update
        current_time = time.time()
        should_send = False
        
        if new_direction is not None:
            # Moving
            if not self.is_moving or new_direction != self.current_direction:
                # Started moving or changed direction
                should_send = True
                self.is_moving = True
                self.current_direction = new_direction
                self.last_direction = new_direction  # Remember this direction
            elif current_time - self.last_movement_send >= self.movement_send_rate:
                # Regular movement update
                should_send = True
        else:
            # Stopped moving
            if self.is_moving:
                should_send = True
                self.is_moving = False
                self.current_direction = None
                # Keep last_direction unchanged for idle sprite
        
        # Send movement packet if needed
        if should_send:
            logger.debug(f"[INPUT] Should send movement: is_moving={self.is_moving}, direction={self.current_direction}")
            self._send_movement()
            self.last_movement_send = current_time
        elif self.is_moving:
            logger.debug(f"[INPUT] NOT sending movement (continuous): time since last={current_time - self.last_movement_send:.3f}s, rate={self.movement_send_rate}s")
    
    def _update_movement_state(self):
        """Update movement state when keys change"""
        # This will trigger movement update in next update() call
        pass
    
    def _send_movement(self):
        """Send movement packet to server"""        
        if self.is_moving and self.current_direction is not None:
            # Send directional movement
            try:
                logger.debug(f"[INPUT] Starting movement - is_moving={self.is_moving}, direction={self.current_direction}")
                
                # Get current player position
                player = None
                if hasattr(self.packet_api, 'client') and hasattr(self.packet_api.client, 'session_manager'):
                    player = self.packet_api.client.session_manager.get_player()
                
                if not player:
                    logger.error("No player available for movement")
                    return
                
                logger.debug(f"[INPUT] Player found at ({player.x:.2f}, {player.y:.2f})")
                
                # Calculate sprite based on direction
                # Direction: 0=Up, 1=Left, 2=Down, 3=Right
                # Sprite: 0=Up, 1=Left, 2=Down, 3=Right, +4 for walking
                sprite = self.current_direction + 4  # Add 4 for walking animation
                
                # Movement speed in tiles per second (fast and responsive)
                movement_speed = 15.0  # Fast movement like classic Reborn
                
                # Use actual movement vector for diagonal movement
                if hasattr(self, 'move_vector'):
                    dx = self.move_vector[0] * movement_speed * self.movement_send_rate
                    dy = self.move_vector[1] * movement_speed * self.movement_send_rate
                else:
                    # Fallback to direction-based movement
                    dx, dy = 0, 0
                    if self.current_direction == 0:  # Up
                        dy = -movement_speed * self.movement_send_rate
                    elif self.current_direction == 1:  # Left
                        dx = -movement_speed * self.movement_send_rate
                    elif self.current_direction == 2:  # Down
                        dy = movement_speed * self.movement_send_rate
                    elif self.current_direction == 3:  # Right
                        dx = movement_speed * self.movement_send_rate
                
                # Calculate new position using WORLD coordinates for physics
                # Use x2/y2 if available (GMAP mode), otherwise use local x/y
                if player.x2 is not None and player.y2 is not None:
                    # GMAP mode - use world coordinates
                    current_world_x = player.x2
                    current_world_y = player.y2
                    new_world_x = current_world_x + dx
                    new_world_y = current_world_y + dy
                    logger.debug(f"[INPUT] GMAP mode - World coords: ({current_world_x:.2f}, {current_world_y:.2f}) -> ({new_world_x:.2f}, {new_world_y:.2f})")
                else:
                    # Single level mode - use local coordinates
                    current_world_x = player.x
                    current_world_y = player.y
                    new_world_x = current_world_x + dx
                    new_world_y = current_world_y + dy
                    logger.debug(f"[INPUT] Single level - Local coords: ({current_world_x:.2f}, {current_world_y:.2f}) -> ({new_world_x:.2f}, {new_world_y:.2f})")
                
                logger.debug(f"[INPUT] Movement delta: ({dx:.3f}, {dy:.3f})")
                
                # Check collision if physics system is available
                can_move = True
                if self.physics_system and -1 in self.physics_system.bodies:
                    logger.debug(f"[INPUT] Checking collision with physics system")
                    body = self.physics_system.bodies[-1]
                    
                    # Temporarily update body position to test collision
                    old_body_x, old_body_y = body.x, body.y
                    
                    # Check if movement would be blocked by calling _move_and_collide
                    final_x, final_y, collision_info = self.physics_system._move_and_collide(body, new_world_x, new_world_y)
                    
                    # Restore body position (we're just testing, not actually moving yet)
                    body.x = old_body_x
                    body.y = old_body_y
                    
                    # Update the target position based on collision results
                    new_world_x = final_x
                    new_world_y = final_y
                    
                    # If we have collision info, update the body's blocked state for link detection
                    if collision_info and collision_info.get('blocked'):
                        body.last_collision_x = collision_info.get('collision_x')
                        body.last_collision_y = collision_info.get('collision_y')
                        body.blocked_direction = collision_info.get('direction')
                        body.blocked_tile_x = collision_info.get('blocked_tile_x')
                        body.blocked_tile_y = collision_info.get('blocked_tile_y')
                        logger.info(f"[INPUT] 🚫 Collision detected, updating body blocked state")
                        
                        # Immediately check for links at collision point
                        if self.physics_system.level_link_manager:
                            collision_point = (body.last_collision_x, body.last_collision_y)
                            blocking_tile = None
                            if body.blocked_tile_x is not None:
                                blocking_tile = (body.blocked_tile_x, body.blocked_tile_y)
                            logger.info(f"[INPUT] 📍 Checking links at collision point: ({collision_point[0]:.1f}, {collision_point[1]:.1f})")
                            
                            transition_triggered = self.physics_system.level_link_manager.update(
                                body.x, body.y, 
                                collision_point=collision_point,
                                blocked_direction=body.blocked_direction,
                                blocking_tile=blocking_tile
                            )
                            if transition_triggered:
                                logger.info(f"[INPUT] Level transition triggered!")
                                return  # Don't send movement if we're transitioning
                    
                    # If we couldn't move at all, movement is blocked completely
                    if abs(final_x - current_world_x) < 0.01 and abs(final_y - current_world_y) < 0.01:
                        can_move = False
                        logger.debug(f"[INPUT] Movement completely blocked by collision")
                    else:
                        logger.debug(f"[INPUT] Movement adjusted by collision: ({current_world_x:.2f}, {current_world_y:.2f}) -> ({final_x:.2f}, {final_y:.2f})")
                else:
                    # No physics system - move without collision detection
                    if self.physics_system:
                        logger.warning(f"[INPUT] Body -1 not found in physics! Bodies: {list(self.physics_system.bodies.keys())}")
                    else:
                        logger.warning(f"[INPUT] No physics system available!")
                
                if can_move:
                    # UPDATE PLAYER POSITION (client-side prediction)
                    if player.x2 is not None and player.y2 is not None:
                        # GMAP mode - update world coordinates and calculate new local/segment
                        player.x2 = new_world_x
                        player.y2 = new_world_y
                        
                        # Calculate new segment and local coordinates
                        new_segment_x = int(new_world_x // 64)
                        new_segment_y = int(new_world_y // 64)
                        new_local_x = new_world_x - (new_segment_x * 64)
                        new_local_y = new_world_y - (new_segment_y * 64)
                        
                        # Update segment if changed
                        if new_segment_x != player.gmaplevelx or new_segment_y != player.gmaplevely:
                            logger.debug(f"[INPUT] Segment would change from ({player.gmaplevelx}, {player.gmaplevely}) to ({new_segment_x}, {new_segment_y}) based on position")
                            # Don't update segment here - let level manager handle actual transitions
                            # player.gmaplevelx = new_segment_x
                            # player.gmaplevely = new_segment_y
                        
                        # Update local coordinates
                        player.x = new_local_x
                        player.y = new_local_y
                        logger.debug(f"[INPUT] Updated player - World: ({new_world_x:.2f}, {new_world_y:.2f}), Local: ({new_local_x:.2f}, {new_local_y:.2f}), Segment: ({new_segment_x}, {new_segment_y})")
                    else:
                        # Single level mode - just update local coordinates
                        player.x = new_world_x
                        player.y = new_world_y
                        logger.debug(f"[INPUT] Updated player - Local: ({new_world_x:.2f}, {new_world_y:.2f})")
                    
                    # Also update render positions to ensure sprite moves immediately
                    if hasattr(player, 'render_x'):
                        player.render_x = player.x
                    if hasattr(player, 'render_y'):
                        player.render_y = player.y
                    # Also update sprite for client-side direction prediction
                    player.sprite = sprite
                    # Set is_moving flag for GANI animation
                    player.is_moving = True
                    
                    # Update physics body with WORLD coordinates
                    if self.physics_system and -1 in self.physics_system.bodies:
                        body = self.physics_system.bodies[-1]
                        body.x = new_world_x
                        body.y = new_world_y
                        logger.debug(f"[INPUT] Updated physics body to world: ({new_world_x:.2f}, {new_world_y:.2f})")
                else:
                    # Movement blocked, just update sprite direction
                    player.sprite = sprite
                    player.is_moving = False
                    return  # Don't send movement packet if blocked
                
                # Convert to pixel coordinates for X2/Y2 (16 pixels per tile)
                # Send world coordinates to server
                pixel_x = int(new_world_x * 16) if (player.x2 is not None) else int(player.x * 16)
                pixel_y = int(new_world_y * 16) if (player.y2 is not None) else int(player.y * 16)
                
                # Send player properties with X2/Y2 world coordinates and sprite
                self.packet_api.set_player_properties(
                    x2=pixel_x,
                    y2=pixel_y,
                    sprite=sprite
                )
                
                # Update session manager with new position for segment tracking
                # DISABLED: Causing incorrect segment warping on first movement
                # try:
                #     session_manager = self.packet_api.client.session_manager
                #     if session_manager and hasattr(session_manager, 'update_player_position'):
                #         session_manager.update_player_position(pixel_x, pixel_y)
                # except Exception as e:
                #     logger.debug(f"Failed to update session manager position: {e}")
                logger.debug(f"Movement: world tiles=({new_world_x:.2f},{new_world_y:.2f}), pixels=({pixel_x},{pixel_y}), dir={self.current_direction}, sprite={sprite}")
            except Exception as e:
                logger.error(f"Failed to send movement: {e}")
        else:
            # Send stop movement
            try:
                # Get current player position
                player = None
                if hasattr(self.packet_api, 'client') and hasattr(self.packet_api.client, 'session_manager'):
                    player = self.packet_api.client.session_manager.get_player()
                
                if not player:
                    return
                
                # Send idle sprite based on last direction (not current which is None)
                sprite = self.last_direction  # Use last_direction which remembers where we were facing
                
                # Update local sprite for client-side prediction
                player.sprite = sprite
                # Clear is_moving flag for GANI animation
                player.is_moving = False
                # Sync render positions when stopping
                if hasattr(player, 'render_x'):
                    player.render_x = player.x
                if hasattr(player, 'render_y'):
                    player.render_y = player.y
                
                # Convert to pixel coordinates for X2/Y2
                pixel_x = int(player.x * 16)
                pixel_y = int(player.y * 16)
                
                # Send current position with idle sprite
                self.packet_api.set_player_properties(
                    x2=pixel_x,
                    y2=pixel_y,
                    sprite=sprite
                )
                logger.debug(f"Stop movement: tiles=({player.x:.2f},{player.y:.2f}), pixels=({pixel_x},{pixel_y}), sprite={sprite}")
            except Exception as e:
                logger.error(f"Failed to send stop movement: {e}")
    
    def _send_attack(self):
        """Send attack action"""
        try:
            # Get current direction
            direction = self.current_direction if self.current_direction is not None else 2
            
            # Trigger combat system if available
            if hasattr(self.packet_api.client, 'combat_system'):
                combat_system = self.packet_api.client.combat_system
                combat_system.perform_attack(0, direction)  # 0 = local player
            else:
                # Fallback: just send attack sprite
                attack_sprite = 8 + direction  # Attack sprites: 8=Up, 9=Left, 10=Down, 11=Right
                self.packet_api.set_player_properties(sprite=attack_sprite)
            
            logger.debug(f"Sent attack: direction={direction}")
        except Exception as e:
            logger.error(f"Failed to send attack: {e}")
    
    def _send_grab(self):
        """Send grab/lift action"""
        try:
            # Get player position
            player = self.packet_api.client.session_manager.get_player()
            if not player:
                return
            
            # Try interaction system first
            if hasattr(self.packet_api.client, 'interaction_system'):
                interaction_system = self.packet_api.client.interaction_system
                if interaction_system.interact_with_object(0, player.x, player.y):
                    logger.debug("Interacted with object")
                    return
            
            # Fallback: send grab sprite
            direction = self.current_direction if self.current_direction is not None else 2
            grab_sprite = 12 + direction  # Grab sprites: 12=Up, 13=Left, 14=Down, 15=Right
            self.packet_api.set_player_properties(
                sprite=grab_sprite
            )
            logger.debug(f"Sent grab: sprite={grab_sprite}")
        except Exception as e:
            logger.error(f"Failed to send grab: {e}")
    
    def is_key_pressed(self, action: str) -> bool:
        """Check if action key is currently pressed"""
        key = self.keybindings.get(action)
        return key in self.state.keys_pressed if key else False
    
    def was_key_pressed(self, action: str) -> bool:
        """Check if action key was just pressed this frame"""
        key = self.keybindings.get(action)
        if not key:
            return False
        return (key in self.state.keys_pressed and 
                key not in self.previous_state.keys_pressed)
    
    def get_mouse_position(self) -> tuple:
        """Get current mouse position"""
        return self.state.mouse_pos
    
    def is_mouse_pressed(self, button: int) -> bool:
        """Check if mouse button is pressed (1=left, 2=middle, 3=right)"""
        if 1 <= button <= 3:
            return self.state.mouse_buttons[button - 1]
        return False