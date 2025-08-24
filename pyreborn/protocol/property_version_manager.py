#!/usr/bin/env python3
"""
Property Version Manager - Handles version-specific property compatibility

This module manages which player properties can be sent based on the client version,
preventing "invalid packet" errors from servers that don't support certain properties
in older protocol versions.
"""

from typing import Set, Optional
from ..protocol.enums import PlayerProp
import logging


class PropertyVersionManager:
    """Manages property compatibility across different client versions"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Define minimum versions for specific properties
        # These are based on Reborn protocol history
        self.property_min_versions = {
            # GMAP properties were added in version 2.2
            PlayerProp.PLPROP_GMAPLEVELX: 2.2,
            PlayerProp.PLPROP_GMAPLEVELY: 2.2,
            
            # High-precision coordinates added in version 2.3
            PlayerProp.PLPROP_X2: 2.3,
            PlayerProp.PLPROP_Y2: 2.3,
            PlayerProp.PLPROP_Z2: 2.3,
            
            # Extended properties
            PlayerProp.PLPROP_OSTYPE: 2.19,
            PlayerProp.PLPROP_TEXTCODEPAGE: 2.19,
            PlayerProp.PLPROP_COMMUNITYNAME: 2.2,
            
            # String attributes were reorganized in v2.2
            PlayerProp.PLPROP_GATTRIB1: 2.0,
            PlayerProp.PLPROP_GATTRIB2: 2.0,
            PlayerProp.PLPROP_GATTRIB3: 2.0,
            PlayerProp.PLPROP_GATTRIB4: 2.0,
            PlayerProp.PLPROP_GATTRIB5: 2.0,
            
            # Extended attributes added later
            PlayerProp.PLPROP_GATTRIB6: 2.2,
            PlayerProp.PLPROP_GATTRIB7: 2.2,
            PlayerProp.PLPROP_GATTRIB8: 2.2,
            PlayerProp.PLPROP_GATTRIB9: 2.2,
            PlayerProp.PLPROP_GATTRIB10: 2.2,
            # ... up to GATTRIB30
        }
        
        # Properties that should NEVER be sent by clients
        # (server-only properties)
        self.server_only_properties = {
            PlayerProp.PLPROP_IPADDR,
            PlayerProp.PLPROP_ACCOUNTNAME,
            PlayerProp.PLPROP_ID,
            PlayerProp.PLPROP_UDPPORT,
        }
        
    def parse_version(self, version_str: str) -> float:
        """Parse version string to float for comparison
        
        Args:
            version_str: Version string like "2.1", "2.22", "6.037"
            
        Returns:
            Float representation for comparison
        """
        try:
            parts = version_str.split('.')
            if len(parts) == 2:
                major = int(parts[0])
                minor = int(parts[1])
                # Handle versions like 2.22 correctly (2.22, not 2.022)
                if minor < 10:
                    return float(f"{major}.{minor}")
                else:
                    # For 2.22, return 2.22 not 2.022
                    return major + (minor / 100.0)
            else:
                return float(version_str)
        except (ValueError, AttributeError):
            self.logger.warning(f"Could not parse version '{version_str}', assuming 2.1")
            return 2.1
            
    def is_property_supported(self, prop: PlayerProp, version_str: str) -> bool:
        """Check if a property is supported in the given client version
        
        Args:
            prop: The player property enum
            version_str: Client version string
            
        Returns:
            True if the property can be sent in this version
        """
        # Server-only properties are never supported for clients
        if prop in self.server_only_properties:
            return False
            
        # Check if property has a minimum version requirement
        if prop in self.property_min_versions:
            min_version = self.property_min_versions[prop]
            current_version = self.parse_version(version_str)
            
            # Special handling for version 3.x+ and 6.x
            # These newer versions support all properties
            major = int(version_str.split('.')[0])
            if major >= 3:
                return True
                
            return current_version >= min_version
            
        # If not in our list, assume it's a basic property supported in all versions
        return True
        
    def filter_properties(self, properties: Set[PlayerProp], version_str: str) -> Set[PlayerProp]:
        """Filter a set of properties to only those supported by the version
        
        Args:
            properties: Set of properties to filter
            version_str: Client version string
            
        Returns:
            Filtered set containing only supported properties
        """
        supported = set()
        
        for prop in properties:
            if self.is_property_supported(prop, version_str):
                supported.add(prop)
            else:
                self.logger.debug(
                    f"Filtering out {prop.name} - not supported in version {version_str}"
                )
                
        return supported
        
    def get_movement_properties(self, version_str: str, is_gmap: bool = False) -> Set[PlayerProp]:
        """Get the appropriate movement properties for a given version
        
        Args:
            version_str: Client version string
            is_gmap: Whether we're in GMAP mode
            
        Returns:
            Set of properties to send for movement
        """
        version = self.parse_version(version_str)
        major = int(version_str.split('.')[0])
        
        # Always send sprite/direction
        props = {PlayerProp.PLPROP_SPRITE}
        
        # IMPORTANT: In GMAP mode, we MUST use X2/Y2 (world coordinates)
        # regardless of version, because X/Y are local coordinates that
        # don't make sense across GMAP boundaries
        if is_gmap:
            # GMAP mode always uses world coordinates
            props.add(PlayerProp.PLPROP_X2)
            props.add(PlayerProp.PLPROP_Y2)
        elif version >= 2.3 or major >= 3:
            # Version 2.3+ or 3.x+ uses high-precision coordinates
            props.add(PlayerProp.PLPROP_X2)
            props.add(PlayerProp.PLPROP_Y2)
        else:
            # Older versions use standard coordinates (non-GMAP only)
            props.add(PlayerProp.PLPROP_X)
            props.add(PlayerProp.PLPROP_Y)
            
        # Only add GMAP properties if:
        # 1. We're in GMAP mode
        # 2. The version supports them (2.2+)
        if is_gmap and version >= 2.2:
            props.add(PlayerProp.PLPROP_GMAPLEVELX)
            props.add(PlayerProp.PLPROP_GMAPLEVELY)
            
        return props


# Singleton instance
_property_version_manager = PropertyVersionManager()


def get_property_manager() -> PropertyVersionManager:
    """Get the singleton property version manager"""
    return _property_version_manager