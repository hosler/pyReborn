#!/usr/bin/env python3
"""
Find Missing Files Test

Comprehensive test to find where files are actually being received by:
1. Monitoring ALL packets before/after file requests
2. Checking cache directories for new files
3. Looking for file data in unexpected packets
4. Examining raw packet data for file signatures
"""

import sys
import os
import time
import logging
from pathlib import Path
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


class FindMissingFiles:
    """Find where files are actually being received"""
    
    def __init__(self, host="localhost", port=14900):
        self.host = host
        self.port = port
        self.client = None
        
        # Track everything
        self.packets_before_request = []
        self.packets_after_request = []
        self.cache_files_before = []
        self.cache_files_after = []
        self.inspection_files_before = []
        self.inspection_files_after = []
        
    def run(self, username: str, password: str) -> bool:
        """Find where files are actually being received"""
        
        logger.info("🔍 FIND MISSING FILES TEST")
        logger.info("=" * 50)
        
        try:
            # Initialize client
            self.client = RebornClient(host=self.host, port=self.port)
            
            # Set up comprehensive monitoring
            self._setup_complete_monitoring()
            
            # Connect
            if not self.client.connect():
                logger.error("❌ Connection failed")
                return False
                
            if not self.client.login(username, password):
                logger.error("❌ Login failed")
                return False
                
            logger.info(f"✅ Connected as {username}")
            
            # Wait for initial loading
            time.sleep(3)
            
            # Snapshot BEFORE file request
            logger.info("📸 Taking 'before' snapshot...")
            self._take_before_snapshot()
            
            # Request file
            filename = "dustynewpics1.png"
            logger.info(f"📤 Requesting file: {filename}")
            success = self.client.request_file(filename)
            
            if not success:
                logger.error("❌ File request failed")
                return False
                
            # Wait and monitor
            logger.info("⏳ Waiting for file activity...")
            time.sleep(10)
            
            # Take AFTER snapshot
            logger.info("📸 Taking 'after' snapshot...")
            self._take_after_snapshot()
            
            # Compare and analyze
            self._analyze_differences()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
            return False
            
        finally:
            if self.client:
                self.client.disconnect()
    
    def _setup_complete_monitoring(self):
        """Monitor absolutely everything"""
        
        original_process = self.client.packet_processor.manager_processor.process_packet
        
        def capture_everything(packet_id, data, announced_size=0):
            packet_info = {
                'id': packet_id,
                'size': len(data),
                'time': time.time(),
                'data_hex': data.hex() if data else '',
                'data_text': data.decode('latin-1', errors='ignore') if data else '',
                'has_png': b'.png' in data,
                'has_file_ext': any(ext in data for ext in [b'.png', b'.jpg', b'.gif', b'.nw', b'.gmap']),
            }
            
            # Store for later analysis
            if not hasattr(self, 'file_request_sent'):
                self.packets_before_request.append(packet_info)
            else:
                self.packets_after_request.append(packet_info)
            
            # Log interesting packets immediately
            if packet_info['has_file_ext']:
                logger.info(f"🗂️ PACKET WITH FILE EXTENSION: ID {packet_id}, size {len(data)}")
                logger.info(f"   Text: {packet_info['data_text'][:100]}")
            
            return original_process(packet_id, data, announced_size)
        
        self.client.packet_processor.manager_processor.process_packet = capture_everything
        logger.info("✅ Complete packet monitoring enabled")
    
    def _take_before_snapshot(self):
        """Take snapshot of files before request"""
        
        # Check cache directory
        cache_dir = Path(self.client.cache_manager.base_cache_dir)
        if cache_dir.exists():
            self.cache_files_before = list(cache_dir.rglob('*'))
            self.cache_files_before = [f for f in self.cache_files_before if f.is_file()]
        
        # Check inspection directory
        inspection_dir = Path("downloads/inspection")
        if inspection_dir.exists():
            self.inspection_files_before = list(inspection_dir.rglob('*'))
            self.inspection_files_before = [f for f in self.inspection_files_before if f.is_file()]
        
        # Mark that we're about to send file request
        self.file_request_sent = True
        
        logger.info(f"📊 Before snapshot:")
        logger.info(f"   Cache files: {len(self.cache_files_before)}")
        logger.info(f"   Inspection files: {len(self.inspection_files_before)}")
        logger.info(f"   Packets captured: {len(self.packets_before_request)}")
    
    def _take_after_snapshot(self):
        """Take snapshot of files after request"""
        
        # Check cache directory
        cache_dir = Path(self.client.cache_manager.base_cache_dir)
        if cache_dir.exists():
            self.cache_files_after = list(cache_dir.rglob('*'))
            self.cache_files_after = [f for f in self.cache_files_after if f.is_file()]
        
        # Check inspection directory
        inspection_dir = Path("downloads/inspection")
        if inspection_dir.exists():
            self.inspection_files_after = list(inspection_dir.rglob('*'))
            self.inspection_files_after = [f for f in self.inspection_files_after if f.is_file()]
        
        logger.info(f"📊 After snapshot:")
        logger.info(f"   Cache files: {len(self.cache_files_after)}")
        logger.info(f"   Inspection files: {len(self.inspection_files_after)}")
        logger.info(f"   Packets captured: {len(self.packets_after_request)}")
    
    def _analyze_differences(self):
        """Analyze what changed after file request"""
        
        logger.info("=" * 60)
        logger.info("🔍 ANALYSIS: WHAT CHANGED AFTER FILE REQUEST")
        logger.info("=" * 60)
        
        # File changes
        logger.info("📁 FILE CHANGES:")
        
        new_cache_files = set(self.cache_files_after) - set(self.cache_files_before)
        new_inspection_files = set(self.inspection_files_after) - set(self.inspection_files_before)
        
        if new_cache_files:
            logger.info(f"   🎉 NEW CACHE FILES: {len(new_cache_files)}")
            for file_path in new_cache_files:
                size = file_path.stat().st_size
                logger.info(f"      📄 {file_path.name} ({size} bytes)")
        else:
            logger.info("   ❌ No new cache files")
        
        if new_inspection_files:
            logger.info(f"   🎉 NEW INSPECTION FILES: {len(new_inspection_files)}")
            for file_path in new_inspection_files:
                size = file_path.stat().st_size
                logger.info(f"      📄 {file_path.name} ({size} bytes)")
        else:
            logger.info("   ❌ No new inspection files")
        
        # Packet analysis
        logger.info(f"\n📦 PACKET ANALYSIS:")
        logger.info(f"   Packets before request: {len(self.packets_before_request)}")
        logger.info(f"   Packets after request: {len(self.packets_after_request)}")
        
        if self.packets_after_request:
            logger.info("   📊 Packets received after file request:")
            
            # Group by packet ID
            packet_counts = defaultdict(int)
            file_related_packets = []
            
            for packet in self.packets_after_request:
                packet_counts[packet['id']] += 1
                
                # Look for file-related content
                if (packet['has_file_ext'] or 
                    packet['size'] > 1000 or  # Large packets might be files
                    packet['id'] in [68, 69, 84, 100, 102, 30, 45]):  # Known file packet IDs
                    file_related_packets.append(packet)
            
            # Show packet counts
            for pid, count in sorted(packet_counts.items()):
                logger.info(f"      Packet {pid:3d}: {count:4d} times")
            
            # Show potentially file-related packets
            if file_related_packets:
                logger.info("   🗂️ POTENTIALLY FILE-RELATED PACKETS:")
                for packet in file_related_packets:
                    logger.info(f"      ID {packet['id']}: {packet['size']} bytes")
                    logger.info(f"         Text: '{packet['data_text'][:50]}'")
                    if packet['has_png']:
                        logger.info(f"         🎉 CONTAINS .PNG REFERENCE!")
        
        # Raw data analysis
        logger.info(f"\n🔍 RAW DATA ANALYSIS:")
        
        # Look for file signatures in packet data
        png_packets = [p for p in self.packets_after_request if b'.png' in p['data_hex'].encode()]
        large_packets = [p for p in self.packets_after_request if p['size'] > 10000]
        
        if png_packets:
            logger.info(f"   🖼️ PACKETS WITH .PNG: {len(png_packets)}")
            for packet in png_packets:
                logger.info(f"      ID {packet['id']}: {packet['data_text'][:100]}")
        
        if large_packets:
            logger.info(f"   📦 LARGE PACKETS (>10KB): {len(large_packets)}")
            for packet in large_packets:
                logger.info(f"      ID {packet['id']}: {packet['size']} bytes")
        
        # Final assessment
        logger.info(f"\n🎯 FINAL ASSESSMENT:")
        
        has_new_files = len(new_cache_files) > 0 or len(new_inspection_files) > 0
        has_file_packets = len(file_related_packets) > 0 if 'file_related_packets' in locals() else False
        has_activity = len(self.packets_after_request) > 0
        
        if has_new_files:
            logger.info("   ✅ SUCCESS: Files were downloaded and cached!")
        elif has_file_packets:
            logger.info("   ⚠️ PARTIAL: File packets detected but not cached properly")
        elif has_activity:
            logger.info("   🔍 HIDDEN: Server responded but files might be in unexpected packets")
        else:
            logger.info("   ❌ FAILED: No file activity detected")
        
        logger.info("=" * 60)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Find Missing Files Test')
    parser.add_argument('username', help='Account username')
    parser.add_argument('password', help='Account password')
    parser.add_argument('--host', default='localhost', help='Server host')
    parser.add_argument('--port', type=int, default=14900, help='Server port')
    
    args = parser.parse_args()
    
    test = FindMissingFiles(host=args.host, port=args.port)
    success = test.run(args.username, args.password)
    
    if success:
        logger.info("🎉 Test completed successfully")
        sys.exit(0)
    else:
        logger.info("⚠️ Test completed with issues")
        sys.exit(1)


if __name__ == "__main__":
    main()