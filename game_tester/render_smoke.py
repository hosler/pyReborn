"""Headless render smoke tests for pyreborn's pygame GameClient.

Covers the Tier 1-4 rendering/gameplay work in pygame_game.py / game/*.py /
sprites.py / gani.py / gs1_client.py: one check per implemented sub-item,
asserting both "renders without raising" and, where practical, the expected
internal state (draw lists, cached surfaces, ...) rather than pixels.

NOT covered here (game_tester/tier1_tests.py, tier2_tests.py, tier3_tests.py,
test_scenarios.py, exercise*.py, packet_coverage.py are owned by a different,
concurrent pass and intentionally untouched/unused for anything but the
reset_account_position() helper).

Run standalone:
    PYTHONPATH=../reborn-protocol python -m game_tester.render_smoke

Requires a GServer-v2 instance on localhost:14900 (override with
PYREBORN_TEST_HOST/PYREBORN_TEST_PORT) with testbot1/testbot2 accounts
(noverifylogin) and testbot1/testbot2 logged OUT beforehand.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import sys
import time
import traceback
from contextlib import ExitStack
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyreborn import Client
from pyreborn.pygame_game import GameClient
from pyreborn.game.constants import TILE_SIZE
from game_tester.login import level_ready, login_client
from game_tester.test_scenarios import reset_account_position

HOST = os.environ.get("PYREBORN_TEST_HOST", "localhost")
PORT = int(os.environ.get("PYREBORN_TEST_PORT", "14900"))

# A fresh account has no persisted PLPROP_MAGICPOINTS, which parses to the
# same 0 as Player.mp's dataclass default - so testing against a fresh
# account can't tell "the wire delivered 0" from "the wire delivered nothing
# and we're just seeing the default." Pin testbot1's MP to a distinguishing
# non-default value via the account fixture (see reset_account_position)
# instead. See tier3a_mp_ap_hud_active_over_the_wire.
_TESTBOT1_MP = 7

_CHECKS = []


def check(name):
    def deco(fn):
        _CHECKS.append((name, fn))
        return fn
    return deco


def _pump(game, n=8, dt=0.05):
    """Advance the game loop's non-pygame-event steps N times (mirrors
    GameClient.run()'s body minus _handle_events/_handle_input, which need a
    real display/keyboard)."""
    for _ in range(n):
        game.client.update(timeout=0.02)
        game._load_new_npcs()
        game._process_pending_warp()
        game._process_self_shoots()
        game.gs1.process_coroutines(dt)
        game.gs1.process_timeouts(dt)
        game.gs1.advance_input_frame()
        game._check_level_change()
        game._update_swimming_state()
        game._update_visual_position(dt)
        game._update_animations(dt)
        game._last_dt = dt
        game._render()


def _quiet_disconnect(client: Client) -> None:
    try:
        client.disconnect()
    except Exception:
        pass


def _login_and_settle(stack: ExitStack, account: str,
                      password: str = "testpass") -> Client:
    """Log one client in, registering its disconnect on `stack` first.

    Registering the teardown before the login can fail is the point: an
    assertion while getting the SECOND client in-game used to abandon the
    first one logged in on the server (main() only disconnected on the
    success path), so the next run's testbot1 login collided with it.

    Keeps its own settle loop instead of login.wait_for_level(): 30 fixed
    iterations, not a wall-clock deadline, so a loaded machine still gets the
    same number of chances at the board.
    """
    client = Client(HOST, PORT, version="6.037")
    stack.callback(_quiet_disconnect, client)
    outcome = login_client(client, account, password, timeout=5.0, settle=False)
    assert outcome.connected, f"{account}: connect failed"
    assert outcome.accepted, f"{account}: login failed"
    for _ in range(30):
        client.update(timeout=0.05)
        if level_ready(client):
            return client
    raise AssertionError(f"{account}: level never loaded")


# ---------------------------------------------------------------------------
# Tier 1: render the server-relayed world
# ---------------------------------------------------------------------------

@check("tier1a_server_bomb_renders")
def _t1a_bomb(game, c1, c2):
    # NOTE: end-to-end PLI_BOMBADD -> PLO_BOMBADD isn't exercisable against
    # this particular GServer-v2 instance: Level::addBombFromClient (server/
    # src/level/Level.cpp) special-cases hasNPCServer()==true (this build has
    # the embedded V8 NPC server) by converting the bomb into an item-NPC
    # pickup instead of relaying PLO_BOMBADD at all, unlike PLO_ARROWADD/
    # PLO_HORSEADD which always relay regardless of NPC-server state (see
    # msgPLI_ARROWADD/msgPLI_HORSEADD in PlayerClientPackets.cpp - no
    # hasNPCServer() check there). That's a server-config fact, not a bug in
    # this rendering pass, so this check drives client.bombs directly to
    # exercise the render path (already proven live for arrows/horses below).
    key = (float(int(c1.x)), float(int(c1.y)))
    c1.bombs[key] = {'owner_id': 999, 'x': key[0], 'y': key[1], 'power': 1, 'timer_ms': 3050}
    try:
        bomb = game._add_remote_bomb(c1.bombs[key], now=123.0)
        assert bomb in game.active_bombs
        assert bomb['source'] == 'remote'
    finally:
        c1.bombs.pop(key, None)


@check("tier1a_server_arrow_renders")
def _t1a_arrow(game, c1, c2):
    before = len(c1.arrows)
    c2.shoot_arrow(c2.x, c2.y, direction=2)
    _pump(game, 3)
    assert len(c1.arrows) > before, "client1.arrows didn't grow after bot2 fired"
    game._render_server_arrows()  # must not raise


@check("tier1a_server_horse_renders")
def _t1a_horse(game, c1, c2):
    before = dict(c1.horses)
    c2.mount_horse(c2.x, c2.y, image="horse.png", direction=2)
    try:
        _pump(game, 3)
        assert len(c1.horses) > len(before), "client1.horses didn't grow after bot2 added one"
        game._render_entities()  # horses draw through the entity depth-sort pass
    finally:
        # GServer-v2 horses otherwise live for `horselifetime` (default 30s,
        # server/src/level/Level.cpp:2220) at this exact (x, y): a horse left
        # behind by one run collides with the next run's `before` snapshot at
        # the same tile within that window and makes this check flaky. Always
        # clean up so back-to-back runs don't see each other's leftovers.
        c2.remove_horse(c2.x, c2.y)
        _pump(game, 2)


@check("tier1b_board_modify_patches_segment_surface_in_place")
def _t1b(game, c1, c2):
    # Post-refactor (per-segment cached surfaces, not one giant world
    # surface), the equivalent of "world_surface identity is preserved" is:
    # the owning segment's surface object is patched in place, and every
    # other cached segment is left completely untouched (same object, same
    # cache entry) rather than the whole world being rebuilt.
    level_name = c1._current_level_name
    segments = game._segments()
    entry_before = segments.get(level_name)
    assert entry_before is not None, "segment surface should already be built"
    surface_before = entry_before['surface']
    other_entries_before = {k: v for k, v in segments.items() if k != level_name}

    tx, ty = int(c1.x) % 60 + 1, int(c1.y) % 60 + 1
    new_tile = 5
    c2.modify_board(tx, ty, 1, 1, [new_tile])
    _pump(game, 6)

    entry_after = segments.get(level_name)
    assert entry_after is not None and entry_after['surface'] is surface_before, \
        "expected an in-place patch (Tier 1b), got a full segment rebuild"
    other_entries_after = {k: v for k, v in segments.items() if k != level_name}
    assert other_entries_after.keys() == other_entries_before.keys(), \
        "boardmodify should not add/evict any other cached segment"
    for k in other_entries_before:
        assert other_entries_after[k] is other_entries_before[k], \
            f"boardmodify should not touch/rebuild segment {k!r}'s cache entry"
    expected = game.tileset_mgr.get_tile_or_color(new_tile).get_at((1, 1))
    actual = surface_before.get_at((tx * TILE_SIZE + 1, ty * TILE_SIZE + 1))
    assert actual[:3] == expected[:3], \
        f"patched tile pixel mismatch: got {actual[:3]}, expected {expected[:3]}"


@check("tier1c_ground_items_render_and_clear_on_pickup")
def _t1c(game, c1, c2):
    game._render_items()  # empty client.items must not raise
    key = (float(int(c1.x)), float(int(c1.y)))
    c1.items[key] = 'greenrupee'
    game._render_items()
    assert key in c1.items
    del c1.items[key]
    game._render_items()
    assert key not in c1.items


@check("tier1d_board_layer_decode_shape")
def _t1d(game, c1, c2):
    # Simulated payload: the 2-byte w/h leftover parse_board_layer glues onto
    # 'tiles' (see render_world.py's _decode_board_layer_tiles docstring),
    # followed by an all-zero 64x64 tile grid.
    raw = bytes([32, 32]) + bytes(8192)
    tiles = game._decode_board_layer_tiles(raw)
    assert len(tiles) == 4096
    assert all(t == 0 for t in tiles)


# Real Bomber Arena (bomber.eevul.net) gani fixtures, captured live and
# checked into cache/bomber_arena/assets - used below to prove the PARAMn
# frame-token substitution and embedded-SCRIPT fallback against the actual
# server assets rather than a synthetic stand-in.
_BOMBER_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "cache", "bomber_arena", "assets")


@check("tier1e_bomber_arena_bomb_param_substitution")
def _t1e(game, c1, c2):
    # eye_bomber_bomb.gani (Bomber Arena's DrawBomb()) picks its body/decal
    # sprite via "PARAM1"/"PARAM3" frame tokens instead of literal sprite ids,
    # and its decal image via a SPRITE whose layer is the literal "PARAM2"
    # (see gani.py's _parse_frame_line and render_entities.py's
    # _render_animated_entity). Without support for either, the bomb's body
    # and decal silently vanish and only the fuse spark (a literal sprite id)
    # draws.
    path = os.path.join(_BOMBER_ASSETS, "eye_bomber_bomb.gani")
    gani = game.gani_parser.parse_file(Path(path))
    assert gani is not None, "eye_bomber_bomb.gani should parse"
    assert gani.has_script is False, "this gani has no embedded SCRIPT block"

    frame = gani.get_frame(0, 0)
    assert frame is not None
    token_ids = {sid for sid, _, _ in frame.sprites if isinstance(sid, str)}
    assert token_ids == {"PARAM1", "PARAM3"}, f"expected PARAM1/PARAM3 tokens, got {token_ids}"

    from pyreborn.gani import AnimationState
    anim = AnimationState(game.gani_parser)
    anim.gani = gani
    anim.direction = 0
    anim.frame = 0

    # No params and no DEFAULTPARAMn happens not to apply here (both DEFAULTs
    # exist), so resolution should fall back to them rather than raising.
    game._render_animated_entity(0, 0, anim, {})  # must not raise

    # A live showani call's params (per arenaGUI.gs1's DrawBomb) should
    # resolve PARAM1 (body sprite 50-63), PARAM2 (decal image), and PARAM3
    # (decal sprite 100-120) - i.e. the actual bomb + decal draw, not just
    # the fuse.
    equip = game._showani_param_equip([56.0, "eye_bombsprites-dec1.png", 112.0])
    assert equip == {
        'param1': 56.0, 'param2': "eye_bombsprites-dec1.png",
        'param2_image': "eye_bombsprites-dec1.png", 'param3': 112.0,
    }
    game._render_animated_entity(0, 0, anim, equip)  # must not raise


@check("tier1f_bomber_arena_explosion_script_fallback")
def _t1f(game, c1, c2):
    # eye_bomber_expl.gani's own ANI frames are a near-blank placeholder -
    # the real visual is an embedded SCRIPT block (light/particle showimg
    # calls) this engine doesn't execute. _render_showani_rec must detect
    # that (has_script) and substitute a synthesized burst rather than
    # drawing nothing.
    path = os.path.join(_BOMBER_ASSETS, "eye_bomber_expl.gani")
    gani = game.gani_parser.parse_file(Path(path))
    assert gani is not None, "eye_bomber_expl.gani should parse"
    assert gani.has_script is True, "expected the embedded SCRIPT block to be flagged"

    rec = {'x': 21.0, 'y': 21.0, 'gani': gani.name, 'params': [1.2, 0.0]}
    from pyreborn.gani import AnimationState
    rec['_anim'] = anim = AnimationState(game.gani_parser)
    anim.gani = gani
    game._render_scripted_gani_fallback(rec)  # must not raise while 'on' > 0

    rec['params'] = [0.0, 0.0]
    game._render_scripted_gani_fallback(rec)  # must not raise once faded out


# ---------------------------------------------------------------------------
# Tier 2: player appearance correctness
# ---------------------------------------------------------------------------

def _other_player_props(viewer, target):
    """`target`'s props dict as seen by `viewer` (e.g. client2-as-seen-by-
    client1). The dict starts empty per-player and only gains keys for props
    the wire actually delivered, so a key's presence - not just its value -
    is proof the server sent that PLPROP.

    Matches by account name rather than "the other entry in viewer.players",
    because a real GServer-v2 injects a pseudo-player for its embedded
    NPC-Server into every level's player list (nickname "NPC-Server
    (Server)", account "(npcserver)") alongside real clients. That entry is
    sent with loginPropsRC (GServer-v2 server/include/player/PlayerProps.h),
    not loginPropsClientOthers, so it never carries colors/mp/ap - grabbing
    it by "next(iter(...))" instead of the real bot silently made these
    checks fail for the wrong reason.
    """
    assert viewer.players, "expected client.players to contain the other bot's entry"
    target_account = target.player.account
    for entry in viewer.players.values():
        if entry.get('account') == target_account or entry.get('nickname') == target_account:
            return entry
    raise AssertionError(
        f"no other-player entry for account {target_account!r} in {viewer.players!r}")


@check("tier2a_recolor_noop_without_colors")
def _t2a_noop(game, c1, c2):
    plain = game.sprite_mgr.get_sprite('body.png', 0, 0, 16, 16)
    via_recolor = game.sprite_mgr.get_sprite_recolored('body.png', None, 0, 0, 16, 16)
    assert (plain is None) == (via_recolor is None), \
        "get_sprite_recolored(colors=None) should behave like get_sprite()"


@check("tier2a_recolor_active_with_colors")
def _t2a_active(game, c1, c2):
    sheet = game.sprite_mgr.load_sheet('body.png')
    if sheet is None:
        return  # body.png not in this asset set - inconclusive, not a failure
    sprite = game.sprite_mgr.get_sprite_recolored('body.png', [4, 0, 10, 2, 18], 0, 0, 16, 16)
    assert sprite is not None
    # Cache hit path must not raise / must return the same object.
    sprite2 = game.sprite_mgr.get_sprite_recolored('body.png', [4, 0, 10, 2, 18], 0, 0, 16, 16)
    assert sprite2 is sprite


@check("tier2a_colors_prop_active_over_the_wire")
def _t2a_wire(game, c1, c2):
    # PLPROP_COLORS (13) is now parsed by packets.py's parse_player_props/
    # parse_other_player into Player.colors / the other-player props dict,
    # and both pygserver and GServer-v2 send it on login and on the
    # other-player announce. This confirms the whole pipe end-to-end rather
    # than just the sprites.py unit behavior covered above.
    #
    # The wire width is 5 (classic) or 8 (new-world) bytes and is a
    # server-wide mode, not something derivable from the client's protocol
    # version (reborn-protocol-docs/docs/protocol/version-gated-behavior.md,
    # "PLPROP_COLORS Width: Two Independent Switches"; confirmed live - this
    # GServer-v2 instance always sends 5 regardless of the v6.037 client
    # version, because its isNewWorldMode() is hardwired false). packets.py's
    # parse_player_props/parse_other_player self-correct the width per
    # packet (_parse_with_colors_retry), so assert one of the two real
    # widths rather than a specific one.
    assert isinstance(c1.player.colors, list) and len(c1.player.colors) in (5, 8), \
        f"expected a 5- or 8-value colors list on the local player, got {c1.player.colors!r}"
    other = _other_player_props(c1, c2)
    assert isinstance(other.get('colors'), list) and len(other['colors']) in (5, 8), \
        f"expected client2's announced props to carry a colors list, got {other.get('colors')!r}"
    equip = {'body_image': 'body.png', 'colors': other['colors']}
    if game.sprite_mgr.load_sheet('body.png') is not None:
        assert game.sprite_mgr.get_sprite_recolored(
            equip['body_image'], equip['colors'], 0, 0, 16, 16) is not None


@check("tier2b_2d_attr_layer_generic_lookup")
def _t2b(game, c1, c2):
    from pyreborn.gani import AnimationState, Gani, GaniSprite, GaniFrame
    anim = AnimationState(game.gani_parser)
    gani = Gani(name="_smoke_hat_test")
    gani.sprites[0] = GaniSprite(0, "ATTR2", 0, 0, 8, 8)
    gani.directions = [[GaniFrame(sprites=[(0, 0, 0)])] for _ in range(4)]
    gani.single_dir = False
    anim.gani = gani
    anim.direction = 2
    anim.frame = 0
    # No equipment override and no gani default for ATTR2 -> must skip the
    # sprite cleanly (no exception), matching the "continue" branch.
    game._render_animated_entity(0, 0, anim, {})
    # With an override, it must resolve through the generic equip_key path
    # (exercised via get_sprite so a missing image is also a clean no-op).
    game._render_animated_entity(0, 0, anim, {'attr2_image': 'does_not_exist.png'})


@check("tier2c_continuous_resumes_frame_after_interruption")
def _t2c(game, c1, c2):
    from pyreborn.gani import AnimationState
    anim = AnimationState(game.gani_parser)
    anim.set_animation("walk", 2)
    if anim.gani is None or not anim.gani.continuous:
        return  # no CONTINUOUS walk.gani in this asset set - inconclusive
    for _ in range(5):
        anim.update(0.05)
    frame_before = anim.frame
    anim.set_animation("sword", 2)   # interrupt
    for _ in range(3):
        anim.update(0.05)
    anim.set_animation("walk", 2)    # resume
    assert anim.frame == frame_before, \
        f"CONTINUOUS gani restarted at {anim.frame}, expected resume at {frame_before}"


# ---------------------------------------------------------------------------
# Tier 3: HUD + feedback
# ---------------------------------------------------------------------------

@check("tier3a_mp_ap_hud_active_over_the_wire")
def _t3a(game, c1, c2):
    # PLPROP_MAGICPOINTS(26)/PLPROP_ALIGNMENT(32) are parsed into Player.mp/
    # .ap and the other-player props dict (packets.py). pygserver sends both
    # on login and on the other-player announce, but a real GServer-v2 does
    # not send MP to other players at all: in server/include/player/
    # PlayerProps.h, both loginPropsClientOthers[26] (login-time announce)
    # and clientPropsSharedLocal[26] (change broadcast) are false for
    # MAGICPOINTS, while [32] (ALIGNMENT) is true in both - i.e. it's a
    # deliberate, permanent omission for MP specifically, not an ordering or
    # parser gap. So MP's only wire-delivery proof available on any server is
    # the SELF PLO_PLAYERPROPS packet (loginPropsClientSelf[26]=true);
    # AP's is verifiable on the other-player dict on both servers.
    #
    # A fresh account's MP is 0, same as Player.mp's dataclass default, so
    # asserting isinstance(int) alone can't tell "parsed from the wire" from
    # "never touched" - the account fixture pins testbot1's MP to a
    # non-default value (_TESTBOT1_MP) so this is a real assertion.
    assert c1.player.mp == _TESTBOT1_MP, \
        f"expected self.mp == {_TESTBOT1_MP} (from the account fixture), got {c1.player.mp!r}"
    other = _other_player_props(c1, c2)
    assert 'ap' in other, \
        f"expected client2's announced props to carry 'ap', got {sorted(other.keys())}"
    assert isinstance(c1.player.ap, int)
    game.hud.update()
    game.hud.draw()  # must not raise now that mp/ap are populated


@check("tier3b_server_text_and_rpg_window_wired")
def _t3b(game, c1, c2):
    game.client.on_server_text("hello from the server")
    assert any("hello from the server" in m for m in game.chat_messages)
    # PLO_RPGWINDOW is the login greeting in practice; it goes to the chat
    # log NON-modally (the real client doesn't gate input on it), so the
    # modal dialogue box must stay untouched (game/setup.py on_rpg_window).
    game.dialogue_text = None
    game.client.on_rpg_window(["line one", "line two"])
    assert game.dialogue_text is None
    assert any("line one" in m for m in game.chat_messages)
    assert any("line two" in m for m in game.chat_messages)


@check("tier3c_status_label_resolves_from_status_list")
def _t3c(game, c1, c2):
    game.client.status_list = ["here", "away", "busy"]
    assert game._status_label(1) == "away"
    assert game._status_label(99) == ""  # out of range -> no guess
    game.client.status_list = []


@check("tier3d_seteffect_sets_and_clears_tint")
def _t3d(game, c1, c2):
    game.gs1.on_seteffect(0.2, 0.4, 0.8, 0.5)
    assert game.screen_tint is not None
    game._render_screen_tint()  # must not raise
    game.gs1.on_seteffect(0, 0, 0, 0)
    assert game.screen_tint is None


@check("tier3e_showpoly_renders")
def _t3e(game, c1, c2):
    # showpoly/showpoly2 are unified into the same imgs layer table as
    # showimg/showani/showtext (gs1_client.py), so they render through
    # _render_npc_layers -> _render_showpoly_rec like any other layer.
    game._render_npc_layers({0: {'poly': [1, 1, 5, 1, 5, 5, 1, 5], 'vis': 4}}, over=True)  # must not raise
    game._render_npc_layers({0: {'poly': [1, 1], 'vis': 4}}, over=True)  # too few points - must be skipped, not raise
    game._render_npc_layers({0: {'poly': [1, 1, 0, 5, 1, 0, 5, 5, 0, 1, 5, 0], 'poly_dim': 3, 'vis': 4}}, over=True)  # dim-3 (showpoly2) - must not raise


@check("tier3f_swim_enter_leave_hooks")
def _t3f(game, c1, c2):
    orig = game._check_water_at_position
    try:
        game.current_anim_name = "idle"
        game.is_swimming = False
        game._check_water_at_position = lambda x, y: True
        game._update_swimming_state()
        assert game.is_swimming is True
        assert game.current_anim_name == "swim"

        game._check_water_at_position = lambda x, y: False
        game._update_swimming_state()
        assert game.is_swimming is False
        assert game.current_anim_name == "idle"
    finally:
        game._check_water_at_position = orig


@check("tier3g_showpoly_dispatch_recolors_and_orders_like_other_layers")
def _t3g(game, c1, c2):
    # End-to-end: a real GS1 script's showpoly/showpoly2 + changeimgcolors +
    # changeimgvis land on the NPC's imgs table exactly like showimg/showani/
    # showtext (gs1_client.py's _dispatch), so the renderer's vis>=2-over-
    # player split and per-layer colour tinting both apply to polygons too.
    npc_id = 9001
    game.client.npcs[npc_id] = {'x': 30.0, 'y': 30.0, 'nickname': 'polytest'}
    try:
        game.gs1.load_script(f"npc_{npc_id}", """
            if (playerenters) {
              showpoly 0,{30,30,34,30,34,34,30,34};
              changeimgcolors 0,1,0,0,0.5;
              changeimgvis 0,1;
              showpoly2 1,{31,31,0,33,31,0,33,33,0};
            }
        """, npc_id=npc_id)
        game.gs1.trigger_npc_event(npc_id, 'playerenters')

        npc = game.client.npcs[npc_id]
        imgs = npc.get('imgs') or {}
        assert 0 in imgs and 1 in imgs, f"expected layers 0 and 1, got {sorted(imgs)}"
        assert imgs[0]['poly'] == [30, 30, 34, 30, 34, 34, 30, 34]
        assert imgs[0]['colors'] == (1, 0, 0, 0.5), imgs[0]['colors']
        assert imgs[0]['vis'] == 1, "changeimgvis must update the shared layer record"
        assert imgs[1].get('poly_dim') == 3, "showpoly2 must record a 3-wide stride"

        game._render_npc(30.0, 30.0, npc, npc_id)  # must not raise
    finally:
        del game.client.npcs[npc_id]
        game.gs1._progs.pop(f"npc_{npc_id}", None)
        game.gs1.scripts.pop(f"npc_{npc_id}", None)


# ---------------------------------------------------------------------------
# Tier 4: animated tiles + bigmap
# ---------------------------------------------------------------------------

@check("tier4a_animated_tiles_render")
def _t4a(game, c1, c2):
    game._render_animated_tiles()  # must not raise with or without water tiles
    # Force a synthetic entry through the real cache path and confirm the
    # shimmer surface builds without error.
    for step in range(4):
        surf = game._get_shimmer_tile(0, step)
        assert surf is not None


@check("tier4b_bigmap_fallback_is_a_noop_without_data")
def _t4b(game, c1, c2):
    game.client.bigmap_info = {}
    game._ensure_bigmap_surface()  # must not raise
    game.client.bigmap_info = {'image': 'does_not_exist_12345.png',
                               'levels_file': '', 'x': 0.0, 'y': 0.0}
    game._ensure_bigmap_surface()  # missing image -> request + no-op, not raise


def main() -> int:
    reset_account_position("testbot1", mp=_TESTBOT1_MP)
    reset_account_position("testbot2")

    with ExitStack() as stack:
        return _run_checks(stack)


def _run_checks(stack: ExitStack) -> int:
    client1 = _login_and_settle(stack, "testbot1")

    # Environment guard: reset_account_position() above must actually reach
    # THIS server's account store (GSERVER_ACCOUNTS_DIR / PYGSERVER_ACCOUNTS_DIR
    # env overrides). When it doesn't - the classic trap is the long-running
    # funtimes-pygserver on :14900, whose accounts live in
    # funtimes-pygserver/accounts, a dir neither default points at - the bots
    # start wherever that server last persisted them (the chicken .gmap world,
    # testbot2 drained to 0 arrows, MP unpinned) and exactly three checks fail
    # ENVIRONMENTALLY, not because the renderer drifted:
    #   tier1a_server_arrow_renders   (server consumes ammo before relaying;
    #                                  0 arrows -> no PLO_ARROWADD at all)
    #   tier1b_board_modify_...       (packet-7 delta on a gmap gets routed by
    #                                  a stale _pending_level_name, so the
    #                                  active segment is never patched)
    #   tier3a_mp_ap_hud_...          (the mp=7 fixture pin never landed)
    # Detect that up front and say so, instead of letting those failures
    # masquerade as regressions. Root-caused 2026-07-23: all 22 checks pass
    # against the pytest fixture server (conftest.py's throwaway pygserver
    # with PYGSERVER_ACCOUNTS_DIR pointed at it) on the same code.
    if (client1._current_level_name != "onlinestartlocal.nw"
            or client1.player.mp != _TESTBOT1_MP):
        print(f"[ENV WARNING] account fixture did not take on {HOST}:{PORT} "
              f"(level={client1._current_level_name!r}, mp={client1.player.mp!r}; "
              f"expected 'onlinestartlocal.nw' / mp={_TESTBOT1_MP}).\n"
              "  reset_account_position() can't reach this server's accounts "
              "dir - expect environmental FAILs in tier1a_server_arrow_renders, "
              "tier1b_board_modify_patches_segment_surface_in_place and "
              "tier3a_mp_ap_hud_active_over_the_wire.\n"
              "  Run against the pytest pygserver fixture (see conftest.py) or "
              "a GServer-v2 whose accounts dir GSERVER_ACCOUNTS_DIR points at.")

    game = GameClient(client1)
    game.running = True
    game.visual_x, game.visual_y = game.client.x, game.client.y
    game._load_npc_scripts()
    game._trigger_playerenters()
    game.npc_handler.update_npcs()
    game._gs1_level = game.client._current_level_name
    game.roster_ready_time = time.time()
    _pump(game, 10)

    client2 = _login_and_settle(stack, "testbot2")
    client2.warp_to_level(client1._current_level_name, client1.x, client1.y)
    for _ in range(10):
        client2.update(timeout=0.05)
    _pump(game, 5)

    ok = True
    for name, fn in _CHECKS:
        try:
            fn(game, client1, client2)
            print(f"[PASS] {name}")
        except AssertionError as e:
            ok = False
            print(f"[FAIL] {name}: {e}")
        except Exception:
            ok = False
            print(f"[FAIL] {name}: unexpected exception")
            traceback.print_exc()

    # Both clients are disconnected by the ExitStack main() owns.
    print("ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
