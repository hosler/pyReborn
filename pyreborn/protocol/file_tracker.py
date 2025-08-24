"""
File Request Tracker - Debug file request/response flow
"""

import time
import logging
from typing import Dict, List, Set, Optional, Tuple
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class FileRequestTracker:
    """Track all file requests and responses for debugging"""
    
    def __init__(self):
        # Track requests
        self.requests: Dict[str, List[float]] = defaultdict(list)  # filename -> [request_times]
        self.received: Dict[str, Tuple[float, int]] = {}  # filename -> (receive_time, size)
        self.failed: Dict[str, List[float]] = defaultdict(list)  # filename -> [fail_times]
        self.pending: Set[str] = set()  # Currently waiting for
        
        # Statistics
        self.total_requested = 0
        self.total_received = 0
        self.total_failed = 0
        self.start_time = time.time()
        
        # Rate tracking
        self.request_times: List[float] = []  # All request timestamps
        self.receive_times: List[float] = []  # All receive timestamps
        
    def on_file_requested(self, filename: str):
        """Called when a file is requested"""
        current_time = time.time()
        self.requests[filename].append(current_time)
        self.pending.add(filename)
        self.total_requested += 1
        self.request_times.append(current_time)
        
        elapsed = current_time - self.start_time
        logger.info(f"[FILE_TRACKER] [{elapsed:.1f}s] REQUESTED: '{filename}' (request #{len(self.requests[filename])}, total: {self.total_requested})")
        
        # Check for duplicate requests
        if len(self.requests[filename]) > 1:
            logger.warning(f"[FILE_TRACKER] DUPLICATE REQUEST: '{filename}' requested {len(self.requests[filename])} times!")
            
    def on_file_received(self, filename: str, size: int):
        """Called when a file is received"""
        current_time = time.time()
        self.received[filename] = (current_time, size)
        self.pending.discard(filename)
        self.total_received += 1
        self.receive_times.append(current_time)
        
        elapsed = current_time - self.start_time
        
        # Calculate response time
        if filename in self.requests and self.requests[filename]:
            request_time = self.requests[filename][-1]  # Most recent request
            response_time = current_time - request_time
            logger.info(f"[FILE_TRACKER] [{elapsed:.1f}s] RECEIVED: '{filename}' ({size} bytes, response time: {response_time:.2f}s, total: {self.total_received})")
        else:
            logger.warning(f"[FILE_TRACKER] [{elapsed:.1f}s] RECEIVED UNREQUESTED: '{filename}' ({size} bytes)")
            
    def on_file_failed(self, filename: str):
        """Called when a file request fails"""
        current_time = time.time()
        self.failed[filename].append(current_time)
        self.pending.discard(filename)
        self.total_failed += 1
        
        elapsed = current_time - self.start_time
        logger.error(f"[FILE_TRACKER] [{elapsed:.1f}s] FAILED: '{filename}' (fail #{len(self.failed[filename])}, total: {self.total_failed})")
        
    def get_pending_files(self) -> List[Tuple[str, float]]:
        """Get list of pending files with wait times"""
        current_time = time.time()
        pending_list = []
        
        for filename in self.pending:
            if filename in self.requests and self.requests[filename]:
                request_time = self.requests[filename][-1]
                wait_time = current_time - request_time
                pending_list.append((filename, wait_time))
                
        return sorted(pending_list, key=lambda x: x[1], reverse=True)
    
    def get_request_rate(self, window_seconds: float = 10.0) -> float:
        """Get request rate over time window"""
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        recent_requests = [t for t in self.request_times if t > cutoff_time]
        return len(recent_requests) / window_seconds if window_seconds > 0 else 0
        
    def get_receive_rate(self, window_seconds: float = 10.0) -> float:
        """Get receive rate over time window"""
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        recent_receives = [t for t in self.receive_times if t > cutoff_time]
        return len(recent_receives) / window_seconds if window_seconds > 0 else 0
        
    def print_summary(self):
        """Print detailed summary of file requests"""
        current_time = time.time()
        elapsed = current_time - self.start_time
        
        print("\n" + "="*80)
        print(f"FILE REQUEST TRACKER SUMMARY (Runtime: {elapsed:.1f}s)")
        print("="*80)
        
        print(f"\nTOTALS:")
        print(f"  Requested: {self.total_requested}")
        print(f"  Received:  {self.total_received}")
        print(f"  Failed:    {self.total_failed}")
        print(f"  Pending:   {len(self.pending)}")
        
        print(f"\nRATES:")
        print(f"  Request rate (10s): {self.get_request_rate(10):.2f} files/sec")
        print(f"  Request rate (60s): {self.get_request_rate(60):.2f} files/sec")
        print(f"  Receive rate (10s): {self.get_receive_rate(10):.2f} files/sec")
        print(f"  Receive rate (60s): {self.get_receive_rate(60):.2f} files/sec")
        
        # Pending files
        if self.pending:
            print(f"\nPENDING FILES ({len(self.pending)}):")
            for filename, wait_time in self.get_pending_files()[:10]:  # Top 10
                print(f"  {filename:<30} waiting {wait_time:6.1f}s")
            if len(self.pending) > 10:
                print(f"  ... and {len(self.pending) - 10} more")
                
        # Failed files
        if self.failed:
            print(f"\nFAILED FILES ({len(self.failed)}):")
            for filename, fail_times in list(self.failed.items())[:10]:
                print(f"  {filename:<30} failed {len(fail_times)} times")
                
        # Duplicate requests
        duplicates = [(f, len(times)) for f, times in self.requests.items() if len(times) > 1]
        if duplicates:
            print(f"\nDUPLICATE REQUESTS ({len(duplicates)} files):")
            for filename, count in sorted(duplicates, key=lambda x: x[1], reverse=True)[:10]:
                print(f"  {filename:<30} requested {count} times")
                
        # Unrequested receives
        unrequested = [f for f in self.received if f not in self.requests]
        if unrequested:
            print(f"\nUNREQUESTED RECEIVES ({len(unrequested)} files):")
            for filename in unrequested[:10]:
                print(f"  {filename}")
                
        print("="*80)
        
    def log_status(self):
        """Log current status"""
        elapsed = time.time() - self.start_time
        pending_count = len(self.pending)
        
        if pending_count > 0:
            oldest_pending = self.get_pending_files()[0] if self.pending else None
            if oldest_pending:
                logger.info(f"[FILE_TRACKER] [{elapsed:.1f}s] STATUS: {pending_count} pending, oldest: '{oldest_pending[0]}' ({oldest_pending[1]:.1f}s)")
        
        # Warn if too many pending
        if pending_count > 10:
            logger.warning(f"[FILE_TRACKER] HIGH PENDING COUNT: {pending_count} files waiting!")
            
        # Log rates
        req_rate = self.get_request_rate(10)
        rec_rate = self.get_receive_rate(10)
        if req_rate > 5:
            logger.warning(f"[FILE_TRACKER] HIGH REQUEST RATE: {req_rate:.1f} files/sec")
            
    def save_log(self, filename: str = "file_requests.log"):
        """Save detailed log to file"""
        with open(filename, 'w') as f:
            f.write(f"File Request Log - {datetime.now()}\n")
            f.write(f"Runtime: {time.time() - self.start_time:.1f}s\n")
            f.write("="*80 + "\n\n")
            
            # All requests in chronological order
            f.write("CHRONOLOGICAL REQUEST LOG:\n")
            f.write("-"*80 + "\n")
            
            events = []
            
            # Add all events
            for filename, times in self.requests.items():
                for t in times:
                    events.append((t, "REQUEST", filename, ""))
                    
            for filename, (t, size) in self.received.items():
                events.append((t, "RECEIVE", filename, f"{size} bytes"))
                
            for filename, times in self.failed.items():
                for t in times:
                    events.append((t, "FAILED", filename, ""))
                    
            # Sort by time
            events.sort(key=lambda x: x[0])
            
            # Write events
            for timestamp, event_type, filename, extra in events:
                elapsed = timestamp - self.start_time
                f.write(f"[{elapsed:8.2f}s] {event_type:8} {filename:<40} {extra}\n")
                
            f.write("\n" + "="*80 + "\n")
            f.write("END OF LOG\n")