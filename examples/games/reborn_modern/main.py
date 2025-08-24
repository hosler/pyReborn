#!/usr/bin/env python3
"""
Reborn Modern - A Modern Pygame Client for PyReborn
===================================================

This client showcases the new PyReborn architecture with:
- ModularRebornClient for clean dependency injection
- Event-driven rendering and updates
- Built-in packet introspection
- Modern UI with configuration support
- Plugin system for extensibility

Usage:
    python main.py                    # Launch with server browser
    python main.py user pass          # Auto-login to localhost
    python main.py user pass --server hastur.frogdice.com
    python main.py --config custom.yaml
"""

import sys
import os
import argparse
import logging
import yaml
from pathlib import Path

# Add PyReborn to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(name)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Import our game client
from client.game import ModernRebornGame


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file"""
    config_file = Path(__file__).parent / config_path
    
    # Default configuration
    default_config = {
        'window': {
            'width': 1280,
            'height': 720,
            'title': 'Reborn Modern',
            'fps': 60
        },
        'client': {
            'host': 'localhost',
            'port': 14900,
            'version': '6.037'
        },
        'debug': {
            'show_fps': True,
            'packet_inspector': False,
            'coordinate_overlay': False
        },
        'audio': {
            'enabled': True,
            'master_volume': 0.7,
            'music_volume': 0.5,
            'sfx_volume': 0.8
        },
        'graphics': {
            'vsync': True,
            'smooth_scaling': True,
            'tile_size': 16
        }
    }
    
    # Load from file if exists
    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                user_config = yaml.safe_load(f)
                # Merge with defaults
                for key, value in user_config.items():
                    if isinstance(value, dict) and key in default_config:
                        default_config[key].update(value)
                    else:
                        default_config[key] = value
        except Exception as e:
            logging.warning(f"Failed to load config from {config_path}: {e}")
    else:
        # Create default config file
        try:
            with open(config_file, 'w') as f:
                yaml.dump(default_config, f, default_flow_style=False)
            logging.info(f"Created default config at {config_file}")
        except Exception as e:
            logging.warning(f"Failed to create config file: {e}")
    
    return default_config


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Reborn Modern - Modern PyReborn Client')
    parser.add_argument('username', nargs='?', help='Username for auto-login')
    parser.add_argument('password', nargs='?', help='Password for auto-login')
    parser.add_argument('--server', default='localhost', help='Server hostname')
    parser.add_argument('--port', type=int, default=14900, help='Server port')
    parser.add_argument('--version', default='6.037', help='Client version')
    parser.add_argument('--config', default='config.yaml', help='Configuration file')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--no-audio', action='store_true', help='Disable audio')
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Override config with command line arguments
    if args.server:
        config['client']['host'] = args.server
    if args.port:
        config['client']['port'] = args.port
    if args.version:
        config['client']['version'] = args.version
    if args.debug:
        config['debug']['packet_inspector'] = True
        config['debug']['coordinate_overlay'] = True
        logging.getLogger().setLevel(logging.DEBUG)
    if args.no_audio:
        config['audio']['enabled'] = False
    
    # Create and run game
    try:
        game = ModernRebornGame(config)
        
        # Auto-login if credentials provided
        if args.username and args.password:
            game.set_auto_login(args.username, args.password)
        
        # Run the game
        game.run()
        
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())