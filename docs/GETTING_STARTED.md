# Getting Started with PyReborn

This guide will help you get up and running with PyReborn quickly.

## Prerequisites

- Python 3.8 or higher
- A running Reborn Server instance (or access to a Reborn server)
- Basic Python knowledge

## Installation

### Option 1: Install from source (recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/pyreborn.git
cd pyreborn

# Install in development mode
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

### Option 2: Install from PyPI (when available)

```bash
pip install pyreborn
```

## Your First Bot

Let's create a simple bot that connects to a server and moves around.

### Step 1: Import and Create Client

```python
from pyreborn import RebornClient

# Create a client instance
client = RebornClient("localhost", 14900)
```

### Step 2: Connect and Login

```python
# Connect to the server
if not client.connect():
    print("Failed to connect!")
    exit(1)

# Login with your credentials
if not client.login("mybot", "password"):
    print("Failed to login!")
    exit(1)

print("Successfully connected!")
```

### Step 3: Set Your Appearance

```python
# Set your nickname (display name)
client.set_nickname("MyFirstBot")

# Set a chat bubble
client.set_chat("Hello, world!")

# Set your appearance (optional)
client.set_head_image("head0.png")
client.set_body_image("body0.png")
```

### Step 4: Move Around

```python
import time

# Move to a specific position
client.move_to(30, 30)
time.sleep(1)

# Move relative to current position
client.move(5, 0)  # Move 5 tiles right
time.sleep(1)

client.move(0, 5)  # Move 5 tiles down
time.sleep(1)
```

### Step 5: Handle Events

```python
# Define event handlers
def on_player_chat(event):
    player = event['player']
    message = event['message']
    print(f"{player.nickname}: {message}")

def on_player_joined(event):
    player = event['player']
    print(f"{player.nickname} joined the game!")

# Subscribe to events
client.events.subscribe('player_chat', on_player_chat)
client.events.subscribe('player_joined', on_player_joined)
```

### Complete Example

Here's a complete bot that puts it all together:

```python
from pyreborn import RebornClient
import time

def main():
    # Create client
    client = RebornClient("localhost", 14900)
    
    # Event handlers
    def on_chat(event):
        player = event['player']
        message = event['message']
        print(f"{player.nickname}: {message}")
        
        # Respond to greetings
        if "hello" in message.lower():
            client.set_chat(f"Hello {player.nickname}!")
    
    def on_player_moved(event):
        player = event['player']
        print(f"{player.nickname} moved to ({player.x}, {player.y})")
    
    # Subscribe to events
    client.events.subscribe('player_chat', on_chat)
    client.events.subscribe('player_moved', on_player_moved)
    
    # Connect and login
    if client.connect() and client.login("mybot", "password"):
        print("Connected successfully!")
        
        # Set appearance
        client.set_nickname("FriendlyBot")
        client.set_chat("I'm a friendly bot!")
        
        # Move to center of map
        client.move_to(32, 32)
        
        # Keep the bot running
        try:
            while client.connected:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nShutting down...")
        
        client.disconnect()
    else:
        print("Failed to connect or login!")

if __name__ == "__main__":
    main()
```

## Understanding Coordinates

- The game world uses a tile-based coordinate system
- Each level is 64x64 tiles
- Coordinates are in tiles, not pixels
- (0, 0) is the top-left corner
- Players can be at fractional positions (e.g., 30.5, 25.5)

## Common Patterns

### Running Forever

```python
# Method 1: Using run()
if client.connect() and client.login("bot", "pass"):
    client.run()  # Blocks forever
```

```python
# Method 2: Manual loop
if client.connect() and client.login("bot", "pass"):
    try:
        while client.connected:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    client.disconnect()
```

### Responding to Commands

```python
def on_chat(event):
    player = event['player']
    message = event['message']
    
    # Check if message is a command
    if message.startswith("!"):
        command = message[1:].lower().split()
        
        if command[0] == "hello":
            client.set_chat(f"Hello {player.nickname}!")
        elif command[0] == "follow":
            # Start following the player
            follow_player(player)
        elif command[0] == "stop":
            # Stop following
            stop_following()
```

### Error Handling

```python
import logging

# Enable logging
logging.basicConfig(level=logging.INFO)

try:
    client = RebornClient("localhost", 14900)
    if not client.connect():
        logging.error("Connection failed")
        return
        
    if not client.login("bot", "pass"):
        logging.error("Login failed")
        return
        
    # Your bot logic here
    
except Exception as e:
    logging.error(f"Error: {e}")
finally:
    if client.connected:
        client.disconnect()
```

## Next Steps

Now that you have a basic bot running, you can:

1. **Explore Events** - See [EVENT_REFERENCE.md](EVENT_REFERENCE.md) for all available events
2. **Learn the API** - Check [API_REFERENCE.md](API_REFERENCE.md) for detailed method documentation
3. **Study Examples** - Look at the `examples/` directory for more complex bots
4. **Understand the Protocol** - Read [PROTOCOL_GUIDE.md](PROTOCOL_GUIDE.md) for low-level details
5. **Build Something Cool** - Create your own unique bot!

## Tips

- Always handle disconnections gracefully
- Don't send packets too rapidly (the client handles rate limiting)
- Use events instead of polling when possible
- Test your bot on a local server first
- Keep your bot's behavior friendly and non-disruptive

## Troubleshooting

### Can't Connect
- Verify the server address and port
- Check if the server is running
- Ensure no firewall is blocking the connection

### Login Fails
- Double-check your username and password
- Ensure the account exists on the server
- Check if the server has any login restrictions

### Bot Crashes
- Enable logging to see detailed error messages
- Use try/except blocks around your code
- Check for None values before using them

### Events Not Firing
- Ensure you subscribed before connecting
- Check the event name spelling
- Verify the event actually occurs (use logging)

## Getting Help

- Check the [FAQ](FAQ.md)
- Look at example bots in `examples/`
- Read the API documentation
- Open an issue on GitHub

Happy botting! 🤖