#!/usr/bin/env python3
"""
Strongly-Typed Packet Enums
============================

This module provides strongly-typed packet enums similar to industry-standard C# patterns.
It maps the existing packet registry to clean, discoverable enum types.

Based on analysis of standard server-client communication enums.
"""

from enum import IntEnum
from typing import Dict, Optional


class IncomingPackets(IntEnum):
    """Server-to-Client packet types (strongly-typed enum)"""
    
    # Core game packets
    LEVEL_BOARD = 0
    LEVEL_LINK = 1
    BADDY_PROPS = 2
    NPC_PROPS = 3
    LEVEL_CHEST = 4
    LEVEL_SIGN = 5
    LEVEL_NAME = 6
    BOARD_MODIFY = 7
    OTHER_PLAYER_PROPS = 8
    PLAYER_PROPS = 9
    IS_LEADER = 10
    
    # Combat packets
    BOMB_ADD = 11
    BOMB_DEL = 12
    ARROW_ADD = 19
    FIRESPY = 20
    THROW_CARRIED = 21
    HURT_PLAYER = 40
    DEFAULT_WEAPON = 43
    EXPLOSION = 36
    
    # Communication packets
    TO_ALL = 13
    PRIVATE_MESSAGE = 37
    ADMIN_MESSAGE = 35
    SERVER_TEXT = 87  # From registry analysis
    
    # Movement packets
    PLAYER_WARP = 14
    WARP_FAILED = 15
    GMAP_WARP2 = 49
    
    # System packets
    DISCONNECT_MESSAGE = 16
    START_MESSAGE = 41
    NEW_WORLD_TIME = 42
    SIGNATURE = 25
    FLAG_SET = 28
    FLAG_DEL = 31
    PUSH_AWAY = 38
    LEVEL_MOD_TIME = 39
    
    # Item packets
    ITEM_ADD = 22
    ITEM_DEL = 23
    
    # NPC packets
    NPC_MOVED = 24
    NPC_ACTION = 26
    BADDY_HURT = 27
    NPC_DEL = 29
    NPC_WEAPON_ADD = 33
    NPC_WEAPON_DEL = 34
    
    # File handling packets
    FILE_SEND_FAILED = 30
    FILE_UPTODATE = 45
    BOARD_PACKET = 101  # From registry analysis
    RAW_DATA = 161  # From registry analysis
    
    # UI packets
    SHOW_IMG = 32
    
    # RC (Remote Control) packets
    RC_SERVERTEXT = 86
    RC_SERVERFLAGSGET = 61
    RC_PLAYERRIGHTSGET = 62
    RC_FILEBROWSER_DIR = 66
    RC_FILEBROWSER_MESSAGE = 67
    
    # Large file packets
    LARGE_FILE_START = 68
    LARGE_FILE_END = 69
    LARGE_FILE_SIZE = 82


class OutgoingPackets(IntEnum):
    """Client-to-Server packet types (strongly-typed enum)"""
    
    # Core packets
    LOGIN = 0
    PLAYER_PROPS = 1
    ADJACENT_LEVEL = 2
    
    # Movement packets
    PLAYER_MOVE = 10
    LEVEL_WARP = 11
    
    # Communication packets
    TO_ALL = 20
    PRIVATE_MESSAGE = 21
    
    # Combat packets
    SHOOT = 30
    SHOOT2 = 31
    BOMB_ADD = 32
    ARROW_ADD = 33
    WEAPON_ADD = 34
    
    # Item packets
    ITEM_TAKE = 40
    ITEM_DEL = 41
    OPEN_CHEST = 42
    
    # System packets
    WANT_FILE = 50
    SEND_TEXT = 51
    REQUEST_TEXT = 52
    FLAG_SET = 53
    FLAG_DEL = 54
    TRIGGER_ACTION = 55
    
    # NPC packets
    NPC_DEL = 60
    NPC_PROPS = 61


