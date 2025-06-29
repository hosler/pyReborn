#!/usr/bin/env python3

import sys
sys.path.insert(0, '/home/hosler/Projects/opengraal2/pyReborn')

from pyreborn import GraalClient, EventType
from pyreborn.protocol.enums import ServerToPlayer, PlayerProp

client = GraalClient("localhost", 14900)

# Track packet statistics
packet_stats = {}

def on_raw_packet(packet_id, data):
    """Show ALL packets"""
    # Update stats
    if packet_id not in packet_stats:
        packet_stats[packet_id] = 0
    packet_stats[packet_id] += 1
    
    try:
        name = ServerToPlayer(packet_id).name
    except:
        name = f"UNKNOWN_{packet_id}"
    
    # Always show the packet
    print(f"[{packet_id:3d}] {name:<25} | hex: {data[:20].hex():<40} | size: {len(data)}")
    
    # Special decoding for some packets
    if packet_id == ServerToPlayer.PLO_OTHERPLPROPS and len(data) >= 2:
        player_id = (data[0] - 32) | ((data[1] - 32) << 8)
        print(f"     └─> Player ID: {player_id}")
        
        # Try to identify what properties are in it
        pos = 2
        props_found = []
        while pos < len(data) and pos < 20:  # Just peek at first few
            try:
                prop_id = data[pos] - 32
                prop = PlayerProp(prop_id)
                props_found.append(prop.name)
                pos += 1
                # Skip to next property (rough estimate)
                if prop in [PlayerProp.PLPROP_X, PlayerProp.PLPROP_Y, PlayerProp.PLPROP_SPRITE]:
                    pos += 1
                elif prop == PlayerProp.PLPROP_GANI:
                    if pos < len(data):
                        length = data[pos] - 32
                        pos += 1 + length
            except:
                break
        if props_found:
            print(f"     └─> Properties: {', '.join(props_found[:5])}...")
            
    elif packet_id == ServerToPlayer.PLO_TOALL and len(data) >= 3:
        player_id = (data[0] - 32) | ((data[1] - 32) << 8)
        msg_len = data[2] - 32
        if msg_len > 0 and len(data) >= 3 + msg_len:
            message = data[3:3+msg_len].decode('ascii', errors='replace')
            print(f"     └─> Player {player_id}: '{message}'")
            
    elif packet_id == ServerToPlayer.PLO_BOARDMODIFY:
        if len(data) >= 4:
            x = data[0] - 32
            y = data[1] - 32
            w = data[2] - 32
            h = data[3] - 32
            print(f"     └─> Board modify at ({x},{y}) size {w}x{h}")
            
    elif packet_id == ServerToPlayer.PLO_HITOBJECTS:
        if len(data) >= 3:
            player_id = (data[0] - 32) | ((data[1] - 32) << 8)
            print(f"     └─> Player {player_id} hit objects")

client.on(EventType.RAW_PACKET_RECEIVED, on_raw_packet)

print("📊 SHOWING ALL PACKETS - Chat what you're doing!")
print("=" * 70)

if client.connect():
    client.login("hosler", "1234")
    
    import time
    start_time = time.time()
    
    # Run until user interrupts
    try:
        while True:
            time.sleep(0.1)
            elapsed = int(time.time() - start_time)
            if elapsed % 30 == 0 and elapsed > 0:
                print(f"\n⏱️  {elapsed} seconds elapsed...")
                print(f"Packet summary: {sum(packet_stats.values())} total packets")
                top_packets = sorted(packet_stats.items(), key=lambda x: x[1], reverse=True)[:5]
                for pid, count in top_packets:
                    try:
                        name = ServerToPlayer(pid).name
                    except:
                        name = f"UNKNOWN_{pid}"
                    print(f"  {name}: {count}")
                print("=" * 70)
    except KeyboardInterrupt:
        print("\n\nStopped by user")
    
    print(f"\n{'=' * 70}")
    print(f"FINAL STATISTICS:")
    print(f"Total packets: {sum(packet_stats.values())}")
    for pid, count in sorted(packet_stats.items(), key=lambda x: x[1], reverse=True):
        try:
            name = ServerToPlayer(pid).name
        except:
            name = f"UNKNOWN_{pid}"
        print(f"  {name:<30}: {count:4d} packets")
    
client.disconnect()