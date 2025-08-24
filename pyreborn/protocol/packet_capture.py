"""
Packet Capture Utility for PyReborn
Captures raw packets for analysis and debugging
"""

import os
import time
import struct
import threading
from typing import Optional, BinaryIO
from datetime import datetime

class PacketCapture:
    """Captures raw packets to binary files for analysis"""
    
    def __init__(self, capture_dir: str = "captures"):
        """Initialize packet capture
        
        Args:
            capture_dir: Directory to store capture files
        """
        self.capture_dir = capture_dir
        self.capture_file: Optional[BinaryIO] = None
        self.is_capturing = False
        self.capture_lock = threading.Lock()
        self.packet_count = 0
        self.bytes_captured = 0
        
        # Create capture directory
        os.makedirs(self.capture_dir, exist_ok=True)
        
    def start_capture(self, filename: Optional[str] = None, max_packets: Optional[int] = None, 
                     max_duration: Optional[float] = None, encryption_key: Optional[int] = None) -> str:
        """Start capturing packets
        
        Args:
            filename: Custom filename (auto-generated if None)
            max_packets: Stop after this many packets
            max_duration: Stop after this many seconds
            encryption_key: Encryption key used for packet decryption
            
        Returns:
            str: Path to the capture file
        """
        with self.capture_lock:
            if self.is_capturing:
                raise RuntimeError("Capture already in progress")
                
            # Generate filename if not provided
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"capture_{timestamp}.bin"
                
            # Ensure .bin extension
            if not filename.endswith('.bin'):
                filename += '.bin'
                
            capture_path = os.path.join(self.capture_dir, filename)
            
            # Open file for binary writing
            self.capture_file = open(capture_path, 'wb')
            
            # Write capture file header with encryption key and metadata
            header = self._create_capture_header(encryption_key)
            self.capture_file.write(header)
            
            self.is_capturing = True
            self.packet_count = 0
            self.bytes_captured = 0
            self.start_time = time.time()
            self.max_packets = max_packets
            self.max_duration = max_duration
            
            # Silently start packet capture (don't interfere with Rich UI)
            pass
                
            return capture_path
    
    def _create_capture_header(self, encryption_key: Optional[int]) -> bytes:
        """Create capture file header with metadata
        
        Format: [MAGIC:4][VERSION:2][KEY_PRESENT:1][KEY:4][RESERVED:21]
        Total: 32 bytes header
        """
        header = bytearray(32)
        
        # Magic number: "PCAP" in ASCII
        header[0:4] = b'PCAP'
        
        # Version (2 bytes, little endian)
        header[4:6] = struct.pack('<H', 1)
        
        # Key present flag (1 byte)
        if encryption_key is not None:
            header[6] = 1
            # Encryption key (4 bytes, little endian) 
            header[7:11] = struct.pack('<I', encryption_key)
        else:
            header[6] = 0
            header[7:11] = b'\x00\x00\x00\x00'
        
        # Reserved space for future metadata (21 bytes)
        header[11:32] = b'\x00' * 21
        
        return bytes(header)
    
    def capture_packet(self, packet_data: bytes, direction: str = "recv") -> bool:
        """Capture a single packet
        
        Args:
            packet_data: Raw packet data (including length prefix if present)
            direction: "recv" or "send" to indicate packet direction
            
        Returns:
            bool: True if captured, False if not capturing or stopped
        """
        with self.capture_lock:
            if not self.is_capturing or not self.capture_file:
                return False
                
            # Check stop conditions
            if self.max_packets and self.packet_count >= self.max_packets:
                self.stop_capture()
                return False
                
            if self.max_duration and (time.time() - self.start_time) >= self.max_duration:
                self.stop_capture()
                return False
            
            try:
                # Write packet with metadata
                # Format: [timestamp:8][direction:1][packet_length:2][packet_data:N]
                # Note: This comes after the 32-byte header in the file
                timestamp = struct.pack('<d', time.time())
                direction_byte = b'R' if direction == "recv" else b'S'
                length = struct.pack('>H', len(packet_data))
                
                self.capture_file.write(timestamp)
                self.capture_file.write(direction_byte)
                self.capture_file.write(length)
                self.capture_file.write(packet_data)
                self.capture_file.flush()
                
                self.packet_count += 1
                self.bytes_captured += len(packet_data)
                
                return True
                
            except Exception as e:
                pass  # Silently handle errors
                return False
    
    def stop_capture(self) -> Optional[str]:
        """Stop capturing packets
        
        Returns:
            str: Path to the capture file, or None if not capturing
        """
        with self.capture_lock:
            if not self.is_capturing:
                return None
                
            capture_path = None
            if self.capture_file:
                capture_path = self.capture_file.name
                self.capture_file.close()
                self.capture_file = None
                
            self.is_capturing = False
            duration = time.time() - self.start_time
            
            # Silently stop capture (don't interfere with Rich UI)
            pass
            
            return capture_path
    
    def is_active(self) -> bool:
        """Check if capture is currently active"""
        return self.is_capturing
    
    def get_stats(self) -> dict:
        """Get current capture statistics"""
        with self.capture_lock:
            return {
                'is_capturing': self.is_capturing,
                'packet_count': self.packet_count,
                'bytes_captured': self.bytes_captured,
                'duration': time.time() - self.start_time if self.is_capturing else 0
            }


