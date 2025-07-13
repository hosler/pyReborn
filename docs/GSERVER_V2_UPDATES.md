# GServer-V2 Updates in pyReborn

This document describes the new GServer-V2 features that have been implemented in pyReborn.

## New Features

### 1. High-Precision Coordinates

The server now supports high-precision coordinates for smoother movement:

```python
# Use high-precision movement
client.move_with_precision(30.5, 45.25, z=10.0)

# Player positions are automatically updated with high precision
def on_player_update(player):
    print(f"Player at precise position: ({player.x}, {player.y}, {player.z})")

client.events.subscribe(EventType.OTHER_PLAYER_UPDATE, on_player_update)
```

### 2. Partial Board Updates

Request updates for specific regions of a level:

```python
# Request update for a 16x16 region starting at (10, 10)
client.request_board_update("level1.nw", x=10, y=10, width=16, height=16)
```

### 3. Ghost Mode Support

Handle ghost mode packets for debugging:

```python
# Subscribe to ghost mode events
def on_ghost_text(text):
    print(f"Ghost text: {text}")

def on_ghost_icon(enabled):
    print(f"Ghost icon: {'enabled' if enabled else 'disabled'}")

client.events.subscribe(EventType.GHOST_TEXT, on_ghost_text)
client.events.subscribe(EventType.GHOST_ICON, on_ghost_icon)
```

### 4. Group Map Support

Players can be assigned to groups for visibility filtering on group maps:

```python
# Set player group
client.set_group("moderators")

# Listen for group changes
def on_group_changed(group):
    print(f"Player group changed to: {group}")

client.events.subscribe(EventType.GROUP_CHANGED, on_group_changed)
```

### 5. Trigger Actions

Handle server trigger actions with proper event parsing:

```python
# Subscribe to all trigger actions
def on_trigger_action(action, params, raw):
    print(f"Trigger action: {action}")
    print(f"Parameters: {params}")
    
    # Handle specific actions
    if action == "gr.addweapon":
        weapon_name = params[0] if params else None
        print(f"Weapon added: {weapon_name}")

client.events.subscribe(EventType.TRIGGER_ACTION, on_trigger_action)
```

### 6. Server Text Values

Request and send text values to/from the server:

```python
# Request a server value
client.request_text("serveroption.startlevel")

# Send a value to the server
client.send_text("playersetting.nickname", "CoolPlayer")

# Handle server text responses
def on_server_message(text):
    print(f"Server says: {text}")

client.events.subscribe(EventType.SERVER_MESSAGE, on_server_message)
```

### 7. New Player Properties

Access new player properties:

```python
# Community name (alias)
print(f"Player alias: {player.community_name}")

# Player list category
if player.playerlist_category == PlayerListCategory.CHANNEL:
    print("Player is in a channel")

# Player group (for group maps)
print(f"Player group: {player.group}")
```

### 8. Minimap Support

Handle minimap data from the server:

```python
def on_minimap_update(text_file, image_file, x, y):
    print(f"Minimap: {image_file} at ({x}, {y})")
    print(f"Text file: {text_file}")

client.events.subscribe(EventType.MINIMAP_UPDATE, on_minimap_update)
```

### 9. Client Freeze Events

Handle client freeze packets:

```python
def on_client_freeze(freeze_type):
    if freeze_type == "fullstop":
        print("Client input frozen (fullstop)")
    elif freeze_type == "fullstop2":
        print("Client input frozen (fullstop2)")

client.events.subscribe(EventType.CLIENT_FREEZE, on_client_freeze)
```

## New Event Types

The following new event types have been added:

- `EventType.TRIGGER_ACTION` - Server trigger action received
- `EventType.GROUP_CHANGED` - Player group changed
- `EventType.LEVELGROUP_CHANGED` - Player level group changed
- `EventType.GHOST_TEXT` - Ghost mode text received
- `EventType.GHOST_ICON` - Ghost mode icon state changed
- `EventType.MINIMAP_UPDATE` - Minimap data received
- `EventType.SERVER_WARP` - Server-initiated warp
- `EventType.CLIENT_FREEZE` - Client freeze command received

## Packet Support

### New Client-to-Server Packets

- `PLI_REQUESTUPDATEBOARD` (130) - Request partial board updates
- `PLI_REQUESTTEXT` (152) - Request server text values
- `PLI_SENDTEXT` (154) - Send text values to server
- `PLI_UPDATEGANI` (157) - GANI update requests
- `PLI_UPDATESCRIPT` (158) - Script update requests
- `PLI_UPDATEPACKAGEREQUESTFILE` (159) - Package file requests
- `PLI_UPDATECLASS` (161) - Class update requests

### New Server-to-Client Packets

- `PLO_MINIMAP` (172) - Minimap data
- `PLO_GHOSTTEXT` (173) - Ghost mode text
- `PLO_GHOSTICON` (174) - Ghost mode icon
- `PLO_FULLSTOP` (176) - Freeze client input
- `PLO_SERVERWARP` (178) - Server-initiated warp

## Example: Using Multiple New Features

```python
from pyreborn import RebornClient
from pyreborn.events import EventType

# Create client
client = RebornClient("localhost", 14900)

# Set up event handlers
def on_trigger_action(action, params, raw):
    if action == "gr.setgroup":
        print(f"Group set to: {params[0]}")
    elif action == "gr.fullhearts":
        print(f"Full hearts set to: {params[0]}")

def on_player_update(player):
    # High-precision coordinates
    print(f"{player.nickname} at ({player.x:.2f}, {player.y:.2f}, {player.z})")
    
    # New properties
    if player.community_name:
        print(f"  Alias: {player.community_name}")
    if player.group:
        print(f"  Group: {player.group}")

# Subscribe to events
client.events.subscribe(EventType.TRIGGER_ACTION, on_trigger_action)
client.events.subscribe(EventType.OTHER_PLAYER_UPDATE, on_player_update)

# Connect and login
if client.connect() and client.login("account", "password"):
    # Use high-precision movement
    client.move_with_precision(30.5, 45.75, z=5.0)
    
    # Set group for group maps
    client.set_group("admins")
    
    # Request server values
    client.request_text("serveroption.startlevel")
    
    # Run client
    client.run()
```

## Backward Compatibility

All new features are implemented in a backward-compatible way:
- Old movement methods still work alongside high-precision movement
- New properties are optional and don't affect existing code
- New events can be ignored if not needed
- The client will work with servers that don't support these features