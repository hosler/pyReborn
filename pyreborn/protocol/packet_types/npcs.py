"""
NPC-related packet implementations
"""

from typing import Dict, Any, Optional
from ..packets import RebornPacket, PacketBuilder, PacketReader
from ..enums import PlayerToServer, ServerToPlayer, NPCProp


class NPCPropsPacket(RebornPacket):
    """Client sets NPC properties"""
    
    def __init__(self, npc_id: int, props: Dict[NPCProp, Any]):
        super().__init__(PlayerToServer.PLI_NPCPROPS)
        self.npc_id = npc_id
        self.props = props
        
    def to_bytes(self) -> bytes:
        """Encode packet: {34}{INT npcid}{props...}"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_int(self.npc_id)
        
        # Add properties
        for prop, value in self.props.items():
            builder.add_byte(prop.value)
            
            # Encode based on property type
            if prop in [NPCProp.IMAGE, NPCProp.SCRIPT, NPCProp.NICK]:
                builder.add_gstring(str(value))
            elif prop in [NPCProp.SAVE0, NPCProp.SAVE1, NPCProp.SAVE2, NPCProp.SAVE3, NPCProp.SAVE4,
                         NPCProp.SAVE5, NPCProp.SAVE6, NPCProp.SAVE7, NPCProp.SAVE8, NPCProp.SAVE9]:
                builder.add_gstring(str(value))
            elif prop == NPCProp.VISFLAGS:
                builder.add_byte(int(value))
            else:
                # Generic string encoding for GATTRIB1-30
                builder.add_gstring(str(value))
                
        return builder.build()


class PutNPCPacket(RebornPacket):
    """Client creates/places an NPC"""
    
    def __init__(self, x: float, y: float, image: str, script: str = ""):
        super().__init__(PlayerToServer.PLI_PUTNPC)
        self.x = x
        self.y = y  
        self.image = image
        self.script = script
        
    def to_bytes(self) -> bytes:
        """Encode packet: {35}{CHAR x}{CHAR y}{STRING image}{STRING script}"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_byte(int(self.x))
        builder.add_byte(int(self.y))
        builder.add_gstring(self.image)
        builder.add_gstring(self.script)
        return builder.build()


class NPCDeletePacket(RebornPacket):
    """Client deletes an NPC"""
    
    def __init__(self, npc_id: int):
        super().__init__(PlayerToServer.PLI_NPCDELETE)
        self.npc_id = npc_id
        
    def to_bytes(self) -> bytes:
        """Encode packet: {37}{INT npcid}"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_int(self.npc_id)
        return builder.build()


class TriggerActionPacket(RebornPacket):
    """Client triggers an action"""
    
    def __init__(self, action: str, params: str = "", x: Optional[float] = None, y: Optional[float] = None):
        super().__init__(PlayerToServer.PLI_TRIGGERACTION)
        self.action = action
        self.params = params
        self.x = x
        self.y = y
        
    def to_bytes(self) -> bytes:
        """Encode packet: {30}{STRING action},{STRING params}[,{FLOAT x},{FLOAT y}]"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        
        # Build action string
        action_str = self.action
        if self.params:
            action_str += "," + self.params
        if self.x is not None and self.y is not None:
            action_str += f",{self.x},{self.y}"
            
        builder.add_gstring(action_str)
        return builder.build()


# Server packets
class ServerNPCPropsPacket:
    """Server updates NPC properties"""
    
    def __init__(self):
        self.npc_id: int = 0
        self.props: Dict[NPCProp, Any] = {}
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {38}{INT npcid}{props...}"""
        packet = cls()
        packet.npc_id = reader.read_int()
        packet.props = {}
        
        # Read properties until end of packet
        while reader.pos < packet_size:
            prop_id = reader.read_byte()
            try:
                prop = NPCProp(prop_id)
                
                # Read value based on property type
                if prop in [NPCProp.IMAGE, NPCProp.SCRIPT, NPCProp.NICK]:
                    value = reader.read_gstring()
                elif prop in [NPCProp.SAVE0, NPCProp.SAVE1, NPCProp.SAVE2, NPCProp.SAVE3, NPCProp.SAVE4,
                             NPCProp.SAVE5, NPCProp.SAVE6, NPCProp.SAVE7, NPCProp.SAVE8, NPCProp.SAVE9]:
                    value = reader.read_gstring()
                elif prop == NPCProp.VISFLAGS:
                    value = reader.read_byte()
                else:
                    # Generic string for GATTRIB1-30
                    value = reader.read_gstring()
                    
                packet.props[prop] = value
            except ValueError:
                # Unknown property, skip
                break
                
        return packet


class ServerNPCDeletePacket:
    """Server notifies of NPC deletion"""
    
    def __init__(self):
        self.npc_id: int = 0
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {41}{INT npcid}"""
        packet = cls()
        packet.npc_id = reader.read_int()
        return packet


class ServerNPCDelete2Packet:
    """Server notifies of NPC deletion (alternate)"""
    
    def __init__(self):
        self.level: str = ""
        self.npc_id: int = 0
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {112}{STRING level}{INT npcid}"""
        packet = cls()
        packet.level = reader.read_gstring()
        packet.npc_id = reader.read_int()
        return packet


class ServerNPCActionPacket:
    """Server notifies of NPC action"""
    
    def __init__(self):
        self.npc_id: int = 0
        self.action: str = ""
        self.params: str = ""
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {43}{INT npcid}{STRING action}[,{STRING params}]"""
        packet = cls()
        packet.npc_id = reader.read_int()
        
        # Parse action string
        action_data = reader.read_gstring()
        parts = action_data.split(",", 1)
        packet.action = parts[0]
        packet.params = parts[1] if len(parts) > 1 else ""
        
        return packet


class ServerNPCMovedPacket:
    """Server notifies that NPC moved"""
    
    def __init__(self):
        self.npc_id: int = 0
        self.x: float = 0
        self.y: float = 0
        self.x2: Optional[float] = None
        self.y2: Optional[float] = None
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {49}{INT npcid}{CHAR x}{CHAR y}[{SHORT x2}{SHORT y2}]"""
        packet = cls()
        packet.npc_id = reader.read_int()
        packet.x = reader.read_byte()
        packet.y = reader.read_byte()
        
        # Check for high precision coordinates
        if reader.pos + 4 <= packet_size:
            packet.x2 = reader.read_short() / 16.0
            packet.y2 = reader.read_short() / 16.0
            
        return packet


class ServerTriggerActionPacket:
    """Server sends trigger action response"""
    
    def __init__(self):
        self.action: str = ""
        self.params: str = ""
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {157}{STRING action}[,{STRING params}]"""
        packet = cls()
        
        # Parse action string
        action_data = reader.read_gstring()
        parts = action_data.split(",", 1)
        packet.action = parts[0]
        packet.params = parts[1] if len(parts) > 1 else ""
        
        return packet