#!/usr/bin/env python3
"""
Chat Logger - Logs all chat messages to a file with timestamps
"""

from pyreborn import RebornClient
import datetime
import json
import logging
import sys

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class ChatLogger:
    def __init__(self, client, output_file='chat_log.jsonl'):
        self.client = client
        self.output_file = output_file
        self.log_count = 0
        
        # Open file in append mode
        self.file_handle = open(output_file, 'a')
        
    def setup_handlers(self):
        """Setup event handlers"""
        self.client.events.subscribe('player_chat', self.on_chat)
        self.client.events.subscribe('private_message', self.on_private_message)
        
    def on_chat(self, event):
        """Log public chat messages"""
        player = event['player']
        message = event['message']
        
        log_entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'type': 'public',
            'player': player.name,
            'nickname': player.nickname,
            'message': message,
            'level': player.level,
            'position': {'x': player.x, 'y': player.y}
        }
        
        self._write_log(log_entry)
        
        # Print to console
        print(f"[{player.level}] {player.nickname}: {message}")
        
    def on_private_message(self, event):
        """Log private messages"""
        from_player = event.get('from_player', 'Unknown')
        message = event['message']
        
        log_entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'type': 'private',
            'from_player': from_player,
            'to_player': self.client.account_name,
            'message': message
        }
        
        self._write_log(log_entry)
        
        # Print to console
        print(f"[PM] {from_player}: {message}")
        
    def _write_log(self, entry):
        """Write log entry to file"""
        # Write as JSON Lines (one JSON object per line)
        json.dump(entry, self.file_handle)
        self.file_handle.write('\n')
        self.file_handle.flush()  # Ensure it's written immediately
        
        self.log_count += 1
        
    def close(self):
        """Close the log file"""
        if self.file_handle:
            self.file_handle.close()
            
    def print_stats(self):
        """Print logging statistics"""
        print(f"\nLogged {self.log_count} messages to {self.output_file}")

def main():
    # Get output file from command line
    output_file = sys.argv[1] if len(sys.argv) > 1 else 'chat_log.jsonl'
    
    client = RebornClient("localhost", 14900)
    
    # Create logger
    logger = ChatLogger(client, output_file)
    logger.setup_handlers()
    
    # Connect and run
    if client.connect():
        logging.info("Connected to server")
        
        if client.login("chatlogger", "1234"):
            logging.info("Login successful")
            
            # Set appearance
            client.set_nickname("ChatLogger")
            client.set_chat(f"Logging chat to {output_file}")
            
            print(f"\nChat Logger Started")
            print(f"===================")
            print(f"Logging to: {output_file}")
            print(f"Format: JSON Lines (one JSON object per line)")
            print(f"\nListening for chat messages...")
            print(f"Press Ctrl+C to stop")
            print()
            
            try:
                while client.connected:
                    import time
                    time.sleep(0.1)
                    
            except KeyboardInterrupt:
                logging.info("Shutting down...")
            finally:
                logger.print_stats()
                logger.close()
                client.disconnect()
                
        else:
            logging.error("Login failed")
    else:
        logging.error("Connection failed")

if __name__ == "__main__":
    main()