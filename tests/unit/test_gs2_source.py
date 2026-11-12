"""Classic source transport must select the appropriate script engine."""

import logging
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from reborn_protocol.gs2.compiler import Gs2Compiler, find_compiler
from reborn_protocol.gs2.detect import looks_like_gs2
from pyreborn.game.callbacks import client_callbacks
from pyreborn.game.setup import SetupMixin
from pyreborn.client import Client
from pyreborn.packets import PacketID

from .sibling_repos import PROTOCOL_FIXTURES, pygserver_root

SERVER = pygserver_root()
GS2_SOURCE = 'function onCreated() { player.chat = "ready"; }'
GS1_SOURCE = 'if (playerenters) { message ready; }'


def path_root(path):
    for root in (PROTOCOL_FIXTURES.parents[1], SERVER, Path(__file__).resolve().parents[2]):
        if root in path.parents:
            return root.parent
    return path.anchor and Path(path.anchor)


def corpus_cases():
    """Label fixture sources independently of the detector under test."""
    cases = []
    for path in sorted(PROTOCOL_FIXTURES.rglob('*.gs2')):
        cases.append(pytest.param(path.read_text(), True,
                                 id=str(path.relative_to(path_root(path)))))
    # These fixture weapons/classes are explicitly GS2 QA scripts.
    for directory in ('weapons', 'scripts'):
        for path in sorted((SERVER / directory).glob('*.txt')):
            source = path.read_text()
            if directory == 'weapons':
                source = re.search(r'(?ms)^SCRIPT\n(.*?)^SCRIPTEND', source)[1]
            cases.append(pytest.param(source, True,
                                     id=str(path.relative_to(path_root(path)))))
    # Level NPC blocks and animation SCRIPT blocks contain source, not the
    # surrounding level/animation metadata. Empty blocks have no language.
    for root in (SERVER / 'levels', Path(__file__).resolve().parents[1] / 'fixtures'):
        for path in sorted(root.rglob('*')):
            if path.suffix not in ('.nw', '.gani', '.gs1'):
                continue
            source = path.read_text(encoding='latin-1')
            if path.suffix == '.gs1':
                scripts = [source]
            else:
                pattern = (r'(?ms)^NPC [^\n]*\n(.*?)^NPCEND' if path.suffix == '.nw'
                           else r'(?ms)^SCRIPT\n(.*?)^SCRIPTEND')
                scripts = re.findall(pattern, source)
            for index, script in enumerate(scripts):
                if script.strip():
                    cases.append(pytest.param(
                        script, False,
                        id=f'{path.relative_to(path_root(path))}#{index}'))
    return cases


@pytest.mark.parametrize('source,expected', corpus_cases())
def test_detector_corpus(source, expected):
    assert looks_like_gs2(source) is expected


@pytest.mark.parametrize('source,expected', [
    (GS2_SOURCE, True),
    ('//#CLIENTSIDE\nfunction helper() { hide(); }', False),
    ('temp.value = 2;', True),
    ('this.value = 2;', False),
    ('player.chat = "ready";', False),
    ('client.value = 2;', False),
    ('value = "a" @ "b";', False),
    ('value = left @ right;', False),
    ('temp.obj = new TStaticVar();', True),
    ('new GuiControl("window") {}', True),
    (GS1_SOURCE, False),
    ('if (created) { this.value = 2; }', False),
    ('message #v(this.value);', False),
    ('setstring client.value,#s(client.other);', False),
    ('timeout = 0.05; this.value = 2;', False),
    ('message this.value;', False),
    ('{ hide; }', False),
    ('if (timeout) { this.value = 2; timeout = 1; }', False),
    ('if (timeout) { this.value = 2; }', False),
    ('message user@example.com;', False),
    ('function helper() { message ready; }', False),
    ('// function onCreated() { temp.x = 1; }\nhide;', False),
    ('/* function onCreated() {} */ hide;', False),
    ('message "function onCreated() { temp.x = 1; }";', False),
    ('message "player.chat = 1;";', False),
    ('', False),
])
def test_detector_rules(source, expected):
    assert looks_like_gs2(source) is expected


