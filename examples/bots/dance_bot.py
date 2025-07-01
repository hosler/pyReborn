#!/usr/bin/env python3
"""
Dance Bot - Dances around in patterns and responds to music commands
"""

from pyreborn import RebornClient
import math
import time
import threading
import logging
import random

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class DanceBot:
    def __init__(self, client):
        self.client = client
        self.dancing = False
        self.dance_thread = None
        self.current_dance = "spin"
        self.dance_speed = 0.5
        self.center_x = 32
        self.center_y = 32
        
        # Dance patterns
        self.dances = {
            'spin': self._spin_dance,
            'square': self._square_dance,
            'zigzag': self._zigzag_dance,
            'random': self._random_dance,
            'moonwalk': self._moonwalk_dance,
            'wave': self._wave_dance
        }
        
    def start_dancing(self, dance_type=None):
        """Start dancing"""
        if self.dancing:
            return
            
        if dance_type and dance_type in self.dances:
            self.current_dance = dance_type
            
        self.dancing = True
        self.dance_thread = threading.Thread(target=self._dance_loop)
        self.dance_thread.daemon = True
        self.dance_thread.start()
        
        self.client.set_chat(f"♪♫ Dancing the {self.current_dance}! ♫♪")
        logging.info(f"Started {self.current_dance} dance")
        
    def stop_dancing(self):
        """Stop dancing"""
        self.dancing = False
        if self.dance_thread:
            self.dance_thread.join()
        self.client.set_chat("*stops dancing*")
        logging.info("Stopped dancing")
        
    def _dance_loop(self):
        """Main dance loop"""
        # Update center to current position
        self.center_x = self.client.player_x
        self.center_y = self.client.player_y
        
        # Get the dance function
        dance_func = self.dances.get(self.current_dance, self._spin_dance)
        
        # Execute the dance
        dance_func()
        
    def _spin_dance(self):
        """Spin in a circle"""
        radius = 3
        angle = 0
        
        while self.dancing and self.client.connected:
            x = self.center_x + radius * math.cos(angle)
            y = self.center_y + radius * math.sin(angle)
            
            self.client.move_to(x, y)
            
            angle += 0.3
            if angle > 2 * math.pi:
                angle -= 2 * math.pi
                
            time.sleep(self.dance_speed)
            
    def _square_dance(self):
        """Dance in a square pattern"""
        positions = [
            (self.center_x - 3, self.center_y - 3),
            (self.center_x + 3, self.center_y - 3),
            (self.center_x + 3, self.center_y + 3),
            (self.center_x - 3, self.center_y + 3),
        ]
        
        while self.dancing and self.client.connected:
            for pos in positions:
                if not self.dancing:
                    break
                self.client.move_to(pos[0], pos[1])
                time.sleep(self.dance_speed)
                
    def _zigzag_dance(self):
        """Zigzag back and forth"""
        while self.dancing and self.client.connected:
            for i in range(6):
                if not self.dancing:
                    break
                x = self.center_x + (i - 3) * 2
                y = self.center_y + (3 if i % 2 == 0 else -3)
                self.client.move_to(x, y)
                time.sleep(self.dance_speed)
                
            # Go back
            for i in range(6, 0, -1):
                if not self.dancing:
                    break
                x = self.center_x + (i - 3) * 2
                y = self.center_y + (3 if i % 2 == 0 else -3)
                self.client.move_to(x, y)
                time.sleep(self.dance_speed)
                
    def _random_dance(self):
        """Random movements"""
        while self.dancing and self.client.connected:
            # Random position within radius
            angle = random.random() * 2 * math.pi
            radius = random.random() * 5
            
            x = self.center_x + radius * math.cos(angle)
            y = self.center_y + radius * math.sin(angle)
            
            self.client.move_to(x, y)
            
            # Random chat messages
            if random.random() < 0.1:
                messages = ["♪", "♫", "♪♫", "*spins*", "*jumps*", "*twirls*"]
                self.client.set_chat(random.choice(messages))
                
            time.sleep(self.dance_speed)
            
    def _moonwalk_dance(self):
        """Moonwalk backwards"""
        direction = 0
        
        while self.dancing and self.client.connected:
            # Move forward but face backward
            for i in range(5):
                if not self.dancing:
                    break
                    
                # Calculate position
                dx = math.cos(direction) * 0.5
                dy = math.sin(direction) * 0.5
                
                # Move backwards (opposite direction)
                self.client.move(-dx, -dy)
                time.sleep(self.dance_speed)
                
            # Turn
            direction += math.pi / 2
            if direction > 2 * math.pi:
                direction -= 2 * math.pi
                
    def _wave_dance(self):
        """Wave motion dance"""
        t = 0
        
        while self.dancing and self.client.connected:
            # Sine wave pattern
            x = self.center_x + t
            y = self.center_y + 3 * math.sin(t * 0.5)
            
            self.client.move_to(x, y)
            
            t += 0.5
            if t > 10:
                t = -10
                
            time.sleep(self.dance_speed)

