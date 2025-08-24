"""Server List Protocol Enumerations

This module contains the enum definitions for the Reborn server list protocol.
"""

from enum import IntEnum, auto


class ServerListClientPacket(IntEnum):
    """Client to Server List packets (PLI - Player List Input)"""
    PLI_V1VER = 0  # Version 1 client
    PLI_SERVERLIST = 1  # Request server list with auth
    PLI_LISTSERVERRC = 2  # Remote control client (not used)
    PLI_LISTSVRPLYRCOUNT = 3  # Request player count (not used)
    PLI_V2VER = 4  # Version 2 client
    PLI_V2SERVERLISTRC = 5  # Version 2 RC client
    PLI_V2ENCRYPTKEYCL = 7  # Version 2+ encrypted client
    PLI_GRSECURELOGIN = 223  # Secure login request


class ServerListServerPacket(IntEnum):
    """Server List to Client packets (PLO - Player List Output)"""
    PLO_SVRLIST = 0  # Server list data
    PLO_ADDSVR = 1  # Add server (deprecated)
    PLO_STATUS = 2  # Status message
    PLO_SITEURL = 3  # Website URL
    PLO_ERROR = 4  # Error message
    PLO_UPGURL = 5  # Upgrade/donate URL
    PLO_DELSERVER = 6  # Delete server (deprecated)
    PLO_UPDSERVER = 7  # Update server (deprecated)
    PLO_SVRLISTRC = 8  # Server list for RC (not used)