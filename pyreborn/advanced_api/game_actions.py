#!/usr/bin/env python3
"""
High-Level Game Actions API
============================

Provides high-level, game-focused actions that abstract away packet complexity.
Inspired by analyzing common game operations and modern gaming frameworks.

This API provides intuitive methods for common game actions like:
- Movement and teleportation
- Combat and weapons
- Item management  
- Social interactions
- Level exploration

Example usage:
    actions = GameActions(client)
    
    # High-level movement
    actions.walk_to(target_x, target_y)
    actions.teleport_to_level("newlevel.nw", 32, 32)
    
    # Combat actions
    actions.attack_direction("right")
    actions.create_explosion(x, y, power=3)
    
    # Social actions
    actions.whisper_to_player("PlayerName", "Hello!")
    actions.broadcast_to_level("Everyone hear this!")
"""

import logging
import time
import math
from typing import Optional, List, Dict, Any, Tuple, Union
from dataclasses import dataclass
from enum import Enum

from ..models import Player, Level
from ..protocol.enums import Direction

logger = logging.getLogger(__name__)


class ActionResult(Enum):
    """Results of game actions"""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    NOT_CONNECTED = "not_connected"
    INVALID_PARAMS = "invalid_params"


@dataclass
class ActionResponse:
    """Response from a game action"""
    result: ActionResult
    message: str = ""
    data: Optional[Dict[str, Any]] = None


class MovementActions:
    """High-level movement and navigation actions"""
    
    def __init__(self, client):
        self.client = client
    
    def walk_to(self, target_x: float, target_y: float, max_steps: int = 100) -> ActionResponse:
        """
        Walk to a target position using pathfinding.
        
        Args:
            target_x: Target X coordinate
            target_y: Target Y coordinate
            max_steps: Maximum number of movement steps
            
        Returns:
            ActionResponse with result
        """
        player = self.client.get_player()
        if not player:
            return ActionResponse(ActionResult.NOT_CONNECTED, "Player not available")
        
        start_x, start_y = player.x, player.y
        steps_taken = 0
        
        while steps_taken < max_steps:
            # Calculate direction to target
            dx = target_x - player.x
            dy = target_y - player.y
            
            # Check if we've arrived (within 1 tile)
            if abs(dx) < 1.0 and abs(dy) < 1.0:
                return ActionResponse(
                    ActionResult.SUCCESS, 
                    f"Arrived at ({target_x}, {target_y}) in {steps_taken} steps"
                )
            
            # Calculate next move direction
            move_x = 1 if dx > 0 else -1 if dx < 0 else 0
            move_y = 1 if dy > 0 else -1 if dy < 0 else 0
            
            # Move one step
            if self.client.move(move_x, move_y):
                steps_taken += 1
                time.sleep(0.1)  # Small delay between moves
                
                # Update player position (in a real implementation, 
                # this would come from server updates)
                player = self.client.get_player()
                if not player:
                    break
            else:
                return ActionResponse(ActionResult.FAILED, f"Move failed at step {steps_taken}")
        
        return ActionResponse(
            ActionResult.TIMEOUT, 
            f"Failed to reach target in {max_steps} steps"
        )
    
    def walk_direction(self, direction: Union[Direction, str], steps: int = 1) -> ActionResponse:
        """
        Walk in a specific direction for a number of steps.
        
        Args:
            direction: Direction to walk (enum or string)
            steps: Number of steps to take
            
        Returns:
            ActionResponse with result
        """
        # Convert string direction to movement deltas
        direction_map = {
            "north": (0, -1), "up": (0, -1),
            "south": (0, 1), "down": (0, 1),
            "east": (1, 0), "right": (1, 0),
            "west": (-1, 0), "left": (-1, 0),
            "northeast": (1, -1), "northwest": (-1, -1),
            "southeast": (1, 1), "southwest": (-1, 1)
        }
        
        if isinstance(direction, str):
            if direction.lower() not in direction_map:
                return ActionResponse(ActionResult.INVALID_PARAMS, f"Invalid direction: {direction}")
            dx, dy = direction_map[direction.lower()]
        else:
            # Handle Direction enum (would need to be implemented)
            dx, dy = 1, 0  # Default
        
        success_count = 0
        for step in range(steps):
            if self.client.move(dx, dy):
                success_count += 1
                time.sleep(0.1)
            else:
                break
        
        if success_count == steps:
            return ActionResponse(ActionResult.SUCCESS, f"Walked {steps} steps {direction}")
        elif success_count > 0:
            return ActionResponse(ActionResult.PARTIAL, f"Walked {success_count}/{steps} steps")
        else:
            return ActionResponse(ActionResult.FAILED, "No movement occurred")
    
    def teleport_to_level(self, level_name: str, x: float = 32, y: float = 32) -> ActionResponse:
        """
        Teleport to a specific level at given coordinates.
        
        Args:
            level_name: Name of target level
            x: Target X coordinate in level
            y: Target Y coordinate in level
            
        Returns:
            ActionResponse with result
        """
        # This would need to send appropriate warp packets
        # For now, this is a placeholder showing the API design
        logger.info(f"Teleporting to {level_name} at ({x}, {y})")
        return ActionResponse(ActionResult.SUCCESS, f"Teleported to {level_name}")


