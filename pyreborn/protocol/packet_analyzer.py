#!/usr/bin/env python3
"""
Packet Analyzer for PyReborn - Detailed packet parsing analysis
"""

import json
import time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import deque
import struct


@dataclass
class PacketAnalysis:
    """Detailed analysis of a single packet"""
    # Timing
    timestamp: float
    sequence: int
    
    # Raw data
    raw_encrypted: bytes  # Before decryption
    raw_decrypted: bytes  # After decryption
    
    # Packet info
    packet_id: int
    packet_name: str
    packet_size: int
    
    # Context
    data_before: bytes  # 50 bytes before this packet
    data_after: bytes   # 50 bytes after this packet
    stream_position: int  # Position in stream
    
    # Parsing details
    handler_name: str
    handler_success: bool
    handler_error: Optional[str]
    parsed_fields: Dict[str, Any]
    
    # Special flags
    is_text_command: bool
    is_raw_data: bool
    is_continuation: bool
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with hex strings for bytes"""
        result = {}
        for key, value in asdict(self).items():
            if isinstance(value, bytes):
                result[key] = value.hex() if value else ""
            elif isinstance(value, dict):
                # Convert any bytes values in parsed_fields
                result[key] = {}
                for k, v in value.items():
                    if isinstance(v, bytes):
                        result[key][k] = v.hex()
                    else:
                        result[key][k] = v
            else:
                result[key] = value
        return result


class PacketAnalyzer:
    """Analyzes packet parsing in detail"""
    
    def __init__(self, max_packets: int = 1000):
        self.enabled = False
        self.max_packets = max_packets
        self.analyses: deque = deque(maxlen=max_packets)
        self.sequence = 0
        self.stream_buffer = bytearray()  # Keep last 1KB of stream
        self.stream_position = 0
        
        # Packet ID to name mapping
        self.packet_names = {
            0: "PLO_ERROR",
            1: "PLO_NULL", 
            2: "PLO_PLAYER_ID",
            3: "PLO_PLAYER_PROPS",
            4: "PLO_PLAYER_PROPS2",
            5: "PLO_PLAYER_ENTER",
            6: "PLO_PLAYER_LEAVE",
            7: "PLO_PLAYER_WARP",
            8: "PLO_PLAYER_KILLED",
            9: "PLO_PLAYERPROPS",
            11: "PLO_OTHERPLAYER_PROPS",
            12: "PLO_OTHERPLAYER_PROPS2",
            13: "PLO_ADDPLAYER_PROPS",
            14: "PLO_ADDPLAYER_PROPS2",
            15: "PLO_PROJECTILE",
            16: "PLO_PROJECTILE2",
            18: "PLO_SHOOT",
            19: "PLO_SERVERFLAGS",
            20: "PLO_SERVERWARP",
            21: "PLO_PLAYERWEAPONS",
            22: "PLO_LEVELNAME",
            23: "PLO_LEVELLINK",
            24: "PLO_LEVELMOD",
            25: "PLO_PLAYERPACKET",
            26: "PLO_ADJACENTLEVEL",
            27: "PLO_HITOBJECTS",
            28: "PLO_LEVELCHEST",
            29: "PLO_LEVELBOARD",
            30: "PLO_LEVELHORSEADD",
            31: "PLO_LEVELHORSEREMOVE",
            32: "PLO_BADDYPROPS",
            33: "PLO_BADDYHIT",
            34: "PLO_NPCWEAPONDEL",
            35: "PLO_SETACTIVELEVEL",
            42: "PLO_NEWWORLDTIME",
            36: "PLO_ITEMDROP",
            37: "PLO_ITEMDEL",
            38: "PLO_GANINFRAME",
            39: "PLO_GANINTILE",
            40: "PLO_GANINATT",
            41: "PLO_MAPINFO",
            42: "PLO_PACKAGEDOWNLOAD",
            72: "PLO_BOARD_CONTINUATION",
            100: "PLO_RAWDATA",
            101: "PLO_BOARDPACKET",
            102: "PLO_FILE",
            130: "PLO_NPCSERVERQUERY",
            150: "PLO_LARGEFILESTART",
            151: "PLO_LARGEFILESTOP",
            152: "PLO_LARGEFILESIZE",
            153: "PLO_LARGEFILEDATA",
            160: "PLO_RAWDATA",
            161: "PLO_BOARDMODIFY",
            162: "PLO_BOARDMODIFYREPEAT",
            163: "PLO_LEVELMODREPEAT",
            164: "PLO_ADJACENTLEVELREPEAT",
            165: "PLO_HITOBJECTSREPEAT",
            166: "PLO_LEVELCHESTREPEAT",
            167: "PLO_LEVELITEMADDREPEAT",
            168: "PLO_LEVELITEMDROPREPEAT",
            197: "PLO_PING",
            198: "PLO_ACCOUNT",
            199: "PLO_ACCOUNTADD",
            200: "PLO_ACCOUNTDEL",
            201: "PLO_ACCOUNTMOD",
            202: "PLO_ACCOUNTNAME",
            203: "PLO_ACCOUNTCOMMENT",
            204: "PLO_ACCOUNTEMAIL",
            205: "PLO_ACCOUNTPASSWORD",
            206: "PLO_ACCOUNTCREATED",
            207: "PLO_ACCOUNTLOGIN",
            208: "PLO_ACCOUNTLIST",
            209: "PLO_PLAYERLIST",
            210: "PLO_PLAYERLISTPROPS",
            211: "PLO_PLAYERLISTMOD",
            212: "PLO_PLAYERLISTADD",
            213: "PLO_PLAYERLISTREMOVE",
            214: "PLO_ACCOUNTLISTMOD",
            215: "PLO_ACCOUNTLISTADD",
            216: "PLO_ACCOUNTLISTREMOVE",
            220: "PLO_PLAYERLISTGROUPS",
            221: "PLO_ACCOUNTLISTGROUPS",
            222: "PLO_LARGEFILEEND",
            223: "PLO_REQUESTTEXT",
            224: "PLO_SENDTEXT",
            225: "PLO_SENDTEXTGET",
            226: "PLO_SENDTEXTSET",
            227: "PLO_SENDTEXTSETGET",
            228: "PLO_SENDTEXTUNSET",
            230: "PLO_RPGWINDOW",
            231: "PLO_SAY2",
            240: "PLO_SHOWIMG",
        }
        
    def enable(self):
        """Enable packet analysis"""
        self.enabled = True
        self.analyses.clear()
        self.sequence = 0
        
    def disable(self):
        """Disable packet analysis"""
        self.enabled = False
        
    def analyze_packet(self, 
                      raw_encrypted: bytes,
                      raw_decrypted: bytes,
                      packet_id: int,
                      packet_data: bytes,
                      handler_name: str = None,
                      handler_result: Any = None,
                      handler_error: Exception = None,
                      parsed_fields: Dict[str, Any] = None,
                      is_text: bool = False,
                      is_raw: bool = False,
                      stream_context: bytes = None) -> PacketAnalysis:
        """Analyze a packet and store the analysis"""
        if not self.enabled:
            return None
            
        # Update stream buffer for context
        if stream_context:
            self.stream_buffer.extend(stream_context)
            if len(self.stream_buffer) > 1024:
                self.stream_buffer = self.stream_buffer[-1024:]
        
        # Find position in stream
        stream_pos = self.stream_position
        self.stream_position += len(raw_decrypted) if raw_decrypted else 0
        
        # Extract context data
        data_before = bytes(self.stream_buffer[-50:]) if len(self.stream_buffer) >= 50 else bytes(self.stream_buffer)
        data_after = b""  # Will be filled by next packet
        
        # Create analysis
        analysis = PacketAnalysis(
            timestamp=time.time(),
            sequence=self.sequence,
            raw_encrypted=raw_encrypted or b"",
            raw_decrypted=raw_decrypted or b"",
            packet_id=packet_id,
            packet_name=self.packet_names.get(packet_id, f"UNKNOWN_{packet_id}"),
            packet_size=len(packet_data) if packet_data else 0,
            data_before=data_before,
            data_after=data_after,
            stream_position=stream_pos,
            handler_name=handler_name or "unknown",
            handler_success=handler_error is None,
            handler_error=str(handler_error) if handler_error else None,
            parsed_fields=parsed_fields or {},
            is_text_command=is_text,
            is_raw_data=is_raw,
            is_continuation=False
        )
        
        # Update previous packet's data_after
        if self.analyses and len(raw_decrypted) > 0:
            prev_analysis = self.analyses[-1]
            prev_analysis.data_after = raw_decrypted[:50]
        
        self.analyses.append(analysis)
        self.sequence += 1
        
        return analysis
        
    def get_analyses(self, last_n: Optional[int] = None) -> List[PacketAnalysis]:
        """Get packet analyses"""
        if last_n:
            return list(self.analyses)[-last_n:]
        return list(self.analyses)
        
    def export_to_file(self, filename: str, last_n: Optional[int] = None):
        """Export analyses to JSON file"""
        analyses = self.get_analyses(last_n)
        data = {
            'metadata': {
                'export_time': time.time(),
                'total_packets': len(analyses),
                'sequence_start': analyses[0].sequence if analyses else 0,
                'sequence_end': analyses[-1].sequence if analyses else 0,
            },
            'packets': [a.to_dict() for a in analyses]
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
            
    def export_readable(self, filename: str, last_n: Optional[int] = None):
        """Export analyses in human-readable format"""
        analyses = self.get_analyses(last_n)
        
        with open(filename, 'w') as f:
            f.write("PyReborn Packet Analysis Report\n")
            f.write("=" * 80 + "\n\n")
            
            for a in analyses:
                f.write(f"Packet #{a.sequence} - {a.packet_name} (ID: {a.packet_id})\n")
                f.write("-" * 60 + "\n")
                f.write(f"Timestamp: {a.timestamp:.3f}\n")
                f.write(f"Stream Position: {a.stream_position}\n")
                f.write(f"Size: {a.packet_size} bytes\n")
                f.write(f"Handler: {a.handler_name} ({'SUCCESS' if a.handler_success else 'FAILED'})\n")
                
                if a.handler_error:
                    f.write(f"Error: {a.handler_error}\n")
                    
                f.write(f"\nRaw Decrypted ({len(a.raw_decrypted)} bytes):\n")
                # Show hex dump
                for i in range(0, min(len(a.raw_decrypted), 64), 16):
                    hex_part = ' '.join(f'{b:02x}' for b in a.raw_decrypted[i:i+16])
                    ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in a.raw_decrypted[i:i+16])
                    f.write(f"  {i:04x}: {hex_part:<48} {ascii_part}\n")
                    
                if len(a.raw_decrypted) > 64:
                    f.write(f"  ... ({len(a.raw_decrypted) - 64} more bytes)\n")
                    
                if a.parsed_fields:
                    f.write(f"\nParsed Fields:\n")
                    for key, value in a.parsed_fields.items():
                        f.write(f"  {key}: {value}\n")
                        
                f.write(f"\nContext (50 bytes before):\n")
                f.write(f"  {a.data_before.hex()}\n")
                
                f.write(f"\nContext (50 bytes after):\n")
                f.write(f"  {a.data_after.hex()}\n")
                
                f.write("\n" + "=" * 80 + "\n\n")
                
    def find_packets_by_id(self, packet_id: int) -> List[PacketAnalysis]:
        """Find all packets with a specific ID"""
        return [a for a in self.analyses if a.packet_id == packet_id]
        
    def find_error_packets(self) -> List[PacketAnalysis]:
        """Find all packets that had parsing errors"""
        return [a for a in self.analyses if not a.handler_success]
        
    def analyze_packet_by_sequence(self, sequence: int) -> Optional[str]:
        """Get human-readable analysis of a specific packet by sequence number"""
        for analysis in self.analyses:
            if analysis.sequence == sequence:
                return self._format_single_packet(analysis)
        return None
        
    def analyze_last_packet(self) -> Optional[str]:
        """Get human-readable analysis of the most recent packet"""
        if self.analyses:
            return self._format_single_packet(self.analyses[-1])
        return None
        
    def analyze_packets_by_name(self, name: str) -> str:
        """Get analysis of all packets matching a name pattern"""
        matching = [a for a in self.analyses if name.lower() in a.packet_name.lower()]
        if not matching:
            return f"No packets found matching '{name}'"
            
        output = [f"Found {len(matching)} packets matching '{name}':\n"]
        for a in matching:
            output.append(self._format_single_packet(a))
            output.append("\n" + "=" * 80 + "\n")
        return '\n'.join(output)
        
    def _format_single_packet(self, a: PacketAnalysis) -> str:
        """Format a single packet analysis in human-readable form"""
        lines = []
        lines.append(f"📦 Packet #{a.sequence} - {a.packet_name} (ID: {a.packet_id})")
        lines.append("─" * 60)
        
        # Basic info
        lines.append(f"⏰ Timestamp: {a.timestamp:.3f}")
        lines.append(f"📍 Stream Position: {a.stream_position}")
        lines.append(f"📏 Size: {a.packet_size} bytes")
        lines.append(f"🔧 Handler: {a.handler_name}")
        lines.append(f"✅ Status: {'SUCCESS' if a.handler_success else f'FAILED - {a.handler_error}'}")
        
        # Special flags
        flags = []
        if a.is_text_command:
            flags.append("TEXT")
        if a.is_raw_data:
            flags.append("RAW")
        if a.is_continuation:
            flags.append("CONTINUATION")
        if flags:
            lines.append(f"🚩 Flags: {', '.join(flags)}")
        
        # Raw data hex dump
        lines.append(f"\n📋 Raw Decrypted Data ({len(a.raw_decrypted)} bytes):")
        if len(a.raw_decrypted) <= 256:
            # Show all for small packets
            for i in range(0, len(a.raw_decrypted), 16):
                hex_part = ' '.join(f'{b:02x}' for b in a.raw_decrypted[i:i+16])
                ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in a.raw_decrypted[i:i+16])
                lines.append(f"  {i:04x}: {hex_part:<48} {ascii_part}")
        else:
            # Show first 128 and last 32 for large packets
            for i in range(0, 128, 16):
                hex_part = ' '.join(f'{b:02x}' for b in a.raw_decrypted[i:i+16])
                ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in a.raw_decrypted[i:i+16])
                lines.append(f"  {i:04x}: {hex_part:<48} {ascii_part}")
            lines.append(f"  ... ({len(a.raw_decrypted) - 160} bytes omitted) ...")
            # Show last 32 bytes
            start = len(a.raw_decrypted) - 32
            for i in range(start, len(a.raw_decrypted), 16):
                hex_part = ' '.join(f'{b:02x}' for b in a.raw_decrypted[i:i+16])
                ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in a.raw_decrypted[i:i+16])
                lines.append(f"  {i:04x}: {hex_part:<48} {ascii_part}")
        
        # Parsed fields
        if a.parsed_fields:
            lines.append(f"\n🔍 Parsed Fields:")
            for key, value in a.parsed_fields.items():
                if isinstance(value, (list, tuple)) and len(str(value)) > 100:
                    # Truncate long lists
                    lines.append(f"  {key}: {str(value)[:100]}... ({len(value)} items)")
                elif isinstance(value, bytes):
                    lines.append(f"  {key}: {value.hex()[:64]}... ({len(value)} bytes)")
                else:
                    lines.append(f"  {key}: {value}")
        
        # Context
        if a.data_before:
            lines.append(f"\n📤 Context Before (50 bytes):")
            lines.append(f"  Hex: {a.data_before.hex()}")
            ascii_before = ''.join(chr(b) if 32 <= b < 127 else '.' for b in a.data_before)
            lines.append(f"  ASCII: {ascii_before}")
            
        if a.data_after:
            lines.append(f"\n📥 Context After (50 bytes):")
            lines.append(f"  Hex: {a.data_after.hex()}")
            ascii_after = ''.join(chr(b) if 32 <= b < 127 else '.' for b in a.data_after)
            lines.append(f"  ASCII: {ascii_after}")
        
        return '\n'.join(lines)
        
    def get_packet_flow_summary(self, last_n: Optional[int] = None) -> str:
        """Get a concise flow summary of packets"""
        analyses = self.get_analyses(last_n)
        if not analyses:
            return "No packets captured yet."
            
        lines = ["📊 Packet Flow Summary:"]
        lines.append("─" * 80)
        
        for a in analyses:
            status = "✅" if a.handler_success else "❌"
            size_str = f"{a.packet_size:>6d}B" if a.packet_size < 1000 else f"{a.packet_size/1024:>5.1f}KB"
            
            # Build compact summary line
            line = f"{a.sequence:>4d} {status} {a.packet_name:<25} {size_str}"
            
            # Add key info based on packet type
            if a.packet_name == "PLO_BOARDPACKET":
                tiles = a.parsed_fields.get('tiles', 0)
                line += f" [{tiles} tiles]"
            elif a.packet_name == "PLO_FILE":
                filename = a.parsed_fields.get('filename', 'unknown')
                line += f" [{filename}]"
            elif a.packet_name == "PLO_LEVELNAME":
                level = a.parsed_fields.get('level_name', 'unknown')
                line += f" [{level}]"
            elif "PLAYER" in a.packet_name:
                player_id = a.parsed_fields.get('player_id', '?')
                line += f" [ID: {player_id}]"
                
            lines.append(line)
            
        # Add summary stats
        lines.append("\n" + "─" * 80)
        total_size = sum(a.packet_size for a in analyses)
        error_count = sum(1 for a in analyses if not a.handler_success)
        lines.append(f"Total: {len(analyses)} packets, {total_size:,} bytes, {error_count} errors")
        
        return '\n'.join(lines)
        
    def get_packet_summary(self) -> Dict[str, Any]:
        """Get summary statistics"""
        if not self.analyses:
            return {}
            
        packet_counts = {}
        error_counts = {}
        total_bytes = 0
        
        for a in self.analyses:
            name = a.packet_name
            packet_counts[name] = packet_counts.get(name, 0) + 1
            if not a.handler_success:
                error_counts[name] = error_counts.get(name, 0) + 1
            total_bytes += a.packet_size
            
        return {
            'total_packets': len(self.analyses),
            'total_bytes': total_bytes,
            'packet_counts': packet_counts,
            'error_counts': error_counts,
            'duration': self.analyses[-1].timestamp - self.analyses[0].timestamp if len(self.analyses) > 1 else 0
        }