@pytest.fixture
def game(monkeypatch):
    monkeypatch.delenv('PYREBORN_GS2_SOURCE', raising=False)
    compiler = Mock(last_error='parse error: expected expression\nsecond line')
    compiler.compile.return_value = b'compiled'
    monkeypatch.setattr(client_callbacks, 'Gs2Compiler', Mock(return_value=compiler))
    client = Client('localhost', 14900)
    client.send_level_chat = Mock()
    client.gs2_bytecode = {'weapon': {}, 'npc': {}}
    client.on_gs2_bytecode = Mock()
    client.current_level_name = 'test.nw'
    game = SimpleNamespace(
        client=client, gs1=Mock(scripts={}), sound_mgr=SimpleNamespace(),
        _request_asset=Mock(), _gs1_level='test.nw', npc_handler=Mock())
    game.previous_weapon_del = Mock()
    client.on_packet[PacketID.PLO_NPCWEAPONDEL] = game.previous_weapon_del
    client_callbacks.wire_client_callbacks(game)
    game.compiler = compiler
    return game


def test_weapon_gs2_uses_bytecode_callback(game):
    game.client.on_weapon_add('source-weapon', {'script': GS2_SOURCE})
    game.compiler.compile.assert_called_once_with(GS2_SOURCE, 'source-weapon')
    game.client.on_gs2_bytecode.assert_called_once_with(
        'weapon', 'source-weapon', b'compiled')
    assert game.client.gs2_bytecode['weapon']['source-weapon'] == b'compiled'
    game.gs1.load_weapon.assert_not_called()
    game.gs1.trigger_event.assert_not_called()


def test_weapon_gs1_uses_only_gs1(game):
    game.client.on_weapon_add('classic', {'script': GS1_SOURCE})
    game.gs1.load_weapon.assert_called_once_with('classic', GS1_SOURCE)
    game.gs1.trigger_event.assert_any_call('created', name='weapon_classic')
    game.gs1.trigger_event.assert_any_call('playerenters', name='weapon_classic')
    game.compiler.compile.assert_not_called()
    game.client.on_gs2_bytecode.assert_not_called()


def test_compile_failure_warns_once_per_weapon(game, caplog):
    game.compiler.compile.return_value = None
    with caplog.at_level(logging.WARNING):
        game.client.on_weapon_add('broken', {'script': GS2_SOURCE})
        game.client.on_weapon_add('broken', {'script': GS2_SOURCE + '\n'})
        game.client.on_weapon_add('broken', {'script': GS2_SOURCE})
    assert len(caplog.records) == 1
    assert 'parse error: expected expression' in caplog.text
    assert 'second line' not in caplog.text
    assert 'GS2-looking weapon broken:' in caplog.text
    assert '; running it in the GS1 engine' in caplog.text
    assert game.gs1.load_weapon.call_args_list == [
        call('broken', GS2_SOURCE), call('broken', GS2_SOURCE + '\n'),
        call('broken', GS2_SOURCE)]
    game.client.on_gs2_bytecode.assert_not_called()


def test_missing_compiler_warns_once(game, monkeypatch, caplog):
    compiler = Gs2Compiler()
    compiler.binary = None
    monkeypatch.setattr(client_callbacks, 'Gs2Compiler', lambda: compiler)
    with caplog.at_level(logging.WARNING):
        for _ in range(2):
            game.client.on_weapon_add('missing', {'script': GS2_SOURCE})
    assert len(caplog.records) == 1
    assert 'compiler unavailable' in caplog.text
    assert game.gs1.load_weapon.call_args_list == [call('missing', GS2_SOURCE)] * 2
    game.client.on_gs2_bytecode.assert_not_called()


def test_opt_out_falls_back_to_gs1_and_warns_once(game, monkeypatch, caplog):
    monkeypatch.setenv('PYREBORN_GS2_SOURCE', '0')
    for _ in range(2):
        game.client.on_weapon_add('disabled', {'script': GS2_SOURCE})
    assert len(caplog.records) == 1
    assert 'PYREBORN_GS2_SOURCE=0' in caplog.text
    game.compiler.compile.assert_not_called()
    assert game.gs1.load_weapon.call_args_list == [call('disabled', GS2_SOURCE)] * 2
    game.client.on_gs2_bytecode.assert_not_called()


@pytest.mark.parametrize('method', ['_load_npc_scripts', '_load_new_npcs'])
def test_npc_source_uses_same_bytecode_callback(game, method):
    game.client.npcs[7] = {'script': GS2_SOURCE}
    game._load_weapon_scripts = Mock()
    getattr(SetupMixin, method)(game)
    getattr(SetupMixin, method)(game)
    game.client.on_gs2_bytecode.assert_called_once_with('npc', 7, b'compiled')
    game.gs1.load_script.assert_not_called()
    # A new NPC with a reused id needs a fresh VM, even with identical source.
    game.client.npcs[7] = {'script': GS2_SOURCE}
    getattr(SetupMixin, method)(game)
    assert game.client.on_gs2_bytecode.call_count == 2


