#!/usr/bin/env python3
"""Test server list connection directly"""

import sys
import logging
from pyreborn import RebornClient

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_serverlist(username, password):
    """Test getting server list"""
    print(f"\nTesting server list connection for account: {username}")
    print("-" * 60)
    
    try:
        # Use the static method to get server list
        servers, status_info = RebornClient.get_server_list(username, password)
        
        print(f"\nStatus info: {status_info}")
        print(f"\nFound {len(servers)} servers")
        
        if servers:
            print("\nServer List:")
            print("-" * 60)
            for i, server in enumerate(servers):
                print(f"{i+1}. {server.name}")
                print(f"   Type: {server.type_name}")
                print(f"   Players: {server.players}")
                print(f"   Address: {server.ip}:{server.port}")
                print(f"   Language: {server.language}")
                print(f"   Version: {server.version}")
                print()
        else:
            print("\nNo servers found!")
            if 'error' in status_info:
                print(f"Error: {status_info['error']}")
                
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_serverlist.py <username> <password>")
        sys.exit(1)
        
    username = sys.argv[1]
    password = sys.argv[2]
    
    test_serverlist(username, password)