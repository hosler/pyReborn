"""Server information data structures."""

from dataclasses import dataclass


@dataclass
class ServerInfo:
    """Information about a game server from the listserver."""
    
    name: str
    type: str  # Server type: "", "P", "3", "H", "U"
    language: str
    description: str
    url: str
    version: str
    players: int
    ip: str
    port: int
    
    @property
    def address(self) -> str:
        """Get the full server address (ip:port)."""
        return f"{self.ip}:{self.port}"
    
    @property
    def type_name(self) -> str:
        """Get human-readable server type name."""
        type_map = {
            "": "Classic",
            "P": "Gold",
            "3": "3D", 
            "H": "Bronze",
            "U": "Hidden"
        }
        return type_map.get(self.type, "Unknown")
    
    def __str__(self) -> str:
        """String representation of server."""
        return f"{self.name} ({self.players} players) - {self.address}"