def test_weapon_reload_does_not_feed_gs2_to_gs1(game):
    game.client.weapons['source'] = {'script': GS2_SOURCE}
    SetupMixin._load_weapon_scripts(game)
    SetupMixin._load_weapon_scripts(game)
    game.client.on_gs2_bytecode.assert_called_once_with('weapon', 'source', b'compiled')
    game.gs1.load_weapon.assert_not_called()


def test_weapon_delete_forgets_attempt_and_identical_readd_loads_vm(game):
    weapon = {'script': GS2_SOURCE}
    game.client.weapons['source'] = weapon
    game.client.on_weapon_add('source', weapon)
    game.client.on_weapon_add('source', weapon)
    game.client.on_gs2_bytecode.assert_called_once()

    Client._handle_packet(game.client, PacketID.PLO_NPCWEAPONDEL, b'source')
    assert 'source' not in game.client.weapons
    assert ('weapon', 'source') not in game._gs2_source_attempts
    game.previous_weapon_del.assert_called_once_with(b'source')

    game.client.weapons['source'] = weapon
    game.client.on_weapon_add('source', weapon)
    assert game.client.on_gs2_bytecode.call_args_list == [
        call('weapon', 'source', b'compiled')] * 2
    game.gs1.load_weapon.assert_not_called()


def test_weapon_delete_before_source_attempt_is_harmless(game):
    Client._handle_packet(game.client, PacketID.PLO_NPCWEAPONDEL, b'unknown')
    game.previous_weapon_del.assert_called_once_with(b'unknown')


def test_cached_compile_failure_keeps_falling_back(game, caplog):
    game.compiler.compile.return_value = None
    for _ in range(2):
        game.client.on_weapon_add('broken', {'script': GS2_SOURCE})
    game.compiler.compile.assert_called_once_with(GS2_SOURCE, 'broken')
    assert game.gs1.load_weapon.call_args_list == [call('broken', GS2_SOURCE)] * 2
    assert len(caplog.records) == 1


def test_warning_is_per_weapon_name(game, caplog):
    game.compiler.compile.return_value = None
    for name in ('first', 'second', 'first'):
        game.client.on_weapon_add(name, {'script': GS2_SOURCE})
    assert len(caplog.records) == 2


def test_gs1_veto_prevents_compiling_mixed_source(game):
    script = 'if (created) { hide; }\n//#CLIENTSIDE\n' + GS2_SOURCE
    game.client.on_weapon_add('mixed', {'script': script})
    game.gs1.load_weapon.assert_called_once_with('mixed', script)
    game.compiler.compile.assert_not_called()


@pytest.mark.parametrize('script,expected', [
    ('function serverHelper() {}\n//#CLIENTSIDE\n' + GS2_SOURCE, GS2_SOURCE),
    ('//#CLIENTSIDE\xa7' + GS2_SOURCE, GS2_SOURCE),
    ('function onCreated() { this.text = "//#CLIENTSIDE"; }',
     'function onCreated() { this.text = "//#CLIENTSIDE"; }'),
])
def test_clientside_split_and_classic_line_separators(game, script, expected):
    game.client.on_weapon_add('source', {'script': script})
    game.compiler.compile.assert_called_once_with(expected, 'source')


def test_existing_runtime_receives_source_via_deferred_queue(game):
    from pyreborn.gs2_client import ClientGS2

    source = PROTOCOL_FIXTURES / 'gs2' / 'vm' / '01_arith.gs2'
    blob = source.with_suffix('.gs2bc').read_bytes()
    game.compiler.compile.return_value = blob
    game.client._in_update = True
    runtime = ClientGS2(game.client).attach()
    game.client.on_weapon_add('source', {'script': source.read_text()})
    assert 'source' not in runtime.vms['weapon']
    assert runtime._pending_bytecode == [('weapon', 'source', blob)]
    game.client._in_update = False
    runtime.pump_pending()
    assert runtime.vms['weapon']['source'].has_function('addNums')
    game.gs1.load_weapon.assert_not_called()


@pytest.mark.skipif(find_compiler() is None, reason='gs2test compiler not built')
def test_real_compiler_matches_committed_bytecode():
    source = PROTOCOL_FIXTURES / 'gs2' / 'vm' / '01_arith.gs2'
    compiler = Gs2Compiler()
    blob = compiler.compile(source.read_text(), source.stem)
    assert blob == source.with_suffix('.gs2bc').read_bytes(), compiler.last_error
