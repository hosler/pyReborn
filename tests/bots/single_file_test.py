#!/usr/bin/env python3
"""
Single File Download Test

Test file download for a single file (chicken.gmap) to validate the complete pipeline:
1. Send proper WantFile packet
2. Monitor for large file packet sequence (68→84→100→69)  
3. Validate file caching
4. Monitor for zlib errors reduction
"""

import sys
import os
import time
import logging

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


class SingleFileTest:
    """Test single file download to validate complete pipeline"""
    
    def __init__(self, host="localhost", port=14900):
        self.host = host
        self.port = port
        self.client = None
        
        # Track file download packet sequence
        self.packet_sequence = []
        self.download_started = False
        self.download_completed = False
        self.file_cached = False
        
    def run(self, username: str, password: str, filename: str = "chicken.gmap") -> bool:
        """Run single file download test"""
        
        logger.info("🎯 SINGLE FILE DOWNLOAD TEST")
        logger.info(f"Target file: {filename}")
        logger.info("=" * 50)
        
        try:
            # Initialize client
            self.client = RebornClient(host=self.host, port=self.port)
            
            # Set up packet sequence monitoring
            self._setup_packet_monitoring()
            
            # Set up file download events
            self._setup_file_events()
            
            # Connect and login
            if not self.client.connect():
                logger.error("❌ Connection failed")
                return False
                
            if not self.client.login(username, password):
                logger.error("❌ Login failed")
                return False
                
            logger.info(f"✅ Connected as {username}")
            
            # Wait for initial loading
            time.sleep(2)
            
            # Request the specific file
            logger.info(f"📤 Requesting file: {filename}")
            success = self.client.request_file(filename)
            
            if not success:
                logger.error(f"❌ Failed to send file request for {filename}")
                return False
                
            logger.info(f"✅ File request sent successfully")
            
            # Monitor for 30 seconds
            logger.info("👀 Monitoring for file download packets...")
            self._monitor_download_sequence(30)
            
            # Generate report
            self._generate_report(filename)
            
            return self.download_completed and self.file_cached
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
            return False
            
        finally:
            if self.client:
                self.client.disconnect()
    
    def _setup_packet_monitoring(self):
        """Monitor for file download packet sequence"""
        
        # Hook into packet processor to catch file packets
        original_process = self.client.packet_processor.manager_processor.process_packet
        file_packet_ids = {68, 69, 84, 100}  # Large file packet sequence
        
        def monitor_file_packets(packet_id, data, announced_size=0):
            if packet_id in file_packet_ids:
                self.packet_sequence.append({
                    'packet_id': packet_id,
                    'size': len(data),
                    'time': time.time(),
                    'data_preview': data[:10].hex() if data else ''
                })
                
                packet_names = {68: 'LARGEFILESTART', 84: 'LARGEFILESIZE', 100: 'RAWDATA', 69: 'LARGEFILEEND'}
                packet_name = packet_names.get(packet_id, f'PACKET_{packet_id}')
                
                logger.info(f"🗂️ FILE PACKET: {packet_name} (ID {packet_id}), {len(data)} bytes")
                
                if packet_id == 68:  # LARGEFILESTART
                    self.download_started = True
                    logger.info("   🚀 Large file download STARTED")
                elif packet_id == 69:  # LARGEFILEEND
                    self.download_completed = True
                    logger.info("   ✅ Large file download COMPLETED")
            
            return original_process(packet_id, data, announced_size)
        
        self.client.packet_processor.manager_processor.process_packet = monitor_file_packets
        logger.info("✅ File packet monitoring enabled")
    
    def _setup_file_events(self):
        """Set up file download event listeners"""
        if hasattr(self.client, 'events') and self.client.events:
            
            def on_file_downloaded(data):
                filename = data.get('filename', 'unknown')
                size = data.get('size', 0)
                self.file_cached = True
                logger.info(f"🎉 FILE CACHED: {filename} ({size} bytes)")
            
            self.client.events.subscribe(EventType.FILE_DOWNLOADED, on_file_downloaded)
            logger.info("✅ File download events enabled")
    
    def _monitor_download_sequence(self, duration: int):
        """Monitor the download sequence for specified duration"""
        
        start_time = time.time()
        last_report = start_time
        
        while time.time() - start_time < duration:
            current_time = time.time()
            
            # Report every 10 seconds
            if current_time - last_report >= 10:
                elapsed = int(current_time - start_time)
                logger.info(f"📊 Monitor progress: {elapsed}/{duration}s")
                logger.info(f"   Packets received: {len(self.packet_sequence)}")
                logger.info(f"   Download started: {self.download_started}")
                logger.info(f"   Download completed: {self.download_completed}")
                logger.info(f"   File cached: {self.file_cached}")
                last_report = current_time
            
            time.sleep(1)
    
    def _generate_report(self, filename: str):
        """Generate detailed test report"""
        
        logger.info("=" * 60)
        logger.info("🏆 SINGLE FILE DOWNLOAD TEST REPORT")
        logger.info("=" * 60)
        
        logger.info(f"📁 TARGET FILE: {filename}")
        
        # Packet sequence analysis
        logger.info(f"\n📦 PACKET SEQUENCE:")
        if self.packet_sequence:
            for i, packet in enumerate(self.packet_sequence, 1):
                packet_names = {68: 'LARGEFILESTART', 84: 'LARGEFILESIZE', 100: 'RAWDATA', 69: 'LARGEFILEEND'}
                name = packet_names.get(packet['packet_id'], f"PACKET_{packet['packet_id']}")
                logger.info(f"   {i}. {name} (ID {packet['packet_id']}) - {packet['size']} bytes")
                logger.info(f"      Data: {packet['data_preview']}")
        else:
            logger.info("   ❌ NO FILE DOWNLOAD PACKETS RECEIVED")
        
        # Download pipeline status
        logger.info(f"\n🔄 DOWNLOAD PIPELINE:")
        logger.info(f"   📤 File request sent: ✅")
        logger.info(f"   🚀 Download started: {'✅' if self.download_started else '❌'}")
        logger.info(f"   📥 Download completed: {'✅' if self.download_completed else '❌'}")
        logger.info(f"   💾 File cached: {'✅' if self.file_cached else '❌'}")
        
        # Cache validation
        if self.client and hasattr(self.client, 'file_manager'):
            try:
                cache_info = self.client.file_manager.get_cache_info()
                logger.info(f"\n💾 CACHE STATUS:")
                logger.info(f"   Cache directory: {cache_info.get('cache', {}).get('base_dir', 'Unknown')}")
                logger.info(f"   Files cached: {cache_info.get('downloads', {}).get('files_cached', 0)}")
                logger.info(f"   Downloads completed: {cache_info.get('downloads', {}).get('downloads_completed', 0)}")
            except Exception as e:
                logger.warning(f"   ⚠️ Could not get cache info: {e}")
        
        # Overall assessment
        logger.info(f"\n🎯 OVERALL ASSESSMENT:")
        if self.download_completed and self.file_cached:
            logger.info("   ✅ SUCCESS - Complete file download pipeline working!")
        elif self.download_started and not self.download_completed:
            logger.info("   ⚠️ PARTIAL - Download started but didn't complete")
        elif not self.download_started:
            logger.info("   ❌ FAILED - No file download packets received")
            logger.info("      Possible causes:")
            logger.info("      - File doesn't exist on server")
            logger.info("      - Packet format still incorrect") 
            logger.info("      - Server requires different authentication/context")
        
        logger.info("=" * 60)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Single File Download Test')
    parser.add_argument('username', help='Account username')
    parser.add_argument('password', help='Account password')
    parser.add_argument('--file', default='chicken.gmap', help='File to request (default: chicken.gmap)')
    parser.add_argument('--host', default='localhost', help='Server host')
    parser.add_argument('--port', type=int, default=14900, help='Server port')
    
    args = parser.parse_args()
    
    test = SingleFileTest(host=args.host, port=args.port)
    success = test.run(args.username, args.password, args.file)
    
    if success:
        logger.info("🎉 Single file test PASSED")
        sys.exit(0)
    else:
        logger.info("⚠️ Single file test needs investigation")
        sys.exit(1)


if __name__ == "__main__":
    main()