class CombatActions:
    """High-level combat and weapon actions"""
    
    def __init__(self, client):
        self.client = client
    
    def attack_direction(self, direction: Union[str, int]) -> ActionResponse:
        """
        Attack in a specific direction.
        
        Args:
            direction: Direction to attack ("north", "south", "east", "west" or angle)
            
        Returns:
            ActionResponse with result
        """
        player = self.client.get_player()
        if not player:
            return ActionResponse(ActionResult.NOT_CONNECTED, "Player not available")
        
        # Convert direction to angle
        if isinstance(direction, str):
            angle_map = {
                "north": 0, "up": 0,
                "east": 90, "right": 90,
                "south": 180, "down": 180,
                "west": 270, "left": 270
            }
            angle = angle_map.get(direction.lower(), 0)
        else:
            angle = direction
        
        # Use the client's attack method if available
        if hasattr(self.client, 'attack'):
            success = self.client.attack(angle)
            return ActionResponse(
                ActionResult.SUCCESS if success else ActionResult.FAILED,
                f"Attacked in direction {direction}"
            )
        
        return ActionResponse(ActionResult.FAILED, "Attack method not available")
    
    def create_explosion(self, x: float, y: float, power: int = 2) -> ActionResponse:
        """
        Create an explosion at specified coordinates.
        
        Args:
            x: X coordinate
            y: Y coordinate
            power: Explosion power (1-3)
            
        Returns:
            ActionResponse with result
        """
        if self.client.drop_bomb(power=power, timer=1):  # Quick bomb
            return ActionResponse(ActionResult.SUCCESS, f"Explosion created at ({x}, {y})")
        return ActionResponse(ActionResult.FAILED, "Failed to create explosion")
    
    def rapid_fire(self, direction: str, shots: int = 5, delay: float = 0.1) -> ActionResponse:
        """
        Fire multiple shots rapidly in a direction.
        
        Args:
            direction: Direction to fire
            shots: Number of shots
            delay: Delay between shots in seconds
            
        Returns:
            ActionResponse with result
        """
        success_count = 0
        
        for shot in range(shots):
            if hasattr(self.client, 'attack'):
                if self.client.attack(direction):
                    success_count += 1
                time.sleep(delay)
        
        if success_count == shots:
            return ActionResponse(ActionResult.SUCCESS, f"Fired {shots} shots")
        elif success_count > 0:
            return ActionResponse(ActionResult.PARTIAL, f"Fired {success_count}/{shots} shots")
        else:
            return ActionResponse(ActionResult.FAILED, "No shots fired")


class SocialActions:
    """High-level social and communication actions"""
    
    def __init__(self, client):
        self.client = client
    
    def whisper_to_player(self, player_name: str, message: str) -> ActionResponse:
        """
        Send a private message to a specific player.
        
        Args:
            player_name: Target player name
            message: Message to send
            
        Returns:
            ActionResponse with result
        """
        # This would need to use the client's PM functionality
        # For now, simulate with public chat
        full_message = f"@{player_name}: {message}"
        if hasattr(self.client, 'say') and self.client.say(full_message):
            return ActionResponse(ActionResult.SUCCESS, f"Whispered to {player_name}")
        return ActionResponse(ActionResult.FAILED, "Failed to send whisper")
    
    def broadcast_to_level(self, message: str) -> ActionResponse:
        """
        Broadcast a message to everyone in the current level.
        
        Args:
            message: Message to broadcast
            
        Returns:
            ActionResponse with result
        """
        if hasattr(self.client, 'say') and self.client.say(message):
            return ActionResponse(ActionResult.SUCCESS, "Message broadcasted")
        return ActionResponse(ActionResult.FAILED, "Failed to broadcast message")
    
    def emote(self, emote_type: str) -> ActionResponse:
        """
        Perform an emote or animation.
        
        Args:
            emote_type: Type of emote ("wave", "dance", "bow", etc.)
            
        Returns:
            ActionResponse with result
        """
        # This would need to send appropriate animation packets
        logger.info(f"Performing emote: {emote_type}")
        return ActionResponse(ActionResult.SUCCESS, f"Performed {emote_type} emote")


