"""Playtest bot daemon: keeps GameBots connected to pygserver and exposes
them over a tiny local HTTP API so LLM agents can drive them at their own
pace (bots stay online + pumped between agent tool calls).

  GET  /spawn?name=X            connect a bot (idempotent)
  GET  /state?name=X            JSON game state for the bot, including
                                npc_dialogue (see caveats below)
  GET  /map?name=X              ASCII map of the current level (B=blocking,
                                .=walkable, W=water, C=chest, S=sign, @=you,
                                P=player, N=npc, D=baddy, L=link)
  GET  /act?name=X&cmd=...      perform an action, returns resulting state
       cmds: move&dx&dy | walkto&x&y | say&msg | sword[&dir] | bomb[&power]
             arrow[&dir] | grab | attack&pid | pm&pid&msg
             warp&level&x&y[&force=1] | open_chest[&x&y] | pickup[&x&y]
       move/walkto accept follow_links=0 to disable auto-warping onto a
       door mid-move (default is on, matching the real client - see
       GameBot.move()). warp accepts force=1 to warp onto a tile that looks
       blocking anyway (default refuses and returns an error string instead
       of stranding the bot - see GameBot.warp_to_checked()). open_chest
       with no x/y
       auto-targets the nearest known chest in reach and only reports
       success once the open is actually confirmed - see GameBot.open_chest.
  GET  /log?name=X              recent events (chat/hurt/pm) + detected
                                issues (including death/respawn - see
                                GameBot._check_death_respawn) + npc_dialogue
                                (see caveats below)
  GET  /leave?name=X            disconnect just bot X (others keep playing)
  GET  /quit?confirm=shutdown   disconnect all bots and stop the daemon
                                (token required so a shared daemon is not killed
                                 by a stray call)

Run: python -m game_tester.playtest_daemon [port]   (default 14990)
Game server via PYREBORN_TEST_HOST/PYREBORN_TEST_PORT (default localhost:14900).

Agent-prompt caveats:
  - /map draws @ at the sprite's TOP-LEFT while movement collision uses two
    direction-sensitive body probes — tell agents or they report false clips.
  - npc_dialogue (PLO_SAY2 text: sign reads / NPC chatter) is in BOTH /state
    and /log, not just one - without it in /state, an agent polling only
    /state never sees scripted NPC dialogue at all.
  - Coordinate conventions per /state field (matters on a GMAP world like
    funtimes/chicken.gmap, where a level segment's own tiles are always
    0-63 but the *player* wanders far past that): x/y and npcs_nearby are
    WORLD coordinates (local + grid*64) - the same frame /act's walkto
    param takes, so `walkto&x&y` can target either your own or an NPC's
    reported position directly. players_visible, chests, signs, baddies_nearby
    and links are LEVEL-LOCAL (0-63) - what the wire protocol actually sends
    for another entity. npcs_nearby and signs are filtered to the bot's
    CURRENT level (npcs via their '_level' tag; signs, chests and baddies via
    their per-level stores).
    /act's warp param is also level-local, matching client.warp_to_level().
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from game_tester.game_bot import GameBot
from pyreborn.tiletypes import get_tile_type, is_blocking, is_water, TileType

# Only read argv when actually run as the daemon: importing this module (the
# unit tests drive do_act() directly) would otherwise try to parse pytest's
# own arguments as a port number and fail at import time.
PORT = int(sys.argv[1]) if __name__ == '__main__' and len(sys.argv) > 1 else 14990
GAME_HOST = os.environ.get('PYREBORN_TEST_HOST', 'localhost')
GAME_PORT = int(os.environ.get('PYREBORN_TEST_PORT', 14900))

bots = {}
lock = threading.RLock()
running = True

# Last level we saw each bot resolve to, for _pump_on_level_change() below.
_bot_last_level = {}


def pump_loop():
    while running:
        with lock:
            for bot in bots.values():
                try:
                    bot.client.update()
                except Exception:
                    pass
        time.sleep(0.05)


def _pump_on_level_change(bot):
    """If bot.level has changed since the last time we looked, pump the
    client once more before building a response.

    Right after an edge warp (a GMAP segment boundary crossed by ordinary
    movement, not warp_to_level) bot.level flips the instant the player's
    world position crosses the boundary - it is derived from position, not
    from a server confirmation - but the new segment's PLO_NPCPROPS /
    PLO_LEVELCHEST / PLO_LEVELSIGN packets can still be in flight. A
    /state or /map read at exactly that moment reports the OLD segment's
    npcs/chests/signs under a level field that already says the NEW
    segment (confirmed live: /state right after an edge warp still listed
    the previous level's entities). This does not guarantee freshness - the
    stream can still be slower than one extra pump - but it closes most of
    the window without adding real latency to the common case (no level
    change -> no extra pump at all).
    """
    prev = _bot_last_level.get(bot.name)
    if prev != bot.level:
        bot.update(0.2)
        _bot_last_level[bot.name] = bot.level


def _current_links(bot, limit=10):
    """Dedupe + return the link rects for the level the bot is actually on.

    - client._current_level_name is not reliable as "the bot's level" on a
      GMAP (see GameBot._resolve_level_name's docstring) - use bot.level,
      which is derived from the bot's world position instead.
    - client.links[level] used to accumulate duplicate entries on revisit
      (re-entering a level - e.g. crossing a GMAP segment boundary out and
      back - makes the server re-stream that level's full data, and
      client.py's PLO_LEVELLINK handler appended without checking for an
      existing identical entry. Confirmed live: cross chicken1.nw ->
      chicken7.nw -> chicken1.nw and chicken1's own links list gained a
      second copy of one of its doors). client.py now dedupes at insertion,
      so this is a defensive no-op kept for the size-limiting/serialization
      shape rather than as the primary fix.
    """
    c = bot.client
    seen = {}
    for l in (c.links.get(bot.level) or []):
        key = (l.get('x'), l.get('y'), l.get('width'), l.get('height'), l.get('dest_level'))
        seen.setdefault(key, l)
    return [{'x': l.get('x'), 'y': l.get('y'), 'w': l.get('width'),
             'h': l.get('height'), 'dest': l.get('dest_level')}
            for l in list(seen.values())[:limit]]


def bot_state(bot):
    c = bot.client
    p = c.player
    others = {}
    for pid, pl in (bot.players or {}).items():
        others[pid] = {k: pl.get(k) for k in ('account', 'nickname', 'x', 'y', 'chat')
                       if pl.get(k) is not None}
    npcs = {}
    for nid, npc in c.npcs.items():
        if len(npcs) >= 30:
            break
        if not isinstance(npc, dict):
            continue
        # Restrict to the bot's CURRENT level: npcs is a flat dict that
        # isn't cleared on a seamless GMAP segment crossing (only on a full
        # warp_to_level - see client._reset_level_state's docstring), so
        # without this filter an npc from a previously-visited segment
        # keeps showing up as "nearby" forever. '_level' is stamped on every
        # npc by client.py's PLO_NPCPROPS handler; fall back to including it
        # if that's somehow missing rather than dropping it silently.
        if npc.get('_level', bot.level) != bot.level:
            continue
        # world_x/world_y (set by client.py on PLO_NPCPROPS, see
        # client.py:885) so this matches the x/y frame below instead of
        # the raw level-local npc['x']/npc['y'].
        npcs[nid] = {'x': npc.get('world_x', npc.get('x')),
                    'y': npc.get('world_y', npc.get('y')),
                    'image': npc.get('image', '')[:30]}
    baddies = {}
    for bid, b in list(c.baddies_in_level(bot.level).items())[:30]:
        if isinstance(b, dict):
            baddies[bid] = {'type': b.get('type'), 'x': b.get('x'), 'y': b.get('y'),
                            'alive': b.get('power', 1) > 0}
    # Signs and chests are keyed per level, so preserve their attribution in
    # the serialized state.
    signs = [{'x': x, 'y': y, 'text': text}
             for (x, y), text in list((c.signs.get(bot.level) or {}).items())[:10]]
    return {
        'name': bot.name, 'connected': bot.connected,
        'level': bot.level, 'x': round(bot.x, 1), 'y': round(bot.y, 1),
        'direction': p.direction, 'hearts': bot.hearts,
        'max_hearts': p.max_hearts, 'bombs': p.bombs, 'arrows': p.arrows,
        'rupees': p.rupees, 'swimming': getattr(bot, 'is_swimming', False),
        'players_visible': others,
        'npcs_nearby': npcs,
        'baddies_nearby': baddies,
        'chests': [{'level': level_name, 'x': x, 'y': y, 'opened': opened,
                    'item': c.chest_items.get(level_name, {}).get((x, y))}
                   for level_name, level_chests in c.chests.items()
                   for (x, y), opened in level_chests.items()][:10],
        'links': _current_links(bot),
        'signs': signs,
        # PLO_SAY2 text (sign reads / NPC chatter) - also in /log's
        # npc_dialogue; kept in both so an agent polling only /state still
        # sees scripted dialogue (see module docstring caveats).
        'npc_dialogue': [txt for txt, _ in getattr(bot, 'say2_received', [])[-10:]],
    }


def bot_map(bot, radius=14):
    c = bot.client
    tiles = c.tiles
    if not tiles:
        return 'no tiles'
    cx, cy = int(bot.x % 64), int(bot.y % 64)
    rows = []
    for y in range(max(0, cy - radius), min(64, cy + radius + 1)):
        row = []
        for x in range(max(0, cx - radius), min(64, cx + radius + 1)):
            ch = '.'
            try:
                tile = tiles[y * 64 + x]
                # Use the SAME predicates the game's collision uses, not a
                # single-enum `== BLOCKING` check — otherwise throw-through,
                # bush/rock/pot, jump-stone and bed tiles (all solid to the
                # player) render as walkable '.', and a playtester reads that
                # as "phantom collision on open ground" (a real false report
                # this map produced). B here now means "your feet will stop".
                if is_blocking(tile):
                    ch = 'B'
                elif is_water(tile):
                    ch = 'W'
                elif get_tile_type(tile) == TileType.CHAIR:
                    ch = 'c'
            except Exception:
                ch = '?'
            row.append(ch)
        rows.append(row)
    ox, oy = max(0, cx - radius), max(0, cy - radius)

    def mark(wx, wy, ch):
        mx, my = int(wx % 64) - ox, int(wy % 64) - oy
        if 0 <= my < len(rows) and 0 <= mx < len(rows[my]):
            rows[my][mx] = ch

    for (chx, chy) in c.chests_in_level(bot.level):
        mark(chx, chy, 'C')
    for (sx, sy) in (c.signs.get(bot.level) or {}):
        mark(sx, sy, 'S')
    for l in _current_links(bot, limit=len(c.links.get(bot.level) or [])):
        mark(l.get('x', -1), l.get('y', -1), 'L')
    for npc in c.npcs.values():
        # Level-local x/y here, not world_x/world_y: the map grid drawn
        # above is always local 0-63 (one segment), same as bot.x % 64 used
        # for cx/cy. Same current-level filter as bot_state() - see that
        # function's comment on why the flat npcs dict needs it.
        if isinstance(npc, dict) and npc.get('_level', bot.level) == bot.level:
            mark(npc.get('x', -1), npc.get('y', -1), 'N')
    for b in c.baddies_in_level(bot.level).values():
        if isinstance(b, dict) and b.get('power', 1) > 0:
            mark(b.get('x', -1), b.get('y', -1), 'D')
    for pl in (bot.players or {}).values():
        mark(pl.get('x', -1), pl.get('y', -1), 'P')
    mark(bot.x, bot.y, '@')
    header = f'level={bot.level} you=({bot.x:.1f},{bot.y:.1f}) map origin=({ox},{oy}) 1 char = 1 tile'
    return header + '\n' + '\n'.join(''.join(r) for r in rows)


def bot_log(bot):
    return {
        'chat_received': [(pid, msg) for pid, msg, _ in bot.chat_received[-15:]],
        'npc_dialogue': [txt for txt, _ in getattr(bot, 'say2_received', [])[-10:]],
        'hurt_received': [(pid, dmg) for pid, dmg, _ in bot.hurt_received[-15:]],
        'pm_received': [(pid, msg) for pid, msg, _ in bot.pm_received[-10:]],
        'issues': [f'[{i.severity}] {i.description}' for i in bot.get_issues()][-15:],
        'action_log_tail': [f'{a.action}({a.args}) -> {a.result}'
                            for a in bot.action_log[-10:]],
    }


def do_act(bot, q):
    """Dispatch /act to GameBot's action registry (GameBot.ACTIONS).

    Transport only: the command names, their parameter coercions and the warp
    safety policy all live with the bot now (game_bot.py) - this used to be a
    parallel implementation of the same twelve actions, and the two had
    already drifted (arrow/grab called client methods directly, bypassing the
    bot's own logging and guards).
    """
    cmd = q.get('cmd', [''])[0]
    action = GameBot.ACTIONS.get(cmd)
    if action is None:
        return f'unknown cmd {cmd!r}'
    return action.run(bot, lambda key: q.get(key, [None])[0])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = (obj if isinstance(obj, str) else
                json.dumps(obj, default=str, indent=1)).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global running
        u = urlparse(self.path)
        q = parse_qs(u.query)
        name = q.get('name', [''])[0]
        try:
            with lock:
                if u.path == '/quit':
                    # Full shutdown kills the daemon for EVERY bot, so when
                    # several agents share one daemon a stray /quit takes them
                    # all down (this is exactly what looked like "random daemon
                    # crashes"). Require an explicit confirm token so a curious
                    # play agent can't do it by accident.
                    if q.get('confirm', [''])[0] != 'shutdown':
                        self._send('refused: /quit needs ?confirm=shutdown '
                                   '(use /leave to drop just your own bot)', 403)
                        return
                    disconnect_all_bots()
                    running = False
                    self._send('bye')
                    threading.Thread(target=self.server.shutdown).start()
                    return
                if u.path == '/leave':
                    b = bots.pop(name, None)
                    if b:
                        b.disconnect()
                    self._send('left' if b else f'no bot {name!r}')
                    return
                if u.path == '/spawn':
                    if name not in bots:
                        b = GameBot(name, GAME_HOST, GAME_PORT)
                        if not b.connect():
                            self._send(f'connect failed for {name}', 500)
                            return
                        bots[name] = b
                        b.update(1.0)
                        _bot_last_level[name] = b.level
                    self._send(bot_state(bots[name]))
                    return
                bot = bots.get(name)
                if not bot:
                    self._send(f'no bot {name!r}; /spawn first', 404)
                    return
                if u.path == '/state':
                    _pump_on_level_change(bot)
                    self._send(bot_state(bot))
                elif u.path == '/map':
                    _pump_on_level_change(bot)
                    self._send(bot_map(bot))
                elif u.path == '/log':
                    self._send(bot_log(bot))
                elif u.path == '/act':
                    result = do_act(bot, q)
                    bot.update(0.3)
                    # The action itself (e.g. a warp, or walking across a
                    # GMAP segment edge) may be exactly what just changed the
                    # level - give it the same extra beat before reporting
                    # state back.
                    _pump_on_level_change(bot)
                    self._send({'result': result, 'state': bot_state(bot)})
                else:
                    self._send('unknown endpoint', 404)
        except (ValueError, TypeError) as e:
            # Bad caller input (e.g. non-numeric x/y for open_chest) — a clean
            # 400, not a 500 with a stack trace leaked to the agent.
            self._send(f'bad argument: {e}', 400)
        except Exception as e:
            import traceback
            self._send(f'error: {e}\n{traceback.format_exc()}', 500)


def disconnect_all_bots():
    """Log every bot out. Called on shutdown however the daemon ends."""
    with lock:
        for bot in bots.values():
            try:
                bot.disconnect()
            except Exception:
                pass
        bots.clear()


if __name__ == '__main__':
    threading.Thread(target=pump_loop, daemon=True).start()
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'playtest daemon on 127.0.0.1:{PORT} -> game {GAME_HOST}:{GAME_PORT}')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # Ctrl-C (or any crash out of serve_forever) used to leave every bot
        # logged in on the game server until it timed them out, so the next
        # daemon run met its own accounts already online.
        running = False
        disconnect_all_bots()
