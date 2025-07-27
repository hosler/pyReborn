"""
Version-specific packet encoding/decoding based on GServer implementation.

Each encryption generation has different packet handling:
- ENCRYPT_GEN_1: No encryption, no compression (web clients)
- ENCRYPT_GEN_2: No encryption, zlib compression (old clients)
- ENCRYPT_GEN_3: Single byte insertion, zlib compression (special case)
- ENCRYPT_GEN_4: Partial encryption, bz2 compression (2.19-2.21)
- ENCRYPT_GEN_5: Partial encryption, dynamic compression (2.22+)
"""

import struct
import zlib
import bz2
from typing import Optional, Tuple
from abc import ABC, abstractmethod

from ..core.encryption import RebornEncryption, CompressionType
from .versions import EncryptionType


class VersionCodec(ABC):
    """Base class for version-specific packet handling"""
    
    def __init__(self, encryption_key: int = 0):
        self.encryption_key = encryption_key
        self.in_codec = None
        self.out_codec = None
        
    @abstractmethod
    def send_packet(self, data: bytes) -> bytes:
        """Encode packet for sending"""
        pass
        
    @abstractmethod
    def recv_packet(self, data: bytes) -> Optional[bytes]:
        """Decode received packet"""
        pass
        


class Gen1Codec(VersionCodec):
    """ENCRYPT_GEN_1: No encryption, no compression (web clients)"""
    
    def send_packet(self, data: bytes) -> bytes:
        """Just add length header"""
        return struct.pack('>H', len(data)) + data
        
    def recv_packet(self, data: bytes) -> Optional[bytes]:
        """No decryption needed"""
        return data


class Gen2Codec(VersionCodec):
    """ENCRYPT_GEN_2: No encryption, zlib compression (old clients)"""
    
    def send_packet(self, data: bytes) -> bytes:
        """Compress with zlib and add length header"""
        compressed = zlib.compress(data)
        return struct.pack('>H', len(compressed)) + compressed
        
    def recv_packet(self, data: bytes) -> Optional[bytes]:
        """Decompress zlib data"""
        try:
            return zlib.decompress(data)
        except:
            return None


class Gen3Codec(VersionCodec):
    """ENCRYPT_GEN_3: Single byte insertion, zlib compression"""
    
    def __init__(self, encryption_key: int = 0):
        super().__init__(encryption_key)
        # Gen3 uses a simple byte insertion algorithm
        
    def send_packet(self, data: bytes) -> bytes:
        """Compress and apply single byte insertion"""
        compressed = zlib.compress(data)
        
        # TODO: Implement single byte insertion encryption
        # For now, just send compressed
        return struct.pack('>H', len(compressed)) + compressed
        
    def recv_packet(self, data: bytes) -> Optional[bytes]:
        """Remove single byte insertion and decompress"""
        try:
            # TODO: Remove single byte insertion
            return zlib.decompress(data)
        except:
            return None


class Gen4Codec(VersionCodec):
    """ENCRYPT_GEN_4: Partial encryption, bz2 compression (2.19-2.21)"""
    
    def __init__(self, encryption_key: int = 0):
        super().__init__(encryption_key)
        self.in_codec = RebornEncryption(encryption_key)
        self.out_codec = RebornEncryption(encryption_key)
        
    def send_packet(self, data: bytes) -> bytes:
        """Compress with bz2 and encrypt"""
        # Always use bz2 for gen4
        compressed = bz2.compress(data)
        
        # Create codec for this packet
        packet_codec = RebornEncryption(self.encryption_key)
        packet_codec.iterator = self.out_codec.iterator
        packet_codec.limit_from_type(CompressionType.BZ2)
        
        # Encrypt
        encrypted = packet_codec.encrypt(compressed)
        self.out_codec.iterator = packet_codec.iterator
        
        # No compression type byte for gen4
        return struct.pack('>H', len(encrypted)) + encrypted
        
    def recv_packet(self, data: bytes) -> Optional[bytes]:
        """Decrypt and decompress"""
        if not data:
            return None
            
        # Create codec for this packet
        packet_codec = RebornEncryption(self.encryption_key)
        packet_codec.iterator = self.in_codec.iterator
        packet_codec.limit_from_type(CompressionType.BZ2)
        
        # Decrypt
        decrypted = packet_codec.decrypt(data)
        self.in_codec.iterator = packet_codec.iterator
        
        # Decompress
        try:
            return bz2.decompress(decrypted)
        except:
            return None


class Gen5Codec(VersionCodec):
    """ENCRYPT_GEN_5: Partial encryption, dynamic compression (2.22+)"""
    
    def __init__(self, encryption_key: int = 0):
        super().__init__(encryption_key)
        self.in_codec = RebornEncryption(encryption_key)
        self.out_codec = RebornEncryption(encryption_key)
        
    def send_packet(self, data: bytes) -> bytes:
        """Apply dynamic compression and encrypt"""
        # Choose compression based on size
        if len(data) <= 55:
            compression_type = CompressionType.UNCOMPRESSED
            compressed_data = data
        elif len(data) > 0x2000:  # > 8KB
            compression_type = CompressionType.BZ2
            compressed_data = bz2.compress(data)
        else:
            compression_type = CompressionType.ZLIB
            compressed_data = zlib.compress(data)
            
        # Create codec for this packet
        packet_codec = RebornEncryption(self.encryption_key)
        packet_codec.iterator = self.out_codec.iterator
        packet_codec.limit_from_type(compression_type)
        
        # Encrypt
        encrypted = packet_codec.encrypt(compressed_data)
        self.out_codec.iterator = packet_codec.iterator
        
        # Build packet with compression type
        packet = bytes([compression_type]) + encrypted
        return struct.pack('>H', len(packet)) + packet
        
    def recv_packet(self, data: bytes) -> Optional[bytes]:
        """Decrypt and decompress based on type"""
        if not data or len(data) == 0:
            return None
            
        compression_type = data[0]
        encrypted_data = data[1:]
        
        # Validate compression type
        if compression_type not in [CompressionType.UNCOMPRESSED, 
                                   CompressionType.ZLIB, 
                                   CompressionType.BZ2]:
            return None
            
        # Create codec for this packet
        packet_codec = RebornEncryption(self.encryption_key)
        packet_codec.iterator = self.in_codec.iterator
        packet_codec.limit_from_type(compression_type)
        
        # Decrypt
        decrypted = packet_codec.decrypt(encrypted_data)
        self.in_codec.iterator = packet_codec.iterator
        
        # Decompress based on type
        try:
            if compression_type == CompressionType.ZLIB:
                return zlib.decompress(decrypted)
            elif compression_type == CompressionType.BZ2:
                return bz2.decompress(decrypted)
            elif compression_type == CompressionType.UNCOMPRESSED:
                return decrypted
        except:
            return None


def create_codec(encryption_type: EncryptionType, encryption_key: int = 0) -> VersionCodec:
    """Factory to create appropriate codec for encryption type"""
    if encryption_type == EncryptionType.ENCRYPT_GEN_1:
        return Gen1Codec(encryption_key)
    elif encryption_type == EncryptionType.ENCRYPT_GEN_2:
        return Gen2Codec(encryption_key)
    elif encryption_type == EncryptionType.ENCRYPT_GEN_3:
        return Gen3Codec(encryption_key)
    elif encryption_type == EncryptionType.ENCRYPT_GEN_4:
        return Gen4Codec(encryption_key)
    elif encryption_type == EncryptionType.ENCRYPT_GEN_5:
        return Gen5Codec(encryption_key)
    else:
        raise ValueError(f"Unknown encryption type: {encryption_type}")