class CaptureAnalyzer:
    """Analyze captured packet files"""
    
    @staticmethod
    def analyze_capture(filepath: str) -> dict:
        """Analyze a capture file and return statistics
        
        Args:
            filepath: Path to the capture file
            
        Returns:
            dict: Analysis results
        """
        stats = {
            'total_packets': 0,
            'recv_packets': 0,
            'send_packets': 0,
            'total_bytes': 0,
            'packet_types': {},
            'first_timestamp': None,
            'last_timestamp': None,
            'duration': 0,
            'packets': [],
            'encryption_key': None,
            'file_version': None
        }
        
        try:
            with open(filepath, 'rb') as f:
                # First, try to read capture file header
                header_data = f.read(32)
                if len(header_data) >= 32 and header_data[:4] == b'PCAP':
                    # New format with header
                    version = struct.unpack('<H', header_data[4:6])[0]
                    key_present = header_data[6]
                    if key_present:
                        encryption_key = struct.unpack('<I', header_data[7:11])[0]
                        stats['encryption_key'] = encryption_key
                    stats['file_version'] = version
                else:
                    # Old format without header, rewind
                    f.seek(0)
                
                while True:
                    # Read packet header
                    header = f.read(11)  # 8 + 1 + 2 bytes
                    if len(header) < 11:
                        break
                        
                    timestamp = struct.unpack('<d', header[:8])[0]
                    direction = header[8:9].decode('ascii')
                    packet_length = struct.unpack('>H', header[9:11])[0]
                    
                    # Read packet data
                    packet_data = f.read(packet_length)
                    if len(packet_data) < packet_length:
                        break
                    
                    # Update stats
                    stats['total_packets'] += 1
                    stats['total_bytes'] += packet_length
                    
                    if direction == 'R':
                        stats['recv_packets'] += 1
                    else:
                        stats['send_packets'] += 1
                    
                    if stats['first_timestamp'] is None:
                        stats['first_timestamp'] = timestamp
                    stats['last_timestamp'] = timestamp
                    
                    # Analyze packet type
                    if packet_data:
                        packet_type = packet_data[0]
                        type_name = f"0x{packet_type:02x}"
                        stats['packet_types'][type_name] = stats['packet_types'].get(type_name, 0) + 1
                    
                    # Store packet info
                    stats['packets'].append({
                        'timestamp': timestamp,
                        'direction': direction,
                        'size': packet_length,
                        'type': packet_type if packet_data else None
                    })
            
            # Calculate duration
            if stats['first_timestamp'] and stats['last_timestamp']:
                stats['duration'] = stats['last_timestamp'] - stats['first_timestamp']
                
        except Exception as e:
            print(f"❌ Error analyzing capture: {e}")
            
        return stats
    
    @staticmethod
    def print_analysis(filepath: str):
        """Print analysis of a capture file"""
        stats = CaptureAnalyzer.analyze_capture(filepath)
        
        print(f"\n📊 CAPTURE ANALYSIS: {os.path.basename(filepath)}")
        print(f"   Total packets: {stats['total_packets']}")
        print(f"   Received: {stats['recv_packets']}")
        print(f"   Sent: {stats['send_packets']}")
        print(f"   Total bytes: {stats['total_bytes']:,}")
        print(f"   Duration: {stats['duration']:.1f}s")
        if stats['encryption_key'] is not None:
            print(f"   🔑 Encryption key: {stats['encryption_key']}")
        if stats['file_version'] is not None:
            print(f"   📄 File version: {stats['file_version']}")
        
        if stats['packet_types']:
            print(f"\n   Packet types:")
            for ptype, count in sorted(stats['packet_types'].items()):
                print(f"     {ptype}: {count}")
        
        return stats


