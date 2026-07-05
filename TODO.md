# PyReborn TODO

Most of the items formerly tracked here (other-player gani/sword/shield rendering,
sword hit detection, damage/hurt/death, bombs/explosions, arrows, NPC movement/anim,
sign reading + dialogue boxes, trigger actions, audio, minimap, weapon switching,
animated tiles, water/lava, item pickup/chest/inventory, level links/warping,
config file, unit tests) are **done** — verified against current `pyreborn/`,
`pyreborn/game/`, `tests/unit/`, and `pygserver/pygserver/` source.

For current implementation status, known gaps, and the roadmap, see
[`../FEATURE_GAPS.md`](../FEATURE_GAPS.md) at the repo root — it is kept up to date
and covers pyReborn, pygserver, and reborn-protocol together.

## Still open (pyReborn-specific, per FEATURE_GAPS.md)

- Remaining GS1 commands: `changeimgpart`, `showpoly`/`hidepoly`, `drawoverplayer`/`drawunderplayer`.
- `pyreborn/listserver.py` defines its own local `PacketReader` instead of importing
  the shared one from `reborn-protocol`.
- No verified `pics1.png` tile-position table for ground-item sprites
  (`pyreborn/game/render_objects.py`) — some item drops render with placeholder art.
- Polish: key rebinding.
- GS2 bytecode execution (no VM) — cross-project gap, see FEATURE_GAPS.md.

## Notes for Next Session

### Debugging Parser Issues
If positions jump randomly, check:
1. Are all props in parse_other_player consuming correct bytes?
2. Is the suspect value (e.g., 39.5) coming from string data being read as position?
3. Add debug: `print(f"prop={prop_id} pos={pos} remaining={len(data)-pos}")`

### GServer Reference
Check prop definitions in: `GServer-v2/server/include/TAccount.h`
Check prop encoding in: `GServer-v2/server/src/TPlayer/TPlayerProps.cpp`

### Quick Test Command
```bash
python -m pyreborn.example_pygame <username> <password> localhost 14900
```
