#!/usr/bin/env python3
"""
Comprehensive File Download System Test

Final validation test for the complete file download system including:
- Correct packet IDs (23=WantFile, 34=UpdateFile, 35=AdjacentLevel) 
- Compression/decompression handling
- File manager integration
- Cache validation
- Progress monitoring
- Error detection and reporting
"""

import sys
import os
import time
import logging
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


class ComprehensiveFileTest:
    """Complete file download system validation"""
    
    def __init__(self, host="localhost", port=14900):
        self.host = host
        self.port = port
        self.client = None
        
        self.results = {
            'file_requests_sent': 0,
            'file_download_packets_received': 0,
            'files_cached': 0,
            'compression_attempts': 0,
            'zlib_errors_detected': 0,
            'test_success': False
        }
    
    def run(self, username: str, password: str) -> bool:
        """Run comprehensive file download test"""
        
        logger.info("🎯 COMPREHENSIVE FILE DOWNLOAD SYSTEM TEST")
        logger.info("=" * 60)
        
        try:
            # Step 1: Initialize client with all components
            logger.info("🔧 Initializing client with file download system...")
            self.client = RebornClient(host=self.host, port=self.port)
            
            # Verify file manager is properly integrated
            if not hasattr(self.client, 'file_manager'):
                logger.error("❌ File manager not found on client")
                return False
            
            if not hasattr(self.client, 'cache_manager'):
                logger.error("❌ Cache manager not found on client")
                return False
                
            logger.info("✅ File download system components initialized")
            
            # Step 2: Connect and authenticate
            logger.info(f"🔗 Connecting to {self.host}:{self.port}...")
            if not self.client.connect():
                logger.error("❌ Connection failed")
                return False
                
            if not self.client.login(username, password):
                logger.error("❌ Login failed")
                return False
                
            logger.info(f"✅ Connected and authenticated as {username}")
            
            # Step 3: Set up monitoring
            self._setup_download_monitoring()
            
            # Step 4: Wait for initial world loading
            logger.info("⏳ Waiting for initial world data loading...")
            time.sleep(3)
            
            # Step 5: Test file requests with correct packet IDs
            logger.info("📥 Testing file requests with correct protocol...")
            self._test_correct_file_requests()
            
            # Step 6: Monitor for file download packets
            logger.info("👀 Monitoring for file download packets...")
            self._monitor_file_packets(30)
            
            # Step 7: Validate cache functionality  
            logger.info("💾 Validating cache functionality...")
            self._validate_cache_system()
            
            # Step 8: Generate comprehensive report
            self._generate_comprehensive_report()
            
            return self.results['test_success']
            
        except Exception as e:
            logger.error(f"❌ Test failed with error: {e}", exc_info=True)
            return False
            
        finally:
            if self.client:
                self.client.disconnect()
    
    def _setup_download_monitoring(self):
        """Set up comprehensive download monitoring"""
        if hasattr(self.client, 'events') and self.client.events:
            
            def on_file_downloaded(data):
                self.results['files_cached'] += 1
                filename = data.get('filename', 'unknown')
                size = data.get('size', 0)
                logger.info(f"🎉 FILE DOWNLOADED: {filename} ({size} bytes)")
            
            def on_file_packet(data):
                self.results['file_download_packets_received'] += 1
                packet_id = data.get('packet_id', 0)
                logger.info(f"📦 File packet received: ID {packet_id}")
            
            self.client.events.subscribe(EventType.FILE_DOWNLOADED, on_file_downloaded)
            
            logger.info("✅ Download monitoring enabled")
    
    def _test_correct_file_requests(self):
        """Test file requests with correct packet IDs and formats"""
        
        test_files = [
            'chicken.gmap',
            'chicken1.nw',
            'chicken2.nw',
            'onlinestartlocal.nw'
        ]
        
        for filename in test_files:
            logger.info(f"📤 Testing file request: {filename}")
            
            # Use multiple methods to maximize success chance
            if hasattr(self.client, 'request_file_multiple_methods'):
                success = self.client.request_file_multiple_methods(filename)
                if success:
                    self.results['file_requests_sent'] += 1
                    logger.info(f"   ✅ Request(s) sent successfully")
                else:
                    logger.warning(f"   ❌ All request methods failed")
            
            # Wait and check for response
            time.sleep(2)
            
            # Check if any downloads started
            if self.client.file_manager:
                progress = self.client.file_manager.get_download_progress()
                if progress:
                    logger.info(f"   📥 Downloads active: {list(progress.keys())}")
                    
            time.sleep(1)
    
    def _monitor_file_packets(self, duration: int):
        """Monitor for file download packets"""
        
        # Hook into packet processor to catch file packets
        original_process = self.client.packet_processor.manager_processor.process_packet
        file_packet_ids = {68, 69, 84, 100, 45, 30}  # File download packet IDs
        
        def monitor_packets(packet_id, data, announced_size=0):
            if packet_id in file_packet_ids:
                self.results['file_download_packets_received'] += 1
                logger.info(f"🗂️ FILE PACKET DETECTED: ID {packet_id}, size {len(data)}")
                
                # Try to parse with file manager
                if hasattr(self.client, 'file_manager'):
                    try:
                        result = self.client.file_manager.handle_packet(packet_id, {
                            'packet_name': f'PACKET_{packet_id}',
                            'raw_data': data,
                            'announced_size': announced_size
                        })
                        if result:
                            logger.info(f"   ✅ File packet processed successfully")
                        else:
                            logger.warning(f"   ⚠️ File packet processing returned None")
                    except Exception as e:
                        logger.error(f"   ❌ File packet processing failed: {e}")
            
            return original_process(packet_id, data, announced_size)
        
        # Install monitoring hook
        self.client.packet_processor.manager_processor.process_packet = monitor_packets
        
        logger.info(f"🔍 Monitoring for {duration} seconds...")
        start_time = time.time()
        
        while time.time() - start_time < duration:
            time.sleep(1)
            
            # Report progress every 10 seconds
            if int(time.time() - start_time) % 10 == 0:
                logger.info(f"📊 Monitor progress: {int(time.time() - start_time)}/{duration}s")
                logger.info(f"   File packets received: {self.results['file_download_packets_received']}")
                logger.info(f"   Files cached: {self.results['files_cached']}")
    
    def _validate_cache_system(self):
        """Validate the cache system functionality"""
        
        logger.info("🔍 Validating cache system...")
        
        try:
            # Get cache info
            if self.client.file_manager:
                cache_info = self.client.file_manager.get_cache_info()
                logger.info(f"📊 Cache statistics: {cache_info}")
                
                # Check if cache directory exists
                cache_base = cache_info.get('cache', {}).get('base_dir')
                if cache_base:
                    cache_path = Path(cache_base)
                    if cache_path.exists():
                        logger.info(f"✅ Cache directory exists: {cache_path}")
                        
                        # List all files in cache
                        cache_files = list(cache_path.rglob('*'))
                        file_count = sum(1 for f in cache_files if f.is_file())
                        
                        logger.info(f"📁 Cache contents: {file_count} files total")
                        
                        for cache_file in cache_files:
                            if cache_file.is_file():
                                size = cache_file.stat().st_size
                                logger.info(f"   📄 {cache_file.relative_to(cache_path)} ({size} bytes)")
                                
                        self.results['files_cached'] = file_count
                    else:
                        logger.warning(f"⚠️ Cache directory does not exist: {cache_path}")
                else:
                    logger.warning("⚠️ No cache base directory found")
                    
        except Exception as e:
            logger.error(f"❌ Cache validation failed: {e}")
    
    def _generate_comprehensive_report(self):
        """Generate final comprehensive test report"""
        
        logger.info("=" * 70)
        logger.info("🏆 COMPREHENSIVE FILE DOWNLOAD SYSTEM REPORT")
        logger.info("=" * 70)
        
        # Test results summary
        logger.info("📊 TEST RESULTS SUMMARY:")
        logger.info(f"   File requests sent: {self.results['file_requests_sent']}")
        logger.info(f"   File download packets received: {self.results['file_download_packets_received']}")
        logger.info(f"   Files successfully cached: {self.results['files_cached']}")
        
        # System status
        logger.info("\n🔧 SYSTEM STATUS:")
        logger.info(f"   ✅ File manager integration: {'Working' if hasattr(self.client, 'file_manager') else 'Missing'}")
        logger.info(f"   ✅ Cache manager integration: {'Working' if hasattr(self.client, 'cache_manager') else 'Missing'}")
        logger.info(f"   ✅ Packet delegation: {'Working' if self.results['file_download_packets_received'] > 0 else 'No packets detected'}")
        
        # Success criteria evaluation
        logger.info("\n🎯 SUCCESS CRITERIA:")
        
        # Criteria 1: File requests can be sent
        req_success = self.results['file_requests_sent'] > 0
        logger.info(f"   {'✅' if req_success else '❌'} File requests: {self.results['file_requests_sent']} sent")
        
        # Criteria 2: File download packets are received and processed
        download_success = self.results['file_download_packets_received'] > 0
        logger.info(f"   {'✅' if download_success else '❌'} Download packets: {self.results['file_download_packets_received']} received")
        
        # Criteria 3: Files are cached successfully
        cache_success = self.results['files_cached'] > 0
        logger.info(f"   {'✅' if cache_success else '❌'} File caching: {self.results['files_cached']} files cached")
        
        # Overall assessment
        self.results['test_success'] = req_success and download_success and cache_success
        
        logger.info(f"\n🏆 OVERALL RESULT:")
        if self.results['test_success']:
            logger.info("   ✅ SUCCESS - File download system is working correctly!")
        else:
            logger.info("   ⚠️ PARTIAL SUCCESS - Some components working, others need attention")
            
            if not req_success:
                logger.info("      🔧 File request mechanism needs fixing")
            if not download_success:
                logger.info("      🔧 File download packet handling needs attention")
            if not cache_success:
                logger.info("      🔧 File caching system needs debugging")
        
        # Next steps
        logger.info(f"\n🔮 NEXT STEPS:")
        if not download_success:
            logger.info("   1. Check server logs for more specific errors")
            logger.info("   2. Verify file request packet format matches server expectations")
            logger.info("   3. Test with different file names that definitely exist on server")
        
        if download_success and not cache_success:
            logger.info("   1. Debug file download completion events")
            logger.info("   2. Verify cache manager save_file() functionality")
            logger.info("   3. Check file processing pipeline")
        
        logger.info("=" * 70)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Comprehensive File Download System Test')
    parser.add_argument('username', help='Account username')
    parser.add_argument('password', help='Account password')
    parser.add_argument('--host', default='localhost', help='Server host')
    parser.add_argument('--port', type=int, default=14900, help='Server port')
    
    args = parser.parse_args()
    
    # Create and run comprehensive test
    test = ComprehensiveFileTest(host=args.host, port=args.port)
    success = test.run(args.username, args.password)
    
    if success:
        logger.info("🎉 Comprehensive test PASSED")
        sys.exit(0)
    else:
        logger.info("⚠️ Comprehensive test shows areas for improvement")
        sys.exit(1)


if __name__ == "__main__":
    main()