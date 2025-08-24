"""
Version Manager - Consolidated version and codec handling

This module provides a unified interface for managing protocol versions,
codecs, and version-specific behavior.
"""

import logging
from typing import Optional, Dict, Any

from .versions import get_version_config, get_default_version, ClientType
from .version_codecs import create_codec

logger = logging.getLogger(__name__)


class VersionManager:
    """Manages protocol versions and codecs"""
    
    def __init__(self, version: str = "6.037"):
        self.version = version
        self.config = get_version_config(version) or get_default_version()
        self.codec = create_codec(self.config)
        
    def get_config(self):
        """Get the current version configuration"""
        return self.config
    
    def get_codec(self):
        """Get the version codec"""
        return self.codec
    
    def create_login_packet(self, account: str, password: str, encryption_key: int) -> bytes:
        """Create version-appropriate login packet"""
        # Use the proper LoginPacket class
        from ..packets.system.login import LoginPacket
        
        login_packet = LoginPacket(
            account=account,
            password=password,
            encryption_key=encryption_key,
            version_config=self.config
        )
        
        return login_packet.to_bytes()
    
    def supports_feature(self, feature: str) -> bool:
        """Check if current version supports a feature"""
        feature_map = {
            'build_string': self.config.sends_build,
            'extended_client_info': self.config.version_id >= 19,
            'new_player_props': self.config.version_id >= 20,
        }
        return feature_map.get(feature, False)