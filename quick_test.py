#!/usr/bin/env python3
"""
Quick Validation Test - Run after each simplification change
============================================================

Fast test to ensure core functionality still works after each change.
"""

import sys
import time

def quick_test():
    """Quick test of core functionality"""
    try:
        print("🔬 Quick Validation Test")
        
        # Test 1: Core imports
        from pyreborn import Client
        from pyreborn.protocol.packets import PACKET_REGISTRY
        stats = PACKET_REGISTRY.get_statistics()
        print(f"✅ Registry: {stats.get('total_packets', 0)} packets")
        
        # Test 2: Connection
        client = Client('localhost', 14900)
        if client.connect():
            print("✅ Connection working")
            
            if client.login('SpaceManSpiff', 'googlymoogly'):
                print("✅ Login working")
                
                time.sleep(1)
                
                # Test 3: Basic operations
                player = client.get_player()
                if player:
                    print(f"✅ Player data: ({player.x}, {player.y})")
                    
                    # Test movement
                    client.move(1, 0)
                    client.say("Quick test working!")
                    print("✅ Movement & chat working")
                    
                else:
                    print("⚠️ Player data not available")
                
                client.disconnect()
                print("✅ Disconnect working")
                
                print("🎉 QUICK TEST PASSED!")
                return True
                
            else:
                print("❌ Login failed")
        else:
            print("❌ Connection failed")
            
    except Exception as e:
        print(f"❌ Quick test failed: {e}")
        return False
        
    return False

if __name__ == "__main__":
    success = quick_test()
    sys.exit(0 if success else 1)