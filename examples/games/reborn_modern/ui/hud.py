"""
HUD (Heads-Up Display)
======================

Modern HUD showing player stats, inventory, and game info.
"""

import pygame
import logging
from typing import Dict, List, Optional

from pyreborn.core.modular_client import ModularRebornClient
from pyreborn.models import Player


logger = logging.getLogger(__name__)


class HUD:
    """Game HUD with player information"""
    
    def __init__(self, screen: pygame.Surface, client: ModularRebornClient):
        """Initialize HUD
        
        Args:
            screen: Pygame surface to render to
            client: PyReborn client for game data
        """
        self.screen = screen
        self.client = client
        
        # UI configuration
        self.margin = 10
        self.padding = 5
        
        # Colors
        self.bg_color = (20, 20, 30, 180)
        self.border_color = (100, 100, 120)
        self.text_color = (200, 200, 220)
        self.health_color = (200, 50, 50)
        self.mana_color = (50, 100, 200)
        
        # Fonts
        self.name_font = pygame.font.Font(None, 24)
        self.stat_font = pygame.font.Font(None, 18)
        self.info_font = pygame.font.Font(None, 16)
        
        # HUD elements
        self.show_stats = True
        self.show_inventory = False
        self.show_minimap = True
        
        # Inventory grid
        self.inventory_cols = 8
        self.inventory_rows = 4
        self.slot_size = 32
        
        logger.info("HUD initialized")
    
    def update(self, dt: float):
        """Update HUD elements"""
        # HUD updates based on events, no continuous update needed
        pass
    
    def render(self):
        """Render HUD elements"""
        if self.show_stats:
            self._render_player_stats()
            
        if self.show_inventory:
            self._render_inventory()
            
        if self.show_minimap:
            self._render_minimap()
            
        # Always show level info
        self._render_level_info()
    
    def _render_player_stats(self):
        """Render player statistics panel"""
        player = self.client.session_manager.get_player()
        if not player:
            return
        
        # Create stats panel
        panel_width = 200
        panel_height = 100
        panel_x = self.margin
        panel_y = self.margin
        
        # Background
        panel_rect = pygame.Rect(panel_x, panel_y, panel_width, panel_height)
        panel_surface = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        panel_surface.fill(self.bg_color)
        pygame.draw.rect(panel_surface, self.border_color, panel_surface.get_rect(), 1)
        
        # Player name
        y = self.padding
        name_text = self.name_font.render(player.nickname, True, self.text_color)
        panel_surface.blit(name_text, (self.padding, y))
        y += name_text.get_height() + 5
        
        # Health bar
        self._render_bar(
            panel_surface,
            self.padding,
            y,
            panel_width - self.padding * 2,
            16,
            player.hearts,
            player.max_hearts,
            self.health_color,
            "HP"
        )
        y += 20
        
        # Rupees
        rupees_text = f"Rupees: {player.rupees}"
        rupees_surface = self.stat_font.render(rupees_text, True, self.text_color)
        panel_surface.blit(rupees_surface, (self.padding, y))
        y += 20
        
        # Bombs and arrows
        items_text = f"Bombs: {player.bombs}  Arrows: {player.arrows}"
        items_surface = self.info_font.render(items_text, True, self.text_color)
        panel_surface.blit(items_surface, (self.padding, y))
        
        # Blit panel to screen
        self.screen.blit(panel_surface, (panel_x, panel_y))
    
    def _render_bar(self, surface: pygame.Surface, x: int, y: int, 
                    width: int, height: int, current: float, maximum: float,
                    color: tuple, label: str = ""):
        """Render a stat bar"""
        # Background
        bar_rect = pygame.Rect(x, y, width, height)
        pygame.draw.rect(surface, (40, 40, 50), bar_rect)
        
        # Fill
        if maximum > 0:
            fill_width = int(width * (current / maximum))
            fill_rect = pygame.Rect(x, y, fill_width, height)
            pygame.draw.rect(surface, color, fill_rect)
        
        # Border
        pygame.draw.rect(surface, self.border_color, bar_rect, 1)
        
        # Label
        if label:
            label_text = f"{label}: {int(current)}/{int(maximum)}"
            label_surface = self.info_font.render(label_text, True, self.text_color)
            label_rect = label_surface.get_rect(center=(x + width // 2, y + height // 2))
            surface.blit(label_surface, label_rect)
    
    def _render_inventory(self):
        """Render inventory grid"""
        # Calculate inventory position (bottom-left)
        inv_width = self.inventory_cols * (self.slot_size + 2) + self.padding * 2
        inv_height = self.inventory_rows * (self.slot_size + 2) + self.padding * 2
        inv_x = self.margin
        inv_y = self.screen.get_height() - inv_height - self.margin
        
        # Background
        inv_rect = pygame.Rect(inv_x, inv_y, inv_width, inv_height)
        inv_surface = pygame.Surface((inv_width, inv_height), pygame.SRCALPHA)
        inv_surface.fill(self.bg_color)
        pygame.draw.rect(inv_surface, self.border_color, inv_surface.get_rect(), 2)
        
        # Draw slots
        for row in range(self.inventory_rows):
            for col in range(self.inventory_cols):
                slot_x = self.padding + col * (self.slot_size + 2)
                slot_y = self.padding + row * (self.slot_size + 2)
                
                slot_rect = pygame.Rect(slot_x, slot_y, self.slot_size, self.slot_size)
                pygame.draw.rect(inv_surface, (60, 60, 80), slot_rect)
                pygame.draw.rect(inv_surface, self.border_color, slot_rect, 1)
                
                # TODO: Draw item if present
                # item = self.client.item_manager.get_inventory_item(row * self.inventory_cols + col)
                # if item:
                #     self._render_item(inv_surface, slot_rect, item)
        
        # Blit to screen
        self.screen.blit(inv_surface, (inv_x, inv_y))
    
    def _render_minimap(self):
        """Render minimap"""
        # Minimap size
        map_size = 150
        map_x = self.screen.get_width() - map_size - self.margin
        map_y = self.margin
        
        # Background
        map_rect = pygame.Rect(map_x, map_y, map_size, map_size)
        map_surface = pygame.Surface((map_size, map_size), pygame.SRCALPHA)
        map_surface.fill(self.bg_color)
        pygame.draw.rect(map_surface, self.border_color, map_surface.get_rect(), 2)
        
        # Get current level
        level = self.client.level_manager.get_current_level()
        if level:
            # Calculate scale
            scale_x = map_size / level.width
            scale_y = map_size / level.height
            scale = min(scale_x, scale_y) * 0.9  # Leave some margin
            
            # Center offset
            offset_x = (map_size - level.width * scale) / 2
            offset_y = (map_size - level.height * scale) / 2
            
            # Draw level outline
            level_rect = pygame.Rect(
                int(offset_x),
                int(offset_y),
                int(level.width * scale),
                int(level.height * scale)
            )
            pygame.draw.rect(map_surface, (80, 80, 100), level_rect, 1)
            
            # Draw player position
            player = self.client.session_manager.get_player()
            if player:
                player_x = int(offset_x + player.x * scale)
                player_y = int(offset_y + player.y * scale)
                pygame.draw.circle(map_surface, (200, 50, 50), (player_x, player_y), 3)
                
                # Draw view cone
                # TODO: Calculate based on camera/view direction
                
            # Draw other players
            # TODO: Get other players when SessionManager exposes them
            # for other in self.client.session_manager.get_all_players().values():
            #     if other.player_id != player.player_id:
            #         other_x = int(offset_x + other.x * scale)
            #         other_y = int(offset_y + other.y * scale)
            #         pygame.draw.circle(map_surface, (100, 200, 100), (other_x, other_y), 2)
        
        # Level name
        if level:
            level_text = self.info_font.render(level.name, True, self.text_color)
            text_rect = level_text.get_rect(centerx=map_size // 2, y=5)
            map_surface.blit(level_text, text_rect)
        
        # Blit to screen
        self.screen.blit(map_surface, (map_x, map_y))
    
    def _render_level_info(self):
        """Render current level information"""
        # Position (top-center)
        info_width = 300
        info_height = 30
        info_x = (self.screen.get_width() - info_width) // 2
        info_y = self.margin
        
        # Get level info
        level = self.client.level_manager.get_current_level()
        if not level:
            return
        
        # Create info panel
        info_surface = pygame.Surface((info_width, info_height), pygame.SRCALPHA)
        info_surface.fill(self.bg_color)
        pygame.draw.rect(info_surface, self.border_color, info_surface.get_rect(), 1)
        
        # Level name
        level_name = level.name
        
        # Check if in GMAP
        if self.client.gmap_manager and self.client.gmap_manager.is_active():
            gmap_name = self.client.gmap_manager.get_current_gmap()
            if gmap_name:
                level_name = f"{gmap_name}.gmap - {level_name}"
        
        level_text = self.stat_font.render(level_name, True, self.text_color)
        text_rect = level_text.get_rect(center=(info_width // 2, info_height // 2))
        info_surface.blit(level_text, text_rect)
        
        # Blit to screen
        self.screen.blit(info_surface, (info_x, info_y))
    
    def toggle_inventory(self):
        """Toggle inventory visibility"""
        self.show_inventory = not self.show_inventory
        logger.debug(f"Inventory {'shown' if self.show_inventory else 'hidden'}")
    
    def toggle_minimap(self):
        """Toggle minimap visibility"""
        self.show_minimap = not self.show_minimap
        logger.debug(f"Minimap {'shown' if self.show_minimap else 'hidden'}")
    
    def show_notification(self, message: str, duration: float = 3.0):
        """Show a notification message"""
        # TODO: Implement notification system
        logger.info(f"Notification: {message}")