#!/usr/bin/env python3
"""
Packet Metrics and Statistics System

This module provides comprehensive metrics tracking for packet processing,
including performance metrics, error rates, and packet flow analysis.
"""

import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics we track"""
    PACKET_COUNT = auto()
    PACKET_SIZE = auto()
    PROCESSING_TIME = auto()
    ERROR_RATE = auto()
    THROUGHPUT = auto()
    LATENCY = auto()


@dataclass
class PacketMetric:
    """Individual packet metric entry"""
    packet_id: int
    packet_name: str
    timestamp: float
    size_bytes: int
    processing_time_ms: float
    success: bool
    direction: str  # 'incoming' or 'outgoing'
    error_message: Optional[str] = None
    
    
@dataclass
class PacketStatistics:
    """Aggregated statistics for a packet type"""
    packet_id: int
    packet_name: str
    total_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_bytes: int = 0
    total_processing_time_ms: float = 0
    min_size_bytes: int = float('inf')
    max_size_bytes: int = 0
    min_processing_time_ms: float = float('inf')
    max_processing_time_ms: float = 0
    avg_size_bytes: float = 0
    avg_processing_time_ms: float = 0
    error_rate: float = 0
    throughput_bps: float = 0  # Bytes per second
    last_seen: Optional[float] = None
    
    def update_averages(self):
        """Update calculated averages"""
        if self.total_count > 0:
            self.avg_size_bytes = self.total_bytes / self.total_count
            self.avg_processing_time_ms = self.total_processing_time_ms / self.total_count
            self.error_rate = (self.error_count / self.total_count) * 100
    

class PacketMetricsCollector:
    """
    Collects and analyzes packet metrics for the pyReborn client.
    
    This provides insights into:
    - Packet frequencies and sizes
    - Processing performance
    - Error rates and patterns
    - Network throughput
    - Packet flow patterns
    """
    
    def __init__(self, window_size_seconds: int = 60):
        """
        Initialize the metrics collector.
        
        Args:
            window_size_seconds: Size of the sliding window for rate calculations
        """
        self.window_size = window_size_seconds
        self.start_time = time.time()
        
        # Metrics storage
        self.packet_stats: Dict[int, PacketStatistics] = {}
        self.recent_metrics: deque = deque(maxlen=10000)  # Last 10k packets
        self.time_windows: Dict[int, deque] = defaultdict(lambda: deque())
        
        # Performance tracking
        self.processing_times: Dict[int, List[float]] = defaultdict(list)
        self.error_patterns: Dict[str, int] = defaultdict(int)
        
        # Flow analysis
        self.packet_sequences: deque = deque(maxlen=1000)
        self.packet_pairs: Dict[Tuple[int, int], int] = defaultdict(int)
        
        # Real-time metrics
        self.current_throughput = 0
        self.current_packet_rate = 0
        self.last_calculation_time = time.time()
        
    def record_packet(self, packet_id: int, packet_name: str, size_bytes: int,
                     processing_time_ms: float, success: bool, direction: str,
                     error_message: Optional[str] = None):
        """
        Record metrics for a processed packet.
        
        Args:
            packet_id: Packet type ID
            packet_name: Human-readable packet name
            size_bytes: Size of the packet in bytes
            processing_time_ms: Time taken to process in milliseconds
            success: Whether processing was successful
            direction: 'incoming' or 'outgoing'
            error_message: Error message if processing failed
        """
        timestamp = time.time()
        
        # Create metric entry
        metric = PacketMetric(
            packet_id=packet_id,
            packet_name=packet_name,
            timestamp=timestamp,
            size_bytes=size_bytes,
            processing_time_ms=processing_time_ms,
            success=success,
            direction=direction,
            error_message=error_message
        )
        
        # Add to recent metrics
        self.recent_metrics.append(metric)
        
        # Update statistics
        if packet_id not in self.packet_stats:
            self.packet_stats[packet_id] = PacketStatistics(
                packet_id=packet_id,
                packet_name=packet_name
            )
        
        stats = self.packet_stats[packet_id]
        stats.total_count += 1
        stats.total_bytes += size_bytes
        stats.total_processing_time_ms += processing_time_ms
        stats.last_seen = timestamp
        
        if success:
            stats.success_count += 1
        else:
            stats.error_count += 1
            if error_message:
                self.error_patterns[error_message] += 1
        
        # Update min/max
        stats.min_size_bytes = min(stats.min_size_bytes, size_bytes)
        stats.max_size_bytes = max(stats.max_size_bytes, size_bytes)
        stats.min_processing_time_ms = min(stats.min_processing_time_ms, processing_time_ms)
        stats.max_processing_time_ms = max(stats.max_processing_time_ms, processing_time_ms)
        
        # Update averages
        stats.update_averages()
        
        # Add to time window for rate calculations
        self.time_windows[packet_id].append((timestamp, size_bytes))
        self._cleanup_time_windows(packet_id)
        
        # Track packet sequences for flow analysis
        self.packet_sequences.append(packet_id)
        if len(self.packet_sequences) >= 2:
            prev_id = self.packet_sequences[-2]
            self.packet_pairs[(prev_id, packet_id)] += 1
        
        # Update real-time metrics periodically
        if timestamp - self.last_calculation_time > 1.0:  # Every second
            self._update_realtime_metrics()
            
    def _cleanup_time_windows(self, packet_id: int):
        """Remove old entries from time window"""
        current_time = time.time()
        cutoff_time = current_time - self.window_size
        
        window = self.time_windows[packet_id]
        while window and window[0][0] < cutoff_time:
            window.popleft()
            
    def _update_realtime_metrics(self):
        """Update real-time throughput and packet rate"""
        current_time = time.time()
        time_diff = current_time - self.last_calculation_time
        
        if time_diff > 0:
            # Calculate overall throughput
            recent_bytes = sum(m.size_bytes for m in self.recent_metrics 
                             if m.timestamp > current_time - 1.0)
            self.current_throughput = recent_bytes  # Bytes per second
            
            # Calculate packet rate
            recent_count = sum(1 for m in self.recent_metrics 
                             if m.timestamp > current_time - 1.0)
            self.current_packet_rate = recent_count  # Packets per second
            
        self.last_calculation_time = current_time
        
    def get_packet_statistics(self, packet_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get statistics for a specific packet or all packets.
        
        Args:
            packet_id: Specific packet ID or None for all
            
        Returns:
            Dictionary of statistics
        """
        if packet_id is not None:
            if packet_id in self.packet_stats:
                stats = self.packet_stats[packet_id]
                return {
                    'packet_id': stats.packet_id,
                    'packet_name': stats.packet_name,
                    'total_count': stats.total_count,
                    'success_rate': (stats.success_count / stats.total_count * 100) if stats.total_count > 0 else 0,
                    'error_rate': stats.error_rate,
                    'avg_size_bytes': stats.avg_size_bytes,
                    'avg_processing_time_ms': stats.avg_processing_time_ms,
                    'total_bytes': stats.total_bytes,
                    'throughput_bps': self._calculate_throughput(packet_id)
                }
            return {}
        
        # Return all statistics
        return {
            'total_packets': sum(s.total_count for s in self.packet_stats.values()),
            'total_bytes': sum(s.total_bytes for s in self.packet_stats.values()),
            'unique_packet_types': len(self.packet_stats),
            'overall_error_rate': self._calculate_overall_error_rate(),
            'current_throughput_bps': self.current_throughput,
            'current_packet_rate': self.current_packet_rate,
            'top_packets': self._get_top_packets(5),
            'top_errors': self._get_top_errors(5)
        }
        
    def _calculate_throughput(self, packet_id: int) -> float:
        """Calculate throughput for a specific packet type"""
        window = self.time_windows[packet_id]
        if not window:
            return 0
            
        time_span = window[-1][0] - window[0][0]
        if time_span > 0:
            total_bytes = sum(size for _, size in window)
            return total_bytes / time_span
        return 0
        
    def _calculate_overall_error_rate(self) -> float:
        """Calculate overall error rate across all packets"""
        total = sum(s.total_count for s in self.packet_stats.values())
        errors = sum(s.error_count for s in self.packet_stats.values())
        return (errors / total * 100) if total > 0 else 0
        
    def _get_top_packets(self, n: int) -> List[Dict[str, Any]]:
        """Get top N most frequent packet types"""
        sorted_stats = sorted(self.packet_stats.values(), 
                            key=lambda s: s.total_count, 
                            reverse=True)
        return [
            {
                'packet_id': s.packet_id,
                'packet_name': s.packet_name,
                'count': s.total_count,
                'percentage': (s.total_count / sum(st.total_count for st in self.packet_stats.values()) * 100)
            }
            for s in sorted_stats[:n]
        ]
        
    def _get_top_errors(self, n: int) -> List[Dict[str, Any]]:
        """Get top N most common error patterns"""
        sorted_errors = sorted(self.error_patterns.items(), 
                             key=lambda x: x[1], 
                             reverse=True)
        return [
            {'error': error, 'count': count}
            for error, count in sorted_errors[:n]
        ]
        
    def get_flow_analysis(self) -> Dict[str, Any]:
        """
        Analyze packet flow patterns.
        
        Returns:
            Dictionary with flow analysis data
        """
        # Find most common packet sequences
        sorted_pairs = sorted(self.packet_pairs.items(), 
                            key=lambda x: x[1], 
                            reverse=True)
        
        common_sequences = []
        for (prev_id, curr_id), count in sorted_pairs[:10]:
            prev_name = self.packet_stats.get(prev_id, PacketStatistics(prev_id, f"UNKNOWN_{prev_id}")).packet_name
            curr_name = self.packet_stats.get(curr_id, PacketStatistics(curr_id, f"UNKNOWN_{curr_id}")).packet_name
            common_sequences.append({
                'sequence': f"{prev_name} -> {curr_name}",
                'count': count
            })
        
        return {
            'common_sequences': common_sequences,
            'unique_sequences': len(self.packet_pairs),
            'total_sequences_analyzed': sum(self.packet_pairs.values())
        }
        
    def get_performance_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive performance report.
        
        Returns:
            Dictionary with performance metrics
        """
        uptime = time.time() - self.start_time
        
        # Find slowest packets
        slowest = sorted(self.packet_stats.values(),
                        key=lambda s: s.avg_processing_time_ms,
                        reverse=True)[:5]
        
        # Find largest packets
        largest = sorted(self.packet_stats.values(),
                       key=lambda s: s.avg_size_bytes,
                       reverse=True)[:5]
        
        return {
            'uptime_seconds': uptime,
            'total_packets_processed': sum(s.total_count for s in self.packet_stats.values()),
            'total_bytes_processed': sum(s.total_bytes for s in self.packet_stats.values()),
            'avg_processing_time_ms': sum(s.avg_processing_time_ms * s.total_count for s in self.packet_stats.values()) / max(1, sum(s.total_count for s in self.packet_stats.values())),
            'slowest_packets': [
                {
                    'packet_name': s.packet_name,
                    'avg_time_ms': s.avg_processing_time_ms,
                    'max_time_ms': s.max_processing_time_ms
                }
                for s in slowest
            ],
            'largest_packets': [
                {
                    'packet_name': s.packet_name,
                    'avg_size_bytes': s.avg_size_bytes,
                    'max_size_bytes': s.max_size_bytes
                }
                for s in largest
            ]
        }
        
    def reset_metrics(self):
        """Reset all collected metrics"""
        self.packet_stats.clear()
        self.recent_metrics.clear()
        self.time_windows.clear()
        self.processing_times.clear()
        self.error_patterns.clear()
        self.packet_sequences.clear()
        self.packet_pairs.clear()
        self.start_time = time.time()
        logger.info("Packet metrics reset")


# Global metrics collector instance
_metrics_collector = None


def get_metrics_collector() -> PacketMetricsCollector:
    """Get or create the global metrics collector"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = PacketMetricsCollector()
    return _metrics_collector


def record_packet_metric(packet_id: int, packet_name: str, size_bytes: int,
                        processing_time_ms: float, success: bool, direction: str,
                        error_message: Optional[str] = None):
    """Convenience function to record a packet metric"""
    collector = get_metrics_collector()
    collector.record_packet(packet_id, packet_name, size_bytes,
                          processing_time_ms, success, direction,
                          error_message)