"""Optional captures must affect loader calls, never module imports."""

import importlib

import pytest


@pytest.mark.parametrize('name,loaders', [
    ('bomber_room0', {'load_capture': (), 'load_flags': (),
                      'load_script': (1,), 'load_scripts': ()}),
    ('bomber_lobby_shop', {'load_capture': (), 'load_script': (1,),
                           'load_scripts': ()}),
    ('bomber_lobby_tailor', {'load_capture': (), 'load_npc_script': (),
                             'load_weapon_script': ()}),
])
def test_capture_loaders_skip_only_when_called(name, loaders, tmp_path, monkeypatch):
    monkeypatch.setenv('PYREBORN_TEST_FIXTURES_DIR', str(tmp_path))
    try:
        module = importlib.import_module(f'.{name}_fixture', __package__)
        importlib.reload(module)
    except pytest.skip.Exception as exc:
        pytest.fail(f'Importing the loader skipped: {exc}')

    for loader, args in loaders.items():
        with pytest.raises(pytest.skip.Exception) as skipped:
            getattr(module, loader)(*args)
        assert str(skipped.value) == (
            f'{name} fixture data not present (uncommitted:'
            ' third-party server scripts)')