class PacketCategories:
    """Packet categories for organization and filtering"""
    
    CORE = [
        IncomingPackets.LEVEL_BOARD,
        IncomingPackets.LEVEL_LINK,
        IncomingPackets.LEVEL_NAME,
        IncomingPackets.LEVEL_CHEST,
        IncomingPackets.LEVEL_SIGN,
        IncomingPackets.PLAYER_PROPS,
        IncomingPackets.OTHER_PLAYER_PROPS,
        IncomingPackets.START_MESSAGE,
    ]
    
    MOVEMENT = [
        IncomingPackets.PLAYER_WARP,
        IncomingPackets.GMAP_WARP2,
        IncomingPackets.WARP_FAILED,
        OutgoingPackets.PLAYER_MOVE,
        OutgoingPackets.LEVEL_WARP,
    ]
    
    COMBAT = [
        IncomingPackets.BOMB_ADD,
        IncomingPackets.BOMB_DEL,
        IncomingPackets.ARROW_ADD,
        IncomingPackets.FIRESPY,
        IncomingPackets.HURT_PLAYER,
        IncomingPackets.EXPLOSION,
        OutgoingPackets.SHOOT,
        OutgoingPackets.SHOOT2,
        OutgoingPackets.BOMB_ADD,
    ]
    
    COMMUNICATION = [
        IncomingPackets.TO_ALL,
        IncomingPackets.PRIVATE_MESSAGE,
        IncomingPackets.SERVER_TEXT,
        OutgoingPackets.TO_ALL,
        OutgoingPackets.PRIVATE_MESSAGE,
    ]
    
    NPCS = [
        IncomingPackets.BADDY_PROPS,
        IncomingPackets.NPC_PROPS,
        IncomingPackets.NPC_MOVED,
        IncomingPackets.NPC_ACTION,
        IncomingPackets.NPC_DEL,
        OutgoingPackets.NPC_DEL,
        OutgoingPackets.NPC_PROPS,
    ]
    
    ITEMS = [
        IncomingPackets.ITEM_ADD,
        IncomingPackets.ITEM_DEL,
        OutgoingPackets.ITEM_TAKE,
        OutgoingPackets.ITEM_DEL,
        OutgoingPackets.OPEN_CHEST,
    ]
    
    SYSTEM = [
        IncomingPackets.DISCONNECT_MESSAGE,
        IncomingPackets.SIGNATURE,
        IncomingPackets.FLAG_SET,
        IncomingPackets.FLAG_DEL,
        IncomingPackets.NEW_WORLD_TIME,
        OutgoingPackets.FLAG_SET,
        OutgoingPackets.FLAG_DEL,
        OutgoingPackets.TRIGGER_ACTION,
    ]
    
    FILES = [
        IncomingPackets.FILE_SEND_FAILED,
        IncomingPackets.FILE_UPTODATE,
        IncomingPackets.BOARD_PACKET,
        IncomingPackets.RAW_DATA,
        IncomingPackets.LARGE_FILE_START,
        IncomingPackets.LARGE_FILE_END,
        OutgoingPackets.WANT_FILE,
    ]
    
    UI = [
        IncomingPackets.SHOW_IMG,
    ]


class PacketRegistry:
    """Helper class for packet type lookups and validation"""
    
    _incoming_map: Dict[int, IncomingPackets] = {}
    _outgoing_map: Dict[int, OutgoingPackets] = {}
    
    @classmethod
    def _initialize_maps(cls):
        """Initialize reverse lookup maps"""
        if not cls._incoming_map:
            cls._incoming_map = {packet.value: packet for packet in IncomingPackets}
        if not cls._outgoing_map:
            cls._outgoing_map = {packet.value: packet for packet in OutgoingPackets}
    
    @classmethod
    def get_incoming_packet(cls, packet_id: int) -> Optional[IncomingPackets]:
        """Get incoming packet enum by ID"""
        cls._initialize_maps()
        return cls._incoming_map.get(packet_id)
    
    @classmethod
    def get_outgoing_packet(cls, packet_id: int) -> Optional[OutgoingPackets]:
        """Get outgoing packet enum by ID"""
        cls._initialize_maps()
        return cls._outgoing_map.get(packet_id)
    
    @classmethod
    def is_valid_incoming(cls, packet_id: int) -> bool:
        """Check if packet ID is a valid incoming packet"""
        return cls.get_incoming_packet(packet_id) is not None
    
    @classmethod
    def is_valid_outgoing(cls, packet_id: int) -> bool:
        """Check if packet ID is a valid outgoing packet"""
        return cls.get_outgoing_packet(packet_id) is not None
    
    @classmethod
    def get_packet_category(cls, packet_id: int) -> Optional[str]:
        """Get the category name for a packet ID"""
        incoming_packet = cls.get_incoming_packet(packet_id)
        if incoming_packet:
            for category_name, packet_list in PacketCategories.__dict__.items():
                if not category_name.startswith('_') and isinstance(packet_list, list):
                    if incoming_packet in packet_list:
                        return category_name.lower()
        
        outgoing_packet = cls.get_outgoing_packet(packet_id)
        if outgoing_packet:
            for category_name, packet_list in PacketCategories.__dict__.items():
                if not category_name.startswith('_') and isinstance(packet_list, list):
                    if outgoing_packet in packet_list:
                        return category_name.lower()
        
        return None
    
    @classmethod
    def get_packets_by_category(cls, category: str) -> list:
        """Get all packets in a specific category"""
        category_attr = getattr(PacketCategories, category.upper(), None)
        return category_attr if category_attr else []


# Convenience exports for easy access
ServerToClient = IncomingPackets
ClientToServer = OutgoingPackets

__all__ = [
    'IncomingPackets',
    'OutgoingPackets', 
    'ServerToClient',
    'ClientToServer',
    'PacketCategories',
    'PacketRegistry'
]