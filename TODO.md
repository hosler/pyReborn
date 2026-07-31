# PyReborn TODO

Most of the items this file once tracked are **done**. That covers other-player
gani/sword/shield rendering, sword hit detection, damage/hurt/death,
bombs/explosions, arrows, NPC movement and animation, sign reading with dialogue
boxes, trigger actions, audio, the minimap, weapon switching, animated tiles,
water and lava, item pickup with chests and inventory, level links and warping,
the config file, and the unit tests. Each one was checked against the current
`pyreborn/`, `pyreborn/game/`, `tests/unit/` and `pygserver/pygserver/` source.

For the current implementation status, the known gaps and the roadmap, see
[`../FEATURE_GAPS.md`](../FEATURE_GAPS.md) at the repo root. That file stays up
to date and covers pyReborn, pygserver and reborn-protocol together.

## Still open (pyReborn-specific, per FEATURE_GAPS.md)

- Remaining GS1 command: `hidepoly`. `changeimgpart`, `showpoly`,
  `drawoverplayer` and `drawunderplayer` all landed with the Bomber Arena lobby
  work and are pinned by `game_tester/gs1_client_conformance.py`.
- No verified `pics1.png` tile-position table for ground-item sprites
  (`pyreborn/game/render_objects.py`). Some item drops therefore render with
  placeholder art.
- Polish: key rebinding.
- GS2 bytecode execution (no VM). This is a cross-project gap, see
  FEATURE_GAPS.md.

## Notes for Next Session

### Debugging Parser Issues
If positions jump randomly, check:
1. Does every prop in parse_other_player consume the correct byte count?
2. Does the suspect value (for example 39.5) come from string data that the
   parser read as a position?
3. Add debug: `print(f"prop={prop_id} pos={pos} remaining={len(data)-pos}")`

### GServer Reference
For the prop definitions, read `GServer-v2/server/include/TAccount.h`.
For the prop encoding, read `GServer-v2/server/src/TPlayer/TPlayerProps.cpp`.

### Quick Test Command
```bash
python -m pyreborn.example_pygame <username> <password> localhost 14900
```
