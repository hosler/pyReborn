#!/usr/bin/env python3
"""
Classic Reborn Client - Main Entry Point
"""

import sys
import logging

# Configure logging before imports
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

from game.client import ClassicRebornClient


def main():
    """Main entry point for Classic Reborn Client"""
    # Check for debug flag early
    if '--debug' in sys.argv:
        logging.getLogger().setLevel(logging.INFO)
        sys.argv.remove('--debug')
    
    # Create and run the client
    client = ClassicRebornClient()
    
    try:
        client.run(sys.argv[1:])
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())