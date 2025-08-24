#!/usr/bin/env python3
"""
File Download Test Bot

Comprehensive test for file download functionality including:
- GMAP file downloads
- Level file downloads
- Image file downloads
- Cache validation
- Progress monitoring
- Error handling
"""

import sys
import os
import time
import logging
import argparse
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


class FileDownloadTestBot:
    """Test bot for comprehensive file download testing"""
    
    def __init__(self, host="localhost", port=14900):
        self.host = host
        self.port = port
        self.client = None
        self.file_manager = None
        
        # Test results tracking
        self.test_results = {
            'downloads_attempted': 0,
            'downloads_completed': 0,
            'downloads_failed': 0,
            'gmap_files': [],
            'level_files': [],
            'image_files': [],
            'cache_files': [],
            'errors': []
        }
        
        # Files we want to test downloading
        self.test_files = [
            'chicken.gmap',  # GMAP file
            'chicken1.nw',   # Level file
            'onlinestartlocal.nw',  # Start level
            'images/ball.png',  # Image file (if available)
        ]
    
    def run(self, username: str, password: str, test_duration: int = 60):
        """Run the file download test"""
        logger.info("=" * 60)
        logger.info("FILE DOWNLOAD TEST BOT STARTING")
        logger.info("=" * 60)
        
        try:
            # Create client with caching enabled
            logger.info(f"Connecting to {self.host}:{self.port}")
            self.client = RebornClient(host=self.host, port=self.port)
            
            # Enable file manager if not already present
            self._ensure_file_manager()
            
            # Set up event listeners for file downloads
            self._setup_event_listeners()
            
            # Connect and login
            if not self.client.connect():
                logger.error("Failed to connect to server")
                return False
                
            if not self.client.login(username, password):
                logger.error("Failed to login")
                return False
                
            logger.info(f"✅ Successfully logged in as {username}")
            
            # Wait a moment for initial level loading
            time.sleep(2)
            
            # Start file download tests
            self._run_file_download_tests()
            
            # Monitor downloads and run tests
            self._monitor_downloads(test_duration)
            
            # Generate test report
            self._generate_report()
            
            return True
            
        except Exception as e:
            logger.error(f"Test bot error: {e}", exc_info=True)
            self.test_results['errors'].append(f"Bot error: {e}")
            return False
            
        finally:
            if self.client:
                self.client.disconnect()
                logger.info("Disconnected from server")
    
    def _ensure_file_manager(self):
        """Ensure file manager is available"""
        try:
            # Check if client has file_manager
            if hasattr(self.client, 'file_manager'):
                self.file_manager = self.client.file_manager
                logger.info("✅ File manager found on client")
            else:
                # Try to get it from the container
                from pyreborn.session.file_manager import FileManager
                from pyreborn.session.cache_manager import CacheManager
                from pyreborn.session.events import EventManager
                
                # Create managers if needed
                cache_manager = CacheManager()
                event_manager = EventManager()
                
                self.file_manager = FileManager(
                    client=self.client,
                    event_manager=event_manager,
                    cache_manager=cache_manager
                )
                
                # Add to client
                self.client.file_manager = self.file_manager
                logger.info("✅ Created file manager for client")
                
        except Exception as e:
            logger.error(f"Failed to ensure file manager: {e}")
            self.test_results['errors'].append(f"File manager setup error: {e}")
    
    def _setup_event_listeners(self):
        """Set up event listeners for file download events"""
        if not hasattr(self.client, 'events') or not self.client.events:
            logger.warning("No event manager available for file download monitoring")
            return
            
        try:
            # Listen for file download events
            self.client.events.subscribe(EventType.FILE_DOWNLOADED, self._on_file_downloaded)
            self.client.events.subscribe(EventType.FILE_UP_TO_DATE, self._on_file_up_to_date)
            self.client.events.subscribe(EventType.FILE_DOWNLOAD_FAILED, self._on_file_download_failed)
            self.client.events.subscribe(EventType.FILE_DOWNLOAD_STARTED, self._on_file_download_started)
            
            logger.info("✅ File download event listeners set up")
            
        except Exception as e:
            logger.error(f"Failed to set up event listeners: {e}")
    
    def _on_file_downloaded(self, event_data):
        """Handle file downloaded event"""
        filename = event_data.get('filename', 'unknown')
        size = event_data.get('size', 0)
        
        logger.info(f"📥 FILE DOWNLOADED: {filename} ({size} bytes)")
        self.test_results['downloads_completed'] += 1
        
        # Categorize file type
        if filename.endswith('.gmap'):
            self.test_results['gmap_files'].append(filename)
        elif filename.endswith('.nw'):
            self.test_results['level_files'].append(filename)
        elif any(filename.endswith(ext) for ext in ['.png', '.gif', '.jpg', '.jpeg']):
            self.test_results['image_files'].append(filename)
    
    def _on_file_up_to_date(self, event_data):
        """Handle file up to date event"""
        filename = event_data.get('filename', 'unknown')
        logger.info(f"✅ FILE UP TO DATE: {filename}")
    
    def _on_file_download_failed(self, event_data):
        """Handle file download failed event"""
        filename = event_data.get('filename', 'unknown')
        logger.error(f"❌ FILE DOWNLOAD FAILED: {filename}")
        self.test_results['downloads_failed'] += 1
        self.test_results['errors'].append(f"Download failed: {filename}")
    
    def _on_file_download_started(self, event_data):
        """Handle file download started event"""
        filename = event_data.get('filename', 'unknown')
        logger.info(f"🚀 FILE DOWNLOAD STARTED: {filename}")
        self.test_results['downloads_attempted'] += 1
    
    def _run_file_download_tests(self):
        """Run various file download tests"""
        logger.info("=" * 40)
        logger.info("STARTING FILE DOWNLOAD TESTS")
        logger.info("=" * 40)
        
        # Test 1: Check if any files are currently being downloaded
        self._test_current_downloads()
        
        # Test 2: Try to trigger file downloads by moving around
        self._test_movement_triggered_downloads()
        
        # Test 3: Check cache functionality
        self._test_cache_functionality()
        
        # Test 4: Force file requests (if possible)
        self._test_force_file_requests()
    
    def _test_current_downloads(self):
        """Test if any files are currently being downloaded"""
        logger.info("🔍 Testing current download status...")
        
        if self.file_manager:
            is_downloading = self.file_manager.is_downloading_file()
            progress = self.file_manager.get_download_progress()
            
            logger.info(f"  Currently downloading files: {is_downloading}")
            if progress:
                logger.info(f"  Download progress: {progress}")
            else:
                logger.info("  No active downloads detected")
        else:
            logger.warning("  File manager not available")
    
    def _test_movement_triggered_downloads(self):
        """Test file downloads triggered by movement/warping"""
        logger.info("🚶 Testing movement-triggered downloads...")
        
        try:
            # Get current player position
            player = self.client.get_player()
            if player:
                logger.info(f"  Current player position: ({player.x}, {player.y})")
                logger.info(f"  Current level: {player.current_level}")
            
            # Try some movement to trigger potential downloads
            movements = [(1, 0), (0, 1), (-1, 0), (0, -1)]
            for dx, dy in movements:
                logger.info(f"  Moving by ({dx}, {dy})")
                self.client.move(dx, dy)
                time.sleep(0.5)  # Give time for potential file requests
                
                # Check for new downloads
                if self.file_manager:
                    progress = self.file_manager.get_download_progress()
                    if progress:
                        logger.info(f"    New downloads detected: {list(progress.keys())}")
                
        except Exception as e:
            logger.error(f"Movement test error: {e}")
            self.test_results['errors'].append(f"Movement test error: {e}")
    
    def _test_cache_functionality(self):
        """Test cache functionality"""
        logger.info("💾 Testing cache functionality...")
        
        if self.file_manager:
            try:
                cache_info = self.file_manager.get_cache_info()
                logger.info(f"  Cache info: {cache_info}")
                
                # List cache files
                if 'cache' in cache_info and 'base_dir' in cache_info['cache']:
                    cache_dir = Path(cache_info['cache']['base_dir'])
                    if cache_dir.exists():
                        cache_files = list(cache_dir.rglob('*'))
                        cache_files = [f for f in cache_files if f.is_file()]
                        
                        logger.info(f"  Found {len(cache_files)} cached files:")
                        for cache_file in cache_files[:10]:  # Show first 10
                            size = cache_file.stat().st_size
                            logger.info(f"    {cache_file.name} ({size} bytes)")
                            self.test_results['cache_files'].append(str(cache_file))
                            
                        if len(cache_files) > 10:
                            logger.info(f"    ... and {len(cache_files) - 10} more")
                    else:
                        logger.info("  Cache directory not found")
                        
            except Exception as e:
                logger.error(f"Cache test error: {e}")
                self.test_results['errors'].append(f"Cache test error: {e}")
        else:
            logger.warning("  File manager not available for cache testing")
    
    def _test_force_file_requests(self):
        """Test forcing file requests"""
        logger.info("🔧 Testing forced file requests...")
        
        # Test requesting specific files
        test_files = [
            'chicken.gmap',
            'chicken1.nw', 
            'chicken2.nw',
            'onlinestartlocal.nw'
        ]
        
        for filename in test_files:
            logger.info(f"  Requesting file: {filename}")
            try:
                # Use multiple request methods to find one that works
                success = self.client.request_file_multiple_methods(filename)
                if success:
                    logger.info(f"    ✅ File requests sent for {filename}")
                    # Wait a moment for potential download to start
                    time.sleep(2)
                    
                    # Check if download started
                    if self.file_manager:
                        progress = self.file_manager.get_download_progress()
                        if progress:
                            logger.info(f"    📥 Download detected: {list(progress.keys())}")
                        else:
                            logger.info(f"    ⏳ No immediate download detected")
                else:
                    logger.warning(f"    ❌ Failed to send file requests for {filename}")
                    
            except Exception as e:
                logger.error(f"    ❌ Error requesting {filename}: {e}")
                self.test_results['errors'].append(f"File request error: {filename} - {e}")
            
            # Brief pause between requests
            time.sleep(1.0)
    
    def _monitor_downloads(self, duration: int):
        """Monitor downloads for specified duration"""
        logger.info(f"📊 Monitoring downloads for {duration} seconds...")
        
        start_time = time.time()
        last_report = start_time
        
        while time.time() - start_time < duration:
            current_time = time.time()
            
            # Report progress every 10 seconds
            if current_time - last_report >= 10:
                self._report_progress()
                last_report = current_time
            
            # Check for active downloads
            if self.file_manager:
                progress = self.file_manager.get_download_progress()
                if progress:
                    for filename, info in progress.items():
                        percent = info.get('progress_percent', 0)
                        received = info.get('received_size', 0)
                        total = info.get('expected_size', 0)
                        logger.info(f"  📥 {filename}: {percent:.1f}% ({received}/{total} bytes)")
            
            time.sleep(1)
        
        logger.info("Monitoring period completed")
    
    def _report_progress(self):
        """Report current progress"""
        logger.info("📊 PROGRESS REPORT:")
        logger.info(f"  Downloads attempted: {self.test_results['downloads_attempted']}")
        logger.info(f"  Downloads completed: {self.test_results['downloads_completed']}")
        logger.info(f"  Downloads failed: {self.test_results['downloads_failed']}")
        logger.info(f"  GMAP files: {len(self.test_results['gmap_files'])}")
        logger.info(f"  Level files: {len(self.test_results['level_files'])}")
        logger.info(f"  Image files: {len(self.test_results['image_files'])}")
        logger.info(f"  Cached files: {len(self.test_results['cache_files'])}")
        
        if self.test_results['errors']:
            logger.info(f"  Errors: {len(self.test_results['errors'])}")
    
    def _generate_report(self):
        """Generate final test report"""
        logger.info("=" * 60)
        logger.info("FILE DOWNLOAD TEST REPORT")
        logger.info("=" * 60)
        
        # Summary statistics
        total_attempted = self.test_results['downloads_attempted']
        total_completed = self.test_results['downloads_completed']
        total_failed = self.test_results['downloads_failed']
        
        success_rate = 0.0
        if total_attempted > 0:
            success_rate = (total_completed / total_attempted) * 100
        
        logger.info(f"📊 DOWNLOAD STATISTICS:")
        logger.info(f"  Total downloads attempted: {total_attempted}")
        logger.info(f"  Total downloads completed: {total_completed}")
        logger.info(f"  Total downloads failed: {total_failed}")
        logger.info(f"  Success rate: {success_rate:.1f}%")
        
        # File type breakdown
        logger.info(f"\n📁 FILE TYPE BREAKDOWN:")
        logger.info(f"  GMAP files downloaded: {len(self.test_results['gmap_files'])}")
        if self.test_results['gmap_files']:
            for gmap_file in self.test_results['gmap_files']:
                logger.info(f"    - {gmap_file}")
                
        logger.info(f"  Level files downloaded: {len(self.test_results['level_files'])}")
        if self.test_results['level_files']:
            for level_file in self.test_results['level_files']:
                logger.info(f"    - {level_file}")
                
        logger.info(f"  Image files downloaded: {len(self.test_results['image_files'])}")
        if self.test_results['image_files']:
            for image_file in self.test_results['image_files']:
                logger.info(f"    - {image_file}")
        
        # Cache information
        logger.info(f"\n💾 CACHE INFORMATION:")
        logger.info(f"  Total cached files found: {len(self.test_results['cache_files'])}")
        
        # File manager statistics
        if self.file_manager:
            try:
                stats = self.file_manager.get_statistics()
                logger.info(f"\n📈 FILE MANAGER STATISTICS:")
                for key, value in stats.items():
                    if key != 'cache_info':  # Skip nested dict
                        logger.info(f"  {key}: {value}")
            except Exception as e:
                logger.warning(f"Could not get file manager statistics: {e}")
        
        # Errors
        if self.test_results['errors']:
            logger.info(f"\n❌ ERRORS ENCOUNTERED:")
            for i, error in enumerate(self.test_results['errors'], 1):
                logger.info(f"  {i}. {error}")
        
        # Overall assessment
        logger.info(f"\n🏆 OVERALL ASSESSMENT:")
        if total_attempted == 0:
            logger.info("  ⚠️  No file downloads were attempted")
            logger.info("     This could indicate:")
            logger.info("     - Server is not sending file download packets")
            logger.info("     - File manager integration issue")
            logger.info("     - Test bot needs to trigger more file requests")
        elif success_rate >= 90:
            logger.info("  ✅ EXCELLENT - File download system working well")
        elif success_rate >= 70:
            logger.info("  ✅ GOOD - File download system mostly working")
        elif success_rate >= 50:
            logger.info("  ⚠️  NEEDS IMPROVEMENT - Some file download issues")
        else:
            logger.info("  ❌ POOR - Significant file download problems")
        
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='File Download Test Bot')
    parser.add_argument('username', help='Account username')
    parser.add_argument('password', help='Account password')
    parser.add_argument('--host', default='localhost', help='Server host (default: localhost)')
    parser.add_argument('--port', type=int, default=14900, help='Server port (default: 14900)')
    parser.add_argument('--duration', type=int, default=60, help='Test duration in seconds (default: 60)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create and run test bot
    bot = FileDownloadTestBot(host=args.host, port=args.port)
    success = bot.run(args.username, args.password, args.duration)
    
    if success:
        logger.info("✅ Test completed successfully")
        sys.exit(0)
    else:
        logger.error("❌ Test failed")
        sys.exit(1)


if __name__ == "__main__":
    main()