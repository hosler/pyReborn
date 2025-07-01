#!/usr/bin/env python3
"""
Server Monitor - Monitors server activity and generates reports
"""

from pyreborn import RebornClient
import time
import json
import datetime
import threading
import logging
from collections import defaultdict

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class ServerMonitor:
    def __init__(self, client):
        self.client = client
        self.start_time = datetime.datetime.now()
        
        # Statistics
        self.stats = {
            'total_players_seen': set(),
            'player_join_count': 0,
            'player_leave_count': 0,
            'chat_message_count': 0,
            'movement_count': 0,
            'level_changes': 0,
            'peak_players': 0,
            'current_players': 0,
        }
        
        # Detailed tracking
        self.player_sessions = {}  # player_name -> list of sessions
        self.chat_log = []
        self.player_activity = defaultdict(lambda: {
            'join_times': [],
            'leave_times': [],
            'chat_count': 0,
            'levels_visited': set(),
            'total_time': 0,
            'last_seen': None,
        })
        
        # Real-time data
        self.online_players = {}
        
    def setup_handlers(self):
        """Setup event handlers"""
        self.client.events.subscribe('player_joined', self.on_player_joined)
        self.client.events.subscribe('player_left', self.on_player_left)
        self.client.events.subscribe('player_chat', self.on_player_chat)
        self.client.events.subscribe('player_moved', self.on_player_moved)
        self.client.events.subscribe('level_changed', self.on_level_changed)
        
    def on_player_joined(self, event):
        """Track player joins"""
        player = event['player']
        
        self.stats['player_join_count'] += 1
        self.stats['total_players_seen'].add(player.name)
        
        # Track session
        self.online_players[player.name] = {
            'player': player,
            'join_time': datetime.datetime.now(),
            'chat_count': 0,
            'move_count': 0,
        }
        
        # Update activity
        activity = self.player_activity[player.name]
        activity['join_times'].append(datetime.datetime.now())
        activity['levels_visited'].add(player.level)
        activity['last_seen'] = datetime.datetime.now()
        
        # Update peak
        self.stats['current_players'] = len(self.online_players)
        if self.stats['current_players'] > self.stats['peak_players']:
            self.stats['peak_players'] = self.stats['current_players']
            
        logging.info(f"Player joined: {player.nickname} ({player.name})")
        
    def on_player_left(self, event):
        """Track player leaves"""
        player = event['player']
        
        self.stats['player_leave_count'] += 1
        
        # Calculate session time
        if player.name in self.online_players:
            session = self.online_players[player.name]
            session_time = (datetime.datetime.now() - session['join_time']).total_seconds()
            
            # Update activity
            activity = self.player_activity[player.name]
            activity['leave_times'].append(datetime.datetime.now())
            activity['total_time'] += session_time
            
            # Remove from online
            del self.online_players[player.name]
            
        self.stats['current_players'] = len(self.online_players)
        logging.info(f"Player left: {player.nickname} ({player.name})")
        
    def on_player_chat(self, event):
        """Track chat messages"""
        player = event['player']
        message = event['message']
        
        self.stats['chat_message_count'] += 1
        
        # Log chat
        self.chat_log.append({
            'timestamp': datetime.datetime.now().isoformat(),
            'player': player.name,
            'nickname': player.nickname,
            'message': message,
            'level': player.level,
        })
        
        # Update activity
        self.player_activity[player.name]['chat_count'] += 1
        
        # Update session
        if player.name in self.online_players:
            self.online_players[player.name]['chat_count'] += 1
            
    def on_player_moved(self, event):
        """Track movements"""
        player = event['player']
        
        self.stats['movement_count'] += 1
        
        # Update session
        if player.name in self.online_players:
            self.online_players[player.name]['move_count'] += 1
            
        # Update activity
        self.player_activity[player.name]['last_seen'] = datetime.datetime.now()
        self.player_activity[player.name]['levels_visited'].add(player.level)
        
    def on_level_changed(self, event):
        """Track level changes"""
        self.stats['level_changes'] += 1
        
    def generate_report(self):
        """Generate activity report"""
        runtime = (datetime.datetime.now() - self.start_time).total_seconds()
        hours = runtime / 3600
        
        report = {
            'generated_at': datetime.datetime.now().isoformat(),
            'runtime_seconds': runtime,
            'runtime_hours': hours,
            'statistics': {
                'total_unique_players': len(self.stats['total_players_seen']),
                'total_joins': self.stats['player_join_count'],
                'total_leaves': self.stats['player_leave_count'],
                'total_chat_messages': self.stats['chat_message_count'],
                'total_movements': self.stats['movement_count'],
                'peak_concurrent_players': self.stats['peak_players'],
                'current_online_players': self.stats['current_players'],
                'average_players': self.stats['player_join_count'] / hours if hours > 0 else 0,
            },
            'online_now': {},
            'player_rankings': {},
            'recent_chat': [],
        }
        
        # Add online players
        for name, session in self.online_players.items():
            player = session['player']
            session_time = (datetime.datetime.now() - session['join_time']).total_seconds()
            report['online_now'][name] = {
                'nickname': player.nickname,
                'level': player.level,
                'session_time_minutes': session_time / 60,
                'chat_messages': session['chat_count'],
                'movements': session['move_count'],
            }
            
        # Calculate player rankings
        rankings = {
            'most_active': [],
            'most_talkative': [],
            'longest_playtime': [],
        }
        
        # Sort by different metrics
        for name, activity in self.player_activity.items():
            if activity['total_time'] > 0:
                rankings['longest_playtime'].append({
                    'player': name,
                    'hours': activity['total_time'] / 3600,
                })
                
            if activity['chat_count'] > 0:
                rankings['most_talkative'].append({
                    'player': name,
                    'messages': activity['chat_count'],
                })
                
            if len(activity['join_times']) > 0:
                rankings['most_active'].append({
                    'player': name,
                    'sessions': len(activity['join_times']),
                    'levels_visited': len(activity['levels_visited']),
                })
                
        # Sort and limit rankings
        rankings['longest_playtime'].sort(key=lambda x: x['hours'], reverse=True)
        rankings['most_talkative'].sort(key=lambda x: x['messages'], reverse=True)
        rankings['most_active'].sort(key=lambda x: x['sessions'], reverse=True)
        
        for key in rankings:
            rankings[key] = rankings[key][:10]  # Top 10
            
        report['player_rankings'] = rankings
        
        # Recent chat (last 20 messages)
        report['recent_chat'] = self.chat_log[-20:]
        
        return report
        
    def save_report(self, filename='server_report.json'):
        """Save report to file"""
        report = self.generate_report()
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        logging.info(f"Report saved to {filename}")
        
    def print_summary(self):
        """Print current summary"""
        print("\n" + "="*60)
        print("SERVER MONITOR SUMMARY")
        print("="*60)
        print(f"Uptime: {(datetime.datetime.now() - self.start_time).total_seconds() / 60:.1f} minutes")
        print(f"Players online: {self.stats['current_players']}")
        print(f"Peak players: {self.stats['peak_players']}")
        print(f"Total unique players: {len(self.stats['total_players_seen'])}")
        print(f"Chat messages: {self.stats['chat_message_count']}")
        print(f"Join/Leave events: {self.stats['player_join_count']}/{self.stats['player_leave_count']}")
        
        if self.online_players:
            print("\nOnline Players:")
            for name, session in self.online_players.items():
                player = session['player']
                session_mins = (datetime.datetime.now() - session['join_time']).total_seconds() / 60
                print(f"  - {player.nickname} ({name}) - {session_mins:.1f} mins")
                
    def start_periodic_reports(self, interval=300):
        """Save reports periodically"""
        def save_periodic():
            while self.client.connected:
                time.sleep(interval)
                if self.client.connected:
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    self.save_report(f"server_report_{timestamp}.json")
                    self.print_summary()
                    
        thread = threading.Thread(target=save_periodic)
        thread.daemon = True
        thread.start()

def main():
    client = RebornClient("localhost", 14900)
    
    # Create monitor
    monitor = ServerMonitor(client)
    monitor.setup_handlers()
    
    # Connect and run
    if client.connect():
        logging.info("Connected to server")
        
        if client.login("monitor", "1234"):
            logging.info("Login successful")
            
            # Set appearance
            client.set_nickname("ServerMonitor")
            client.set_chat("Monitoring server activity...")
            
            # Start periodic reports (every 5 minutes)
            monitor.start_periodic_reports(300)
            
            # Print initial status
            print("\nServer Monitor Started")
            print("=====================")
            print("Monitoring server activity...")
            print("Reports will be saved every 5 minutes")
            print("Press Ctrl+C to stop and save final report")
            print()
            
            try:
                while client.connected:
                    time.sleep(30)  # Print summary every 30 seconds
                    monitor.print_summary()
                    
            except KeyboardInterrupt:
                logging.info("Shutting down...")
            finally:
                # Save final report
                monitor.save_report("server_report_final.json")
                monitor.print_summary()
                client.disconnect()
                
        else:
            logging.error("Login failed")
    else:
        logging.error("Connection failed")

if __name__ == "__main__":
    main()