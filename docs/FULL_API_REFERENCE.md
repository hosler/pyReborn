# PyReborn Full API Reference - 100% GServer-v2 Coverage

## Table of Contents
1. [Installation & Setup](#installation--setup)
2. [Core Features](#core-features)
3. [Item System](#item-system)
4. [Combat System](#combat-system)
5. [NPC System](#npc-system)
6. [High-Precision Movement](#high-precision-movement)
7. [Extended Attributes](#extended-attributes)
8. [Event System](#event-system)
9. [Advanced Features](#advanced-features)

## Installation & Setup

### Creating a Client

```python
from pyreborn import RebornClient

# Create client with all features
client = RebornClient("localhost", 14900)
client.connect()
client.login("username", "password")
```

### Manual Patching (if needed)

```python
from pyreborn import RebornClient
from pyreborn.client_patch import patch_reborn_client

# Apply all enhancements to existing client
patch_reborn_client()
client = RebornClient("localhost", 14900)
```

## Core Features

### Basic Movement & Properties
```python
# High-precision movement
client.move_to(30.5, 30.25)  # Automatically uses X2/Y2 if available

# Set properties
client.set_nickname("PlayerName")
client.set_chat("Hello!")
client.set_colors(0, 1, 2, 3, 4)  # skin, coat, sleeves, shoes, belt

# Get player info
print(f"Position: {client.local_player.x}, {client.local_player.y}")
print(f"Health: {client.local_player.cur_power}/{client.local_player.max_power}")
```

## Item System

### Item Management
```python
# Pick up items
success = client.pickup_item(x=10, y=10)
picked_count = client.items.pickup_nearby_items(radius=2.0)

# Drop items
from pyreborn.protocol.enums import LevelItemType
client.drop_item(LevelItemType.GREENRUPEE, x=15, y=15)
client.drop_item(LevelItemType.BOMB)  # Drops at player position

# Open chests
client.open_chest(tile_x=20, tile_y=20)

# Carry and throw
client.set_carry_sprite("bush")  # or "pot", "bomb", etc.
client.throw_carried(power=0.8)  # 0.0 to 1.0
```

### Item Events
```python
def on_item_spawned(item):
    print(f"Item {item['type'].name} spawned at {item['x']}, {item['y']}")
    
def on_object_thrown(player_id, power, player):
    print(f"Player {player.nickname} threw object with power {power}")

client.events.subscribe(EventType.ITEM_SPAWNED, on_item_spawned)
client.events.subscribe(EventType.OBJECT_THROWN, on_object_thrown)
```

### Item Manager API
```python
# Get items in current level
items = client.item_manager.get_items_in_level(client.local_player.level)

# Check specific position
item = client.item_manager.get_item_at(level, x, y, radius=0.5)

# Inventory tracking
client.item_manager.add_to_inventory(LevelItemType.HEART, count=3)
hearts = client.item_manager.get_inventory_count(LevelItemType.HEART)
```

## Combat System

### Basic Combat
```python
# Attack players
client.hurt_player(player_id=123, damage=0.5)
client.hurt_player(player_id=123, damage=1.0, x=10, y=10)  # Specify hit location

# Hit detection
hit_ids = client.check_hit(x=10, y=10, width=3, height=3, power=1.0)

# Explosions
client.create_explosion(x=20, y=20, power=2.0, radius=4.0)

# Baddy/enemy combat
client.combat.hurt_baddy(baddy_id=5, damage=1.0)
```

### Advanced Combat
```python
# Sword attack (in front of player)
hits = client.combat.sword_attack(reach=2.5)

# Arrow attack (projectile path)
hits = client.combat.arrow_attack(target_x=30, target_y=30, power=1.0)

# Health management
current, maximum = client.combat.get_player_health()
current, maximum = client.combat.get_player_health(player_id=123)

# Check invulnerability
if not client.combat.is_invulnerable(player_id):
    client.hurt_player(player_id, 0.5)
```

### Combat Events
```python
def on_player_hurt(attacker_id, target_id, damage, new_health):
    print(f"Player {target_id} hurt by {attacker_id} for {damage} damage")
    print(f"New health: {new_health}")

def on_explosion(x, y, power, radius, creator_id):
    print(f"Explosion at ({x}, {y}) with power {power}")

client.events.subscribe(EventType.PLAYER_HURT, on_player_hurt)
client.events.subscribe(EventType.EXPLOSION, on_explosion)
```

### Combat Manager API
```python
# Track damage events
recent_damage = client.combat_manager.get_recent_damage_events(seconds=5.0)

# Create hitboxes for custom collision
client.combat_manager.create_hitbox("sword_swing", x=10, y=10, width=3, height=1, duration=0.2)

# Manual health management
client.combat_manager.set_player_health(player_id, health=2.5, max_health=3.0)
client.combat_manager.heal_player(player_id, amount=1.0)
```

## NPC System

### NPC Creation & Management
```python
# Create NPCs
npc_id = client.create_npc(x=25, y=25, image="oldman.png", script="say Hello!")
npc_id = client.create_npc(x=30, y=30, image="guard.gif", script="if (playerenters) { say Stop!; }")

# Delete NPCs
client.delete_npc(npc_id)

# Update NPC properties
from pyreborn.protocol.enums import NPCProp
client.npcs.update_npc_prop(npc_id, NPCProp.IMAGE, "newimage.png")
client.npcs.set_npc_nickname(npc_id, "Shop Keeper")
client.npcs.move_npc(npc_id, new_x=35, new_y=35)
```

### NPC Interaction
```python
# Touch/activate NPCs
client.touch_npc(npc_id)  # Trigger touch event
client.activate_npc(npc_id)  # Like pressing 'A'

# Find nearby NPCs
nearby_npcs = client.npcs.find_nearby_npcs(radius=3.0)
client.npcs.interact_with_nearest_npc()

# Trigger actions
client.trigger_action("shop", "buy,sword")
client.trigger_action("warp", "level2.nw,30,30")
client.trigger_action("giveplayer", "rupees,100")
```

### NPC Events
```python
def on_npc_touch(npc, player_id):
    print(f"NPC {npc.name} touched by player {player_id}")
    
def on_npc_action(npc_id, action, params):
    print(f"NPC {npc_id} action: {action} with params: {params}")

# Register callbacks
client.npc_manager.add_touch_callback(on_npc_touch)
client.events.subscribe(EventType.NPC_ACTION, on_npc_action)
```

### NPC Manager API
```python
# Get NPC data
npc = client.npc_manager.get_npc(npc_id)
level_npcs = client.npc_manager.get_npcs_in_level("level.nw")

# Extended NPC properties
npc.set_save(0, "quest_started")  # save0-save9
npc.set_gattrib(1, "special_type")  # gattrib1-30

value = npc.get_save(0, default="no_quest")
attr = npc.get_gattrib(1)

# NPC state
npc.visible = False
npc.blocking = True
npc.touch_enabled = False
```

## High-Precision Movement

### Using High-Precision Coordinates
```python
# Movement automatically uses high precision if available
client.move_to(30.123, 25.456)  # Sub-pixel precision

# Access high-precision values
print(f"Precise position: {client.local_player.x2}, {client.local_player.y2}")

# Z-coordinate support
client.local_player.z = 0.5  # Height/layer
client.move_to(30, 30)  # Also sends Z2
```

### Manual Property Setting
```python
from pyreborn.protocol.enums import PlayerProp

# Set high-precision properties directly
client.set_player_prop(PlayerProp.PLPROP_X2, 30.123)
client.set_player_prop(PlayerProp.PLPROP_Y2, 25.456)
client.set_player_prop(PlayerProp.PLPROP_Z2, 0.5)
```

## Extended Attributes

### Using GATTRIB 1-30
```python
# Set extended attributes
for i in range(1, 31):
    prop = getattr(PlayerProp, f"PLPROP_GATTRIB{i}")
    client.set_player_prop(prop, f"value_{i}")

# Common uses:
client.set_player_prop(PlayerProp.PLPROP_GATTRIB1, "clan_name")
client.set_player_prop(PlayerProp.PLPROP_GATTRIB2, "rank") 
client.set_player_prop(PlayerProp.PLPROP_GATTRIB3, "score")
# ... up to GATTRIB30
```

### Special Properties
```python
# Operating system type
client.set_player_prop(PlayerProp.PLPROP_OSTYPE, "windows")

# Text encoding
client.set_player_prop(PlayerProp.PLPROP_TEXTCODEPAGE, "utf-8")

# Community name (Graal v5)
client.set_player_prop(PlayerProp.PLPROP_COMMUNITYNAME, "MyName")

# Player list category
client.set_player_prop(PlayerProp.PLPROP_PLAYERLISTCATEGORY, 1)  # Staff tab
```

## Event System

### All Available Events
```python
# Item events
EventType.ITEM_SPAWNED      # Item appeared
EventType.ITEM_REMOVED      # Item picked up
EventType.CHEST_OPENED      # Chest was opened
EventType.OBJECT_THROWN     # Object was thrown

# Combat events  
EventType.PLAYER_HURT       # Player took damage
EventType.EXPLOSION         # Explosion occurred
EventType.HIT_CONFIRMED     # Hit detection confirmed
EventType.PLAYER_PUSHED     # Player was pushed

# NPC events
EventType.NPC_ADDED         # NPC created
EventType.NPC_REMOVED       # NPC deleted
EventType.NPC_UPDATED       # NPC properties changed
EventType.NPC_ACTION        # NPC performed action
EventType.NPC_MOVED         # NPC position changed
EventType.TRIGGER_RESPONSE  # Trigger action response
```

### Custom Event Handlers
```python
# Subscribe to multiple events
events_to_monitor = [
    EventType.ITEM_SPAWNED,
    EventType.PLAYER_HURT,
    EventType.NPC_ACTION
]

def universal_handler(**kwargs):
    print(f"Event data: {kwargs}")

for event in events_to_monitor:
    client.events.subscribe(event, universal_handler)
```

## Advanced Features

### Trigger Actions
```python
# Server-specific triggers
client.trigger_action("health", "full")
client.trigger_action("weapon", "add,sword")
client.trigger_action("level", "warp,start.nw")
client.trigger_action("script", "run,mycustomscript")

# With position
client.npcs.trigger_action("activate", "switch1", x=10, y=10)
```

### Batch Operations
```python
# Pick up all items in area
items_picked = 0
for item in client.item_manager.get_items_in_level(client.local_player.level):
    if abs(item.x - client.local_player.x) < 5 and abs(item.y - client.local_player.y) < 5:
        if client.pickup_item(item.x, item.y):
            items_picked += 1
            
print(f"Picked up {items_picked} items")

# Attack all nearby players
for player_id, player in client._players.items():
    if player_id == client.local_player.id:
        continue
    
    dx = abs(player.x - client.local_player.x)
    dy = abs(player.y - client.local_player.y)
    
    if dx < 3 and dy < 3:
        client.hurt_player(player_id, 0.5)
```

### Manager Access
```python
# Direct manager access for advanced operations
client.item_manager.clear_level("level.nw")
client.combat_manager.reset_player(player_id)
client.npc_manager.clear_all()

# Cleanup
client.combat_manager.cleanup_expired()
```

## Best Practices

1. **Always check return values**
   ```python
   if client.pickup_item(x, y):
       print("Item picked up successfully")
   ```

2. **Handle events asynchronously**
   ```python
   def delayed_response(player_id):
       time.sleep(1)
       client.hurt_player(player_id, 0.5)
       
   threading.Thread(target=delayed_response, args=(player_id,)).start()
   ```

3. **Use manager APIs for complex operations**
   ```python
   # Instead of manual tracking
   items = client.item_manager.get_items_in_level(level)
   # Not: items = my_custom_item_list
   ```

4. **Subscribe to events early**
   ```python
   # Before login
   client.events.subscribe(EventType.LOGIN_SUCCESS, on_login)
   client.login(username, password)
   ```

## Troubleshooting

### Common Issues

1. **Features not available**
   ```python
   # Ensure client is patched
   from pyreborn.client_patch import apply_all_enhancements
   apply_all_enhancements()
   ```

2. **Packet not recognized**
   - Check server version supports the feature
   - Some features are GServer-v2 specific

3. **Events not firing**
   - Ensure event subscription before the action
   - Check event name spelling

### Debug Mode
```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Will show all packet sends/receives
```

## Complete Example

```python
from pyreborn import RebornClient, EventType
from pyreborn.protocol.enums import LevelItemType

# Create and connect
client = RebornClient("localhost", 14900)
client.connect()
client.login("testuser", "password")

# Set up character
client.set_nickname("PowerUser")
client.move_to(30, 30)

# Combat example
nearby_players = client.check_hit(client.local_player.x, client.local_player.y, 5, 5)
for player_id in nearby_players:
    client.hurt_player(player_id, 0.5)

# Item example  
client.drop_item(LevelItemType.BOMB)
client.items.pickup_nearby_items(radius=10)

# NPC example
npc = client.create_npc(35, 35, "guard.png", "say Don't pass!")
client.touch_npc(npc)

# Stay connected
import time
while client.connected:
    time.sleep(1)
```

---

## Congratulations! 🎉

You now have access to 100% of the GServer-v2 protocol features in PyReborn!