def main():
    client = RebornClient("localhost", 14900)
    
    # Create dance bot
    dancer = DanceBot(client)
    
    # Handle chat commands
    def on_chat(event):
        player = event['player']
        message = event['message'].lower().strip()
        
        if message == "!dance":
            if not dancer.dancing:
                dancer.start_dancing()
            else:
                client.set_chat("Already dancing! Say !stop to stop")
                
        elif message.startswith("!dance "):
            dance_type = message.split()[1]
            if dance_type in dancer.dances:
                if dancer.dancing:
                    dancer.stop_dancing()
                    time.sleep(0.5)
                dancer.start_dancing(dance_type)
            else:
                dances = ", ".join(dancer.dances.keys())
                client.set_chat(f"Unknown dance! Try: {dances}")
                
        elif message == "!stop":
            if dancer.dancing:
                dancer.stop_dancing()
            else:
                client.set_chat("I'm not dancing!")
                
        elif message == "!dances":
            dances = ", ".join(dancer.dances.keys())
            client.set_chat(f"I know: {dances}")
            
        elif message.startswith("!speed "):
            try:
                speed = float(message.split()[1])
                dancer.dance_speed = max(0.1, min(2.0, speed))
                client.set_chat(f"Dance speed set to {dancer.dance_speed}")
            except:
                client.set_chat("Usage: !speed <0.1-2.0>")
                
        elif message in ["!music", "♪", "♫"]:
            # Start dancing if someone plays music
            if not dancer.dancing:
                dancer.start_dancing(random.choice(list(dancer.dances.keys())))
                
    client.events.subscribe('player_chat', on_chat)
    
    # Connect and run
    if client.connect():
        logging.info("Connected to server")
        
        if client.login("dancebot", "1234"):
            logging.info("Login successful")
            
            # Set appearance
            client.set_nickname("DanceBot")
            client.set_head_image("head0.png")
            client.set_body_image("body0.png")
            client.set_chat("Say !dance to see me dance!")
            
            # Move to dance floor
            client.move_to(32, 32)
            
            # Periodic dance announcements
            def announce_dances():
                announcements = [
                    "Want to see me dance? Say !dance",
                    "I know many dances! Say !dances to see",
                    "♪ ♫ Music makes me dance! ♫ ♪",
                    "Control my speed with !speed <0.1-2.0>",
                ]
                
                while client.connected:
                    time.sleep(45)  # Every 45 seconds
                    if client.connected and not dancer.dancing:
                        msg = random.choice(announcements)
                        client.set_chat(msg)
                        
            announce_thread = threading.Thread(target=announce_dances)
            announce_thread.daemon = True
            announce_thread.start()
            
            try:
                logging.info("DanceBot is ready to dance! Press Ctrl+C to stop.")
                while client.connected:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                logging.info("Shutting down...")
            finally:
                dancer.stop_dancing()
                client.disconnect()
        else:
            logging.error("Login failed")
    else:
        logging.error("Connection failed")

if __name__ == "__main__":
    main()