# Integration helpers for RebornClient
def add_capture_to_client(client, capture_dir: str = "captures"):
    """Add packet capture capability to a RebornClient instance
    
    Args:
        client: RebornClient instance
        capture_dir: Directory for capture files
    """
    client.packet_capture = PacketCapture(capture_dir)
    
    # Store original methods
    client._original_send_packet = getattr(client, 'send_packet', None)
    client._original_recv_encrypted_packet_data = getattr(client, 'recv_encrypted_packet_data', None)
    
    # Wrap send_packet if it exists
    if hasattr(client, 'send_packet'):
        def captured_send_packet(*args, **kwargs):
            result = client._original_send_packet(*args, **kwargs)
            # Note: We'd need access to the raw packet data here
            # This is a placeholder for send packet capture
            return result
        client.send_packet = captured_send_packet
    
    # Wrap recv_encrypted_packet_data
    if hasattr(client, 'recv_encrypted_packet_data'):
        def captured_recv_packet(packet_data):
            # Capture the raw packet before processing
            if client.packet_capture.is_active():
                client.packet_capture.capture_packet(packet_data, "recv")
            return client._original_recv_encrypted_packet_data(packet_data)
        client.recv_encrypted_packet_data = captured_recv_packet

def start_capture_session(client, duration: float = 30.0, filename: Optional[str] = None) -> str:
    """Start a capture session for a client
    
    Args:
        client: RebornClient with capture capability
        duration: How long to capture (seconds)
        filename: Optional custom filename
        
    Returns:
        str: Path to capture file
    """
    if not hasattr(client, 'packet_capture'):
        add_capture_to_client(client)
    
    return client.packet_capture.start_capture(
        filename=filename,
        max_duration=duration
    )

def stop_capture_session(client) -> Optional[str]:
    """Stop capture session for a client
    
    Returns:
        str: Path to capture file, or None if not capturing
    """
    if not hasattr(client, 'packet_capture'):
        return None
    
    return client.packet_capture.stop_capture()


