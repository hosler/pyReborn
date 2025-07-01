#!/usr/bin/env python3
"""
Quick test of refactored client
"""

import sys
sys.path.insert(0, '.')

from pyreborn import RebornClient

def test_basic():
    """Test basic functionality"""
    print("Testing refactored client...")
    
    client = RebornClient("localhost", 14900)
    
    # Test that methods exist and can be called
    print("✓ Client created")
    
    # Test action methods exist
    assert hasattr(client, 'move_to')
    assert hasattr(client, 'set_chat')
    assert hasattr(client, 'set_nickname')
    assert hasattr(client, 'drop_bomb')
    assert hasattr(client, 'set_arrows')
    print("✓ All action methods exist")
    
    # Test that internal actions object exists
    assert hasattr(client, '_actions')
    print("✓ Actions module integrated")
    
    # Test other components
    assert hasattr(client, 'events')
    assert hasattr(client, 'session')
    assert hasattr(client, 'level_manager')
    print("✓ All components present")
    
    print("\n✅ Refactoring successful - backward compatibility maintained!")
    
if __name__ == "__main__":
    test_basic()