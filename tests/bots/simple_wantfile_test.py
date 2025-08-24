#!/usr/bin/env python3
"""
Simple WantFile Test

Basic test to see if we get ANY response from WantFile requests:
- Request files that exist and don't exist
- Monitor for ANY file-related response packets
- Focus on just getting the server to acknowledge our requests
"""

import sys
import os
import time
import logging

# Add pyreborn to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from pyreborn.core.reborn_client import RebornClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SimpleWantFileTest:
    """Simple test to get any WantFile response"""
    
    def __init__(self, host="localhost", port=14900):
        self.host = host
        self.port = port
        self.client = None
        self.responses_received = []
        
    def run(self, username: str, password: str) -> bool:
        """Run simple WantFile test"""
        
        logger.info("🎯 SIMPLE WANTFILE RESPONSE TEST")
        logger.info("=" * 50)
        
        try:
            # Initialize client
            self.client = RebornClient(host=self.host, port=self.port)
            
            # Monitor ALL packets for any file responses
            self._setup_response_monitoring()
            
            # Connect
            if not self.client.connect():
                logger.error("❌ Connection failed")
                return False
                
            if not self.client.login(username, password):
                logger.error("❌ Login failed")
                return False
                
            logger.info(f"✅ Connected as {username}")
            
            # Wait for login to complete
            time.sleep(3)
            
            logger.info("🧪 Testing file requests for ANY server response...")
            
            # Test 1: Request file that definitely exists
            self._test_file_request("dustynewpics1.png", "Large PNG file that exists")
            
            # Test 2: Request file that doesn't exist  
            self._test_file_request("nonexistent_file.png", "File that doesn't exist")
            
            # Test 3: Request GMAP file
            self._test_file_request("chicken.gmap", "GMAP file that exists")
            
            # Test 4: Request level file
            self._test_file_request("chicken1.nw", "Level file that exists")
            
            # Final wait for any delayed responses
            logger.info("⏳ Final wait for delayed responses...")
            time.sleep(5)
            
            # Generate report
            self._generate_report()
            
            return len(self.responses_received) > 0
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
            return False
            
        finally:
            if self.client:
                self.client.disconnect()
    
    def _setup_response_monitoring(self):
        """Monitor for ANY file-related response packets"""
        
        original_process = self.client.packet_processor.manager_processor.process_packet
        
        def monitor_file_responses(packet_id, data, announced_size=0):
            # Look for ANY possible file response packets
            file_response_ids = {30, 45, 67, 68, 69, 84, 100, 102}
            
            if packet_id in file_response_ids:
                response_info = {
                    'packet_id': packet_id,
                    'size': len(data),
                    'time': time.time(),
                    'data_hex': data[:50].hex() if data else '',
                    'data_text': data[:50].decode('latin-1', errors='ignore') if data else ''
                }
                self.responses_received.append(response_info)
                
                packet_names = {
                    30: 'FILESENDFAILED', 45: 'FILEUPTODATE', 67: 'PARTICLEEFFECT',
                    68: 'LARGEFILESTART', 69: 'LARGEFILEEND', 84: 'LARGEFILESIZE',
                    100: 'RAWDATA', 102: 'FILE'
                }
                name = packet_names.get(packet_id, f'PACKET_{packet_id}')
                
                logger.info(f"🎉 FILE RESPONSE DETECTED: {name} (ID {packet_id}) - {len(data)} bytes")
                logger.info(f"   Data preview: {response_info['data_hex'][:40]}")
                logger.info(f"   Text preview: '{response_info['data_text'][:30]}'")
            
            return original_process(packet_id, data, announced_size)
        
        self.client.packet_processor.manager_processor.process_packet = monitor_file_responses
        logger.info("✅ File response monitoring enabled")
    
    def _test_file_request(self, filename: str, description: str):
        """Test a single file request"""
        
        logger.info(f"📤 Test: {filename} ({description})")
        
        initial_count = len(self.responses_received)
        
        # Send request
        try:
            success = self.client.request_file(filename)
            if success:
                logger.info(f"   ✅ WantFile packet sent")
            else:
                logger.error(f"   ❌ Failed to send WantFile packet")
                return
        except Exception as e:
            logger.error(f"   ❌ Exception: {e}")
            return
        
        # Wait for response
        logger.info("   ⏳ Waiting 5 seconds for response...")
        time.sleep(5)
        
        new_responses = len(self.responses_received) - initial_count
        if new_responses > 0:
            logger.info(f"   🎉 Got {new_responses} file response(s)!")
            for response in self.responses_received[initial_count:]:
                packet_names = {30: 'FILESENDFAILED', 102: 'FILE', 68: 'LARGEFILESTART'}
                name = packet_names.get(response['packet_id'], f"PACKET_{response['packet_id']}")
                logger.info(f"      {name}: {response['size']} bytes")
        else:
            logger.info(f"   ❌ No file responses")
    
    def _generate_report(self):
        """Generate test report"""
        
        logger.info("=" * 60)
        logger.info("🏆 SIMPLE WANTFILE TEST REPORT")
        logger.info("=" * 60)
        
        logger.info(f"📊 RESULTS:")
        logger.info(f"   File response packets: {len(self.responses_received)}")
        
        if self.responses_received:
            logger.info("   🎉 SUCCESS - Server is responding to WantFile requests!")
            
            packet_counts = {}
            for response in self.responses_received:
                pid = response['packet_id']
                packet_counts[pid] = packet_counts.get(pid, 0) + 1
            
            for pid, count in sorted(packet_counts.items()):
                packet_names = {30: 'FILESENDFAILED', 102: 'FILE', 68: 'LARGEFILESTART'}
                name = packet_names.get(pid, f'PACKET_{pid}')
                logger.info(f"      {name} (ID {pid}): {count} responses")
        else:
            logger.info("   ❌ FAILED - No file responses detected")
            logger.info("      This suggests:")
            logger.info("      - WantFile packets not reaching msgPLI_WANTFILE function")
            logger.info("      - Client type not recognized as eligible for file downloads")
            logger.info("      - Packet routing issue in GServer")
            logger.info("      - Authentication/permission issue")
        
        logger.info("=" * 60)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Simple WantFile Test')
    parser.add_argument('username', help='Account username')
    parser.add_argument('password', help='Account password')
    parser.add_argument('--host', default='localhost', help='Server host')
    parser.add_argument('--port', type=int, default=14900, help='Server port')
    
    args = parser.parse_args()
    
    test = SimpleWantFileTest(host=args.host, port=args.port)
    success = test.run(args.username, args.password)
    
    if success:
        logger.info("🎉 WantFile responses detected - file system working!")
        sys.exit(0)
    else:
        logger.info("⚠️ No WantFile responses - needs debugging")
        sys.exit(1)


if __name__ == "__main__":
    main()