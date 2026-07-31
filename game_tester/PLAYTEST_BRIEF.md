# Playtest brief: you play a live game to find bugs

You drive a real game bot. The bot connects to a running Reborn game server over
a local HTTP API. Play the game like a curious, adversarial human. Find what is
broken, wrong, or strange. You do not write tests. You are the tester.

## The API (use curl; the daemon is at http://127.0.0.1:14990)

- `GET /spawn?name=YOU` — connect your bot. Call it once at the start. It is
  idempotent and returns the state.
- `GET /state?name=YOU` — JSON: pos (x,y), direction, hearts/max_hearts, bombs, arrows,
  rupees, swimming, players_visible {name: {x,y,...}}, npcs_nearby, chests (with
  x/y/opened/item), signs (with x/y/text), links, npc_dialogue (last ~10 sign/NPC texts).
- `GET /map?name=YOU` — ASCII of the level around you. Legend: `@`=you, `P`=other player,
  `B`=blocking/wall, `W`=water, `C`=chest, `S`=sign, `L`=link/warp, `N`=npc, `.`=walkable.
- `GET /act?name=YOU&cmd=CMD&...` — do something. It returns the resulting state.
  Commands:
  - `move&dx=1&dy=0` (step in a direction; dx/dy in tiles)
  - `walkto&x=35&y=35` (pathfind-ish walk to a tile)
  - `say&msg=hello`
  - `sword` (optionally `&dir=0..3`; 0=up 1=left 2=down 3=right)
  - `bomb` (optionally `&power=1`) / `arrow` (optionally `&dir=`)
  - `grab` / `attack&pid=PLAYERID` / `pm&pid=PLAYERID&msg=hi`
  - `warp&level=NAME.nw&x=30&y=30`
  - `open_chest` (optionally `&x=&y=`). With no coordinates it targets the
    nearest known chest in reach. It reports success only after the server
    confirms the open. An out-of-reach or unknown chest returns an error string,
    not a false `true`.
  - `pickup` (optionally `&x=&y=`)
- `GET /log?name=YOU` — recent chat_received, hurt_received, pm_received, npc_dialogue,
  and any issues the bot's own detector flagged (including death/respawn events).
- `GET /leave?name=YOU` — disconnect your own bot when you finish. This is
  optional. Do not disconnect anyone else.

Do NOT call `/quit`. It stops the whole shared daemon for every agent, not just you.

curl pattern: `curl -s 'http://127.0.0.1:14990/act?name=YOU&cmd=walkto&x=40&y=40'`
Keep every URL safe. Use `+` or `%20` for a space in `msg`. Parse the JSON with
`python3.13 -c` if that helps.

## CRITICAL caveat (or you WILL report false bugs)

`/map` draws `@` at your sprite's TOP-LEFT. Collision uses the FEET only. Your
sprite is 2 tiles wide and 3 tall, so the feet are roughly tiles y+2 to y+3. You
can therefore "overlap" a wall by up to 2 tiles above your feet, and that is
CORRECT, not a clip-through. Judge collision by your feet, not by the `@`. You
also stand on your feet position, not on the `@`.

## How to play

Spend your budget on real actions, and check the RESULT of each one. Do not fire
actions blindly. Move around the whole level. Cross into water. Walk into walls
from every side. Open every chest twice and see whether it gives the loot again.
Swing your sword at NPCs and at the other players. Throw bombs and watch what
they do. Pick things up. Warp between levels and back. Chat and send PMs.

After each action, read `/state` and `/log`. Then ask three questions. Did the
world change the way a real game should? Did the hearts, bombs, arrows and rupees
move correctly? Did the other player see it? Use `say` and `pm` to confirm that
last one with them.

Hunt for these:

- Actions that silently do nothing.
- Counts that do not change, or that go negative or absurd.
- A position that desyncs from what you did and where you ended up.
- Actions that work when they should not, and the reverse.
- Effects that land on the wrong player.
- A bot that gets stuck or stranded.
- Crashes or error spam.
- Anything that feels wrong for a game.

## Coordinate with the other bots

Other agents drive their own bots on the SAME server right now. Your task names
them. Use in-game `say` and `pm` to set up joint tests. Tell another bot to hold
still at 30,30, bomb it, then check that its hearts drop. Ask whether it saw you
swing. Stand on the same tile. Race it to a chest.

Multiplayer interactions carry the most bugs: visibility, PvP and chat relay.
Exercise them together. Do not test only on your own.

## Report back

Return a short, ranked list of concrete findings. For each one, give:

1. What you did, with the exact actions and coordinates.
2. What you observed.
3. What you expected.
4. How sure you are that it is a real bug and not expected behavior.
5. The raw `/state` or `/log` evidence.

Zero findings is a fine answer if the game held up. Say so, and say what you
covered. Do NOT edit any source code. You are a player, not a fixer.