class PacketReplay:
    """Replays captured packets to a RebornClient for testing and debugging"""
    
    def __init__(self, capture_filepath: str):
        """Initialize packet replay from a capture file
        
        Args:
            capture_filepath: Path to the capture file to replay
        """
        self.capture_filepath = capture_filepath
        self.packets = []
        self.encryption_key = None
        self.file_version = None
        self.current_index = 0
        self.start_time = None
        self.time_offset = 0
        
        # Load capture data
        self._load_capture()
    
    def _load_capture(self):
        """Load packets from capture file"""
        try:
            with open(self.capture_filepath, 'rb') as f:
                # Read header
                header_data = f.read(32)
                if len(header_data) >= 32 and header_data[:4] == b'PCAP':
                    # New format with header
                    self.file_version = struct.unpack('<H', header_data[4:6])[0]
                    key_present = header_data[6]
                    if key_present:
                        self.encryption_key = struct.unpack('<I', header_data[7:11])[0]
                else:
                    # Old format without header, rewind
                    f.seek(0)
                
                # Read all packets
                while True:
                    # Read packet header: timestamp(8) + direction(1) + length(2)
                    header = f.read(11)
                    if len(header) < 11:
                        break
                        
                    timestamp = struct.unpack('<d', header[:8])[0]
                    direction = header[8:9].decode('ascii')
                    packet_length = struct.unpack('>H', header[9:11])[0]
                    
                    # Read packet data
                    packet_data = f.read(packet_length)
                    if len(packet_data) < packet_length:
                        break
                    
                    self.packets.append({
                        'timestamp': timestamp,
                        'direction': direction,
                        'data': packet_data
                    })
                
                print(f"📁 Loaded {len(self.packets)} packets from {os.path.basename(self.capture_filepath)}")
                if self.encryption_key:
                    print(f"🔑 Encryption key: {self.encryption_key}")
                    
        except Exception as e:
            print(f"❌ Error loading capture file: {e}")
            raise
    
    def replay_to_client(self, client, speed_multiplier: float = 1.0, 
                        recv_only: bool = True, start_from: int = 0):
        """Replay packets to a RebornClient instance
        
        Args:
            client: RebornClient instance to replay packets to
            speed_multiplier: Speed multiplier (1.0 = real-time, 0 = instant)
            recv_only: Only replay received packets (ignore sent packets)
            start_from: Start replay from this packet index
        """
        if not self.packets:
            print("❌ No packets to replay")
            return
        
        if start_from >= len(self.packets):
            print(f"❌ Start index {start_from} exceeds packet count {len(self.packets)}")
            return
        
        # Set encryption key if available
        if self.encryption_key and hasattr(client, 'encryption_key'):
            client.encryption_key = self.encryption_key
            print(f"🔑 Set client encryption key: {self.encryption_key}")
        
        # Filter packets if recv_only
        packets_to_replay = []
        for i, packet in enumerate(self.packets[start_from:], start_from):
            if recv_only and packet['direction'] != 'R':
                continue
            packets_to_replay.append((i, packet))
        
        print(f"🎬 Starting replay: {len(packets_to_replay)} packets")
        if speed_multiplier == 0:
            print("⚡ Instant replay mode")
        else:
            print(f"⏰ Speed: {speed_multiplier}x")
        
        # Replay packets
        self.start_time = time.time()
        first_timestamp = packets_to_replay[0][1]['timestamp'] if packets_to_replay else None
        
        for packet_index, packet in packets_to_replay:
            # Calculate timing
            if speed_multiplier > 0 and first_timestamp:
                packet_delay = packet['timestamp'] - first_timestamp
                target_time = self.start_time + (packet_delay / speed_multiplier)
                current_time = time.time()
                
                if target_time > current_time:
                    time.sleep(target_time - current_time)
            
            # Send packet to client's packet handler
            try:
                if hasattr(client, 'recv_encrypted_packet_data'):
                    print(f"📦 Replaying packet {packet_index}: {len(packet['data'])} bytes")
                    client.recv_encrypted_packet_data(packet['data'])
                else:
                    print(f"❌ Client missing recv_encrypted_packet_data method")
                    break
                    
            except Exception as e:
                print(f"❌ Error replaying packet {packet_index}: {e}")
                # Continue with next packet instead of stopping
                continue
        
        print(f"✅ Replay complete: {len(packets_to_replay)} packets processed")
    
    def get_packet_info(self, index: int) -> dict:
        """Get information about a specific packet
        
        Args:
            index: Packet index
            
        Returns:
            dict: Packet information
        """
        if 0 <= index < len(self.packets):
            packet = self.packets[index]
            info = {
                'index': index,
                'timestamp': packet['timestamp'],
                'direction': 'Received' if packet['direction'] == 'R' else 'Sent',
                'size': len(packet['data']),
                'data_preview': packet['data'][:20].hex() if packet['data'] else ''
            }
            
            # Add packet type if data available
            if packet['data']:
                info['packet_type'] = f"0x{packet['data'][0]:02x}"
            
            return info
        
        return {}
    
    def print_packet_summary(self, max_packets: int = 50):
        """Print summary of packets in the capture
        
        Args:
            max_packets: Maximum number of packets to show details for
        """
        print(f"\n📋 PACKET SUMMARY: {os.path.basename(self.capture_filepath)}")
        print(f"Total packets: {len(self.packets)}")
        
        recv_count = sum(1 for p in self.packets if p['direction'] == 'R')
        send_count = len(self.packets) - recv_count
        
        print(f"Received: {recv_count}")
        print(f"Sent: {send_count}")
        
        if self.encryption_key:
            print(f"🔑 Encryption key: {self.encryption_key}")
        
        print(f"\nFirst {min(max_packets, len(self.packets))} packets:")
        for i in range(min(max_packets, len(self.packets))):
            info = self.get_packet_info(i)
            direction_symbol = "⬇️" if info['direction'] == 'Received' else "⬆️"
            print(f"  {i:3d}: {direction_symbol} {info['packet_type']:>6} | {info['size']:4d}B | {info['data_preview']}")


def replay_capture_to_client(client, capture_filepath: str, **kwargs):
    """Convenience function to replay a capture file to a client
    
    Args:
        client: RebornClient instance
        capture_filepath: Path to capture file
        **kwargs: Additional arguments passed to replay_to_client()
    """
    replay = PacketReplay(capture_filepath)
    replay.replay_to_client(client, **kwargs)