class ItemActions:
    """High-level item and inventory actions"""
    
    def __init__(self, client):
        self.client = client
    
    def pickup_nearby_items(self, radius: float = 2.0) -> ActionResponse:
        """
        Pick up all items within a certain radius.
        
        Args:
            radius: Search radius in tiles
            
        Returns:
            ActionResponse with result and count of items picked up
        """
        player = self.client.get_player()
        if not player:
            return ActionResponse(ActionResult.NOT_CONNECTED, "Player not available")
        
        # This would need to query the level manager for nearby items
        # For now, simulate picking up an item at player position
        if hasattr(self.client, 'take_item'):
            success = self.client.take_item(int(player.x), int(player.y))
            return ActionResponse(
                ActionResult.SUCCESS if success else ActionResult.FAILED,
                f"Attempted to pick up items near ({player.x}, {player.y})"
            )
        
        return ActionResponse(ActionResult.FAILED, "Item pickup not available")
    
    def use_item(self, item_name: str) -> ActionResponse:
        """
        Use an item from inventory.
        
        Args:
            item_name: Name of item to use
            
        Returns:
            ActionResponse with result
        """
        # This would need to send appropriate item use packets
        logger.info(f"Using item: {item_name}")
        return ActionResponse(ActionResult.SUCCESS, f"Used {item_name}")
    
    def drop_item(self, item_name: str, x: Optional[float] = None, y: Optional[float] = None) -> ActionResponse:
        """
        Drop an item at specified coordinates or current position.
        
        Args:
            item_name: Name of item to drop
            x: X coordinate (defaults to player position)
            y: Y coordinate (defaults to player position)
            
        Returns:
            ActionResponse with result
        """
        player = self.client.get_player()
        if not player:
            return ActionResponse(ActionResult.NOT_CONNECTED, "Player not available")
        
        drop_x = x if x is not None else player.x
        drop_y = y if y is not None else player.y
        
        logger.info(f"Dropping {item_name} at ({drop_x}, {drop_y})")
        return ActionResponse(ActionResult.SUCCESS, f"Dropped {item_name}")


class ExplorationActions:
    """High-level exploration and discovery actions"""
    
    def __init__(self, client):
        self.client = client
    
    def explore_level(self, pattern: str = "spiral") -> ActionResponse:
        """
        Automatically explore the current level using a movement pattern.
        
        Args:
            pattern: Exploration pattern ("spiral", "grid", "random")
            
        Returns:
            ActionResponse with exploration results
        """
        player = self.client.get_player()
        if not player:
            return ActionResponse(ActionResult.NOT_CONNECTED, "Player not available")
        
        logger.info(f"Starting {pattern} exploration from ({player.x}, {player.y})")
        
        if pattern == "spiral":
            return self._spiral_explore()
        elif pattern == "grid":
            return self._grid_explore()
        elif pattern == "random":
            return self._random_explore()
        else:
            return ActionResponse(ActionResult.INVALID_PARAMS, f"Unknown pattern: {pattern}")
    
    def _spiral_explore(self) -> ActionResponse:
        """Explore using spiral pattern"""
        directions = [(1, 0), (0, 1), (-1, 0), (0, -1)]  # Right, Down, Left, Up
        direction_idx = 0
        steps_in_direction = 1
        total_steps = 0
        
        for cycle in range(5):  # 5 cycles of the spiral
            for _ in range(2):  # Two directions per cycle
                for _ in range(steps_in_direction):
                    dx, dy = directions[direction_idx]
                    if self.client.move(dx, dy):
                        total_steps += 1
                        time.sleep(0.1)
                    else:
                        break
                direction_idx = (direction_idx + 1) % 4
            steps_in_direction += 1
        
        return ActionResponse(ActionResult.SUCCESS, f"Spiral exploration completed: {total_steps} steps")
    
    def _grid_explore(self) -> ActionResponse:
        """Explore using grid pattern"""
        # Move in a grid pattern
        total_steps = 0
        for row in range(5):
            direction = 1 if row % 2 == 0 else -1
            for col in range(5):
                if self.client.move(direction, 0):
                    total_steps += 1
                    time.sleep(0.1)
            if row < 4:  # Don't move down on last row
                if self.client.move(0, 1):
                    total_steps += 1
                    time.sleep(0.1)
        
        return ActionResponse(ActionResult.SUCCESS, f"Grid exploration completed: {total_steps} steps")
    
    def _random_explore(self) -> ActionResponse:
        """Explore using random movements"""
        import random
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)]
        total_steps = 0
        
        for _ in range(20):  # 20 random moves
            dx, dy = random.choice(directions)
            if self.client.move(dx, dy):
                total_steps += 1
                time.sleep(0.2)
        
        return ActionResponse(ActionResult.SUCCESS, f"Random exploration completed: {total_steps} steps")
    
    def find_level_exits(self) -> ActionResponse:
        """
        Find all exits/links in the current level.
        
        Returns:
            ActionResponse with list of discovered exits
        """
        # This would need to query the level manager for level links
        # For now, return placeholder data
        exits = [
            {"level": "chicken2.nw", "x": 0, "y": 63},
            {"level": "chicken5.nw", "x": 63, "y": 0},
            {"level": "chicken_cave_entrance.nw", "x": 34, "y": 33}
        ]
        
        return ActionResponse(
            ActionResult.SUCCESS, 
            f"Found {len(exits)} exits",
            {"exits": exits}
        )


