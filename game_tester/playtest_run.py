"""One-shot LLM playtest: stand up a throwaway server + daemon, turn a fleet of
persona agents loose to PLAY the game and find bugs, collect their findings,
tear everything down.

Unlike the pytest suites (fixed assertions), this drives the game the way a
curious/adversarial human would and reports whatever feels wrong — the class of
bug a substring-matching test sails past (see game_tester/playtest_daemon.py and
the chat-length-prefix bug it caught).

Usage:
    python -m game_tester.playtest_run [--agents N] [--turns T] [--model M]
    ./playtest.sh                       # wrapper with sensible defaults

Needs ANTHROPIC_API_KEY in the environment (falls back to `rbw get
anthropic-api-key`). Uses only the stdlib + a local pygserver checkout.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PYR = Path(__file__).resolve().parent.parent
PYG = Path(os.environ.get("PYGSERVER_DIR", PYR.parent / "pygserver"))
PROTO = PYR.parent / "reborn-protocol"
BRIEF = PYR / "game_tester" / "PLAYTEST_BRIEF.md"

FIXTURE_LEVELS = ["onlinestartlocal.nw", "qa_testlevel.nw", "qa_tier3.nw"]
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Personas: (bot name, one-line role, focus paragraph woven into the system prompt)
PERSONAS = [
    ("brawler", "COMBAT BREAKER",
     "Push the fight systems adversarially: sword in all 4 directions at NPCs and "
     "players, bombs (fuse, blast radius, self/other damage, placement cap), arrows, "
     "PvP damage and knockback, death/respawn, and count integrity (never negative). "
     "Try attacks out of range, through walls, across a warp, and on your own id."),
    ("explorer", "WORLD EXPLORER",
     "Stress movement, collision, geometry, and warps. Walk into every wall (judge by "
     "your FEET, not the @ — re-read the caveat), cross water, step on links, warp "
     "between levels and to a bogus level name, and hunt position desync and off-map "
     "coordinates."),
    ("trader", "ITEMS & ECONOMY ADVERSARY",
     "Break item/economy logic: open every chest (then re-open — dupe?), pickups, "
     "rupee/bomb/arrow counts, NPCs, signs, and adversarial chat (empty, huge, unicode, "
     "%s / #v() / injection-shaped). Confirm the others' logs receive your chat intact."),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        try:
            key = subprocess.check_output(
                ["rbw", "get", "anthropic-api-key"], text=True).strip()
        except Exception:
            pass
    if not key:
        sys.exit("No ANTHROPIC_API_KEY in env and `rbw get anthropic-api-key` failed.")
    return key


def start_server():
    """Spawn a throwaway pygserver on a free port with a fresh accounts dir.
    Returns (proc, port, tmpdir, logfile)."""
    d = Path(tempfile.mkdtemp(prefix="playtest_"))
    for sub in ("accounts", "npcs", "world", "config"):
        (d / sub).mkdir()
    for n in FIXTURE_LEVELS:
        src = PYG / "levels" / n
        if src.exists():
            shutil.copy(src, d / "world" / n)
    port = _free_port()
    (d / "config" / "serveroptions.txt").write_text(
        f"serverport = {port}\nnoverifylogin = true\n"
        "startlevel = onlinestartlocal.nw\nstartx = 30\nstarty = 30.5\n")
    logf = open(d / "server.log", "wb")
    env = dict(os.environ, PYGSERVER_QA="1",
               PYGSERVER_ACCOUNTS_DIR=str(d / "accounts"))
    proc = subprocess.Popen(
        [sys.executable, str(PYG / "run_server.py"), str(d)],
        cwd=str(PYG), stdout=logf, stderr=subprocess.STDOUT, env=env)
    deadline = time.time() + 25
    while time.time() < deadline:
        if (d / "server.log").read_text(errors="replace").find("Server listening") >= 0:
            break
        if proc.poll() is not None:
            sys.exit("pygserver exited during startup; see " + str(d / "server.log"))
        time.sleep(0.25)
    time.sleep(1.0)
    return proc, port, d, logf


def start_daemon(game_port: int, game_host: str = "localhost"):
    """Spawn the playtest daemon on a free port pointed at the game server."""
    dport = _free_port()
    env = dict(os.environ, PYREBORN_TEST_HOST=game_host,
               PYREBORN_TEST_PORT=str(game_port),
               PYTHONPATH=os.pathsep.join([str(PYR), str(PROTO),
                                           os.environ.get("PYTHONPATH", "")]))
    proc = subprocess.Popen(
        [sys.executable, "-m", "game_tester.playtest_daemon", str(dport)],
        cwd=str(PYR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{dport}/state?name=_ping",
                                   timeout=2)
            break
        except urllib.error.HTTPError:
            break  # daemon answered (404 for no bot) -> it's up
        except Exception:
            time.sleep(0.3)
    return proc, dport


def daemon_get(dport: int, path: str) -> str:
    try:
        return urllib.request.urlopen(
            f"http://127.0.0.1:{dport}{path}", timeout=15).read().decode()
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return f"ERROR: {e}"


# One tool the model calls; we translate it into a daemon HTTP request.
GAME_TOOL = {
    "name": "game",
    "description": "Drive your game bot. Returns the resulting game state / map / log as text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "endpoint": {"type": "string",
                         "enum": ["spawn", "state", "map", "act", "log", "leave"]},
            "cmd": {"type": "string",
                    "description": "For endpoint=act: move|walkto|say|sword|bomb|arrow|"
                                   "grab|attack|pm|warp|open_chest|pickup"},
            "args": {"type": "object",
                     "description": "extra query params, e.g. {\"x\":35,\"y\":35} or "
                                    "{\"dx\":1,\"dy\":0} or {\"msg\":\"hi\"} or "
                                    "{\"pid\":2} or {\"level\":\"x.nw\"}"},
        },
        "required": ["endpoint"],
    },
}


def _tool_to_path(bot_name: str, ti: dict) -> str:
    from urllib.parse import urlencode
    ep = ti["endpoint"]
    q = {"name": bot_name}
    if ep == "act":
        q["cmd"] = ti.get("cmd", "")
    for k, v in (ti.get("args") or {}).items():
        q[k] = v
    return f"/{ep}?{urlencode(q)}"


def anthropic_call(key: str, model: str, system: str, messages: list) -> dict:
    body = json.dumps({
        "model": model, "max_tokens": 1024, "system": system,
        "messages": messages, "tools": [GAME_TOOL],
    }).encode()
    req = urllib.request.Request(ANTHROPIC_URL, data=body, method="POST", headers={
        "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 529) and attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"anthropic {e.code}: {e.read().decode()[:300]}")
    raise RuntimeError("anthropic retries exhausted")


def run_persona(key, model, dport, name, role, focus, others, max_turns, out):
    brief = BRIEF.read_text()
    system = (
        f"{brief}\n\n---\nYou are bot `{name}`. Persona: {role}. {focus}\n"
        f"The other players on this server right now are: {', '.join(others)} — "
        f"coordinate joint tests with them via in-game say/pm. Call the `game` tool "
        f"to act; start by spawning. After about {max_turns} actions, stop calling "
        f"tools and reply with your final ranked findings report as plain text."
    )
    messages = [{"role": "user", "content":
                 "Begin playtesting. Spawn your bot and start finding bugs."}]
    report = None
    for turn in range(max_turns):
        try:
            resp = anthropic_call(key, model, system, messages)
        except Exception as e:
            report = f"(agent aborted: {e})"
            break
        blocks = resp.get("content", [])
        messages.append({"role": "assistant", "content": blocks})
        text = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if resp.get("stop_reason") != "tool_use":
            if text.strip():
                report = text.strip()
            break
        tool_results = []
        for b in blocks:
            if b.get("type") != "tool_use":
                continue
            path = _tool_to_path(name, b["input"])
            result = daemon_get(dport, path)
            tool_results.append({"type": "tool_result", "tool_use_id": b["id"],
                                 "content": result[:4000]})
        messages.append({"role": "user", "content": tool_results})

    # Budget spent mid-play: force one final tools-free turn so we always
    # capture findings instead of losing them when the loop runs out.
    if report is None:
        messages.append({"role": "user", "content":
                         "Time's up — stop playing and reply now with your final "
                         "ranked findings report (concrete actions, observed vs "
                         "expected, confidence). Do not call any tool."})
        try:
            body = json.dumps({"model": model, "max_tokens": 1500, "system": system,
                               "messages": messages}).encode()  # no tools -> text only
            req = urllib.request.Request(ANTHROPIC_URL, data=body, method="POST",
                                         headers={"x-api-key": key,
                                                  "anthropic-version": ANTHROPIC_VERSION,
                                                  "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                fin = json.loads(r.read())
            report = " ".join(b.get("text", "") for b in fin.get("content", [])
                              if b.get("type") == "text").strip() or "(empty report)"
        except Exception as e:
            report = f"(no report; final call failed: {e})"

    daemon_get(dport, f"/leave?name={name}")
    out[name] = report


def _serve_only(external_host: str = None, external_port: int = 14900):
    """Bring up the throwaway server + daemon and block until interrupted, so a
    Claude Code session (or a human with curl) can drive the agents. No API
    calls, no cost. Always tears the children down on exit.

    If external_host is given, skip spawning a throwaway pygserver entirely and
    point the daemon at the already-running server instead — teardown then
    never touches it (we didn't start it, we don't stop it)."""
    import signal
    srv = tmpdir = logf = None
    if external_host:
        ghost, gport = external_host, external_port
    else:
        srv, gport, tmpdir, logf = start_server()
        ghost = "localhost"
    dproc, dport = start_daemon(gport, ghost)

    def teardown(*_):
        try:
            daemon_get(dport, "/quit?confirm=shutdown")
        except Exception:
            pass
        procs = (dproc, srv) if srv is not None else (dproc,)
        for p in procs:
            p.terminate()
            try:
                p.wait(8)
            except Exception:
                p.kill()
        if logf is not None:
            logf.close()
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)
        print("\n[playtest] served infra torn down.")
        sys.exit(0)

    signal.signal(signal.SIGINT, teardown)
    signal.signal(signal.SIGTERM, teardown)
    print(f"[playtest] SERVE MODE — no API cost. Drive the agents yourself.\n"
          f"  game server : {ghost}:{gport}"
          f"{'  (external, not managed by us)' if external_host else ''}\n"
          f"  daemon (API): http://127.0.0.1:{dport}\n"
          f"  brief       : {BRIEF}\n"
          f"  personas    : {', '.join(n for n, _, _ in PERSONAS)}\n"
          f"Ctrl-C to stop.", flush=True)
    signal.pause()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=3,
                    help="number of persona agents (1-3)")
    ap.add_argument("--turns", type=int, default=40,
                    help="approx actions per agent")
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--out", default=None, help="report path (default: timestamped)")
    ap.add_argument("--serve", action="store_true",
                    help="just bring up the throwaway server + daemon and wait "
                         "(no API calls / no cost) so a Claude Code session can "
                         "drive the persona agents itself; Ctrl-C to tear down")
    ap.add_argument("--external-host", default=None,
                    help="target an already-running Reborn server instead of "
                         "spawning a throwaway pygserver; teardown won't touch it")
    ap.add_argument("--external-port", type=int, default=14900,
                    help="port for --external-host (default: 14900)")
    args = ap.parse_args()

    if args.serve:
        _serve_only(args.external_host, args.external_port)
        return

    key = _api_key()
    if not BRIEF.exists():
        sys.exit(f"Brief not found at {BRIEF}")
    personas = PERSONAS[:max(1, min(args.agents, len(PERSONAS)))]

    srv = tmpdir = logf = None
    if args.external_host:
        ghost, gport = args.external_host, args.external_port
        print(f"[playtest] targeting external server {ghost}:{gport}...")
    else:
        print(f"[playtest] starting throwaway server + daemon...")
        srv, gport, tmpdir, logf = start_server()
        ghost = "localhost"
    dproc, dport = start_daemon(gport, ghost)
    print(f"[playtest] server :{gport}  daemon :{dport}  agents={len(personas)}  "
          f"turns~{args.turns}  model={args.model}")

    out = {}
    threads = []
    names = [p[0] for p in personas]
    try:
        for name, role, focus in personas:
            others = [n for n in names if n != name]
            t = threading.Thread(target=run_persona, args=(
                key, args.model, dport, name, role, focus, others, args.turns, out))
            t.start()
            threads.append(t)
            time.sleep(1.0)  # stagger connects
        for t in threads:
            t.join()
    finally:
        daemon_get(dport, "/quit?confirm=shutdown")
        procs = (dproc, srv) if srv is not None else (dproc,)
        for p in procs:
            p.terminate()
            try:
                p.wait(8)
            except Exception:
                p.kill()
        if logf is not None:
            logf.close()
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = Path(args.out or (PYR / f"playtest_report_{stamp}.md"))
    lines = [f"# Playtest report — {stamp}",
             f"\n{len(personas)} agents, ~{args.turns} actions each, model {args.model}.\n"]
    for name, role, _ in personas:
        lines.append(f"\n## {name} — {role}\n\n{out.get(name, '(no output)')}\n")
    out_path.write_text("\n".join(lines))
    print(f"[playtest] done. Report: {out_path}")


if __name__ == "__main__":
    main()
