"""
Debug overlay for GMAP grid visualization
"""

import pygame
import time
import logging

logger = logging.getLogger(__name__)

def draw_gmap_grid_overlay(renderer, screen):
    """Draw a grid overlay showing GMAP level loading status
    
    Args:
        renderer: GameRenderer instance
        screen: Pygame screen surface
    """
    if not hasattr(renderer, 'gmap_handler') or not renderer.gmap_handler or not renderer.gmap_handler.current_gmap:
        return
        
    gmap_handler = renderer.gmap_handler
    
    # Create semi-transparent overlay
    overlay = pygame.Surface((600, 600))
    overlay.set_alpha(220)
    overlay.fill((20, 20, 20))
    
    # Position in top-right corner
    overlay_x = screen.get_width() - 620
    overlay_y = 20
    
    # Draw title
    font = pygame.font.Font(None, 24)
    title = font.render(f"GMAP: {gmap_handler.current_gmap}", True, (255, 255, 255))
    overlay.blit(title, (10, 10))
    
    # Grid settings
    grid_start_x = 10
    grid_start_y = 40
    cell_size = 40
    
    # Get GMAP dimensions (default to 10x10 if not set)
    width = getattr(gmap_handler, 'gmap_width', 10)
    height = getattr(gmap_handler, 'gmap_height', 10)
    
    # Draw grid cells
    for row in range(height):
        for col in range(width):
            x = grid_start_x + col * cell_size
            y = grid_start_y + row * cell_size
            
            # Get segment name for this position
            segment_name = gmap_handler.get_segment_name(col, row)
            
            # Determine cell color
            if segment_name in gmap_handler.level_objects:
                # Level is loaded
                if (hasattr(renderer, 'game_state') and renderer.game_state and 
                    renderer.game_state.current_level and 
                    renderer.game_state.current_level.name == segment_name):
                    # Current level
                    color = (255, 255, 0)  # Yellow
                else:
                    # Loaded level
                    color = (0, 200, 0)  # Green
            else:
                # Not loaded
                color = (50, 50, 50)  # Dark gray
            
            # Draw cell
            pygame.draw.rect(overlay, color, (x, y, cell_size-1, cell_size-1))
            
            # Draw segment identifier
            if segment_name and segment_name in gmap_handler.level_objects:
                font_small = pygame.font.Font(None, 12)
                # Extract segment code (e.g., "d8" from "zlttp-d8.nw")
                if '-' in segment_name:
                    seg_code = segment_name.split('-')[1].replace('.nw', '')
                    text = font_small.render(seg_code, True, (0, 0, 0))
                    text_rect = text.get_rect(center=(x + cell_size//2, y + cell_size//2))
                    overlay.blit(text, text_rect)
            
            # Draw grid lines
            pygame.draw.rect(overlay, (100, 100, 100), (x, y, cell_size, cell_size), 1)
    
    # Draw coordinate labels
    font_coord = pygame.font.Font(None, 14)
    
    # Column labels (a-z)
    for col in range(min(26, width)):
        x = grid_start_x + col * cell_size + cell_size//2
        label = font_coord.render(chr(ord('a') + col), True, (200, 200, 200))
        label_rect = label.get_rect(center=(x, grid_start_y - 10))
        overlay.blit(label, label_rect)
    
    # Row labels (0-9+)
    for row in range(height):
        y = grid_start_y + row * cell_size + cell_size//2
        label = font_coord.render(str(row), True, (200, 200, 200))
        label_rect = label.get_rect(midright=(grid_start_x - 5, y))
        overlay.blit(label, label_rect)
    
    # Status info
    info_y = grid_start_y + height * cell_size + 20
    info_font = pygame.font.Font(None, 18)
    
    # Loaded levels count
    loaded_count = len(gmap_handler.level_objects)
    info_text = info_font.render(f"Loaded: {loaded_count} levels", True, (0, 255, 0))
    overlay.blit(info_text, (grid_start_x, info_y))
    
    # Current position
    if hasattr(renderer, 'game_state') and renderer.game_state and renderer.game_state.current_level:
        level_name = renderer.game_state.current_level.name
        segment_info = gmap_handler.parse_segment_name(level_name)
        if segment_info:
            _, col, row = segment_info
            pos_text = info_font.render(f"Position: [{col}, {row}] ({level_name})", True, (255, 255, 0))
            overlay.blit(pos_text, (grid_start_x, info_y + 25))
    
    # Camera info
    if hasattr(renderer, 'camera_x'):
        cam_text = info_font.render(f"Camera: ({renderer.camera_x:.1f}, {renderer.camera_y:.1f})", True, (150, 150, 255))
        overlay.blit(cam_text, (grid_start_x, info_y + 50))
    
    # Legend
    legend_y = info_y + 80
    legend_items = [
        ((255, 255, 0), "Current"),
        ((0, 200, 0), "Loaded"),
        ((50, 50, 50), "Not loaded")
    ]
    
    for i, (color, label) in enumerate(legend_items):
        x = grid_start_x + i * 100
        pygame.draw.rect(overlay, color, (x, legend_y, 15, 15))
        text = info_font.render(label, True, (200, 200, 200))
        overlay.blit(text, (x + 20, legend_y))
    
    # Draw the overlay on screen
    screen.blit(overlay, (overlay_x, overlay_y))
    
    # Draw border around overlay
    pygame.draw.rect(screen, (255, 255, 255), (overlay_x, overlay_y, 600, 600), 2)