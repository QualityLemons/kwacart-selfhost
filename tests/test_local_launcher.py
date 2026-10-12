"""Fast unit checks; real native installation is in source-launchers.yml."""
from argparse import Namespace
from pathlib import Path
import socket
from unittest.mock import Mock

import pytest

import start_kwacart as launcher


def test_private_runtime_installs_once_and_retries_changed_requirements(tmp_path, monkeypatch):
    root = tmp_path / 'Toolkit with spaces'
    root.mkdir()
    requirements = root / 'requirements.txt'
    requirements.write_text('django==6.0.8\n')

    def fake_create(path):
        python = path / ('Scripts/python.exe' if launcher.os.name == 'nt' else 'bin/python')
        python.parent.mkdir(parents=True)
        python.touch()

    create = Mock(side_effect=fake_create)
    monkeypatch.setattr(launcher.venv.EnvBuilder, 'create', create)
    install = Mock()
    monkeypatch.setattr(launcher, 'run', install)
    python = launcher.runtime_python(root)
    assert launcher.runtime_python(root) == python
    create.assert_called_once()
    install.assert_called_once_with(
        [str(python), '-m', 'pip', 'install', '-r', str(requirements)], root,
    )
    requirements.write_text('django==6.0.8\nwhitenoise==6.6.0\n')
    launcher.runtime_python(root)
    assert install.call_count == 2


def test_failed_install_is_not_marked_complete(tmp_path, monkeypatch):
    (tmp_path / 'requirements.txt').write_text('django==6.0.8')
    python = tmp_path / '.kwacart-runtime' / (
        'Scripts/python.exe' if launcher.os.name == 'nt' else 'bin/python'
    )
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(launcher, 'run', Mock(side_effect=launcher.LauncherError('failed')))
    with pytest.raises(launcher.LauncherError):
        launcher.runtime_python(tmp_path)
    assert not (tmp_path / '.kwacart-runtime/kwacart-requirements.sha256').exists()


def test_current_python_mode_never_installs_packages(tmp_path, monkeypatch):
    builder = Mock()
    monkeypatch.setattr(launcher.venv, 'EnvBuilder', builder)
    assert launcher.runtime_python(tmp_path, True) == Path(launcher.sys.executable)
    builder.assert_not_called()


def test_local_settings_and_key_stay_local_and_stable(tmp_path, monkeypatch):
    monkeypatch.setenv('CLOUDINARY_URL', 'cloudinary://key:secret@example')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://example.invalid/demo')
    monkeypatch.setenv('DYNO', 'test')
    monkeypatch.setenv('DJANGO_SETTINGS_MODULE', 'config.settings.production')
    first = launcher.local_environment(tmp_path)
    second = launcher.local_environment(tmp_path)
    assert first['SECRET_KEY'] == second['SECRET_KEY']
    assert len(first['SECRET_KEY']) >= 40
    assert first['DJANGO_SETTINGS_MODULE'] == 'config.settings.local'
    assert first['DEBUG'] == 'True'
    assert not {'CLOUDINARY_URL', 'DATABASE_URL', 'DYNO'} & first.keys()


def test_empty_local_key_fails_instead_of_resetting_it(tmp_path):
    (tmp_path / '.kwacart-local-key').touch()
    with pytest.raises(launcher.LauncherError, match='empty'):
        launcher.local_environment(tmp_path)


def test_busy_port_has_clear_error():
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        with pytest.raises(launcher.LauncherError, match='already in use'):
            launcher.check_port(port)

def test_recently_stopped_port_does_not_prevent_restart():
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', 0))
    port = server.getsockname()[1]
    server.listen()
    client = socket.create_connection(('127.0.0.1', port))
    peer, _ = server.accept()
    peer.close()
    client.close()
    server.close()
    launcher.check_port(port)


