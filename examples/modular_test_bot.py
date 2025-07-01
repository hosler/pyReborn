#!/usr/bin/env python3
"""
Modular Test Bot - Tests and demonstrates the refactored PyReborn architecture
"""

import sys
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, '..')

from pyreborn import RebornClient
from pyreborn.protocol.enums import ServerToPlayer, PlayerToServer

# Custom modules to demonstrate extensibility
class StatisticsModule:
    """Track bot statistics"""
    def __init__(self):
        self.start_time = time.time()
        self.events_received = 0
        self.packets_sent = 0
        self.players_encountered = set()
        self.chat_messages = []
        self.movements = 0
        
    def record_event(self, event_type: str):
        self.events_received += 1
        
    def record_packet(self):
        self.packets_sent += 1
        
    def record_player(self, player_name: str):
        self.players_encountered.add(player_name)
        
    def record_chat(self, player: str, message: str):
        self.chat_messages.append({
            'time': datetime.now(),
            'player': player,
            'message': message
        })
        
    def record_movement(self):
        self.movements += 1
        
    def get_summary(self) -> Dict:
        elapsed = time.time() - self.start_time
        return {
            'uptime': f"{elapsed:.1f}s",
            'events': self.events_received,
            'packets': self.packets_sent,
            'players_seen': len(self.players_encountered),
            'chat_count': len(self.chat_messages),
            'movements': self.movements
        }

class CommandModule:
    """Handle chat commands"""
    def __init__(self, bot: 'ModularTestBot'):
        self.bot = bot
        self.commands = {
            'help': self.cmd_help,
            'stats': self.cmd_stats,
            'test': self.cmd_test,
            'move': self.cmd_move,
            'follow': self.cmd_follow,
            'stop': self.cmd_stop
        }
        
    def process_command(self, player: str, message: str):
        """Process commands starting with !"""
        if not message.startswith('!'):
            return False
            
        parts = message[1:].split()
        if not parts:
            return False
            
        cmd = parts[0].lower()
        args = parts[1:]
        
        if cmd in self.commands:
            self.commands[cmd](player, args)
            return True
        else:
            self.bot.set_chat(f"Unknown command: {cmd}")
            return False
            
    def cmd_help(self, player: str, args: List[str]):
        """Show help"""
        self.bot.set_chat("Commands: !help !stats !test !move !follow !stop")
        
    def cmd_stats(self, player: str, args: List[str]):
        """Show statistics"""
        stats = self.bot.stats.get_summary()
        self.bot.set_chat(f"Stats: {stats['events']} events, {stats['players_seen']} players")
        
    def cmd_test(self, player: str, args: List[str]):
        """Run tests"""
        self.bot.run_tests()
        
    def cmd_move(self, player: str, args: List[str]):
        """Start movement pattern"""
        pattern = args[0] if args else 'circle'
        self.bot.movement_module.start_pattern(pattern)
        
    def cmd_follow(self, player: str, args: List[str]):
        """Follow a player"""
        target = args[0] if args else player
        self.bot.follow_target = target
        self.bot.set_chat(f"Following {target}")
        
    def cmd_stop(self, player: str, args: List[str]):
        """Stop current action"""
        self.bot.movement_module.stop()
        self.bot.follow_target = None
        self.bot.set_chat("Stopped")

class MovementModule:
    """Handle movement patterns"""
    def __init__(self, bot: 'ModularTestBot'):
        self.bot = bot
        self.pattern = None
        self.pattern_step = 0
        self.center_x = 30
        self.center_y = 30
        
    def start_pattern(self, pattern: str):
        """Start a movement pattern"""
        self.pattern = pattern
        self.pattern_step = 0
        self.center_x = self.bot.local_player.x
        self.center_y = self.bot.local_player.y
        self.bot.set_chat(f"Starting {pattern} pattern")
        
    def stop(self):
        """Stop movement"""
        self.pattern = None
        
    def update(self):
        """Update movement"""
        if not self.pattern:
            return
            
        if self.pattern == 'circle':
            self._move_circle()
        elif self.pattern == 'square':
            self._move_square()
        elif self.pattern == 'random':
            self._move_random()
            
    def _move_circle(self):
        """Circular movement"""
        import math
        radius = 5
        angle = (self.pattern_step * 30) * math.pi / 180
        x = self.center_x + radius * math.cos(angle)
        y = self.center_y + radius * math.sin(angle)
        self.bot.move_to(x, y)
        self.pattern_step = (self.pattern_step + 1) % 12
        
    def _move_square(self):
        """Square movement"""
        positions = [
            (self.center_x - 4, self.center_y - 4),
            (self.center_x + 4, self.center_y - 4),
            (self.center_x + 4, self.center_y + 4),
            (self.center_x - 4, self.center_y + 4)
        ]
        pos = positions[self.pattern_step % 4]
        self.bot.move_to(pos[0], pos[1])
        self.pattern_step += 1
        
    def _move_random(self):
        """Random movement"""
        import random
        x = self.center_x + random.uniform(-5, 5)
        y = self.center_y + random.uniform(-5, 5)
        self.bot.move_to(max(5, min(59, x)), max(5, min(59, y)))

