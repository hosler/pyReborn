"""
Login packet - Client to server authentication

This is a special client-to-server packet used only during initial connection.
It contains authentication credentials and version information.
"""

import logging

logger = logging.getLogger(__name__)


class LoginPacket:
    """Login packet with configurable version support"""
    
    def __init__(self, account: str, password: str, encryption_key: int, version_config=None):
        self.account = account
        self.password = password
        self.encryption_key = encryption_key
        self.version_config = version_config
    
    def to_bytes(self) -> bytes:
        """Create login packet based on version configuration"""
        from ...connection.versions import ClientType, get_default_version
        
        # Use provided config or default
        config = self.version_config or get_default_version()
        
        logger.debug(f"LoginPacket: account={self.account}, enc_key={self.encryption_key}")
        
        packet = bytearray()
        
        # Client type byte
        packet.append((config.client_type.value + 32) & 0xFF)
        
        # Encryption key
        packet.append((self.encryption_key + 32) & 0xFF)
        
        # Protocol version string (must be exactly 8 bytes)
        version_bytes = config.protocol_string.encode('ascii')
        if len(version_bytes) != 8:
            raise ValueError(f"Version string must be 8 bytes, got {len(version_bytes)}: {config.protocol_string}")
        packet.extend(version_bytes)
        
        # Account and password
        packet.append((len(self.account) + 32) & 0xFF)
        packet.extend(self.account.encode('ascii'))
        packet.append((len(self.password) + 32) & 0xFF)
        packet.extend(self.password.encode('ascii'))
        
        # Build string (if version sends it)
        if config.sends_build and config.build_string:
            packet.append((len(config.build_string) + 32) & 0xFF)
            packet.extend(config.build_string.encode('ascii'))
        
        # Client info/identity string
        # Format: {platform},{mobile_id},{harddisk_md5},{network_md5},{os_info},{android_id}
        if config.version_id >= 19:  # Linux 6.037
            packet.extend(b'linux,,,,,PyReborn')
        else:
            packet.extend(b'PC,,,,,PyReborn')
        
        # Debug: Log what we're sending
        logger.debug(f"Login packet for version {config.name}:")
        logger.debug(f"  Client type: {config.client_type.value} (+32 = {config.client_type.value + 32})")
        logger.debug(f"  Version string: {config.protocol_string} (hex: {version_bytes.hex()})")
        
        try:
            result = bytes(packet)
            logger.debug(f"  Full packet ({len(result)} bytes): {result[:30].hex()}...")
            return result
        except ValueError as e:
            logger.error(f"Failed to create login packet: {e}")
            logger.error(f"Packet values: {list(packet)}")
            raise