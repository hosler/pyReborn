#!/usr/bin/env python3
"""
Player Tracker Utility - monitors and logs player activity
"""

import sys
import time
import json
from datetime import datetime
sys.path.insert(0, '../..')

from pyreborn.client import RebornClient

class PlayerTracker:
    def __init__(self, client):
        self.client = client
        self.players_seen = {}
        self.events_log = []
        self.running = True
        
        # Subscribe to events
        self.client.events.subscribe('player_joined', self.on_player_joined)
        self.client.events.subscribe('player_left', self.on_player_left)
        self.client.events.subscribe('player_moved', self.on_player_moved)
        self.client.events.subscribe('player_chat', self.on_player_chat)
        self.client.events.subscribe('level_changed', self.on_level_changed)
    
    def log_event(self, event_type, data):
        """Log an event with timestamp"""
        event = {
            'timestamp': datetime.now().isoformat(),
            'type': event_type,
            'data': data
        }
        self.events_log.append(event)
        print(f"[{event['timestamp']}] {event_type}: {data}")
    
    def on_player_joined(self, event):
        """Handle player joining"""
        player = event.get('player')
        if player and hasattr(player, 'name'):
            self.players_seen[player.name] = {
                'first_seen': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat(),
                'positions': [],
                'chat_messages': []
            }
            self.log_event('PLAYER_JOINED', {'name': player.name, 'id': player.id})
    
    def on_player_left(self, event):
        """Handle player leaving"""
        player = event.get('player')
        if player and hasattr(player, 'name'):
            if player.name in self.players_seen:
                self.players_seen[player.name]['last_seen'] = datetime.now().isoformat()
            self.log_event('PLAYER_LEFT', {'name': player.name, 'id': player.id})
    
    def on_player_moved(self, event):
        """Handle player movement"""
        player = event.get('player')
        if player and hasattr(player, 'name'):
            position = {'x': player.x, 'y': player.y, 'time': datetime.now().isoformat()}
            
            if player.name in self.players_seen:
                self.players_seen[player.name]['positions'].append(position)
                # Keep only last 10 positions
                if len(self.players_seen[player.name]['positions']) > 10:
                    self.players_seen[player.name]['positions'].pop(0)
            
            self.log_event('PLAYER_MOVED', {
                'name': player.name,
                'position': {'x': player.x, 'y': player.y}
            })
    
    def on_player_chat(self, event):
        """Handle player chat"""
        player = event.get('player')
        message = event.get('message', '')
        
        if player and hasattr(player, 'name'):
            chat_entry = {'message': message, 'time': datetime.now().isoformat()}
            
            if player.name in self.players_seen:
                self.players_seen[player.name]['chat_messages'].append(chat_entry)
                # Keep only last 5 messages
                if len(self.players_seen[player.name]['chat_messages']) > 5:
                    self.players_seen[player.name]['chat_messages'].pop(0)
            
            self.log_event('PLAYER_CHAT', {'name': player.name, 'message': message})
    
    def on_level_changed(self, event):
        """Handle level changes"""
        level_name = event.get('level_name', 'unknown')
        self.log_event('LEVEL_CHANGED', {'level': level_name})
    
    def print_summary(self):
        """Print tracking summary"""
        print("\n" + "="*50)
        print("PLAYER TRACKING SUMMARY")
        print("="*50)
        
        print(f"Total players seen: {len(self.players_seen)}")
        print(f"Total events logged: {len(self.events_log)}")
        
        print("\nPlayer Details:")
        for name, data in self.players_seen.items():
            print(f"\n{name}:")
            print(f"  First seen: {data['first_seen']}")
            print(f"  Last seen: {data['last_seen']}")
            print(f"  Positions tracked: {len(data['positions'])}")
            print(f"  Chat messages: {len(data['chat_messages'])}")
            
            if data['positions']:
                last_pos = data['positions'][-1]
                print(f"  Last position: ({last_pos['x']:.1f}, {last_pos['y']:.1f})")
            
            if data['chat_messages']:
                last_chat = data['chat_messages'][-1]
                print(f"  Last message: \"{last_chat['message']}\"")
    
    def save_log(self, filename):
        """Save tracking data to JSON file"""
        data = {
            'players_seen': self.players_seen,
            'events_log': self.events_log,
            'session_end': datetime.now().isoformat()
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"\n✅ Tracking data saved to: {filename}")
    
    def start(self):
        """Start tracking"""
        print("Player tracking started. Press Ctrl+C to stop and save.")
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping tracker...")
            self.running = False
    
    def stop(self):
        """Stop tracking"""
        self.running = False

def main():
    """Player tracker utility"""
    print("Player Tracker Utility")
    print("======================\n")
    
    # Get output filename
    output_file = sys.argv[1] if len(sys.argv) > 1 else f"player_tracking_{int(time.time())}.json"
    
    client = RebornClient("localhost", 14900)
    
    print("1. Connecting...")
    if not client.connect():
        return 1
    
    print("2. Logging in...")
    if not client.login("trackerbot", "1234"):
        return 1
    
    print("3. Starting tracker...")
    tracker = PlayerTracker(client)
    
    try:
        tracker.start()
    except KeyboardInterrupt:
        pass
    
    tracker.print_summary()
    tracker.save_log(output_file)
    
    client.disconnect()
    return 0

if __name__ == "__main__":
    sys.exit(main())