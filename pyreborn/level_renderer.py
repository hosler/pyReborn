"""
Easy level visualization helper for pyReborn bots
"""

from PIL import Image
from typing import Optional, Tuple

class LevelRenderer:
    """Helper class for bots to easily render level images"""
    
    def __init__(self, tileset_path: str = "Pics1formatwithcliffs.png"):
        """Initialize with tileset"""
        self.tileset = Image.open(tileset_path)
        self.tile_size = 16
    
    def render_level(self, level, width: Optional[int] = None, height: Optional[int] = None) -> Image.Image:
        """Render entire level or specified area to image"""
        if width is None:
            width = level.width
        if height is None:
            height = level.height
        
        # Create output image
        output_img = Image.new('RGB', (width * self.tile_size, height * self.tile_size))
        
        # Render each tile
        for y in range(height):
            for x in range(width):
                tile_img = self.get_tile_image(level, x, y)
                if tile_img:
                    output_img.paste(tile_img, (x * self.tile_size, y * self.tile_size))
        
        return output_img
    
    def render_area(self, level, start_x: int, start_y: int, width: int, height: int) -> Image.Image:
        """Render specific area of level"""
        output_img = Image.new('RGB', (width * self.tile_size, height * self.tile_size))
        
        for y in range(height):
            for x in range(width):
                level_x = start_x + x
                level_y = start_y + y
                
                tile_img = self.get_tile_image(level, level_x, level_y)
                if tile_img:
                    output_img.paste(tile_img, (x * self.tile_size, y * self.tile_size))
        
        return output_img
    
    def get_tile_image(self, level, x: int, y: int) -> Optional[Image.Image]:
        """Get tile image for position"""
        if level.is_tile_transparent(x, y):
            return None  # Skip transparent tiles
        
        # Get tileset position
        tileset_x, tileset_y = level.get_tile_tileset_position(x, y)
        
        # Check bounds
        if (tileset_x * self.tile_size >= self.tileset.width or 
            tileset_y * self.tile_size >= self.tileset.height):
            return None
        
        # Extract tile
        tile_box = (tileset_x * self.tile_size, tileset_y * self.tile_size, 
                   (tileset_x + 1) * self.tile_size, (tileset_y + 1) * self.tile_size)
        return self.tileset.crop(tile_box)
    
    def save_level_snapshot(self, level, filename: str, width: Optional[int] = None, height: Optional[int] = None):
        """Save level snapshot to file"""
        img = self.render_level(level, width, height)
        img.save(filename)
        return img
