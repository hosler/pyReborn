# Server List Integration Guide

This guide explains how to use pyReborn's server list functionality to connect to Graal server lists and browse available game servers.

## Overview

The server list functionality allows clients to:
- Connect to the official Graal server list at `listserver.graal.in`
- Authenticate with account credentials
- Retrieve a list of available game servers
- Get server information (name, player count, IP/port)
- Select and connect to game servers

The default server list host is `listserver.graal.in` on port 14922.

## Basic Usage

### Simple Server List Connection

```python
from pyreborn import ServerListClient

# Create server list client
sl_client = ServerListClient()  # defaults to listserver.graal.in:14922

# Connect
if sl_client.connect():
    # Request server list with authentication
    sl_client.request_server_list("username", "password")
    
    # Wait for response
    import time
    time.sleep(2)
    
    # Access servers
    for server in sl_client.servers:
        print(f"{server.name} - {server.player_count} players")
    
    # Disconnect
    sl_client.disconnect()
```

### Using Callbacks

```python
from pyreborn import ServerListClient

def on_server_list(servers):
    print(f"Received {len(servers)} servers")
    for server in servers:
        print(f"- {server.name} ({server.ip}:{server.port})")

def on_error(message):
    print(f"Error: {message}")

# Create client with callbacks
sl_client = ServerListClient()
sl_client.set_callbacks(
    on_server_list=on_server_list,
    on_error=on_error
)

# Connect and authenticate
sl_client.connect()
sl_client.request_server_list("username", "password")
```

## ServerInfo Object

Each server in the list is represented by a `ServerInfo` object:

```python
class ServerInfo:
    name: str          # Server name
    type: str          # Server type (e.g., "reborn", "classic")
    language: str      # Server language
    description: str   # Server description
    url: str          # Server website URL
    version: str      # Server version
    player_count: int  # Current player count
    ip: str           # Server IP address
    port: int         # Server port
```

## Pygame Server Browser

The modular client includes a graphical server browser:

```python
from server_browser import ServerBrowser

# Create browser
browser = ServerBrowser()

# Show browser and get selection
result = browser.select_server()

if result:
    host, port = result
    print(f"User selected: {host}:{port}")
```

### Server Browser Features

- Graphical interface using pygame
- Login form for authentication
- Sortable server list
- Server details display
- Mouse and keyboard navigation
- Scroll support for long lists

## Complete Integration Example

```python
from pyreborn import RebornClient, ServerListClient

# Step 1: Get server list
sl_client = ServerListClient()
sl_client.connect()
sl_client.request_server_list("account", "password")

# Wait for servers
import time
time.sleep(2)

# Step 2: Select a server
if sl_client.servers:
    selected = sl_client.servers[0]  # or let user choose
    print(f"Connecting to {selected.name}...")
    
    # Step 3: Connect to game server
    game_client = RebornClient(selected.ip, selected.port)
    if game_client.connect():
        game_client.login("account", "password")
        # Play game...
        game_client.disconnect()

sl_client.disconnect()
```

## Enhanced Main Script

The modular client includes an enhanced main script with server browser integration:

```bash
# Run with server browser
python enhanced_main.py

# Options:
# 1. Server Browser (graphical selection)
# 2. Direct localhost connection
# 3. Custom server connection
```

## Protocol Details

### Client Packets (PLI)
- `PLI_V2ENCRYPTKEYCL`: Version identification
- `PLI_SERVERLIST`: Request server list with auth

### Server Packets (PLO)
- `PLO_SVRLIST`: Server list data
- `PLO_STATUS`: Status messages
- `PLO_ERROR`: Error messages
- `PLO_SITEURL`: Website URL
- `PLO_UPGURL`: Upgrade/donation URL

### Authentication Flow

1. Client connects to server list (port 14922)
2. Client sends version packet
3. Client sends authentication request
4. Server responds with:
   - Server list (if authenticated)
   - Error message (if failed)
   - Status and URL information

## Error Handling

Common errors and solutions:

```python
# Connection timeout
sl_client = ServerListClient()
sl_client.socket.settimeout(10.0)  # 10 second timeout

# Authentication failure
def on_error(message):
    if "Invalid" in message:
        print("Check your credentials")
    elif "banned" in message:
        print("Account may be banned")

# No servers available
if not sl_client.servers:
    print("No servers online or authentication failed")
```

## Security Considerations

- Credentials are sent encrypted using the same encryption as game protocol
- Server list uses simple encryption by default
- Don't store passwords in plain text
- Consider using environment variables for credentials

## Running Examples

```bash
# Basic server list test
python examples/test_serverlist.py

# Comprehensive demo
python examples/serverlist_demo.py

# Modular client with browser
python examples/games/modular_client/enhanced_main.py

# Standalone browser test
python examples/games/modular_client/server_browser.py
```

## Troubleshooting

### Can't connect to server list
- Check server list is running on expected port (14922)
- Verify firewall settings
- Try telnet to test connectivity

### Authentication fails
- Verify account exists in server list database
- Check password is correct
- Ensure account is not banned

### No servers shown
- Servers must register with the list server
- Check if any game servers are online
- Verify authentication succeeded

### Selected server won't connect
- Server may be offline despite being in list
- Firewall may block game server port
- Server may be full or restricted