#!/usr/bin/env python3
"""
Compression utilities for Reborn protocol

Handles zlib compression/decompression for file transfers and other data.
"""

import zlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def compress_data(data: bytes, level: int = 6) -> bytes:
    """Compress data using zlib
    
    Args:
        data: Raw data to compress
        level: Compression level (1-9, default 6)
        
    Returns:
        Compressed data
    """
    try:
        compressed = zlib.compress(data, level)
        logger.debug(f"Compressed {len(data)} bytes -> {len(compressed)} bytes ({len(compressed)/len(data)*100:.1f}%)")
        return compressed
    except Exception as e:
        logger.error(f"Compression failed: {e}")
        return data  # Return original data on failure


def decompress_data(data: bytes, max_size: int = 10 * 1024 * 1024) -> Optional[bytes]:
    """Decompress zlib-compressed data
    
    Args:
        data: Compressed data
        max_size: Maximum allowed decompressed size (safety limit)
        
    Returns:
        Decompressed data or None on failure
    """
    try:
        # Create decompressor with size limit
        decompressor = zlib.decompressobj()
        
        # Decompress in chunks to avoid memory issues
        result = b''
        chunk_size = 8192
        
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            try:
                decompressed_chunk = decompressor.decompress(chunk)
                result += decompressed_chunk
                
                # Check size limit
                if len(result) > max_size:
                    logger.error(f"Decompressed data exceeds size limit: {len(result)} > {max_size}")
                    return None
                    
            except zlib.error as e:
                logger.error(f"Zlib decompression error at chunk {i//chunk_size}: {e}")
                return None
        
        # Finalize decompression
        try:
            result += decompressor.flush()
        except zlib.error as e:
            logger.error(f"Zlib finalization error: {e}")
            return None
            
        logger.debug(f"Decompressed {len(data)} bytes -> {len(result)} bytes")
        return result
        
    except Exception as e:
        logger.error(f"Decompression failed: {e}")
        return None


def is_compressed(data: bytes) -> bool:
    """Check if data appears to be zlib compressed
    
    Args:
        data: Data to check
        
    Returns:
        True if data appears to be zlib compressed
    """
    if len(data) < 2:
        return False
        
    # Check zlib header
    # zlib header is 2 bytes: CMF (Compression Method and Flags) + FLG (Flags)
    # CMF lower 4 bits should be 8 (deflate), upper 4 bits are window size
    # Common zlib headers: 0x78 0x9C, 0x78 0xDA, 0x78 0x01, etc.
    cmf = data[0]
    flg = data[1]
    
    # Check if it's a valid zlib header
    if (cmf & 0x0F) == 0x08:  # Deflate compression method
        # Check header checksum
        header_check = (cmf * 256 + flg) % 31
        if header_check == 0:
            return True
    
    return False


def safe_decompress(data: bytes) -> bytes:
    """Safely decompress data, returning original if not compressed
    
    Args:
        data: Data that may or may not be compressed
        
    Returns:
        Decompressed data if it was compressed, otherwise original data
    """
    if is_compressed(data):
        decompressed = decompress_data(data)
        if decompressed is not None:
            return decompressed
        else:
            logger.warning("Failed to decompress data that appeared to be compressed")
            return data
    else:
        return data


def compress_if_beneficial(data: bytes, min_ratio: float = 0.9) -> bytes:
    """Compress data only if it provides good compression ratio
    
    Args:
        data: Data to potentially compress
        min_ratio: Only compress if compressed size / original size < min_ratio
        
    Returns:
        Compressed data if beneficial, otherwise original data
    """
    if len(data) < 100:  # Don't compress very small data
        return data
        
    compressed = compress_data(data)
    ratio = len(compressed) / len(data)
    
    if ratio < min_ratio:
        logger.debug(f"Compression beneficial: {ratio:.2f} ratio")
        return compressed
    else:
        logger.debug(f"Compression not beneficial: {ratio:.2f} ratio")
        return data