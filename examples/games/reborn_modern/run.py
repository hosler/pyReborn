#!/usr/bin/env python3
"""
Run the Modern Reborn Client

Usage:
    python run.py <username> <password> [options]
    
Options:
    --server HOST    Server hostname (default: localhost)
    --port PORT      Server port (default: 14900)
    --version VER    Protocol version (default: 6.037)
"""

import sys
import argparse
import logging
from client.game import ModernRebornGame

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(name)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

def main():
    parser = argparse.ArgumentParser(description='Modern Reborn Client')
    parser.add_argument('username', help='Account username')
    parser.add_argument('password', help='Account password')
    parser.add_argument('--server', default='localhost', help='Server hostname')
    parser.add_argument('--port', type=int, default=14900, help='Server port')
    parser.add_argument('--version', default='6.037', help='Protocol version')
    
    args = parser.parse_args()
    
    # Create config dictionary
    config = {
        'window': {
            'width': 1280,
            'height': 720,
            'title': 'Modern Reborn Client',
            'fps': 60
        },
        'client': {
            'host': args.server,
            'port': args.port,
            'version': args.version
        },
        'graphics': {
            'vsync': True,
            'smooth_scaling': True,
            'tile_size': 16
        },
        'audio': {
            'enabled': True,
            'master_volume': 0.8,
            'music_volume': 0.7,
            'sfx_volume': 0.9
        },
        'keybindings': {
            'move_up': 'up',
            'move_down': 'down',
            'move_left': 'left',
            'move_right': 'right',
            'attack': 'space',
            'grab': 'lctrl',
            'chat': 'return'
        },
        'debug': {
            'show_fps': True,
            'packet_inspector': False,
            'coordinate_overlay': False
        },
        'connection': {
            'username': args.username,
            'password': args.password
        }
    }
    
    # Create and run game
    game = ModernRebornGame(config)
    
    try:
        game.run()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    except Exception as e:
        logging.error(f"Game crashed: {e}", exc_info=True)
    finally:
        if hasattr(game, 'cleanup'):
            game.cleanup()
        elif hasattr(game, '_cleanup'):
            game._cleanup()

if __name__ == "__main__":
    main()