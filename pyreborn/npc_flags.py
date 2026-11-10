"""NPC BLOCKFLAGS bits (NPCPROP 14) shared by the wire parser and GS1.

The byte is one property on the wire: bit 0 no-block, bit 1 can-be-carried,
bit 2 can-be-pulled, bit 3 can-be-pushed (GServer-v2 NPCBlockFlags,
server/include/object/NPC.h:170-176). The reference client stores all four from
one `0x0e` property and its GS1 commands write the single bits back
(Preagonal/FourPlay/quattroplay/src/TServerNPC.cpp:1118-1127,
TServerNPCProperties.cpp:373-378).

The reference client never READS the carry/pull/push bits: its player lifts
only tile patterns and bombs (TPlayer::liftObjects, TPlayer.cpp:1926-2019), and
push/pull are `triggeraction` probes (TPlayer::moveStones/pullStones,
TPlayer.cpp:5811-5880) that reach an NPC by position alone. The bits are state a
script or server can read back, so they live on the NPC dict under the same
`blockflags` key the wire parser fills.
"""

NOBLOCK = 0x01
CAN_BE_CARRIED = 0x02
CAN_BE_PULLED = 0x04
CAN_BE_PUSHED = 0x08


def blockflags(npc) -> int:
    try:
        return int(npc.get('blockflags', 0) or 0) & 0xFF
    except (TypeError, ValueError):
        return 0


def set_flag(npc, bit: int, on: bool) -> None:
    flags = blockflags(npc)
    npc['blockflags'] = (flags | bit) if on else (flags & ~bit)


def can_be_carried(npc) -> bool:
    return bool(blockflags(npc) & CAN_BE_CARRIED)


def can_be_pulled(npc) -> bool:
    return bool(blockflags(npc) & CAN_BE_PULLED)


def can_be_pushed(npc) -> bool:
    return bool(blockflags(npc) & CAN_BE_PUSHED)
