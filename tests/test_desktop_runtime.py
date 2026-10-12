import json
import sqlite3
from contextlib import closing
from unittest.mock import Mock

import pytest
from desktop import runtime
from desktop.launcher import worker_command


def test_desktop_key_and_data_are_stable_without_cloud(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://invalid.invalid/test')
    monkeypatch.setenv('CLOUDINARY_URL', 'cloudinary://key:secret@example')
    monkeypatch.setenv('KWACART_TRUST_PROXY_SSL', '1')
    first = runtime.environment(tmp_path, 'one')
    second = runtime.environment(tmp_path, 'two')
    assert first['SECRET_KEY'] == second['SECRET_KEY']
    assert first['KWACART_SETUP_TICKET'] != second['KWACART_SETUP_TICKET']
    assert first['KWACART_DATA_DIR'] == str(tmp_path)
    assert first['DJANGO_SETTINGS_MODULE'] == 'config.settings.desktop'
    assert not {'DATABASE_URL', 'CLOUDINARY_URL', 'KWACART_TRUST_PROXY_SSL'} & first.keys()


def test_missing_key_with_existing_data_is_not_regenerated(tmp_path):
    (tmp_path / 'db.sqlite3').touch()
    with pytest.raises(RuntimeError, match='missing'):
        runtime.environment(tmp_path, 'ticket')
    assert not (tmp_path / '.kwacart-local-key').exists()


def test_update_preserves_database_media_key_and_backs_up_once(tmp_path, monkeypatch):
    runtime.environment(tmp_path, 'ticket')
    with closing(sqlite3.connect(tmp_path / 'db.sqlite3')) as db:
        db.execute('CREATE TABLE saved (value TEXT)')
        db.execute("INSERT INTO saved VALUES ('preserve')")
        db.commit()
    (tmp_path / 'media').mkdir()
    (tmp_path / 'media/upload.txt').write_text('keep')
    (tmp_path / 'installed-version.json').write_text(json.dumps({'version': '0.9.0'}))
    key = (tmp_path / '.kwacart-local-key').read_bytes()
    connections = []
    connect = sqlite3.connect
    def tracked_connect(path):
        connection = connect(path)
        connections.append(connection)
        return connection
    monkeypatch.setattr(runtime.sqlite3, 'connect', tracked_connect)
    runtime.prepare_update(tmp_path)
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            connection.execute('SELECT 1')
    backup = next((tmp_path / 'backups').iterdir())
    assert (backup / '.kwacart-local-key').read_bytes() == key
    assert (backup / 'media/upload.txt').read_text() == 'keep'
    with closing(sqlite3.connect(backup / 'db.sqlite3')) as db:
        assert db.execute('SELECT value FROM saved').fetchone() == ('preserve',)
    runtime.mark_updated(tmp_path)
    runtime.prepare_update(tmp_path)
    assert len(list((tmp_path / 'backups').iterdir())) == 1
    assert (tmp_path / '.kwacart-local-key').read_bytes() == key


def test_downgrade_refused(tmp_path):
    (tmp_path / 'installed-version.json').write_text(json.dumps({'version': '99.0.0'}))
    with pytest.raises(RuntimeError, match='older'):
        runtime.prepare_update(tmp_path)


def test_one_instance_and_crash_safe_lock_release(tmp_path):
    with runtime.exclusive_instance(tmp_path):
        with pytest.raises(RuntimeError, match='already running'):
            with runtime.exclusive_instance(tmp_path):
                pass
    with runtime.exclusive_instance(tmp_path):
        pass


def test_frozen_subprocess_dispatch_does_not_use_python_scripts(monkeypatch):
    monkeypatch.setattr(runtime.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(runtime.sys, 'executable', '/read only folder/KwaCart')
    assert worker_command(8088) == [
        '/read only folder/KwaCart', '--desktop-worker', '--port', '8088',
    ]


@pytest.mark.parametrize('base', ['', 'relative-folder'])
def test_empty_or_relative_data_base_never_uses_install_folder(monkeypatch, base):
    monkeypatch.setattr(runtime.sys, 'platform', 'linux')
    monkeypatch.delenv('KWACART_DESKTOP_DATA_DIR', raising=False)
    monkeypatch.setenv('XDG_DATA_HOME', base)
    assert runtime.data_directory() == runtime.Path.home() / '.local/share/kwacart'


def test_system_browser_restores_bundle_environment_even_on_error(monkeypatch):
    from desktop import browser
    monkeypatch.setenv('LD_LIBRARY_PATH', '/bundle/libs')
    monkeypatch.setenv('LD_LIBRARY_PATH_ORIG', '/system/libs')
    monkeypatch.setenv('DYLD_LIBRARY_PATH', '/bundle/mac-libs')
    monkeypatch.delenv('DYLD_LIBRARY_PATH_ORIG', raising=False)
    def failed_browser(url):
        assert runtime.os.environ['LD_LIBRARY_PATH'] == '/system/libs'
        assert 'DYLD_LIBRARY_PATH' not in runtime.os.environ
        raise OSError('No browser')
    monkeypatch.setattr(browser.webbrowser, 'open', failed_browser)
    with pytest.raises(OSError):
        browser.open_system_browser('http://127.0.0.1:8080/')
    assert runtime.os.environ['LD_LIBRARY_PATH'] == '/bundle/libs'
    assert runtime.os.environ['DYLD_LIBRARY_PATH'] == '/bundle/mac-libs'
