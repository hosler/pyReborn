# PyReborn Packet Documentation
*Generated on 2025-08-08 12:43:34*

## Statistics

- **Total Packets**: 115
- **Categories**: 8
- **Client Packets**: 113
- **RC Packets**: 2

## Packet Categories

### [combat](categories/combat.md)
*3 packets*

- [PLO_EXPLOSION](packets/PLO_EXPLOSION.md) (ID: 36)
- [PLO_RC_ADMINMESSAGE](packets/PLO_RC_ADMINMESSAGE.md) (ID: 35)
- [PLO_HURTPLAYER](packets/PLO_HURTPLAYER.md) (ID: 40)

### [core](categories/core.md)
*21 packets*

- [PLO_PLAYERWARP](packets/PLO_PLAYERWARP.md) (ID: 14)
- [PLO_BADDYPROPS](packets/PLO_BADDYPROPS.md) (ID: 2)
- [PLO_NPCPROPS](packets/PLO_NPCPROPS.md) (ID: 3)
- [PLO_LEVELSIGN](packets/PLO_LEVELSIGN.md) (ID: 5)
- [PLO_ISLEADER](packets/PLO_ISLEADER.md) (ID: 10)
- *...and 16 more*

### [files](categories/files.md)
*6 packets*

- [PLO_LARGEFILESTART](packets/PLO_LARGEFILESTART.md) (ID: 68)
- [PLO_FILE](packets/PLO_FILE.md) (ID: 102)
- [PLO_LARGEFILESIZE](packets/PLO_LARGEFILESIZE.md) (ID: 84)
- [PLO_RAWDATA](packets/PLO_RAWDATA.md) (ID: 100)
- [PLO_LARGEFILEEND](packets/PLO_LARGEFILEEND.md) (ID: 69)
- *...and 1 more*

### [movement](categories/movement.md)
*1 packets*

- [PLO_GMAPWARP2](packets/PLO_GMAPWARP2.md) (ID: 49)

### [npcs](categories/npcs.md)
*3 packets*

- [PLO_NPCWEAPONDEL](packets/PLO_NPCWEAPONDEL.md) (ID: 34)
- [PLO_NPCMOVED](packets/PLO_NPCMOVED.md) (ID: 24)
- [PLO_NPCWEAPONADD](packets/PLO_NPCWEAPONADD.md) (ID: 33)

### [system](categories/system.md)
*8 packets*

- [PLO_DELPLAYER](packets/PLO_DELPLAYER.md) (ID: 56)
- [PLO_STARTMESSAGE](packets/PLO_STARTMESSAGE.md) (ID: 41)
- [PLO_SERVERTEXT](packets/PLO_SERVERTEXT.md) (ID: 82)
- [PLO_ADMINMESSAGE](packets/PLO_ADMINMESSAGE.md) (ID: 57)
- [PLO_PLAYERBAN](packets/PLO_PLAYERBAN.md) (ID: 58)
- *...and 3 more*

### [ui](categories/ui.md)
*16 packets*

- [PLO_MOVE2](packets/PLO_MOVE2.md) (ID: 189)
- [PLO_CLEARWEAPONS](packets/PLO_CLEARWEAPONS.md) (ID: 194)
- [PLO_SHOOT2](packets/PLO_SHOOT2.md) (ID: 191)
- [PLO_BIGMAP](packets/PLO_BIGMAP.md) (ID: 171)
- [PLO_GHOSTMODE](packets/PLO_GHOSTMODE.md) (ID: 170)
- *...and 11 more*

### [unknown](categories/unknown.md)
*57 packets*

- [PLO_PLAYERMOVED](packets/PLO_PLAYERMOVED.md) (ID: 165)
- [PLO_NPCACTION](packets/PLO_NPCACTION.md) (ID: 26)
- [PLO_NPCDEL](packets/PLO_NPCDEL.md) (ID: 29)
- [PLO_HIDENPCS](packets/PLO_HIDENPCS.md) (ID: 151)
- [PLO_NPCDEL2](packets/PLO_NPCDEL2.md) (ID: 150)
- *...and 52 more*

## Protocol Coverage

| Range | Description | Implemented | Total | Coverage |
|:------|:------------|------------:|------:|---------:|
| 0-50 | Core Packets | 4 | 50 | 8.0% |
| 51-100 | System Packets | 2 | 33 | 6.1% |
| 101-150 | File/Data Packets | 1 | 9 | 11.1% |
| 151-200 | Extended Packets | 5 | 23 | 21.7% |
