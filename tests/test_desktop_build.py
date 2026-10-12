from pathlib import Path
from unittest.mock import Mock
import pytest
from scripts import build_desktop as build


@pytest.mark.parametrize('private_file', ['.env', 'db.sqlite3'])
def test_build_refuses_workspace_data(tmp_path, monkeypatch, private_file):
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    (tmp_path / private_file).touch()
    run = Mock()
    monkeypatch.setattr(build.subprocess, 'run', run)
    with pytest.raises(SystemExit, match='clean public checkout'):
        build.main()
    run.assert_not_called()


def test_bundler_inspects_desktop_settings_with_disposable_build_state(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    monkeypatch.setattr(build.sys, 'base_prefix', str(tmp_path))
    monkeypatch.setenv('SECRET_KEY', 'do-not-bundle-developer-key')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://invalid.invalid/test')
    (tmp_path / 'LICENSE.txt').write_text('Python licence', encoding='utf-8')
    (tmp_path / 'packaging').mkdir()
    (tmp_path / 'packaging/native-notices.txt').write_text('Native notices', encoding='utf-8')
    (tmp_path / 'LICENSE').write_text('AGPL')
    (tmp_path / 'NOTICE').write_text('Attribution')
    (tmp_path / 'dist/KwaCart').mkdir(parents=True)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if 'PyInstaller' in command:
            env = kwargs['env']
            assert env['DJANGO_SETTINGS_MODULE'] == 'config.settings.desktop'
            assert Path(env['KWACART_DATA_DIR']).is_dir()
            assert 'DATABASE_URL' not in env
            assert env['SECRET_KEY'] != 'do-not-bundle-developer-key'
    monkeypatch.setattr(build.subprocess, 'run', run)
    monkeypatch.setattr(build.subprocess, 'check_output', Mock(return_value='Third-party terms'))
    build.main()
    assert len(calls) == 2
    assert not Path(calls[-1][1]['env']['KWACART_DATA_DIR']).exists()
    assert (tmp_path / 'dist/KwaCart/THIRD_PARTY_NOTICES.txt').is_file()
