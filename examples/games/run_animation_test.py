#!/usr/bin/env python3
"""
Quick test runner for animation fixes
"""

import subprocess
import sys

print("=" * 60)
print("ANIMATION FIX TEST")
print("=" * 60)
print()
print("Starting Classic Reborn Client with animation debug logging...")
print()
print("Test steps:")
print("1. Connect to the server")
print("2. Try moving with arrow keys - you should see:")
print("   - 'DEBUG: Started walking animation' in console")
print("   - Walking animation should play continuously while moving")
print()
print("3. Press S or Space to swing sword - you should see:")
print("   - 'DEBUG: Started sword animation' in console")
print("   - After a moment: 'DEBUG: Sword animation finished'")
print("   - Then either 'DEBUG: Returning to idle' or 'DEBUG: Returning to walk'")
print()
print("4. The sword animation should NOT get stuck on the last frame")
print()
print("-" * 60)
print()

# Run the client
subprocess.run([sys.executable, "classic_reborn_client.py"])