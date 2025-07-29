"""
Packet recording and replay system for testing
"""

import json
import time
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path


class PacketRecord:
    """Represents a recorded packet"""
    
    def __init__(self, timestamp: float, packet_id: int, data: bytes, direction: str):
        self.timestamp = timestamp
        self.packet_id = packet_id
        self.data = data
        self.direction = direction  # 'sent' or 'received'
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'timestamp': self.timestamp,
            'packet_id': self.packet_id,
            'data': self.data.hex(),
            'direction': self.direction
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PacketRecord':
        """Create from dictionary"""
        return cls(
            timestamp=data['timestamp'],
            packet_id=data['packet_id'],
            data=bytes.fromhex(data['data']),
            direction=data['direction']
        )


class PacketRecorder:
    """Records packets for replay"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.records: List[PacketRecord] = []
        self.recording = False
        self.start_time: Optional[float] = None
    
    def start_recording(self) -> None:
        """Start recording packets"""
        self.recording = True
        self.start_time = time.time()
        self.records.clear()
        self.logger.debug("Started packet recording")
    
    def stop_recording(self) -> None:
        """Stop recording packets"""
        self.recording = False
        self.logger.debug(f"Stopped packet recording - {len(self.records)} packets recorded")
    
    def record_packet(self, packet_id: int, data: bytes, direction: str) -> None:
        """Record a packet"""
        if not self.recording:
            return
        
        current_time = time.time()
        relative_time = current_time - (self.start_time or current_time)
        
        record = PacketRecord(relative_time, packet_id, data, direction)
        self.records.append(record)
    
    def save_recording(self, filename: str) -> bool:
        """Save recording to file"""
        try:
            data = {
                'version': '1.0',
                'packet_count': len(self.records),
                'duration': self.records[-1].timestamp if self.records else 0.0,
                'packets': [record.to_dict() for record in self.records]
            }
            
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
            
            self.logger.info(f"Saved {len(self.records)} packets to {filename}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to save recording: {e}")
            return False
    
    def get_recording_stats(self) -> Dict[str, Any]:
        """Get recording statistics"""
        if not self.records:
            return {'packet_count': 0, 'duration': 0.0}
        
        sent_count = sum(1 for r in self.records if r.direction == 'sent')
        received_count = sum(1 for r in self.records if r.direction == 'received')
        
        return {
            'packet_count': len(self.records),
            'sent_packets': sent_count,
            'received_packets': received_count,
            'duration': self.records[-1].timestamp,
            'unique_packet_ids': len(set(r.packet_id for r in self.records))
        }


class PacketReplayer:
    """Replays recorded packets"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.records: List[PacketRecord] = []
        self.replay_speed = 1.0
        self.current_index = 0
    
    def load_recording(self, filename: str) -> bool:
        """Load recording from file"""
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            self.records = [
                PacketRecord.from_dict(packet_data)
                for packet_data in data['packets']
            ]
            
            self.current_index = 0
            self.logger.info(f"Loaded {len(self.records)} packets from {filename}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load recording: {e}")
            return False
    
    def set_replay_speed(self, speed: float) -> None:
        """Set replay speed multiplier"""
        self.replay_speed = max(0.1, speed)
    
    def get_next_packet(self, max_wait: float = None) -> Optional[PacketRecord]:
        """Get next packet in sequence"""
        if self.current_index >= len(self.records):
            return None
        
        record = self.records[self.current_index]
        self.current_index += 1
        
        # Apply speed adjustment to timing
        if max_wait is not None and record.timestamp > max_wait:
            # Skip timing if it would exceed max wait
            pass
        elif self.current_index > 1:
            # Calculate delay based on previous packet
            prev_record = self.records[self.current_index - 2]
            delay = (record.timestamp - prev_record.timestamp) / self.replay_speed
            time.sleep(max(0, min(delay, max_wait or delay)))
        
        return record
    
    def get_all_packets(self, direction: str = None) -> List[PacketRecord]:
        """Get all packets, optionally filtered by direction"""
        if direction:
            return [r for r in self.records if r.direction == direction]
        return self.records.copy()
    
    def reset(self) -> None:
        """Reset replay position"""
        self.current_index = 0
    
    def get_replay_stats(self) -> Dict[str, Any]:
        """Get replay statistics"""
        return {
            'total_packets': len(self.records),
            'current_position': self.current_index,
            'remaining_packets': len(self.records) - self.current_index,
            'replay_speed': self.replay_speed
        }