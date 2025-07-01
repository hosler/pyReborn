#!/usr/bin/env python3
"""
Tag Game - A bot that plays tag with players
Say "!tag" to start a game, then try to catch the bot or run away!
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

class TagGame:
    def __init__(self, client):
        self.client = client
        self.game_active = False
        self.who_is_it = None  # Player name who is "it"
        self.players_in_game = set()
        self.tag_cooldown = {}  # Prevent instant re-tags
        self.scores = {}  # Track how long each player was "it"
        self.game_thread = None
        self.safe_zone = (32, 32, 5)  # x, y, radius
        
        # AI behavior
        self.ai_mode = 'chase'  # 'chase' or 'flee'
        self.target_player = None
        self.last_position_update = 0
        
    def start_game(self, starter_name):
        """Start a new game of tag"""
        if self.game_active:
            self.client.set_chat("Game already in progress!")
            return
            
        self.game_active = True
        self.who_is_it = starter_name
        self.players_in_game = {starter_name}
        self.tag_cooldown = {}
        
        self.client.set_chat(f"Tag game started! {starter_name} is IT!")
        logging.info(f"Tag game started with {starter_name}")
        
        # Start game thread
        self.game_thread = threading.Thread(target=self._game_loop)
        self.game_thread.daemon = True
        self.game_thread.start()
        
    def join_game(self, player_name):
        """Add a player to the game"""
        if not self.game_active:
            self.client.set_chat("No game in progress! Say !tag to start")
            return
            
        if player_name not in self.players_in_game:
            self.players_in_game.add(player_name)
            self.scores[player_name] = 0
            self.client.set_chat(f"{player_name} joined the game!")
            logging.info(f"{player_name} joined tag game")
            
    def end_game(self):
        """End the current game"""
        if not self.game_active:
            return
            
        self.game_active = False
        
        # Calculate winner (who was "it" the least)
        if self.scores:
            winner = min(self.scores.items(), key=lambda x: x[1])
            self.client.set_chat(f"Game over! Winner: {winner[0]} (was IT for {winner[1]:.1f}s)")
        else:
            self.client.set_chat("Game ended!")
            
        logging.info("Tag game ended")
        
    def _game_loop(self):
        """Main game loop"""
        start_time = time.time()
        last_score_update = time.time()
        
        while self.game_active and self.client.connected:
            current_time = time.time()
            
            # Update scores
            if current_time - last_score_update > 1.0:
                if self.who_is_it in self.scores:
                    self.scores[self.who_is_it] += 1.0
                last_score_update = current_time
                
            # Bot AI behavior
            if self.who_is_it == self.client.account_name:
                # Bot is "it" - chase nearest player
                self._ai_chase()
            else:
                # Bot is not "it" - run from whoever is
                self._ai_flee()
                
            # Check for tags
            self._check_for_tags()
            
            # Update status
            if int(current_time) % 10 == 0 and current_time - self.last_position_update > 1:
                elapsed = int(current_time - start_time)
                self.client.set_chat(f"{self.who_is_it} is IT! ({elapsed}s)")
                self.last_position_update = current_time
                
            time.sleep(0.1)
            
    def _ai_chase(self):
        """AI behavior when bot is 'it'"""
        # Find nearest player
        nearest_player = None
        nearest_distance = float('inf')
        
        for player in self.client.session_manager.get_all_players():
            if player.name in self.players_in_game and player.name != self.client.account_name:
                dist = self._distance_to_player(player)
                if dist < nearest_distance:
                    nearest_distance = dist
                    nearest_player = player
                    
        if nearest_player:
            # Move towards nearest player
            self._move_towards(nearest_player.x, nearest_player.y, speed=0.5)
            
            # Taunt occasionally
            if random.random() < 0.01:
                taunts = ["I'm gonna get you!", "You can't escape!", "Tag, you're it... soon!"]
                self.client.set_chat(random.choice(taunts))
                
    def _ai_flee(self):
        """AI behavior when bot is not 'it'"""
        # Find who is "it"
        it_player = None
        for player in self.client.session_manager.get_all_players():
            if player.name == self.who_is_it:
                it_player = player
                break
                
        if it_player:
            # Run away from them
            self._move_away_from(it_player.x, it_player.y, speed=0.4)
            
            # Taunt if far enough away
            dist = self._distance_to_player(it_player)
            if dist > 10 and random.random() < 0.01:
                taunts = ["Can't catch me!", "Too slow!", "Nah nah nah nah nah!"]
                self.client.set_chat(random.choice(taunts))
                
    def _move_towards(self, target_x, target_y, speed=0.5):
        """Move towards a target position"""
        dx = target_x - self.client.player_x
        dy = target_y - self.client.player_y
        
        dist = math.sqrt(dx*dx + dy*dy)
        if dist > 0.5:
            # Normalize and apply speed
            dx = (dx / dist) * speed
            dy = (dy / dist) * speed
            self.client.move(dx, dy)
            
    def _move_away_from(self, danger_x, danger_y, speed=0.4):
        """Move away from a position"""
        dx = self.client.player_x - danger_x
        dy = self.client.player_y - danger_y
        
        dist = math.sqrt(dx*dx + dy*dy)
        if dist < 8:  # Only flee if they're close
            if dist > 0:
                # Normalize and apply speed
                dx = (dx / dist) * speed
                dy = (dy / dist) * speed
            else:
                # Random direction if on same tile
                angle = random.random() * 2 * math.pi
                dx = math.cos(angle) * speed
                dy = math.sin(angle) * speed
                
            # Add some randomness to make it harder to catch
            dx += random.uniform(-0.1, 0.1)
            dy += random.uniform(-0.1, 0.1)
            
            self.client.move(dx, dy)
            
    def _distance_to_player(self, player):
        """Calculate distance to another player"""
        dx = player.x - self.client.player_x
        dy = player.y - self.client.player_y
        return math.sqrt(dx*dx + dy*dy)
        
    def _check_for_tags(self):
        """Check if anyone tagged anyone"""
        current_time = time.time()
        
        # Get who is "it"
        it_player = None
        if self.who_is_it == self.client.account_name:
            it_player = self.client.local_player
        else:
            for player in self.client.session_manager.get_all_players():
                if player.name == self.who_is_it:
                    it_player = player
                    break
                    
        if not it_player:
            return
            
        # Check all players
        for player in self.client.session_manager.get_all_players():
            if player.name not in self.players_in_game:
                continue
                
            if player.name == self.who_is_it:
                continue
                
            # Check distance for tag
            if player.name == self.client.account_name:
                # Check if bot got tagged
                dist = self._distance_to_player(it_player)
            else:
                # Check if it_player tagged someone
                dx = player.x - it_player.x
                dy = player.y - it_player.y
                dist = math.sqrt(dx*dx + dy*dy)
                
            # Tag if close enough and not on cooldown
            if dist < 1.5:
                tag_key = f"{self.who_is_it}->{player.name}"
                if tag_key not in self.tag_cooldown or current_time - self.tag_cooldown[tag_key] > 3.0:
                    # Tag successful!
                    old_it = self.who_is_it
                    self.who_is_it = player.name
                    self.tag_cooldown[tag_key] = current_time
                    
                    self.client.set_chat(f"TAG! {player.name} is now IT!")
                    logging.info(f"{old_it} tagged {player.name}")
                    
                    # Ensure new player is in the game
                    self.join_game(player.name)
                    
    def on_player_moved(self, event):
        """Track player movements for the game"""
        if not self.game_active:
            return
            
        player = event['player']
        
        # Auto-join players who get close
        if player.name not in self.players_in_game:
            dist = self._distance_to_player(player)
            if dist < 10:
                self.join_game(player.name)

def main():
    client = RebornClient("localhost", 14900)
    
    # Create game
    tag_game = TagGame(client)
    
    # Handle chat commands
    def on_chat(event):
        player = event['player']
        message = event['message'].lower().strip()
        
        if message == "!tag":
            if not tag_game.game_active:
                tag_game.start_game(player.name)
            else:
                tag_game.join_game(player.name)
                
        elif message == "!join":
            tag_game.join_game(player.name)
            
        elif message == "!endgame":
            if tag_game.game_active:
                tag_game.end_game()
                
        elif message == "!score":
            if tag_game.scores:
                scores_text = ", ".join([f"{p}:{s:.0f}s" for p, s in tag_game.scores.items()])
                client.set_chat(f"Scores: {scores_text}")
            else:
                client.set_chat("No scores yet!")
                
        elif message == "!taghelp":
            client.set_chat("Commands: !tag (start/join), !endgame, !score")
            
    # Subscribe to events
    client.events.subscribe('player_chat', on_chat)
    client.events.subscribe('player_moved', tag_game.on_player_moved)
    
    # Connect and run
    if client.connect():
        logging.info("Connected to server")
        
        if client.login("tagbot", "1234"):
            logging.info("Login successful")
            
            # Set appearance
            client.set_nickname("TagBot")
            client.set_head_image("head0.png")
            client.set_body_image("body0.png")
            client.set_chat("Let's play tag! Say !tag to start!")
            
            # Move to center
            client.move_to(32, 32)
            
            # Announce periodically
            def announce():
                announcements = [
                    "Who wants to play tag? Say !tag",
                    "I love playing tag! Say !tag to play!",
                    "Tag is the best game! Say !tag",
                    "Running away is my specialty! !tag to play",
                ]
                
                while client.connected:
                    time.sleep(60)  # Every minute
                    if client.connected and not tag_game.game_active:
                        msg = random.choice(announcements)
                        client.set_chat(msg)
                        
            announce_thread = threading.Thread(target=announce)
            announce_thread.daemon = True
            announce_thread.start()
            
            try:
                logging.info("TagBot is ready to play! Press Ctrl+C to stop.")
                while client.connected:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                logging.info("Shutting down...")
            finally:
                if tag_game.game_active:
                    tag_game.end_game()
                client.disconnect()
        else:
            logging.error("Login failed")
    else:
        logging.error("Connection failed")

if __name__ == "__main__":
    main()