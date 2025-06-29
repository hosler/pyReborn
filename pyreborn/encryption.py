"""
Graal encryption implementation (ENCRYPT_GEN_5)
"""

import struct

class CompressionType:
    UNCOMPRESSED = 0x02
    ZLIB = 0x04
    BZ2 = 0x06

class GraalEncryption:
    """ENCRYPT_GEN_5 implementation (fixed from working client)"""
    
    def __init__(self, key: int = 0):
        self.key = key
        self.iterator = 0x4A80B38
        self.limit = -1
        self.multiplier = 0x8088405
        self.bytes_encrypted = 0  # Track total bytes encrypted
        
    def reset(self, key: int):
        """Reset encryption with new key"""
        self.key = key
        self.iterator = 0x4A80B38
        self.limit = -1
        
    def limit_from_type(self, compression_type: int):
        """Set limit based on compression type"""
        if compression_type == CompressionType.UNCOMPRESSED:
            self.limit = 12
        elif compression_type in (CompressionType.ZLIB, CompressionType.BZ2):
            self.limit = 4
            
    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data - only encrypts first X bytes based on limit"""
        result = bytearray(data)
        
        # Determine how many bytes to encrypt
        if self.limit < 0:
            # No limit, encrypt everything
            bytes_to_encrypt = len(data)
        elif self.limit == 0:
            # Limit reached, don't encrypt anything
            return bytes(result)
        else:
            # Encrypt up to limit * 4 bytes
            bytes_to_encrypt = min(len(data), self.limit * 4)
        
        for i in range(bytes_to_encrypt):
            if i % 4 == 0:
                if self.limit == 0:
                    break  # Stop encrypting
                    
                # Update iterator
                self.iterator = (self.iterator * self.multiplier + self.key) & 0xFFFFFFFF
                
                # Decrement limit if it's positive
                if self.limit > 0:
                    self.limit -= 1
                    
            iterator_bytes = struct.pack('<I', self.iterator)
            result[i] ^= iterator_bytes[i % 4]
            
        self.bytes_encrypted += bytes_to_encrypt
        return bytes(result)
        
    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data (same as encrypt for XOR)"""
        return self.encrypt(data)