class ModularTestBot(RebornClient):
    """Test bot using modular architecture"""
    
    def __init__(self, host: str, port: int = 14900):
        super().__init__(host, port)
        
        # Initialize modules
        self.stats = StatisticsModule()
        self.commands = CommandModule(self)
        self.movement_module = MovementModule(self)
        
        # Bot state
        self.follow_target: Optional[str] = None
        self.test_results = []
        
        # Setup event handlers
        self._setup_handlers()
        
    def _setup_handlers(self):
        """Setup all event handlers"""
        # Player events
        self.events.subscribe('player_added', self._on_player_added)
        self.events.subscribe('player_removed', self._on_player_removed)
        self.events.subscribe('player_moved', self._on_player_moved)
        self.events.subscribe('player_chat', self._on_player_chat)
        self.events.subscribe('player_props_changed', self._on_player_props)
        
        # Level events
        self.events.subscribe('level_changed', self._on_level_changed)
        
        # Connection events
        self.events.subscribe('connected', self._on_connected)
        self.events.subscribe('disconnected', self._on_disconnected)
        
    def _on_player_added(self, event):
        """Handle player joining"""
        player = event.get('player')
        if player and hasattr(player, 'name'):
            self.stats.record_player(player.name)
            self.stats.record_event('player_added')
            print(f"[+] Player joined: {player.name}")
            
    def _on_player_removed(self, event):
        """Handle player leaving"""
        player = event.get('player')
        if player and hasattr(player, 'name'):
            self.stats.record_event('player_removed')
            print(f"[-] Player left: {player.name}")
            
    def _on_player_moved(self, event):
        """Handle player movement"""
        player = event.get('player')
        if player and hasattr(player, 'name'):
            self.stats.record_event('player_moved')
            
            # Follow logic
            if self.follow_target and player.name == self.follow_target:
                self._follow_player(player)
                
    def _on_player_chat(self, event):
        """Handle chat messages"""
        player = event.get('player')
        message = event.get('message', '')
        
        if player and hasattr(player, 'name'):
            self.stats.record_chat(player.name, message)
            self.stats.record_event('player_chat')
            print(f"[Chat] {player.name}: {message}")
            
            # Process commands
            self.commands.process_command(player.name, message)
            
    def _on_player_props(self, event):
        """Handle property changes"""
        self.stats.record_event('player_props_changed')
        
    def _on_level_changed(self, event):
        """Handle level changes"""
        self.stats.record_event('level_changed')
        level_name = event.get('level_name', 'unknown')
        print(f"[Level] Changed to: {level_name}")
        
    def _on_connected(self, event):
        """Handle connection"""
        self.stats.record_event('connected')
        print("[Connected]")
        
    def _on_disconnected(self, event):
        """Handle disconnection"""
        self.stats.record_event('disconnected')
        print("[Disconnected]")
        
    def _follow_player(self, target):
        """Follow a player"""
        import math
        dx = target.x - self.local_player.x
        dy = target.y - self.local_player.y
        distance = math.sqrt(dx**2 + dy**2)
        
        if distance > 2:
            move_x = self.local_player.x + (dx / distance)
            move_y = self.local_player.y + (dy / distance)
            self.move_to(move_x, move_y)
            
    # Override to track statistics
    def move_to(self, x: float, y: float, direction=None):
        """Override to track movements"""
        super().move_to(x, y, direction)
        self.stats.record_movement()
        
    def _send_packet(self, packet):
        """Override to track packets"""
        super()._send_packet(packet)
        self.stats.record_packet()
        
    def run_tests(self):
        """Run tests on the refactored architecture"""
        print("\n" + "="*50)
        print("RUNNING MODULAR ARCHITECTURE TESTS")
        print("="*50)
        
        tests_passed = 0
        tests_total = 0
        
        # Test 1: Actions module exists
        tests_total += 1
        try:
            assert hasattr(self, '_actions'), "Actions module not found"
            assert self._actions is not None, "Actions module is None"
            print("✓ Test 1: Actions module integrated")
            tests_passed += 1
        except AssertionError as e:
            print(f"✗ Test 1: {e}")
            
        # Test 2: All action methods work
        tests_total += 1
        try:
            # Test that methods exist and delegate properly
            assert hasattr(self, 'set_chat'), "set_chat method missing"
            assert hasattr(self, 'set_nickname'), "set_nickname missing"
            assert hasattr(self, 'drop_bomb'), "drop_bomb missing"
            print("✓ Test 2: Action methods available")
            tests_passed += 1
        except AssertionError as e:
            print(f"✗ Test 2: {e}")
            
        # Test 3: Event system works
        tests_total += 1
        try:
            test_data = {'test': True}
            received = []
            
            def test_handler(event):
                received.append(event)
                
            self.events.subscribe('test_event', test_handler)
            self.events.emit('test_event', test_data)
            
            assert len(received) == 1, "Event not received"
            assert received[0] == test_data, "Event data mismatch"
            print("✓ Test 3: Event system functional")
            tests_passed += 1
        except AssertionError as e:
            print(f"✗ Test 3: {e}")
            
        # Test 4: Components accessible
        tests_total += 1
        try:
            assert hasattr(self, 'session'), "Session missing"
            assert hasattr(self, 'level_manager'), "Level manager missing"
            assert hasattr(self, 'events'), "Events missing"
            print("✓ Test 4: All components accessible")
            tests_passed += 1
        except AssertionError as e:
            print(f"✗ Test 4: {e}")
            
        # Test 5: Custom modules work
        tests_total += 1
        try:
            assert hasattr(self, 'stats'), "Stats module missing"
            assert hasattr(self, 'commands'), "Commands module missing"
            assert hasattr(self, 'movement_module'), "Movement module missing"
            
            # Test module functionality
            initial_events = self.stats.events_received
            self.stats.record_event('test')
            assert self.stats.events_received == initial_events + 1
            print("✓ Test 5: Custom modules functional")
            tests_passed += 1
        except AssertionError as e:
            print(f"✗ Test 5: {e}")
            
        # Summary
        print("="*50)
        print(f"Tests passed: {tests_passed}/{tests_total}")
        self.set_chat(f"Tests: {tests_passed}/{tests_total} passed")
        
        return tests_passed == tests_total
        
    def run(self):
        """Main bot loop"""
        print("\nModular Test Bot Running")
        print("Commands: !help !stats !test !move !follow !stop")
        print("Press Ctrl+C to stop\n")
        
        last_update = time.time()
        last_stats = time.time()
        
        try:
            while self.connected:
                current_time = time.time()
                
                # Update movement
                if current_time - last_update >= 1.0:
                    self.movement_module.update()
                    last_update = current_time
                    
                # Show stats periodically
                if current_time - last_stats >= 30.0:
                    stats = self.stats.get_summary()
                    print(f"\n[Stats] {stats}")
                    last_stats = current_time
                    
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\nShutting down...")
            
        # Final stats
        print("\nFinal Statistics:")
        stats = self.stats.get_summary()
        for key, value in stats.items():
            print(f"  {key}: {value}")

def main():
    """Main entry point"""
    print("Modular Test Bot")
    print("================")
    print("This bot tests the refactored PyReborn architecture")
    print()
    
    bot = ModularTestBot("localhost", 14900)
    
    print("Connecting...")
    if not bot.connect():
        print("Failed to connect!")
        return 1
        
    print("Logging in...")
    if not bot.login("modularbot", "1234"):
        print("Login failed!")
        return 1
        
    print("Setting up bot...")
    bot.set_nickname("ModularBot")
    bot.set_chat("Modular test bot online! Say !help")
    
    # Run initial tests
    print("\nRunning architecture tests...")
    if bot.run_tests():
        print("All tests passed! ✅")
    else:
        print("Some tests failed! ❌")
        
    # Start main loop
    bot.run()
    
    bot.disconnect()
    return 0

if __name__ == "__main__":
    sys.exit(main())