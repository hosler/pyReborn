"""
Simple Version Manager - Replaces complex VersionManager
"""

from .versions import get_version_config

class SimpleVersionManager:
    """Simplified version manager with just essential functionality"""
    
    def __init__(self, version: str):
        self.version = version
        self.config = get_version_config(version)
    
    def create_login_packet(self, account: str, password: str, encryption_key: int) -> bytes:
        """Create login packet for the configured version"""
        client_type_value = 1 << self.config.client_type.value
        
        if self.config.sends_build:
            packet = f"ADDSIGN {client_type_value}|{account}|{password}|{self.config.build_string}|{self.config.protocol_string}|{encryption_key}|0|\n"
        else:
            packet = f"ADDSIGN {client_type_value}|{account}|{password}|{self.config.protocol_string}|{encryption_key}|0|\n"
            
        return packet.encode('ascii')