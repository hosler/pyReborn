"""
Protocol packet implementations
"""

# Import new packet modules that exist
try:
    from .items import *
except ImportError:
    pass

try:
    from .combat import *
except ImportError:
    pass

try:
    from .npcs import *
except ImportError:
    pass

# Export packet classes that are available
__all__ = []

# Add available item packets
try:
    from .items import (
        ItemAddPacket, ItemDeletePacket, ItemTakePacket,
        OpenChestPacket, ThrowCarriedPacket,
        ServerItemAddPacket, ServerItemDeletePacket, ServerThrowCarriedPacket
    )
    __all__.extend([
        'ItemAddPacket', 'ItemDeletePacket', 'ItemTakePacket',
        'OpenChestPacket', 'ThrowCarriedPacket',
        'ServerItemAddPacket', 'ServerItemDeletePacket', 'ServerThrowCarriedPacket'
    ])
except ImportError:
    pass

# Add available combat packets
try:
    from .combat import (
        HurtPlayerPacket, HitObjectsPacket, ExplosionPacket, BaddyHurtPacket,
        ServerHurtPlayerPacket, ServerExplosionPacket, ServerHitObjectsPacket,
        ServerPushAwayPacket
    )
    __all__.extend([
        'HurtPlayerPacket', 'HitObjectsPacket', 'ExplosionPacket', 'BaddyHurtPacket',
        'ServerHurtPlayerPacket', 'ServerExplosionPacket', 'ServerHitObjectsPacket',
        'ServerPushAwayPacket'
    ])
except ImportError:
    pass

# Add available NPC packets
try:
    from .npcs import (
        NPCPropsPacket, PutNPCPacket, NPCDeletePacket,
        ServerNPCPropsPacket, ServerNPCDeletePacket, ServerNPCDelete2Packet,
        ServerNPCActionPacket, ServerNPCMovedPacket,
        TriggerActionPacket, ServerTriggerActionPacket
    )
    __all__.extend([
        'NPCPropsPacket', 'PutNPCPacket', 'NPCDeletePacket',
        'ServerNPCPropsPacket', 'ServerNPCDeletePacket', 'ServerNPCDelete2Packet',
        'ServerNPCActionPacket', 'ServerNPCMovedPacket',
        'TriggerActionPacket', 'ServerTriggerActionPacket'
    ])
except ImportError:
    pass