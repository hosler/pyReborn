#!/usr/bin/env python3
"""
Custom Handler Example - Shows how to extend PyReborn with custom packet handlers
"""

import sys
sys.path.insert(0, '..')

from pyreborn import RebornClient
from pyreborn.protocol.enums import ServerToPlayer

class CustomClient(RebornClient):
    """Extended client with custom packet handling"""
    
    def __init__(self, host: str, port: int = 14900):
        super().__init__(host, port)
        
        # Track custom data
        self.server_messages = []
        self.custom_stats = {}
        
        # Register custom handlers
        self._register_custom_handlers()
        
    def _register_custom_handlers(self):
        """Register handlers for packets we want to track specially"""
        
        # Add custom handler for server messages
        original_handler = self.packet_handler.handlers.get(ServerToPlayer.PLO_ADMINMESSAGE, None)
        
        def handle_admin_message(data):
            """Custom handler for admin messages"""
            # Call original handler if exists
            if original_handler:
                original_handler(data)
                
            # Add our custom logic
            message = data.decode('ascii', errors='ignore')
            self.server_messages.append({
                'time': time.time(),
                'message': message
            })
            print(f"[ADMIN] {message}")
            
            # Emit custom event
            self.events.emit('admin_message', {'message': message})
        
        # Register the custom handler
        if hasattr(self.packet_handler, 'register_handler'):
            self.packet_handler.register_handler(
                ServerToPlayer.PLO_ADMINMESSAGE, 
                handle_admin_message
            )
    
    def get_server_messages(self):
        """Get all server messages received"""
        return self.server_messages.copy()
    
    def on_custom_event(self, event_name: str, handler):
        """Register handler for custom events"""
        self.events.subscribe(event_name, handler)

def main():
    """Demonstrate custom client"""
    print("Custom Handler Example")
    print("=" * 50)
    
    # Create custom client
    client = CustomClient("localhost", 14900)
    
    # Add handler for our custom event
    def on_admin_msg(event):
        print(f"Custom handler got: {event['message']}")
        
    client.on_custom_event('admin_message', on_admin_msg)
    
    # Connect and use normally
    if client.connect() and client.login("custombot", "1234"):
        print("✅ Connected with custom client")
        
        # The client works exactly like normal RebornClient
        client.set_nickname("CustomBot")
        client.set_chat("I have custom handlers!")
        
        # But also has our extensions
        print(f"Server messages so far: {len(client.get_server_messages())}")
        
        import time
        time.sleep(10)
        
        client.disconnect()
    
    return 0

if __name__ == "__main__":
    import time
    sys.exit(main())