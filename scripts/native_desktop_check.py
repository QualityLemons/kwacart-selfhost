"""Exercise the actual frozen executable on its matching native runner."""
import argparse
from contextlib import closing
import http.cookiejar
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from native_desktop_media_check import check_private_media


def native_window(binary, env, data):
    marker = data / 'native-window-check.txt'
    marker.unlink(missing_ok=True)
    gui = subprocess.Popen([str(binary), '--smoke-test'], env=env)
    try:
        code = gui.wait(timeout=180)
        assert code == 0 and marker.exists(), 'native GUI did not reach ready state'
    except (AssertionError, subprocess.TimeoutExpired):
        gui.kill()
        gui.wait(timeout=15)
        for name in ('native-window-check-error.txt', 'desktop.log', 'worker.log'):
            log = data / name
            if log.exists():
                print(f'{name}:\n{log.read_text(encoding="utf-8", errors="replace")[-8000:]}', flush=True)
        raise
    assert marker.read_text() == 'ready'


def check(binary):
    with tempfile.TemporaryDirectory(prefix='KwaCart native check ') as directory:
        data = Path(directory) / 'user data'
        # Run the packaged GUI and its own packaged subprocess, not a Python
        # approximation. The check closes through the same window close handler.
        env = os.environ.copy()
        env['KWACART_DESKTOP_DATA_DIR'] = str(data)
        env['DATABASE_URL'] = 'postgresql://invalid.invalid/forbidden'
        env['DJANGO_SETTINGS_MODULE'] = 'config.settings.production'
        native_window(binary, env, data)
        key_before = (data / '.kwacart-local-key').read_bytes()
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar),
        )

        def start():
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            child_env = env.copy()
            child_env.update(
                DJANGO_SETTINGS_MODULE='config.settings.desktop',
                SECRET_KEY=key_before.decode(),
                KWACART_DATA_DIR=str(data), KWACART_SETUP_TICKET='native-check-only',
            )
            proc = subprocess.Popen(
                [str(binary), '--desktop-worker', '--port', str(port)], env=child_env,
            )
            base = f'http://127.0.0.1:{port}'
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                assert proc.poll() is None, 'packaged worker crashed'
                try:
                    opener.open(base + '/desktop/health/', timeout=1).close()
                    return proc, base
                except OSError:
                    time.sleep(0.25)
            proc.terminate()
            raise AssertionError('packaged worker never became ready')

        def stop(proc):
            proc.terminate()
            proc.wait(timeout=20)

        proc, base = start()
        try:
            try:
                opener.open(base + '/desktop/setup/')
                raise AssertionError('unauthorised setup was allowed')
            except urllib.error.HTTPError as exc:
                assert exc.code == 403
            page = opener.open(base + '/desktop/setup/?ticket=native-check-only').read().decode()
            assert 'Set up KwaCart on this computer' in page
            assert '<label for="id_email">' in page
            assert '<label for="id_password1">' in page
            assert 'signup.css' in page
            token = next(c.value for c in jar if c.name == 'csrftoken')
            payload = urllib.parse.urlencode({
                'csrfmiddlewaretoken': token, 'email': 'native@example.test',
                'password1': 'Native-Only-Check-947!x', 'password2': 'Native-Only-Check-947!x',
            }).encode()
            result = opener.open(urllib.request.Request(
                base + '/desktop/setup/', data=payload, headers={'Referer': base + '/desktop/setup/'},
            ))
            assert result.geturl() == base + '/', result.geturl()
            for path in ('/static/css/signup.css', '/tools/', '/learn/', '/archive/knowledge-bank/'):
                response = opener.open(base + path)
                assert response.status == 200, path
                assert response.read(), path
            db = sqlite3.connect(data / 'db.sqlite3')
            assert db.execute(
                'SELECT is_superuser FROM accounts_user WHERE email=?', ('native@example.test',),
            ).fetchone() == (1,)
            db.close()
            retained = check_private_media(opener, base, data, key_before)
            try:
                opener.open(urllib.request.Request(
                    base + '/desktop/health/', headers={'Host': 'hostile.example'},
                ))
                raise AssertionError('host-header allowlist not enforced')
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
        finally:
            stop(proc)
        # Force an earlier schema-version marker to exercise the real parent
        # backup/update path, then restart the extracted application.
        (data / 'installed-version.json').write_text(json.dumps({'version': '0.9.0'}))
        native_window(binary, env, data)
        assert (data / '.kwacart-local-key').read_bytes() == key_before
        assert (data / 'media' / retained).read_text() == 'retain this upload'
        backups = list((data / 'backups').iterdir())
        assert len(backups) == 1
        assert (backups[0] / '.kwacart-local-key').read_bytes() == key_before
        assert (backups[0] / 'media' / retained).is_file()
        with closing(sqlite3.connect(backups[0] / 'db.sqlite3')) as db:
            assert db.execute('SELECT COUNT(*) FROM accounts_user').fetchone() == (2,)
        proc, base = start()
        try:
            # The original cookies can still be authenticated because the
            # signing key survived. Check first-run closure as a new visitor.
            jar.clear()
            assert opener.open(base + '/desktop/setup/').geturl().endswith('/accounts/login/')
        finally:
            stop(proc)
        print('PASS: native frozen GUI, worker, first account, static/tool/media routes, restart, update backup.')


def check_read_only_install(binary):
    source = next((p for p in binary.parents if p.name.endswith('.app')), binary.parent)
    with tempfile.TemporaryDirectory(prefix='KwaCart installation with spaces ') as directory:
        install = Path(directory) / source.name
        shutil.copytree(source, install, symlinks=True)
        executable = install / binary.relative_to(source)
        modes = {}
        for path in [install, *install.rglob('*')]:
            if not path.is_symlink():
                modes[path] = path.stat().st_mode
                path.chmod(modes[path] & ~0o222)
        def snapshot():
            return {
                str(p.relative_to(install)): (p.lstat().st_size, p.lstat().st_mtime_ns)
                for p in install.rglob('*') if p.is_file() or p.is_symlink()
            }
        before = snapshot()
        try:
            check(executable)
            assert snapshot() == before, 'The app wrote into its installation folder'
        finally:
            for path, mode in modes.items():
                if path.exists():
                    path.chmod(mode)
        print('PASS: copied native package runs from a read-only installation with spaces.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('binary', type=Path)
    check_read_only_install(parser.parse_args().binary.resolve())