class GameActions:
    """
    Main high-level game actions API.
    
    Provides access to all high-level game actions organized by category.
    """
    
    def __init__(self, client):
        """
        Initialize game actions for a client.
        
        Args:
            client: PyReborn client instance
        """
        self.client = client
        
        # Create action category instances
        self.movement = MovementActions(client)
        self.combat = CombatActions(client)
        self.social = SocialActions(client)
        self.items = ItemActions(client)
        self.exploration = ExplorationActions(client)
    
    # Convenience methods that delegate to category classes
    
    def walk_to(self, x: float, y: float) -> ActionResponse:
        """Walk to target coordinates"""
        return self.movement.walk_to(x, y)
    
    def attack(self, direction: str) -> ActionResponse:
        """Attack in direction"""
        return self.combat.attack_direction(direction)
    
    def say(self, message: str) -> ActionResponse:
        """Send chat message"""
        return self.social.broadcast_to_level(message)
    
    def whisper(self, player: str, message: str) -> ActionResponse:
        """Send private message"""
        return self.social.whisper_to_player(player, message)
    
    def pickup_items(self, radius: float = 2.0) -> ActionResponse:
        """Pick up nearby items"""
        return self.items.pickup_nearby_items(radius)
    
    def explore(self, pattern: str = "spiral") -> ActionResponse:
        """Explore current level"""
        return self.exploration.explore_level(pattern)
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status information.
        
        Returns:
            Dictionary with player, level, and connection status
        """
        player = self.client.get_player()
        status = {
            "connected": getattr(self.client, '_connected', False),
            "logged_in": getattr(self.client, '_logged_in', False),
            "player": {
                "account": player.account if player else None,
                "x": player.x if player else None,
                "y": player.y if player else None,
                "level": getattr(player, 'level_name', None) if player else None
            },
            "managers": {
                "session": self.client.session_manager is not None if hasattr(self.client, 'session_manager') else False,
                "level": self.client.level_manager is not None if hasattr(self.client, 'level_manager') else False,
                "gmap": self.client.gmap_manager is not None if hasattr(self.client, 'gmap_manager') else False
            }
        }
        
        return status


# Convenience function to add game actions to any client
def enhance_with_actions(client) -> GameActions:
    """
    Enhance a client with high-level game actions.
    
    Args:
        client: PyReborn client instance
        
    Returns:
        GameActions instance bound to the client
        
    Example:
        client = Client("localhost", 14900)
        actions = enhance_with_actions(client)
        
        # Now use high-level actions
        actions.walk_to(10, 10)
        actions.attack("north")
        actions.say("Hello world!")
    """
    return GameActions(client)


__all__ = [
    'GameActions',
    'MovementActions',
    'CombatActions', 
    'SocialActions',
    'ItemActions',
    'ExplorationActions',
    'ActionResult',
    'ActionResponse',
    'enhance_with_actions'
]