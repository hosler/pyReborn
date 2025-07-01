#!/usr/bin/env python3
"""
Quest Bot - Gives quests to players and tracks their progress
"""

from pyreborn import RebornClient
import json
import time
import logging
import random
from enum import Enum

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class QuestType(Enum):
    MOVEMENT = "movement"
    COLLECTION = "collection"
    SOCIAL = "social"
    EXPLORATION = "exploration"

class Quest:
    def __init__(self, quest_id, name, description, quest_type, requirements, reward):
        self.id = quest_id
        self.name = name
        self.description = description
        self.type = quest_type
        self.requirements = requirements
        self.reward = reward
        
class QuestBot:
    def __init__(self, client):
        self.client = client
        self.quests = self._init_quests()
        self.player_quests = {}  # player_name -> current quest
        self.completed_quests = {}  # player_name -> list of completed quest IDs
        self.quest_progress = {}  # player_name -> progress data
        
    def _init_quests(self):
        """Initialize available quests"""
        return [
            Quest("move_1", "First Steps", 
                  "Move to position (40, 40)", 
                  QuestType.MOVEMENT,
                  {'x': 40, 'y': 40, 'radius': 2},
                  {'message': 'Well done! Here\'s your reward!', 'xp': 10}),
                  
            Quest("explore_1", "Explorer", 
                  "Visit all four corners of the map", 
                  QuestType.EXPLORATION,
                  {'corners': [(5, 5), (59, 5), (59, 59), (5, 59)]},
                  {'message': 'Amazing exploration!', 'xp': 50}),
                  
            Quest("social_1", "Make Friends", 
                  "Say hello to 3 different players", 
                  QuestType.SOCIAL,
                  {'greet_count': 3},
                  {'message': 'You\'re so friendly!', 'xp': 25}),
                  
            Quest("move_2", "The Journey", 
                  "Travel a total distance of 100 tiles", 
                  QuestType.MOVEMENT,
                  {'distance': 100},
                  {'message': 'What a journey!', 'xp': 30}),
                  
            Quest("social_2", "Chatterbox", 
                  "Send 10 chat messages", 
                  QuestType.SOCIAL,
                  {'chat_count': 10},
                  {'message': 'You\'re quite the talker!', 'xp': 20}),
        ]
        
    def on_chat(self, event):
        """Handle quest-related chat commands"""
        player = event['player']
        message = event['message'].lower().strip()
        player_name = player.name
        
        # Track chat for social quests
        self._track_chat(player_name, message)
        
        if message == "!quest":
            self.show_current_quest(player_name)
            
        elif message == "!newquest":
            self.assign_new_quest(player_name)
            
        elif message == "!progress":
            self.show_quest_progress(player_name)
            
        elif message == "!complete":
            self.try_complete_quest(player_name)
            
        elif message == "!questhelp":
            self.client.set_chat("Commands: !quest, !newquest, !progress, !complete")
            
        # Check for greetings for social quest
        greetings = ['hello', 'hi', 'hey', 'greetings']
        if any(greeting in message for greeting in greetings):
            self._track_greeting(player_name, event)
            
    def show_current_quest(self, player_name):
        """Show player's current quest"""
        if player_name not in self.player_quests:
            self.client.set_chat("You have no active quest. Say !newquest to start!")
            return
            
        quest = self.player_quests[player_name]
        self.client.set_chat(f"Quest: {quest.name} - {quest.description}")
        
    def assign_new_quest(self, player_name):
        """Assign a new quest to player"""
        # Check if player already has a quest
        if player_name in self.player_quests:
            self.client.set_chat("Complete your current quest first!")
            return
            
        # Get completed quests
        completed = self.completed_quests.get(player_name, [])
        
        # Find available quests
        available = [q for q in self.quests if q.id not in completed]
        
        if not available:
            self.client.set_chat("You've completed all quests! Amazing!")
            return
            
        # Assign random quest
        quest = random.choice(available)
        self.player_quests[player_name] = quest
        self.quest_progress[player_name] = self._init_progress(quest)
        
        self.client.set_chat(f"New quest: {quest.name}!")
        time.sleep(0.5)
        self.client.set_chat(quest.description)
        
        logging.info(f"Assigned quest '{quest.name}' to {player_name}")
        
    def _init_progress(self, quest):
        """Initialize progress tracking for a quest"""
        progress = {}
        
        if quest.type == QuestType.MOVEMENT:
            if 'distance' in quest.requirements:
                progress['distance_traveled'] = 0
                progress['last_position'] = None
            elif 'x' in quest.requirements:
                progress['reached_target'] = False
                
        elif quest.type == QuestType.EXPLORATION:
            if 'corners' in quest.requirements:
                progress['visited_corners'] = []
                
        elif quest.type == QuestType.SOCIAL:
            if 'greet_count' in quest.requirements:
                progress['greeted_players'] = []
            elif 'chat_count' in quest.requirements:
                progress['chat_messages'] = 0
                
        return progress
        
    def show_quest_progress(self, player_name):
        """Show current quest progress"""
        if player_name not in self.player_quests:
            self.client.set_chat("No active quest!")
            return
            
        quest = self.player_quests[player_name]
        progress = self.quest_progress[player_name]
        
        if quest.type == QuestType.MOVEMENT:
            if 'distance' in quest.requirements:
                dist = progress.get('distance_traveled', 0)
                req = quest.requirements['distance']
                self.client.set_chat(f"Progress: {dist:.1f}/{req} tiles traveled")
                
        elif quest.type == QuestType.EXPLORATION:
            if 'corners' in quest.requirements:
                visited = len(progress.get('visited_corners', []))
                total = len(quest.requirements['corners'])
                self.client.set_chat(f"Progress: {visited}/{total} corners visited")
                
        elif quest.type == QuestType.SOCIAL:
            if 'greet_count' in quest.requirements:
                greeted = len(progress.get('greeted_players', []))
                req = quest.requirements['greet_count']
                self.client.set_chat(f"Progress: {greeted}/{req} players greeted")
            elif 'chat_count' in quest.requirements:
                count = progress.get('chat_messages', 0)
                req = quest.requirements['chat_count']
                self.client.set_chat(f"Progress: {count}/{req} messages sent")
                
    def try_complete_quest(self, player_name):
        """Check if quest is complete and give reward"""
        if player_name not in self.player_quests:
            self.client.set_chat("No active quest!")
            return
            
        quest = self.player_quests[player_name]
        progress = self.quest_progress[player_name]
        
        if self._is_quest_complete(quest, progress):
            # Give reward
            self.client.set_chat(quest.reward['message'])
            if 'xp' in quest.reward:
                self.client.set_chat(f"+{quest.reward['xp']} XP!")
                
            # Mark as completed
            if player_name not in self.completed_quests:
                self.completed_quests[player_name] = []
            self.completed_quests[player_name].append(quest.id)
            
            # Remove from active
            del self.player_quests[player_name]
            del self.quest_progress[player_name]
            
            logging.info(f"{player_name} completed quest '{quest.name}'")
        else:
            self.client.set_chat("Quest not complete yet! Say !progress to check")
            
    def _is_quest_complete(self, quest, progress):
        """Check if quest requirements are met"""
        if quest.type == QuestType.MOVEMENT:
            if 'distance' in quest.requirements:
                return progress.get('distance_traveled', 0) >= quest.requirements['distance']
            elif 'x' in quest.requirements:
                return progress.get('reached_target', False)
                
        elif quest.type == QuestType.EXPLORATION:
            if 'corners' in quest.requirements:
                return len(progress.get('visited_corners', [])) >= len(quest.requirements['corners'])
                
        elif quest.type == QuestType.SOCIAL:
            if 'greet_count' in quest.requirements:
                return len(progress.get('greeted_players', [])) >= quest.requirements['greet_count']
            elif 'chat_count' in quest.requirements:
                return progress.get('chat_messages', 0) >= quest.requirements['chat_count']
                
        return False
        
    def track_player_movement(self, event):
        """Track movement for movement quests"""
        player = event['player']
        if player.name != self.client.account_name:  # Only track other players for now
            return
            
        player_name = self.client.account_name
        if player_name not in self.player_quests:
            return
            
        quest = self.player_quests[player_name]
        progress = self.quest_progress[player_name]
        
        if quest.type == QuestType.MOVEMENT:
            if 'distance' in quest.requirements:
                # Track distance
                if progress['last_position']:
                    last_x, last_y = progress['last_position']
                    dist = ((self.client.player_x - last_x)**2 + (self.client.player_y - last_y)**2)**0.5
                    progress['distance_traveled'] += dist
                progress['last_position'] = (self.client.player_x, self.client.player_y)
                
            elif 'x' in quest.requirements:
                # Check if reached target
                target_x = quest.requirements['x']
                target_y = quest.requirements['y']
                radius = quest.requirements.get('radius', 1)
                
                dist = ((self.client.player_x - target_x)**2 + (self.client.player_y - target_y)**2)**0.5
                if dist <= radius:
                    progress['reached_target'] = True
                    self.client.set_chat("Target reached! Say !complete")
                    
        elif quest.type == QuestType.EXPLORATION:
            if 'corners' in quest.requirements:
                # Check corners
                for corner in quest.requirements['corners']:
                    cx, cy = corner
                    dist = ((self.client.player_x - cx)**2 + (self.client.player_y - cy)**2)**0.5
                    if dist <= 3 and corner not in progress['visited_corners']:
                        progress['visited_corners'].append(corner)
                        self.client.set_chat(f"Corner visited! {len(progress['visited_corners'])}/4")
                        
    def _track_greeting(self, player_name, event):
        """Track greetings for social quests"""
        if player_name not in self.player_quests:
            return
            
        quest = self.player_quests[player_name]
        progress = self.quest_progress[player_name]
        
        if quest.type == QuestType.SOCIAL and 'greet_count' in quest.requirements:
            target_player = event['player'].name
            if target_player not in progress['greeted_players'] and target_player != player_name:
                progress['greeted_players'].append(target_player)
                remaining = quest.requirements['greet_count'] - len(progress['greeted_players'])
                if remaining > 0:
                    self.client.set_chat(f"Greeted {target_player}! {remaining} more to go")
                    
    def _track_chat(self, player_name, message):
        """Track chat messages for social quests"""
        if player_name not in self.player_quests:
            return
            
        quest = self.player_quests[player_name]
        progress = self.quest_progress[player_name]
        
        if quest.type == QuestType.SOCIAL and 'chat_count' in quest.requirements:
            progress['chat_messages'] = progress.get('chat_messages', 0) + 1

