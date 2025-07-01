#!/usr/bin/env python3
"""
Patrol Bot - Patrols between waypoints in a loop
"""

from pyreborn import RebornClient
import threading
import time
import logging
import math

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class PatrolBot:
    def __init__(self, client, waypoints, patrol_speed=3.0):
        self.client = client
        self.waypoints = waypoints
        self.patrol_speed = patrol_speed
        self.current_waypoint = 0
        self.patrolling = True
        self.patrol_thread = None
        
    def start_patrol(self):
        """Start the patrol in a separate thread"""
        self.patrol_thread = threading.Thread(target=self._patrol_loop)
        self.patrol_thread.daemon = True
        self.patrol_thread.start()
        logging.info(f"Started patrol with {len(self.waypoints)} waypoints")
        
    def stop_patrol(self):
        """Stop the patrol"""
        self.patrolling = False
        if self.patrol_thread:
            self.patrol_thread.join()
            
    def _patrol_loop(self):
        """Main patrol loop"""
        while self.patrolling and self.client.connected:
            # Get current waypoint
            target_x, target_y = self.waypoints[self.current_waypoint]
            
            # Move to waypoint
            self.client.move_to(target_x, target_y)
            
            # Update chat to show current waypoint
            self.client.set_chat(f"Patrolling to point {self.current_waypoint + 1}/{len(self.waypoints)}")
            
            # Log the movement
            logging.info(f"Moving to waypoint {self.current_waypoint + 1}: ({target_x}, {target_y})")
            
            # Wait before moving to next waypoint
            time.sleep(self.patrol_speed)
            
            # Move to next waypoint
            self.current_waypoint = (self.current_waypoint + 1) % len(self.waypoints)
            
    def add_waypoint(self, x, y):
        """Add a new waypoint to the patrol route"""
        self.waypoints.append((x, y))
        logging.info(f"Added waypoint: ({x}, {y})")

def main():
    client = RebornClient("localhost", 14900)
    
    # Define patrol waypoints (square pattern)
    waypoints = [
        (25, 25),  # Top-left
        (40, 25),  # Top-right
        (40, 40),  # Bottom-right
        (25, 40),  # Bottom-left
    ]
    
    # Alternative: Circle pattern
    # center_x, center_y = 32, 32
    # radius = 10
    # num_points = 8
    # waypoints = []
    # for i in range(num_points):
    #     angle = (2 * math.pi * i) / num_points
    #     x = center_x + radius * math.cos(angle)
    #     y = center_y + radius * math.sin(angle)
    #     waypoints.append((x, y))
    
    # Create patrol bot
    patrol = PatrolBot(client, waypoints, patrol_speed=2.0)
    
    # Handle chat commands
    def on_chat(event):
        player = event['player']
        message = event['message'].lower()
        
        if message == "!stop":
            patrol.patrolling = False
            client.set_chat("Patrol stopped")
            
        elif message == "!start":
            patrol.patrolling = True
            client.set_chat("Patrol resumed")
            
        elif message.startswith("!speed "):
            try:
                speed = float(message.split()[1])
                patrol.patrol_speed = max(0.5, min(10.0, speed))
                client.set_chat(f"Patrol speed set to {patrol.patrol_speed}")
            except:
                client.set_chat("Usage: !speed <number>")
                
        elif message == "!waypoints":
            client.set_chat(f"I have {len(patrol.waypoints)} waypoints")
    
    client.events.subscribe('player_chat', on_chat)
    
    # Connect and run
    if client.connect():
        logging.info("Connected to server")
        
        if client.login("hosler", "1234"):
            logging.info("Login successful")
            
            # Set appearance
            client.set_nickname("PatrolBot")
            client.set_head_image("head2.png")
            client.set_body_image("body2.png")
            client.set_chat("Starting patrol...")
            
            # Start patrol
            patrol.start_patrol()
            
            try:
                logging.info("PatrolBot is running. Press Ctrl+C to stop.")
                while client.connected:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                logging.info("Shutting down...")
            finally:
                patrol.stop_patrol()
                client.disconnect()
        else:
            logging.error("Login failed")
    else:
        logging.error("Connection failed")

if __name__ == "__main__":
    main()