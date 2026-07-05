# Playtest brief — you are playing a live game to find bugs

You drive a real game bot connected to a running Reborn (Graal-style) game server, over a
local HTTP API. Your job is to PLAY THE GAME like a curious, adversarial human and find
things that are broken, wrong, or weird. You are not writing tests — you are the tester.

## The API (use curl; the daemon is at http://127.0.0.1:14990)

- `GET /spawn?name=YOU` — connect your bot (call once at start; idempotent). Returns state.
- `GET /state?name=YOU` — JSON: pos (x,y), direction, hearts/max_hearts, bombs, arrows,
  rupees, swimming, players_visible {name: {x,y,...}}, npcs_nearby, chests, links.
- `GET /map?name=YOU` — ASCII of the level around you. Legend: `@`=you, `P`=other player,
  `B`=blocking/wall, `W`=water, `C`=chest, `L`=link/warp, `N`=npc, `.`=walkable.
- `GET /act?name=YOU&cmd=CMD&...` — do something; returns resulting state. Commands:
  - `move&dx=1&dy=0` (step in a direction; dx/dy in tiles)
  - `walkto&x=35&y=35` (pathfind-ish walk to a tile)
  - `say&msg=hello`
  - `sword` (optionally `&dir=0..3`; 0=up 1=left 2=down 3=right)
  - `bomb` (optionally `&power=1`) / `arrow` (optionally `&dir=`)
  - `grab` / `attack&pid=PLAYERID` / `pm&pid=PLAYERID&msg=hi`
  - `warp&level=NAME.nw&x=30&y=30`
  - `open_chest` (optionally `&x=&y=`) / `pickup` (optionally `&x=&y=`)
- `GET /log?name=YOU` — recent chat_received, hurt_received, pm_received, and any issues the
  bot's own detector flagged.
- `GET /leave?name=YOU` — disconnect just your bot when done (optional; don't disconnect others).

Do NOT call `/quit` — it stops the whole shared daemon for every agent, not just you.

curl pattern: `curl -s 'http://127.0.0.1:14990/act?name=YOU&cmd=walkto&x=40&y=40'`
Always URL-safe: use `+` or `%20` for spaces in msg. Parse JSON with `python3.13 -c` if useful.

## CRITICAL caveat (or you WILL report false bugs)

`/map` draws `@` at your sprite's TOP-LEFT, but collision is FEET-only (the bottom row of
your 2-wide, 3-tall sprite — roughly tiles y+2..y+3). So you can visually "overlap" a wall
by up to ~2 tiles above your feet and that is CORRECT, not a clip-through. Judge collision by
your feet, not the `@`. Likewise you stand ON your feet position, not the `@`.

## How to play

Spend your budget actually doing things and observing the RESULT of each — don't just fire
actions blindly. Move around the whole level, cross into water, walk into walls from every
side, open every chest (twice — does it re-give loot?), swing your sword at NPCs and at the
other players, throw bombs and watch what they do, pick things up, warp between levels and
back, chat and PM. After each action check `/state` and `/log` and ask: did the world change
the way a real game should? Did hearts/bombs/arrows/rupees move correctly? Did the other
player actually see it (coordinate with them via `say`/`pm`)?

Hunt specifically for: things that silently do nothing, counts that don't change (or go
negative/absurd), positions that desync between what you did and where you ended up, actions
that work when they shouldn't (or vice versa), stuff that affects the wrong player, getting
stuck/stranded, crashes or error spam, and anything that just feels wrong for a game.

## Coordinate with the other bots

Other agents are playing their own bots on the SAME server right now (names in your task).
Use in-game `say`/`pm` to set up joint tests: "hold still at 30,30, I'm bombing you" then
verify their hearts drop; "did you see me swing?"; stand on the same tile; race to a chest.
Multiplayer interactions (visibility, PvP, chat relay) are the richest bug source — actually
exercise them together, don't just test solo.

## Report back

Return a concise, ranked list of concrete findings. For each: what you did (the exact
actions/coords), what you observed, what you expected, and how sure you are it's a real bug
vs. expected behavior. Include the raw `/state` or `/log` evidence. Empty/○ findings is a
fine answer if the game held up — say so and say what you covered. Do NOT edit any source
code; you are a player, not a fixer.
