"""
Classic Graal Constants - Tile IDs and game values matching original Graal
"""

# Item pickup tile IDs (from pics1.png)
class ClassicItems:
    # Hearts (full heart pickup)
    HEART_TILES = [324, 325, 340, 341]  # 2x2 animated heart
    
    # Rupees (money)
    GREEN_RUPEE_TILES = [336, 337, 352, 353]  # 1 rupee
    BLUE_RUPEE_TILES = [338, 339, 354, 355]  # 5 rupees
    RED_RUPEE_TILES = [656, 657, 672, 673]  # 20 rupees
    
    # Bombs
    BOMB_TILES = [328, 329, 344, 345]  # Bomb pickup
    
    # Arrows
    ARROW_TILES = [332, 333, 348, 349]  # 5 arrows
    
    # Keys
    KEY_TILES = [658, 659, 674, 675]  # Key pickup
    
    # Heart containers
    HEART_CONTAINER_TILES = [660, 661, 676, 677]  # Increases max hearts
    
    # Chest types (2x2 each)
    CHEST_BROWN = 640  # Base tile for brown chest
    CHEST_BLUE = 644   # Base tile for blue chest
    CHEST_RED = 648    # Base tile for red chest
    CHEST_GREEN = 652  # Base tile for green chest

# Item values
class ItemValues:
    GREEN_RUPEE = 1
    BLUE_RUPEE = 5
    RED_RUPEE = 20
    ARROW_BUNDLE = 5
    BOMB_PICKUP = 1
    HEART_HEAL = 1.0  # Full heart
    
# Classic game constants
class ClassicConstants:
    # Movement (tiles per second)
    MOVE_SPEED = 20.0  # Very fast movement
    SWIM_SPEED = 0.1  # Slower in water
    HORSE_SPEED = 0.4  # Double speed on horse
    
    # Combat
    SWORD_DAMAGE = 0.5  # Half heart damage
    KNOCKBACK_DISTANCE = 2.0  # Tiles
    INVINCIBILITY_TIME = 1.5  # Seconds after hit
    
    # Animations
    FLOAT_AMPLITUDE = 0.25  # Item float distance
    FLOAT_SPEED = 2.0  # Oscillations per second
    PICKUP_RISE_SPEED = 2.0  # Tiles per second when picked up
    PICKUP_DURATION = 1.0  # Seconds for pickup animation
    
    # Respawn times
    BUSH_RESPAWN_TIME = 30.0  # Seconds
    GRASS_RESPAWN_TIME = 60.0  # Seconds
    
    # Drop rates (0-100)
    GRASS_DROP_RATE = 25  # 25% chance
    GRASS_HEART_CHANCE = 40  # 40% of drops are hearts
    GRASS_RUPEE_CHANCE = 40  # 40% of drops are rupees  
    GRASS_ARROW_CHANCE = 15  # 15% of drops are arrows
    GRASS_BOMB_CHANCE = 5   # 5% of drops are bombs

# Tile type additions for Classic items
class ClassicTileTypes:
    # Pickupable items (add to tile_defs.py)
    HEART = 20
    RUPEE = 21
    BOMB = 22
    ARROW = 23
    KEY = 24
    HEART_CONTAINER = 25
    
    # Cuttable tiles
    GRASS = 26
    TALL_GRASS = 27
    
    # Special tiles
    SIGN_POST = 28
    HORSE = 29