"""Playtest bot daemon: keeps GameBots connected to pygserver and exposes
them over a tiny local HTTP API so LLM agents can drive them at their own
pace (bots stay online + pumped between agent tool calls).

  GET  /spawn?name=X            connect a bot (idempotent)
  GET  /state?name=X            JSON game state for the bot
  GET  /map?name=X              ASCII map of the current level (B=blocking,
                                .=walkable, W=water, C=chest, @=you, P=player,
                                N=npc, L=link)
  GET  /act?name=X&cmd=...      perform an action, returns resulting state
       cmds: move&dx&dy | walkto&x&y | say&msg | sword[&dir] | bomb[&power]
             arrow[&dir] | grab | attack&pid | pm&pid&msg | warp&level&x&y
             open_chest[&x&y] | pickup[&x&y]
  GET  /log?name=X              recent events (chat/hurt/pm) + detected issues
  GET  /leave?name=X            disconnect just bot X (others keep playing)
  GET  /quit?confirm=shutdown   disconnect all bots and stop the daemon
                                (token required so a shared daemon isn't killed
                                 by a stray call)

Run: python -m game_tester.playtest_daemon [port]   (default 14990)
Game server via PYREBORN_TEST_HOST/PYREBORN_TEST_PORT (default localhost:14900).

Agent-prompt caveat: /map draws @ at the sprite's TOP-LEFT while collision is
feet-only (rows y+2..y+3) — tell agents or they report false wall-clips.
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

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 14990
GAME_HOST = os.environ.get('PYREBORN_TEST_HOST', 'localhost')
GAME_PORT = int(os.environ.get('PYREBORN_TEST_PORT', 14900))

bots = {}
lock = threading.RLock()
running = True


def pump_loop():
    while running:
        with lock:
            for bot in bots.values():
                try:
                    bot.client.update()
                except Exception:
                    pass
        time.sleep(0.05)


def bot_state(bot):
    c = bot.client
    p = c.player
    others = {}
    for pid, pl in (bot.players or {}).items():
        others[pid] = {k: pl.get(k) for k in ('account', 'nickname', 'x', 'y', 'chat')
                       if pl.get(k) is not None}
    npcs = {}
    for nid, npc in list(c.npcs.items())[:30]:
        if isinstance(npc, dict):
            npcs[nid] = {'x': npc.get('x'), 'y': npc.get('y'),
                         'image': npc.get('image', '')[:30]}
    return {
        'name': bot.name, 'connected': bot.connected,
        'level': bot.level, 'x': round(bot.x, 1), 'y': round(bot.y, 1),
        'direction': p.direction, 'hearts': bot.hearts,
        'max_hearts': p.max_hearts, 'bombs': p.bombs, 'arrows': p.arrows,
        'rupees': p.rupees, 'swimming': getattr(bot, 'is_swimming', False),
        'players_visible': others,
        'npcs_nearby': npcs,
        # chests: {(x,y): opened}; chest_items: {(x,y): item name}
        'chests': [{'x': x, 'y': y, 'opened': opened,
                    'item': c.chest_items.get((x, y))}
                   for (x, y), opened in list(c.chests.items())[:10]],
        # links: {level_name: [link dicts]}
        'links': [{'x': l.get('x'), 'y': l.get('y'), 'w': l.get('width'),
                   'h': l.get('height'), 'dest': l.get('dest_level')}
                  for l in (c.links.get(c._current_level_name) or [])][:10],
        'signs': len(c.signs or []),
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

    for (chx, chy) in c.chests:
        mark(chx, chy, 'C')
    for l in (c.links.get(c._current_level_name) or []):
        mark(l.get('x', -1), l.get('y', -1), 'L')
    for npc in c.npcs.values():
        if isinstance(npc, dict):
            mark(npc.get('x', -1), npc.get('y', -1), 'N')
    for pl in (bot.players or {}).values():
        mark(pl.get('x', -1), pl.get('y', -1), 'P')
    mark(bot.x, bot.y, '@')
    header = f'level={bot.level} you=({bot.x:.1f},{bot.y:.1f}) map origin=({ox},{oy}) 1 char = 1 tile'
    return header + '\n' + '\n'.join(''.join(r) for r in rows)


def bot_log(bot):
    return {
        'chat_received': [(pid, msg) for pid, msg, _ in bot.chat_received[-15:]],
        'hurt_received': [(pid, dmg) for pid, dmg, _ in bot.hurt_received[-15:]],
        'pm_received': [(pid, msg) for pid, msg, _ in bot.pm_received[-10:]],
        'issues': [f'[{i.severity}] {i.description}' for i in bot.get_issues()][-15:],
        'action_log_tail': [f'{a.action}({a.args}) -> {a.result}'
                            for a in bot.action_log[-10:]],
    }


def do_act(bot, q):
    cmd = q.get('cmd', [''])[0]
    g = lambda k, d=None: q.get(k, [d])[0]  # noqa: E731
    if cmd == 'move':
        return bot.move(int(g('dx', 0)), int(g('dy', 0)))
    if cmd == 'walkto':
        return bot.walk_to(float(g('x')), float(g('y')), timeout=8.0)
    if cmd == 'say':
        return bot.say_and_wait_echo(g('msg', ''))
    if cmd == 'sword':
        d = g('dir')
        return bot.sword_attack(int(d) if d is not None else None)
    if cmd == 'bomb':
        return bot.drop_bomb(int(g('power', 1)))
    if cmd == 'arrow':
        d = g('dir')
        return bot.client.shoot_arrow(
            direction=int(d) if d is not None else None)
    if cmd == 'grab':
        return bot.client.set_animation('grab')
    if cmd == 'attack':
        return bot.attack_player(int(g('pid')))
    if cmd == 'pm':
        return bot.send_pm(int(g('pid')), g('msg', ''))
    if cmd == 'warp':
        return bot.warp_to(g('level'), float(g('x', 30)), float(g('y', 30)))
    if cmd == 'open_chest':
        x, y = g('x'), g('y')
        return bot.open_chest(float(x) if x else None, float(y) if y else None)
    if cmd == 'pickup':
        x, y = g('x'), g('y')
        return bot.pickup_item(float(x) if x else None, float(y) if y else None)
    return f'unknown cmd {cmd!r}'


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
                    for b in bots.values():
                        b.disconnect()
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
                    self._send(bot_state(bots[name]))
                    return
                bot = bots.get(name)
                if not bot:
                    self._send(f'no bot {name!r}; /spawn first', 404)
                    return
                if u.path == '/state':
                    self._send(bot_state(bot))
                elif u.path == '/map':
                    self._send(bot_map(bot))
                elif u.path == '/log':
                    self._send(bot_log(bot))
                elif u.path == '/act':
                    result = do_act(bot, q)
                    bot.update(0.3)
                    self._send({'result': result, 'state': bot_state(bot)})
                else:
                    self._send('unknown endpoint', 404)
        except Exception as e:
            import traceback
            self._send(f'error: {e}\n{traceback.format_exc()}', 500)


if __name__ == '__main__':
    threading.Thread(target=pump_loop, daemon=True).start()
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'playtest daemon on 127.0.0.1:{PORT} -> game {GAME_HOST}:{GAME_PORT}')
    srv.serve_forever()