@pytest.mark.parametrize('admin_exists', [False, True])
def test_first_login_prompt_and_browser_after_readiness(tmp_path, monkeypatch, admin_exists):
    (tmp_path / 'manage.py').touch()
    (tmp_path / 'requirements.txt').touch()
    monkeypatch.setattr(launcher, 'check_port', Mock())
    monkeypatch.setattr(launcher, 'runtime_python', Mock(return_value=Path('/test/python')))
    monkeypatch.setattr(launcher, 'local_environment', Mock(return_value={}))
    run = Mock(side_effect=lambda *args, **kwargs: str(admin_exists) if kwargs.get('capture') else '')
    monkeypatch.setattr(launcher, 'run', run)
    process = Mock()
    process.wait.return_value = 0
    process.poll.return_value = 0
    popen = Mock(return_value=process)
    monkeypatch.setattr(launcher.subprocess, 'Popen', popen)
    events = []
    monkeypatch.setattr(launcher, 'wait_for_server', lambda *a: events.append('ready'))
    monkeypatch.setattr(launcher.webbrowser, 'open', lambda url: events.append('browser') or True)
    launcher.launch(tmp_path, Namespace(port=8000, use_current_python=True, no_browser=False))
    commands = [call.args[0] for call in run.call_args_list]
    assert any('createsuperuser' in command for command in commands) == (not admin_exists)
    assert events == ['ready', 'browser']
    assert popen.call_args.args[0][-2:] == ['127.0.0.1:8000', '--noreload']


def test_exited_server_never_claims_to_be_ready():
    process = Mock()
    process.poll.return_value = 1
    with pytest.raises(launcher.LauncherError, match='could not start'):
        launcher.wait_for_server(process, 'http://127.0.0.1:8000/')


@pytest.mark.parametrize('version', [(3, 11), (3, 15)])
def test_unsupported_python_fails_before_touching_instance(tmp_path, monkeypatch, version):
    monkeypatch.setattr(launcher.sys, 'version_info', version)
    runtime = Mock()
    monkeypatch.setattr(launcher, 'runtime_python', runtime)
    with pytest.raises(launcher.LauncherError, match='3.12, 3.13 or 3.14'):
        launcher.launch(tmp_path, Namespace(port=8000, use_current_python=False, no_browser=True))
    runtime.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_source_ci_publication_is_explicitly_allowlisted():
    from scripts.build_source_release import ROOT_FILES, SOURCE_DIRS
    assert '.github' not in SOURCE_DIRS
    assert {
        '.github/workflows/source-launchers.yml',
        'scripts/native_source_check.py',
        'scripts/source_check_hooks.py',
        'docs/SOURCE_LAUNCHER_CHECKS.md',
    } <= ROOT_FILES
    assert '.github/workflows/accessibility.yml' not in ROOT_FILES


def test_native_check_refuses_to_mislabel_linux_as_native(tmp_path, monkeypatch):
    from scripts import native_source_check
    monkeypatch.setattr(native_source_check.sys, 'platform', 'linux')
    with pytest.raises(AssertionError, match='native Windows or macOS'):
        native_source_check.check(tmp_path / 'not-a-real-archive.zip')


def test_source_zip_command_permissions_do_not_depend_on_builder_os(tmp_path):
    from scripts.build_source_release import source_zip_entry
    path = tmp_path / 'Start KwaCart.command'
    path.write_text('#!/bin/sh\n')
    path.chmod(0o644)  # Windows checkout cannot supply Unix execute bits.
    entry = source_zip_entry(path, 'kwacart/Start KwaCart.command')
    assert entry.create_system == 3
    assert entry.external_attr >> 16 == 0o100755


def test_native_terminal_accepts_windows_batch_confirmation():
    from scripts.native_source_check import Terminal
    terminal = Terminal.__new__(Terminal)
    terminal.output = 'Stopping KwaCart.\r\nTerminate batch job (Y/N)?'
    terminal.cursor = 0
    assert terminal.expect('Stopping KwaCart.') == 'Stopping KwaCart.'
    assert terminal.expect(('Press any key', 'Terminate batch job')) == 'Terminate batch job'


def test_native_terminal_matches_final_output_after_child_exit(monkeypatch):
    from scripts import native_source_check
    monkeypatch.setattr(native_source_check.os, 'name', 'posix')
    terminal = native_source_check.Terminal.__new__(native_source_check.Terminal)
    terminal.output = ''
    terminal.cursor = 0
    terminal.redactions = []
    terminal.child = Mock()
    terminal.child.read_nonblocking.return_value = 'Stopping KwaCart.'
    terminal.child.isalive.return_value = False
    assert terminal.expect('Stopping KwaCart.', timeout=1) == 'Stopping KwaCart.'
