"""
Render Mode Enumeration
======================

Defines the different rendering modes for the game.
"""

from enum import Enum, auto


class RenderMode(Enum):
    """Rendering mode enumeration"""
    
    SINGLE_LEVEL = auto()    # Rendering a single level
    GMAP = auto()           # Rendering multiple levels in GMAP mode
    TRANSITIONING = auto()  # Transitioning between modes
    LOADING = auto()        # Loading state