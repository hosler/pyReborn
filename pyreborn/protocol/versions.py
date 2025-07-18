"""
Client version definitions and protocol configurations for different Graal versions.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class EncryptionType(Enum):
    """Encryption types used by different client versions"""
    ENCRYPT_GEN_1 = "gen1"  # Uncompressed
    ENCRYPT_GEN_2 = "gen2"  # Compressed (old clients)
    ENCRYPT_GEN_3 = "gen3"  # Not commonly used
    ENCRYPT_GEN_4 = "gen4"  # Clients 2.19-2.21, 3-3.01
    ENCRYPT_GEN_5 = "gen5"  # Clients 2.22+, 5.x, 6.x


class ClientType(Enum):
    """Client connection types"""
    TYPE_CLIENT = 0   # PLTYPE_CLIENT - older clients (1 << 0)
    TYPE_CLIENT2 = 4  # PLTYPE_CLIENT2 - 2.19-2.21, 3-3.01 (1 << 4)
    TYPE_CLIENT3 = 5  # PLTYPE_CLIENT3 - 2.22+, 5.x, 6.x (1 << 5)
    TYPE_RC = 1       # PLTYPE_RC - Remote Control (1 << 1)
    TYPE_RC2 = 6      # PLTYPE_RC2 - New RC (1 << 6)
    TYPE_NPCSERVER = 2  # PLTYPE_NPCSERVER (1 << 2)
    TYPE_NC = 3       # PLTYPE_NC (1 << 3)


@dataclass
class VersionConfig:
    """Configuration for a specific client version"""
    # Display name
    name: str
    
    # Version ID (internal enum value)
    version_id: int
    
    # Protocol version string sent to server
    protocol_string: str
    
    # Build string (optional, for some versions)
    build_string: Optional[str]
    
    # Client type (determines encryption and protocol)
    client_type: ClientType
    
    # Encryption type
    encryption: EncryptionType
    
    # Whether this version sends build string
    sends_build: bool = False
    
    # Protocol quirks/features
    supports_utf8: bool = False
    supports_big_tiles: bool = False
    supports_v6_features: bool = False


# Version configurations based on GServer source
VERSIONS = {
    "1.39": VersionConfig(
        name="1.39",
        version_id=0,
        protocol_string="",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT,
        encryption=EncryptionType.ENCRYPT_GEN_2,
        sends_build=False
    ),
    
    "1.41": VersionConfig(
        name="1.41r1",
        version_id=1,
        protocol_string="GNW13110",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT,
        encryption=EncryptionType.ENCRYPT_GEN_2,
        sends_build=False
    ),
    
    "2.17": VersionConfig(
        name="2.17",
        version_id=7,
        protocol_string="GNW22122",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT,
        encryption=EncryptionType.ENCRYPT_GEN_3,
        sends_build=False
    ),
    
    "2.19": VersionConfig(
        name="2.19",
        version_id=8,
        protocol_string="GNW01940",
        build_string="177",
        client_type=ClientType.TYPE_CLIENT2,
        encryption=EncryptionType.ENCRYPT_GEN_4,
        sends_build=True
    ),
    
    "2.21": VersionConfig(
        name="2.21",
        version_id=9,
        protocol_string="GNW01113",
        build_string="306",
        client_type=ClientType.TYPE_CLIENT2,
        encryption=EncryptionType.ENCRYPT_GEN_4,
        sends_build=True
    ),
    
    "2.22": VersionConfig(
        name="2.22",
        version_id=10,
        protocol_string="GNW03014",
        build_string="356",
        client_type=ClientType.TYPE_CLIENT3,
        encryption=EncryptionType.ENCRYPT_GEN_5,
        sends_build=True
    ),
    
    "3.0": VersionConfig(
        name="3.0",
        version_id=11,
        protocol_string="G3D16053",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT2,
        encryption=EncryptionType.ENCRYPT_GEN_4,
        sends_build=False
    ),
    
    "3.041": VersionConfig(
        name="3.041",
        version_id=12,
        protocol_string="G3D03014",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT2,
        encryption=EncryptionType.ENCRYPT_GEN_4,
        sends_build=False
    ),
    
    "5.07": VersionConfig(
        name="5.07",
        version_id=13,
        protocol_string="G3D22067",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT3,
        encryption=EncryptionType.ENCRYPT_GEN_5,
        sends_build=False,
        supports_utf8=True
    ),
    
    "5.12": VersionConfig(
        name="5.12",
        version_id=14,
        protocol_string="G3D14097",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT3,
        encryption=EncryptionType.ENCRYPT_GEN_5,
        sends_build=False,
        supports_utf8=True
    ),
    
    "5.31": VersionConfig(
        name="5.31",
        version_id=15,
        protocol_string="G3D26090",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT3,
        encryption=EncryptionType.ENCRYPT_GEN_5,
        sends_build=False,
        supports_utf8=True,
        supports_big_tiles=True
    ),
    
    "6.015": VersionConfig(
        name="6.015",
        version_id=16,
        protocol_string="G3D3007A",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT3,
        encryption=EncryptionType.ENCRYPT_GEN_5,
        sends_build=False,
        supports_utf8=True,
        supports_big_tiles=True,
        supports_v6_features=True
    ),
    
    "6.034": VersionConfig(
        name="6.034",
        version_id=17,
        protocol_string="G3D2505C",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT3,
        encryption=EncryptionType.ENCRYPT_GEN_5,
        sends_build=False,
        supports_utf8=True,
        supports_big_tiles=True,
        supports_v6_features=True
    ),
    
    "6.037": VersionConfig(
        name="6.037",
        version_id=18,
        protocol_string="G3D0311C",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT3,
        encryption=EncryptionType.ENCRYPT_GEN_5,
        sends_build=False,
        supports_utf8=True,
        supports_big_tiles=True,
        supports_v6_features=True
    ),
    
    "6.037_linux": VersionConfig(
        name="6.037 (Linux)",
        version_id=19,
        protocol_string="G3D0511C",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT3,
        encryption=EncryptionType.ENCRYPT_GEN_5,
        sends_build=False,
        supports_utf8=True,
        supports_big_tiles=True,
        supports_v6_features=True
    )
}


def get_version_config(version: str) -> Optional[VersionConfig]:
    """Get version configuration by name"""
    return VERSIONS.get(version)


def get_default_version() -> VersionConfig:
    """Get the default version configuration"""
    return VERSIONS["2.22"]


def get_supported_versions() -> list[str]:
    """Get list of supported version names"""
    return list(VERSIONS.keys())