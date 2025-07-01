"""
Optional rendering extension for PyReborn.

This extension provides level rendering capabilities using PIL.
It's completely optional and not required for bot functionality.

To use:
    from pyreborn.extensions.rendering import LevelRenderer
    
Note: Requires PIL/Pillow to be installed.
"""

try:
    from .level_renderer import LevelRenderer
    __all__ = ['LevelRenderer']
except ImportError:
    # PIL not installed, rendering not available
    __all__ = []