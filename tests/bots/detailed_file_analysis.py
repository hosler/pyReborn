#!/usr/bin/env python3
"""
Detailed File Analysis Bot

Analyzes how files are actually being transferred by:
1. Monitoring all packets during level changes
2. Analyzing existing file transfer mechanisms 
3. Understanding when large file vs normal file transfers are used
4. Testing different file sizes to find large file threshold
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


class DetailedFileAnalysis:
    """Detailed analysis of file transfer mechanisms"""
    
    def __init__(self, host="localhost", port=14900):
        self.host = host
        self.port = port
        self.client = None
        
        # Track all packet activity
        self.all_packets = []
        self.file_related_packets = []
        self.level_changes = []
        
    def run(self, username: str, password: str) -> bool:
        """Run detailed file analysis"""
        
        logger.info("🔍 DETAILED FILE TRANSFER ANALYSIS")
        logger.info("=" * 50)
        
        try:
            # Initialize client
            self.client = RebornClient(host=self.host, port=self.port)
            
            # Set up comprehensive packet monitoring
            self._setup_comprehensive_monitoring()
            
            # Connect
            if not self.client.connect():
                logger.error("❌ Connection failed")
                return False
                
            if not self.client.login(username, password):
                logger.error("❌ Login failed")
                return False
                
            logger.info(f"✅ Connected as {username}")
            
            # Step 1: Monitor initial loading
            logger.info("📊 Step 1: Monitoring initial world loading...")
            time.sleep(5)
            self._analyze_initial_loading()
            
            # Step 2: Test movement to trigger file activity
            logger.info("📊 Step 2: Testing movement to trigger file activity...")
            self._test_movement_file_activity()
            
            # Step 3: Test direct file requests
            logger.info("📊 Step 3: Testing direct file requests...")
            self._test_direct_file_requests()
            
            # Step 4: Generate comprehensive analysis
            self._generate_analysis()
            
            return len(self.file_related_packets) > 0
            
        except Exception as e:
            logger.error(f"❌ Analysis failed: {e}", exc_info=True)
            return False
            
        finally:
            if self.client:
                self.client.disconnect()
    
    def _setup_comprehensive_monitoring(self):
        """Set up monitoring for all packet types"""
        
        original_process = self.client.packet_processor.manager_processor.process_packet
        
        def monitor_all_packets(packet_id, data, announced_size=0):
            # Track all packets
            packet_info = {
                'id': packet_id,
                'size': len(data),
                'time': time.time(),
                'data': data[:50].hex() if data else '',  # First 50 bytes
                'text': data[:50].decode('latin-1', errors='ignore') if data else ''
            }
            self.all_packets.append(packet_info)
            
            # Track file-related packets
            file_packet_ids = {68, 69, 84, 100, 45, 30, 102, 0, 1, 5, 6}  # Include level packets
            if packet_id in file_packet_ids:
                self.file_related_packets.append(packet_info)
                
                packet_names = {
                    68: 'LARGEFILESTART', 69: 'LARGEFILEEND', 84: 'LARGEFILESIZE',
                    100: 'RAWDATA', 45: 'FILEUPTODATE', 30: 'FILESENDFAILED', 
                    102: 'FILE', 0: 'LEVELBOARD', 1: 'LEVELLINK', 5: 'BOARDPACKET',
                    6: 'LEVELNAME'
                }
                name = packet_names.get(packet_id, f'PACKET_{packet_id}')
                
                logger.info(f"🗂️ FILE-RELATED: {name} (ID {packet_id}) - {len(data)} bytes")
                
                # Special analysis for specific packets
                if packet_id == 6:  # LEVELNAME
                    level_name = data.decode('latin-1', errors='ignore').rstrip('\x00')
                    self.level_changes.append(level_name)
                    logger.info(f"   📍 Level change: {level_name}")
                elif packet_id == 102:  # FILE
                    logger.info(f"   📄 Direct file transfer detected!")
                elif packet_id in [68, 69, 84, 100]:  # Large file packets
                    logger.info(f"   📦 Large file transfer packet!")
            
            return original_process(packet_id, data, announced_size)
        
        self.client.packet_processor.manager_packet_processor.process_packet = monitor_all_packets
        logger.info("✅ Comprehensive packet monitoring enabled")
    
    def _analyze_initial_loading(self):
        """Analyze packets received during initial loading"""
        logger.info("🔍 Analyzing initial loading packets...")
        
        total_packets = len(self.all_packets)
        file_packets = len(self.file_related_packets)
        
        logger.info(f"   📦 Total packets during loading: {total_packets}")
        logger.info(f"   🗂️ File-related packets: {file_packets}")
        
        if file_packets > 0:
            logger.info("   📊 File packet breakdown:")
            packet_counts = defaultdict(int)
            for packet in self.file_related_packets:
                packet_counts[packet['id']] += 1
            
            for pid, count in sorted(packet_counts.items()):
                packet_names = {0: 'LEVELBOARD', 1: 'LEVELLINK', 5: 'BOARDPACKET', 6: 'LEVELNAME'}
                name = packet_names.get(pid, f'PACKET_{pid}')
                logger.info(f"      {name} (ID {pid}): {count} packets")
        
        if self.level_changes:
            logger.info(f"   📍 Level changes detected: {self.level_changes}")
        
        # Check for large file activity
        large_file_packets = [p for p in self.file_related_packets if p['id'] in [68, 69, 84, 100]]
        if large_file_packets:
            logger.info(f"   🎉 LARGE FILE ACTIVITY DETECTED: {len(large_file_packets)} packets")
        else:
            logger.info("   ⚠️ No large file transfer packets during initial loading")
    
    def _test_movement_file_activity(self):
        """Test if movement triggers file activity"""
        logger.info("🚶 Testing movement-triggered file activity...")
        
        initial_packet_count = len(self.file_related_packets)
        
        # Try several movements
        movements = [(1, 0), (0, 1), (-1, 0), (0, -1), (2, 2), (-2, -2)]
        for i, (dx, dy) in enumerate(movements):
            logger.info(f"   🚶 Movement {i+1}: ({dx}, {dy})")
            
            try:
                self.client.move(dx, dy)
                time.sleep(1)  # Wait for potential file activity
                
                new_packets = len(self.file_related_packets) - initial_packet_count
                if new_packets > 0:
                    logger.info(f"      📦 Movement triggered {new_packets} file packets!")
                    return True
                    
            except Exception as e:
                logger.error(f"      ❌ Movement failed: {e}")
        
        logger.info("   ⚠️ No file activity triggered by movement")
        return False
    
    def _test_direct_file_requests(self):
        """Test direct file requests with detailed monitoring"""
        logger.info("📤 Testing direct file requests...")
        
        # Files that definitely exist on server
        test_files = [
            'chicken.gmap',
            'chicken1.nw',
            'ball_game.nw'
        ]
        
        for filename in test_files:
            logger.info(f"   📤 Requesting: {filename}")
            
            initial_count = len(self.file_related_packets)
            
            # Send WantFile request
            success = self.client.request_file(filename)
            if success:
                logger.info(f"      ✅ WantFile packet sent")
                
                # Wait for response
                time.sleep(3)
                
                new_packets = len(self.file_related_packets) - initial_count
                if new_packets > 0:
                    logger.info(f"      🎉 {new_packets} file packets received in response!")
                    return True
                else:
                    logger.info(f"      ⏳ No response packets")
            else:
                logger.warning(f"      ❌ Failed to send request")
        
        return False
    
    def _generate_analysis(self):
        """Generate comprehensive analysis report"""
        
        logger.info("=" * 70)
        logger.info("🔍 DETAILED FILE TRANSFER ANALYSIS REPORT")
        logger.info("=" * 70)
        
        # Overall packet statistics
        total_packets = len(self.all_packets)
        file_packets = len(self.file_related_packets)
        
        logger.info(f"📊 PACKET STATISTICS:")
        logger.info(f"   Total packets monitored: {total_packets}")
        logger.info(f"   File-related packets: {file_packets}")
        
        if total_packets > 0:
            file_percentage = (file_packets / total_packets) * 100
            logger.info(f"   File packet percentage: {file_percentage:.1f}%")
        
        # Packet type breakdown
        logger.info(f"\n📦 ALL PACKET TYPES SEEN:")
        if self.all_packets:
            packet_counts = defaultdict(int)
            for packet in self.all_packets:
                packet_counts[packet['id']] += 1
            
            for pid, count in sorted(packet_counts.items()):
                percentage = (count / total_packets) * 100
                logger.info(f"   Packet {pid:3d}: {count:4d} times ({percentage:5.1f}%)")
        
        # File packet analysis
        logger.info(f"\n🗂️ FILE PACKET ANALYSIS:")
        if self.file_related_packets:
            file_counts = defaultdict(int)
            for packet in self.file_related_packets:
                file_counts[packet['id']] += 1
            
            packet_names = {
                68: 'LARGEFILESTART', 69: 'LARGEFILEEND', 84: 'LARGEFILESIZE',
                100: 'RAWDATA', 45: 'FILEUPTODATE', 30: 'FILESENDFAILED',
                102: 'FILE', 0: 'LEVELBOARD', 1: 'LEVELLINK', 5: 'BOARDPACKET', 6: 'LEVELNAME'
            }
            
            for pid, count in sorted(file_counts.items()):
                name = packet_names.get(pid, f'PACKET_{pid}')
                logger.info(f"   {name} (ID {pid}): {count} packets")
        
        # Large file analysis
        large_file_packets = [p for p in self.file_related_packets if p['id'] in [68, 69, 84, 100]]
        logger.info(f"\n📦 LARGE FILE TRANSFER ANALYSIS:")
        logger.info(f"   Large file packets detected: {len(large_file_packets)}")
        
        if large_file_packets:
            logger.info("   🎉 LARGE FILE SYSTEM IS ACTIVE!")
            for packet in large_file_packets:
                packet_names = {68: 'START', 69: 'END', 84: 'SIZE', 100: 'DATA'}
                name = packet_names.get(packet['id'], str(packet['id']))
                logger.info(f"      {name}: {packet['size']} bytes, data: {packet['data'][:40]}")
        else:
            logger.info("   ⚠️ NO LARGE FILE TRANSFERS DETECTED")
            logger.info("      This suggests:")
            logger.info("      - Server uses inline file transfers (normal packets)")
            logger.info("      - Large file system only for very large files")
            logger.info("      - Files are embedded in level/GMAP packets")
            logger.info("      - Our file requests aren't triggering large transfers")
        
        # Level change analysis
        logger.info(f"\n📍 LEVEL CHANGE ANALYSIS:")
        logger.info(f"   Level changes detected: {len(self.level_changes)}")
        if self.level_changes:
            for level in self.level_changes:
                logger.info(f"      📍 {level}")
        
        # Conclusions
        logger.info(f"\n🎯 CONCLUSIONS:")
        
        if large_file_packets:
            logger.info("   ✅ Large file transfer system is working")
            logger.info("   ✅ File download pipeline is active")
        elif file_packets > 0:
            logger.info("   ✅ Files are being transferred via normal packets")
            logger.info("   ⚠️ Large file system not triggered in this test")
            logger.info("   💡 Normal packet file transfers are working correctly")
        else:
            logger.info("   ❌ No file transfer activity detected")
            logger.info("   🔧 File transfer system may need investigation")
        
        # Recommendations
        logger.info(f"\n💡 RECOMMENDATIONS:")
        
        if not large_file_packets and file_packets > 0:
            logger.info("   1. ✅ Current file system (normal packets) is working")
            logger.info("   2. 🔧 Large file system may need different trigger conditions")
            logger.info("   3. 🔧 Test with very large files to trigger large file transfers")
            logger.info("   4. 📊 Monitor longer sessions for large file activity")
        
        logger.info("=" * 70)
        
        return len(self.file_related_packets) > 0


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Detailed File Analysis')
    parser.add_argument('username', help='Account username')
    parser.add_argument('password', help='Account password')
    parser.add_argument('--host', default='localhost', help='Server host')
    parser.add_argument('--port', type=int, default=14900, help='Server port')
    
    args = parser.parse_args()
    
    analysis = DetailedFileAnalysis(host=args.host, port=args.port)
    success = analysis.run(args.username, args.password)
    
    if success:
        logger.info("🎉 Analysis completed - file activity detected")
        sys.exit(0)
    else:
        logger.info("⚠️ Analysis completed - limited file activity")
        sys.exit(1)


if __name__ == "__main__":
    main()