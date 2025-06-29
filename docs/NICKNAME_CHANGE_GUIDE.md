# How to Change Player Nickname in OpenGraal

## Overview
To change a player's nickname after logging in, the client needs to send a `PLI_PLAYERPROPS` packet with the nickname property.

## Packet Structure

### Packet ID
- `PLI_PLAYERPROPS = 2` (from IEnums.h)

### Property ID for Nickname
- `PLPROP_NICKNAME = 0` (from TAccount.h)

### Packet Format
```
{PLI_PLAYERPROPS}{PLPROP_NICKNAME}{length}{nickname_string}
```

Where:
- `PLI_PLAYERPROPS` = 0x02 (1 byte)
- `PLPROP_NICKNAME` = 0x00 (1 byte)
- `length` = length of nickname string (1 byte, max 223)
- `nickname_string` = the actual nickname (variable length)

## Encoding Details

1. The nickname is limited to 223 characters maximum
2. The length is encoded as a single byte (GUCHAR)
3. The nickname can include a guild tag in parentheses, e.g., "PlayerName (GuildName)"
4. If the nickname starts with '*', it will be removed unless forced
5. If the nickname is empty after processing, it defaults to "unknown"

## Server Processing

When the server receives this packet:
1. It calls `msgPLI_PLAYERPROPS()` which forwards to `setProps()`
2. The nickname is processed in the `PLPROP_NICKNAME` case
3. Word filter is applied to check for inappropriate content
4. The nickname is set via `setNick()` function
5. The change is forwarded to other players if `PLSETPROPS_FORWARD` flag is set

## Attributes (ATTR1-ATTR30)

The server also supports 30 custom attributes that can be set via player properties:
- `PLPROP_GATTRIB1` through `PLPROP_GATTRIB30` (IDs 37-74)
- These are stored in `attrList[0]` through `attrList[29]`
- Each attribute follows the same format: `{property_id}{length}{value}`

These attributes can be used for custom player data like titles, clan names, or other game-specific information.

## Example Code (Client-side)

To send a nickname change packet:
```cpp
CString packet;
packet >> (char)PLI_PLAYERPROPS;
packet >> (char)PLPROP_NICKNAME;
packet >> (char)newNickname.length();
packet << newNickname;
sendPacket(packet);
```

## Notes
- The server validates nickname changes and may reject inappropriate names
- Guild tags in parentheses are parsed separately
- The nickname is broadcast to other players in the same level/area