def main():
    client = RebornClient("localhost", 14900)
    
    # Create quest bot
    quest_bot = QuestBot(client)
    
    # Subscribe to events
    client.events.subscribe('player_chat', quest_bot.on_chat)
    
    # Track our own movement
    def movement_tracker():
        last_pos = None
        while client.connected:
            current_pos = (client.player_x, client.player_y)
            if last_pos != current_pos:
                quest_bot.track_player_movement({'player': type('Player', (), {'name': client.account_name})})
                last_pos = current_pos
            time.sleep(0.1)
            
    # Connect and run
    if client.connect():
        logging.info("Connected to server")
        
        if client.login("questbot", "1234"):
            logging.info("Login successful")
            
            # Set appearance
            client.set_nickname("QuestGiver")
            client.set_head_image("head5.png")
            client.set_body_image("body5.png")
            client.set_chat("Quests available! Say !newquest")
            
            # Move to quest giver position
            client.move_to(25, 25)
            
            # Start movement tracker
            import threading
            tracker_thread = threading.Thread(target=movement_tracker)
            tracker_thread.daemon = True
            tracker_thread.start()
            
            try:
                logging.info("QuestBot is ready. Press Ctrl+C to stop.")
                while client.connected:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                logging.info("Shutting down...")
            finally:
                client.disconnect()
        else:
            logging.error("Login failed")
    else:
        logging.error("Connection failed")

if __name__ == "__main__":
    main()