#!/usr/bin/env python3
"""
Packet Monitor Bot

Monitors all incoming packets to identify any file-related packets
that might be missed or unknown packet IDs.
"""

import sys
import os
import time
import logging
from collections import defaultdict

# Add pyreborn to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from pyreborn.core.reborn_client import RebornClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PacketMonitorBot:
    """Monitor all incoming packets for debugging"""
    
    def __init__(self, host="localhost", port=14900):
        self.host = host
        self.port = port
        self.client = None
        
        # Packet statistics
        self.packet_stats = defaultdict(int)
        self.unknown_packets = defaultdict(int)
        self.file_related_packets = []
        
        # File-related packet IDs we're looking for
        self.file_packet_ids = {68, 69, 84, 100, 45, 30, 67, 95, 102}
    
    def run(self, username: str, password: str, duration: int = 30):
        """Run the packet monitor"""
        logger.info("=" * 60)
        logger.info("PACKET MONITOR BOT STARTING")
        logger.info("=" * 60)
        
        try:
            # Create client
            self.client = RebornClient(host=self.host, port=self.port)
            
            # Set up packet monitoring
            self._setup_packet_monitoring()
            
            # Connect and login
            if not self.client.connect():
                logger.error("Failed to connect to server")
                return False
                
            if not self.client.login(username, password):
                logger.error("Failed to login")
                return False
                
            logger.info(f"✅ Successfully logged in as {username}")
            
            # Wait and monitor
            time.sleep(2)
            
            # Send some file requests with different packet IDs
            self._test_different_file_request_methods()
            
            # Monitor for specified duration
            logger.info(f"📊 Monitoring packets for {duration} seconds...")
            start_time = time.time()
            
            while time.time() - start_time < duration:
                time.sleep(1)
                if (time.time() - start_time) % 10 == 0:
                    self._report_stats()
            
            # Final report
            self._generate_final_report()
            
            return True
            
        except Exception as e:
            logger.error(f"Monitor bot error: {e}", exc_info=True)
            return False
            
        finally:
            if self.client:
                self.client.disconnect()
                logger.info("Disconnected from server")
    
    def _setup_packet_monitoring(self):
        """Set up packet monitoring hooks"""
        
        # Hook into the manager packet processor to monitor all packets
        original_process = self.client.packet_processor.manager_processor.process_packet
        
        def monitor_process_packet(packet_id, data, announced_size=0):
            # Track packet statistics
            self.packet_stats[packet_id] += 1
            
            # Check for file-related packets
            if packet_id in self.file_packet_ids:
                self.file_related_packets.append({
                    'packet_id': packet_id,
                    'size': len(data),
                    'time': time.time(),
                    'data_preview': data[:20].hex() if data else ''
                })
                logger.info(f"🗂️ FILE PACKET DETECTED: ID={packet_id}, size={len(data)}, preview={data[:10].hex()}")
            
            # Check for unknown packets (those that return None)
            result = original_process(packet_id, data, announced_size)
            if result is None and packet_id not in [0, 1, 2, 6, 9]:  # Skip common known packets
                self.unknown_packets[packet_id] += 1
                if self.unknown_packets[packet_id] <= 3:  # Only log first few occurrences
                    logger.info(f"❓ UNKNOWN PACKET: ID={packet_id}, size={len(data)}, preview={data[:10].hex()}")
            
            return result
        
        # Replace the process_packet method
        self.client.packet_processor.manager_processor.process_packet = monitor_process_packet
        
        logger.info("✅ Packet monitoring hooks installed")
    
    def _test_different_file_request_methods(self):
        """Test different file request packet IDs"""
        logger.info("🔧 Testing different file request methods...")
        
        test_filename = "chicken.gmap"
        
        # Try different packet IDs that might be used for file requests
        request_packet_ids = [
            (95, "PLO_REQUESTFILE (guess)"),
            (94, "PLO_FILESIZE (possible)"), 
            (96, "PLO_REQUESTLEVEL (possible)"),
            (93, "PLO_FILEREQUEST (possible)"),
            (21, "PLO_LEVELREQUEST (possible)"),
            (150, "PLO_REQUESTFILE2 (guess)")
        ]
        
        for packet_id, description in request_packet_ids:
            logger.info(f"  Testing packet ID {packet_id}: {description}")
            try:
                # Create file request packet
                packet_data = bytearray()
                packet_data.append(packet_id)
                packet_data.extend(test_filename.encode('latin-1'))
                packet_data.append(0)  # Null terminator
                
                if self.client.connection_manager:
                    self.client.connection_manager.send_packet(bytes(packet_data))
                    logger.info(f"    ✅ Sent file request with packet ID {packet_id}")
                    
                    # Wait a moment for potential response
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"    ❌ Error with packet ID {packet_id}: {e}")
            
            time.sleep(0.5)  # Brief pause between requests
    
    def _report_stats(self):
        """Report current packet statistics"""
        total_packets = sum(self.packet_stats.values())
        logger.info(f"📊 Packet stats: {total_packets} total packets received")
        
        # Show top packet types
        top_packets = sorted(self.packet_stats.items(), key=lambda x: x[1], reverse=True)[:5]
        for packet_id, count in top_packets:
            logger.info(f"  Packet {packet_id}: {count} times")
        
        # File-related packets
        if self.file_related_packets:
            logger.info(f"🗂️ File packets detected: {len(self.file_related_packets)}")
        
        # Unknown packets
        if self.unknown_packets:
            logger.info(f"❓ Unknown packets: {len(self.unknown_packets)} types")
    
    def _generate_final_report(self):
        """Generate final monitoring report"""
        logger.info("=" * 60)
        logger.info("PACKET MONITORING REPORT")
        logger.info("=" * 60)
        
        total_packets = sum(self.packet_stats.values())
        logger.info(f"📊 TOTAL PACKETS RECEIVED: {total_packets}")
        
        # All packet types
        logger.info(f"\n📦 ALL PACKET TYPES:")
        sorted_packets = sorted(self.packet_stats.items())
        for packet_id, count in sorted_packets:
            percentage = (count / total_packets) * 100 if total_packets > 0 else 0
            logger.info(f"  Packet {packet_id:3d}: {count:4d} times ({percentage:5.1f}%)")
        
        # File-related packets
        logger.info(f"\n🗂️ FILE-RELATED PACKETS:")
        if self.file_related_packets:
            for packet_info in self.file_related_packets:
                logger.info(f"  ID {packet_info['packet_id']:3d}: {packet_info['size']:4d} bytes, preview: {packet_info['data_preview']}")
        else:
            logger.info("  ❌ NO FILE-RELATED PACKETS DETECTED")
        
        # Unknown packets
        logger.info(f"\n❓ UNKNOWN PACKETS:")
        if self.unknown_packets:
            for packet_id, count in sorted(self.unknown_packets.items()):
                logger.info(f"  ID {packet_id:3d}: {count:4d} times")
                
            logger.info(f"\n💡 RECOMMENDATIONS:")
            logger.info(f"  - Unknown packet IDs might be file download packets")
            logger.info(f"  - Consider implementing handlers for frequent unknown packets")
            logger.info(f"  - Check if any unknown packets have file-like data patterns")
        else:
            logger.info("  ✅ All packets recognized by registry")
        
        # Analysis
        logger.info(f"\n🔍 ANALYSIS:")
        if not self.file_related_packets:
            logger.info(f"  ⚠️  No file download packets detected during monitoring")
            logger.info(f"     This suggests:")
            logger.info(f"     - Server may not respond to our file request packets")
            logger.info(f"     - Files may be sent via different packet types")
            logger.info(f"     - Server may not have the requested files")
            logger.info(f"     - File requests may require different authentication/context")
        
        if self.unknown_packets:
            logger.info(f"  🔧 Consider investigating unknown packets:")
            frequent_unknown = [(pid, count) for pid, count in self.unknown_packets.items() if count >= 3]
            for packet_id, count in frequent_unknown:
                logger.info(f"     - Packet {packet_id} ({count} times) might be important")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Packet Monitor Bot')
    parser.add_argument('username', help='Account username')
    parser.add_argument('password', help='Account password')
    parser.add_argument('--host', default='localhost', help='Server host')
    parser.add_argument('--port', type=int, default=14900, help='Server port')
    parser.add_argument('--duration', type=int, default=30, help='Monitor duration in seconds')
    
    args = parser.parse_args()
    
    # Create and run monitor bot
    bot = PacketMonitorBot(host=args.host, port=args.port)
    success = bot.run(args.username, args.password, args.duration)
    
    if success:
        logger.info("✅ Monitoring completed successfully")
        sys.exit(0)
    else:
        logger.error("❌ Monitoring failed")
        sys.exit(1)


if __name__ == "__main__":
    main()