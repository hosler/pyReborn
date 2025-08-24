#!/usr/bin/env python3
"""
Fresh Download Test

Try to trigger fresh file downloads by:
1. Clearing cache first
2. Moving to different levels to trigger natural file requests
3. Requesting files that might not be cached
4. Monitor the complete download pipeline
"""

import sys
import os
import time
import logging
import shutil
from pathlib import Path

# Add pyreborn to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from pyreborn.core.reborn_client import RebornClient
from pyreborn.session.events import EventType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FreshDownloadTest:
    """Test file downloads by clearing cache and triggering natural requests"""
    
    def __init__(self, host="localhost", port=14900):
        self.host = host
        self.port = port
        self.client = None
        
        # Track file activity
        self.file_packets_received = []
        self.files_downloaded = []
        self.cache_dir = None
        
    def run(self, username: str, password: str) -> bool:
        """Run fresh download test"""
        
        logger.info("🚀 FRESH FILE DOWNLOAD TEST")
        logger.info("=" * 50)
        
        try:
            # Step 1: Clear any existing cache
            self._clear_cache()
            
            # Step 2: Initialize client
            self.client = RebornClient(host=self.host, port=self.port)
            self.cache_dir = Path(self.client.cache_manager.base_cache_dir)
            
            # Step 3: Set up monitoring
            self._setup_monitoring()
            
            # Step 4: Connect
            if not self.client.connect():
                logger.error("❌ Connection failed")
                return False
                
            if not self.client.login(username, password):
                logger.error("❌ Login failed") 
                return False
                
            logger.info(f"✅ Connected as {username}")
            
            # Step 5: Wait for initial loading
            time.sleep(3)
            
            # Step 6: Check what files were loaded initially
            self._check_initial_files()
            
            # Step 7: Request files that might trigger downloads
            self._test_fresh_file_requests()
            
            # Step 8: Try level warping to trigger more downloads
            self._test_level_warping()
            
            # Step 9: Final monitoring period
            logger.info("📊 Final monitoring period...")
            time.sleep(10)
            
            # Step 10: Check final cache state
            self._check_final_cache_state()
            
            # Step 11: Generate report
            self._generate_report()
            
            return len(self.files_downloaded) > 0
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
            return False
            
        finally:
            if self.client:
                self.client.disconnect()
    
    def _clear_cache(self):
        """Clear existing cache to force fresh downloads"""
        cache_paths = [
            Path("cache"),
            Path("downloads"),
            Path.home() / ".pyreborn" / "cache"
        ]
        
        for cache_path in cache_paths:
            if cache_path.exists():
                logger.info(f"🗑️ Clearing cache: {cache_path}")
                shutil.rmtree(cache_path)
            else:
                logger.info(f"📁 Cache not found: {cache_path}")
    
    def _setup_monitoring(self):
        """Set up comprehensive monitoring"""
        
        # Monitor file packets
        original_process = self.client.packet_processor.manager_processor.process_packet
        file_packet_ids = {68, 69, 84, 100, 45, 30, 102}  # All file-related packets
        
        def monitor_packets(packet_id, data, announced_size=0):
            if packet_id in file_packet_ids:
                packet_info = {
                    'packet_id': packet_id,
                    'size': len(data),
                    'time': time.time(),
                    'data_preview': data[:20].hex() if data else ''
                }
                self.file_packets_received.append(packet_info)
                
                packet_names = {
                    68: 'LARGEFILESTART', 69: 'LARGEFILEEND', 84: 'LARGEFILESIZE', 
                    100: 'RAWDATA', 45: 'FILEUPTODATE', 30: 'FILESENDFAILED', 102: 'FILE'
                }
                name = packet_names.get(packet_id, f'PACKET_{packet_id}')
                
                logger.info(f"🗂️ FILE PACKET: {name} (ID {packet_id}) - {len(data)} bytes")
                if packet_id == 68 and len(data) > 4:
                    # Try to extract filename from LARGEFILESTART
                    try:
                        filename = data[4:].decode('latin-1', errors='ignore').rstrip('\x00')
                        logger.info(f"   📄 Starting download: {filename}")
                    except:
                        pass
            
            return original_process(packet_id, data, announced_size)
        
        self.client.packet_processor.manager_processor.process_packet = monitor_packets
        
        # Monitor file events
        if hasattr(self.client, 'events'):
            def on_file_downloaded(data):
                filename = data.get('filename', 'unknown')
                size = data.get('size', 0)
                self.files_downloaded.append({'filename': filename, 'size': size})
                logger.info(f"🎉 FILE DOWNLOADED AND CACHED: {filename} ({size} bytes)")
            
            self.client.events.subscribe(EventType.FILE_DOWNLOADED, on_file_downloaded)
        
        logger.info("✅ Comprehensive monitoring enabled")
    
    def _check_initial_files(self):
        """Check what files were loaded during initial connection"""
        logger.info("🔍 Checking initial file activity...")
        
        if self.file_packets_received:
            logger.info(f"   📦 {len(self.file_packets_received)} file packets received during login")
            for packet in self.file_packets_received:
                packet_names = {68: 'START', 69: 'END', 84: 'SIZE', 100: 'DATA'}
                name = packet_names.get(packet['packet_id'], str(packet['packet_id']))
                logger.info(f"      {name}: {packet['size']} bytes")
        else:
            logger.info("   📦 No file packets during initial login")
        
        # Check cache directory
        if self.cache_dir and self.cache_dir.exists():
            cache_files = list(self.cache_dir.rglob('*'))
            file_count = sum(1 for f in cache_files if f.is_file())
            logger.info(f"   💾 Cache files after login: {file_count}")
    
    def _test_fresh_file_requests(self):
        """Test requesting files that should trigger downloads"""
        logger.info("📤 Testing fresh file requests...")
        
        # Files to test (exist on server)
        test_files = [
            'chicken.gmap',      # GMAP file
            'chicken1.nw',       # Level file
            'chicken_cave_1.nw', # Cave level
            'ball_game.nw'       # Different level
        ]
        
        for filename in test_files:
            logger.info(f"   📤 Requesting: {filename}")
            
            # Clear packet tracking for this request
            initial_packet_count = len(self.file_packets_received)
            
            # Send request
            success = self.client.request_file(filename)
            if success:
                logger.info(f"      ✅ Request sent")
                
                # Wait and check for response
                time.sleep(2)
                
                new_packets = len(self.file_packets_received) - initial_packet_count
                if new_packets > 0:
                    logger.info(f"      📦 {new_packets} file packets received!")
                    break  # Found working file request
                else:
                    logger.info(f"      ⏳ No packets received")
            else:
                logger.warning(f"      ❌ Request failed")
            
            time.sleep(1)
    
    def _test_level_warping(self):
        """Test level warping to trigger file downloads"""
        logger.info("🌍 Testing level warping...")
        
        # Try warping to different levels
        levels_to_try = [
            'chicken1.nw',
            'chicken2.nw', 
            'chicken_cave_1.nw',
            'ball_game.nw'
        ]
        
        for level_name in levels_to_try:
            logger.info(f"   🌍 Attempting warp to: {level_name}")
            
            initial_packets = len(self.file_packets_received)
            
            try:
                # Create a level warp packet 
                from pyreborn.packets.outgoing.movement.level_warp import LevelWarpPacketHelper
                packet = LevelWarpPacketHelper.create(level_name)
                packet_bytes = packet.to_bytes()
                
                if self.client.connection_manager:
                    self.client.connection_manager.send_packet(packet_bytes)
                    logger.info(f"      ✅ Warp packet sent")
                    
                    # Wait for response
                    time.sleep(3)
                    
                    new_packets = len(self.file_packets_received) - initial_packets
                    if new_packets > 0:
                        logger.info(f"      📦 Warp triggered {new_packets} file packets!")
                    else:
                        logger.info(f"      ⏳ No file packets from warp")
                        
            except Exception as e:
                logger.error(f"      ❌ Warp failed: {e}")
            
            time.sleep(1)
    
    def _check_final_cache_state(self):
        """Check final state of cache"""
        logger.info("💾 Checking final cache state...")
        
        if self.cache_dir and self.cache_dir.exists():
            cache_files = list(self.cache_dir.rglob('*'))
            file_count = sum(1 for f in cache_files if f.is_file())
            
            logger.info(f"   📁 Final cache files: {file_count}")
            
            for cache_file in cache_files:
                if cache_file.is_file():
                    size = cache_file.stat().st_size
                    rel_path = cache_file.relative_to(self.cache_dir)
                    logger.info(f"      📄 {rel_path} ({size} bytes)")
        else:
            logger.info("   📁 No cache directory found")
    
    def _generate_report(self):
        """Generate comprehensive test report"""
        
        logger.info("=" * 60)
        logger.info("🏆 FRESH DOWNLOAD TEST REPORT")
        logger.info("=" * 60)
        
        # File packet analysis
        logger.info(f"📦 FILE PACKET ANALYSIS:")
        logger.info(f"   Total file packets received: {len(self.file_packets_received)}")
        
        if self.file_packets_received:
            packet_counts = {}
            for packet in self.file_packets_received:
                pid = packet['packet_id']
                packet_counts[pid] = packet_counts.get(pid, 0) + 1
            
            for pid, count in sorted(packet_counts.items()):
                packet_names = {68: 'LARGEFILESTART', 69: 'LARGEFILEEND', 84: 'LARGEFILESIZE', 100: 'RAWDATA'}
                name = packet_names.get(pid, f'PACKET_{pid}')
                logger.info(f"      {name} (ID {pid}): {count} packets")
        
        # Download analysis
        logger.info(f"\n📥 DOWNLOAD ANALYSIS:")
        logger.info(f"   Files downloaded: {len(self.files_downloaded)}")
        
        if self.files_downloaded:
            for file_info in self.files_downloaded:
                logger.info(f"      📄 {file_info['filename']} ({file_info['size']} bytes)")
        
        # Success assessment
        logger.info(f"\n🎯 SUCCESS ASSESSMENT:")
        
        has_file_packets = len(self.file_packets_received) > 0
        has_downloads = len(self.files_downloaded) > 0
        has_complete_sequence = any(p['packet_id'] == 68 for p in self.file_packets_received) and \
                               any(p['packet_id'] == 69 for p in self.file_packets_received)
        
        logger.info(f"   📦 File packets received: {'✅' if has_file_packets else '❌'}")
        logger.info(f"   📥 Files downloaded: {'✅' if has_downloads else '❌'}")  
        logger.info(f"   🔄 Complete download sequence: {'✅' if has_complete_sequence else '❌'}")
        
        if has_downloads:
            logger.info("   🎉 SUCCESS - File download system is working!")
        elif has_file_packets:
            logger.info("   ⚠️ PARTIAL - File packets received but not processed correctly")
        else:
            logger.info("   ❌ FAILED - No file download activity detected")
            logger.info("      Next steps:")
            logger.info("      1. Check if server is configured to send large files")
            logger.info("      2. Verify file request packet format")
            logger.info("      3. Test with files that definitely require downloading")
        
        logger.info("=" * 60)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Fresh File Download Test')
    parser.add_argument('username', help='Account username')
    parser.add_argument('password', help='Account password')
    parser.add_argument('--host', default='localhost', help='Server host')
    parser.add_argument('--port', type=int, default=14900, help='Server port')
    
    args = parser.parse_args()
    
    test = FreshDownloadTest(host=args.host, port=args.port)
    success = test.run(args.username, args.password)
    
    if success:
        logger.info("🎉 Fresh download test PASSED")
        sys.exit(0)
    else:
        logger.info("⚠️ Fresh download test shows file download issues")
        sys.exit(1)


if __name__ == "__main__":
    main()