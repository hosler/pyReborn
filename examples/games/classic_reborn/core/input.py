"""
Input Manager Module - Handles keyboard and mouse input for the game
"""

import pygame
from typing import Set, Optional, Tuple, Callable
from pyreborn.protocol.enums import Direction


class InputManager:
    """Manages all input handling for the game"""
    
    def __init__(self):
        """Initialize the input manager"""
        # Keyboard state
        self.keys_pressed: Set[int] = set()
        
        # Chat mode
        self.chat_mode = False
        self.chat_buffer = ""
        
        # Key bindings
        self.key_bindings = {
            'move_up': [pygame.K_UP],
            'move_down': [pygame.K_DOWN],
            'move_left': [pygame.K_LEFT],
            'move_right': [pygame.K_RIGHT],
            'attack': [pygame.K_SPACE, pygame.K_s],
            'grab': [pygame.K_a],
            'chat': [pygame.K_TAB],
            'debug': [pygame.K_F1],
            'collision_debug': [pygame.K_F2],
            'tile_debug': [pygame.K_F3],
            'warp_menu': [pygame.K_F4],
            'clear_cache': [pygame.K_F5],
            'minimap': [pygame.K_m],
            'player_list': [pygame.K_p],
            'quit': [pygame.K_ESCAPE]
        }
        
        # Callbacks
        self.on_attack: Optional[Callable] = None
        self.on_grab: Optional[Callable] = None
        self.on_grab_release: Optional[Callable] = None
        self.on_chat_send: Optional[Callable[[str], None]] = None
        self.on_quit: Optional[Callable] = None
        self.on_debug_toggle: Optional[Callable[[str], None]] = None
        self.on_click_move: Optional[Callable[[int, int], None]] = None
        self.on_warp_menu: Optional[Callable] = None
        self.on_clear_cache: Optional[Callable] = None
        
        # Warp mode
        self.warp_mode = False
        self.warp_input = ""
        
    def is_key_pressed(self, action: str) -> bool:
        """Check if a key for the given action is pressed
        
        Args:
            action: Action name from key_bindings
            
        Returns:
            True if any key bound to the action is pressed
        """
        if action in self.key_bindings:
            return any(key in self.keys_pressed for key in self.key_bindings[action])
        return False
        
    def get_movement_direction(self) -> Optional[Direction]:
        """Get the current movement direction based on input
        
        Returns:
            Direction enum or None if no movement keys pressed
        """
        # Check each direction
        up = self.is_key_pressed('move_up')
        down = self.is_key_pressed('move_down')
        left = self.is_key_pressed('move_left')
        right = self.is_key_pressed('move_right')
        
        # Handle diagonal prevention (prioritize last pressed)
        if left and not right:
            return Direction.LEFT
        elif right and not left:
            return Direction.RIGHT
        elif up and not down:
            return Direction.UP
        elif down and not up:
            return Direction.DOWN
            
        return None
        
    def get_movement_vector(self) -> Tuple[float, float]:
        """Get movement vector based on pressed keys
        
        Returns:
            Tuple of (dx, dy) representing movement direction
        """
        dx = dy = 0.0
        
        if self.is_key_pressed('move_left'):
            dx -= 1.0
        if self.is_key_pressed('move_right'):
            dx += 1.0
        if self.is_key_pressed('move_up'):
            dy -= 1.0
        if self.is_key_pressed('move_down'):
            dy += 1.0
        return dx, dy
        
    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle a pygame event
        
        Args:
            event: Pygame event to process
            
        Returns:
            True if event was handled, False otherwise
        """
        if event.type == pygame.KEYDOWN:
            return self._handle_keydown(event)
        elif event.type == pygame.KEYUP:
            return self._handle_keyup(event)
        elif event.type == pygame.QUIT:
            if self.on_quit:
                self.on_quit()
            return True
        elif event.type == pygame.MOUSEBUTTONDOWN:
            return self._handle_mouse_click(event)
            
        return False
        
    def _handle_mouse_click(self, event: pygame.event.Event) -> bool:
        """Handle mouse click events"""
        if event.button == 1:  # Left click
            if self.on_click_move:
                self.on_click_move(event.pos[0], event.pos[1])
                return True
        return False
        
    def _handle_keydown(self, event: pygame.event.Event) -> bool:
        """Handle key press events"""
        if self.chat_mode:
            # Chat input handling
            if event.key == pygame.K_RETURN:
                if self.chat_buffer and self.on_chat_send:
                    self.on_chat_send(self.chat_buffer)
                    self.chat_buffer = ""
                self.chat_mode = False
                return True
            elif event.key == pygame.K_ESCAPE:
                self.chat_buffer = ""
                self.chat_mode = False
                return True
            elif event.key == pygame.K_BACKSPACE:
                self.chat_buffer = self.chat_buffer[:-1]
                return True
            elif event.unicode and len(self.chat_buffer) < 200:
                self.chat_buffer += event.unicode
                return True
        elif self.warp_mode:
            # Warp input handling
            if event.key == pygame.K_RETURN:
                if self.warp_input and self.on_chat_send:
                    # Use chat send to process warp command
                    self.on_chat_send(f"/warp {self.warp_input}")
                    self.warp_input = ""
                self.warp_mode = False
                return True
            elif event.key == pygame.K_ESCAPE:
                self.warp_input = ""
                self.warp_mode = False
                return True
            elif event.key == pygame.K_BACKSPACE:
                self.warp_input = self.warp_input[:-1]
                return True
            elif event.unicode and len(self.warp_input) < 100:
                self.warp_input += event.unicode
                return True
        else:
            # Normal game input
            # ALWAYS track key press state first (for movement keys)
            self.keys_pressed.add(event.key)
            
            # Then handle special keys
            if event.key in self.key_bindings['chat']:
                self.chat_mode = True
                return True
            elif event.key in self.key_bindings['quit']:
                if self.on_quit:
                    self.on_quit()
                return True
            elif event.key in self.key_bindings['attack']:
                if self.on_attack:
                    self.on_attack()
                return True
            elif event.key in self.key_bindings['grab']:
                if self.on_grab:
                    self.on_grab()
                return True
            elif event.key in self.key_bindings['debug']:
                if self.on_debug_toggle:
                    self.on_debug_toggle('debug')
                return True
            elif event.key in self.key_bindings['collision_debug']:
                if self.on_debug_toggle:
                    self.on_debug_toggle('collision')
                return True
            elif event.key in self.key_bindings['tile_debug']:
                if self.on_debug_toggle:
                    self.on_debug_toggle('tiles')
                return True
            elif event.key in self.key_bindings['minimap']:
                if self.on_debug_toggle:
                    self.on_debug_toggle('minimap')
                return True
            elif event.key in self.key_bindings['player_list']:
                if self.on_debug_toggle:
                    self.on_debug_toggle('players')
                return True
            elif event.key in self.key_bindings['warp_menu']:
                self.warp_mode = True
                self.warp_input = ""
                if self.on_warp_menu:
                    self.on_warp_menu()
                return True
            elif event.key in self.key_bindings['clear_cache']:
                if self.on_clear_cache:
                    self.on_clear_cache()
                return True
                
        return False
        
    def _handle_keyup(self, event: pygame.event.Event) -> bool:
        """Handle key release events"""
        if event.key in self.keys_pressed:
            self.keys_pressed.remove(event.key)
            
        # Special handling for grab release
        if event.key in self.key_bindings['grab']:
            if self.on_grab_release:
                self.on_grab_release()
            return True
            
        return False
        
    def reset(self):
        """Reset input state"""
        self.keys_pressed.clear()
        self.chat_mode = False
        self.chat_buffer = ""
        self.warp_mode = False
        self.warp_input = ""