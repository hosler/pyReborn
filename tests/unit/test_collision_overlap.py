#!/usr/bin/env python3
"""
Test collision box overlap detection for level links
"""

def check_overlap(player_x, player_y, link_x, link_y, link_w, link_h):
    """Check if player's collision box overlaps with link area"""
    # Player collision box parameters
    player_width = 1.0   # Full tile width
    player_height = 0.5  # Half tile height (feet/shadow area)
    offset_x = 1.0       # Offset right by 1 tile
    offset_y = 2.0       # Offset down by 2 tiles
    
    # Apply offsets to get actual collision box position
    collision_x = player_x + offset_x
    collision_y = player_y + offset_y
    
    # Check AABB collision with epsilon for edge touching
    epsilon = 0.01  # Small tolerance for edge detection
    overlaps = (collision_x < link_x + link_w + epsilon and
               collision_x + player_width > link_x - epsilon and
               collision_y < link_y + link_h + epsilon and
               collision_y + player_height > link_y - epsilon)
    
    print(f"Player at ({player_x:.1f}, {player_y:.1f})")
    print(f"Collision box at ({collision_x:.1f}, {collision_y:.1f}) size ({player_width}x{player_height})")
    print(f"Link at ({link_x}, {link_y}) size ({link_w}x{link_h})")
    print(f"Overlaps: {overlaps}")
    
    if overlaps:
        print("✅ COLLISION DETECTED - Link should trigger!")
    else:
        # Calculate distance to show how close we are
        dx = 0
        dy = 0
        if collision_x + player_width <= link_x:
            dx = link_x - (collision_x + player_width)
        elif collision_x >= link_x + link_w:
            dx = collision_x - (link_x + link_w)
        
        if collision_y + player_height <= link_y:
            dy = link_y - (collision_y + player_height)
        elif collision_y >= link_y + link_h:
            dy = collision_y - (link_y + link_h)
        
        print(f"❌ No collision - Distance: x={dx:.1f}, y={dy:.1f}")
    
    return overlaps

# Test case: Player at (74.9, 87.1) near chicken_house1.nw link at (75, 88)
print("=== Test 1: Player at (74.9, 87.1) near door link ===")
check_overlap(74.9, 87.1, 75, 88, 2, 1)

print("\n=== Test 2: Player slightly closer at (74.9, 86.5) ===")
check_overlap(74.9, 86.5, 75, 88, 2, 1)

print("\n=== Test 3: Player at exact door position (74.0, 86.0) ===")
check_overlap(74.0, 86.0, 75, 88, 2, 1)

print("\n=== Test 4: Player walking into door from left (73.5, 86.0) ===")
check_overlap(73.5, 86.0, 75, 88, 2, 1)

print("\n=== Test 5: Player collision box edge touches link (73.0, 85.5) ===")
check_overlap(73.0, 85.5, 75, 88, 2, 1)

print("\n=== Test 6: Player collision box edge EXACTLY touches link (74.0, 85.5) ===")
check_overlap(74.0, 85.5, 75, 88, 2, 1)

print("\n=== Test 7: Player walking toward door from below (73.9, 87.5) ===")
check_overlap(73.9, 87.5, 75, 88, 2, 1)

print("\n=== Test 8: Edge case - player 0.001 away from link ===")
check_overlap(73.999, 85.5, 75, 88, 2, 1)

print("\n=== Explanation ===")
print("The player's collision box is offset from their position:")
print("- Collision box is 1.0 tiles to the right (offset_x)")
print("- Collision box is 2.0 tiles down (offset_y)")
print("- So if player is at (X, Y), collision box is at (X+1, Y+2)")
print("- Collision box size is 1.0x0.5 tiles")
print("\nFor a door link at (75, 88) with size 2x1:")
print("- Link covers tiles from (75, 88) to (77, 89)")
print("- With epsilon=0.01, collision box edges can be up to 0.01 tiles away and still trigger")