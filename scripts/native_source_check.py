"""Native source-ZIP checks. Run on Windows/macOS, never against workspace data."""
import argparse
from contextlib import closing
import hashlib
import http.cookiejar
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile


class Terminal:
    """Use a real terminal so getpass and Ctrl+C behave like a double click."""

    def __init__(self, command, cwd, env):
        self.output = ''
        self.cursor = 0
        if os.name == 'nt':
            from winpty import PtyProcess
            self.child = PtyProcess.spawn(subprocess.list2cmdline(command), cwd=str(cwd), env=env)
        else:
            import pexpect
            self.child = pexpect.spawn(command[0], command[1:], cwd=str(cwd), env=env,
                                       encoding='utf-8', timeout=1)

    def alive(self):
        return self.child.isalive()

    def send(self, value):
        if os.name == 'nt':
            self.child.write(value)
        else:
            self.child.send(value)

    def expect(self, text, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            index = self.output.find(text, self.cursor)
            if index >= 0:
                self.cursor = index + len(text)
                return
            try:
                if os.name == 'nt':
                    chunk = self.child.read(4096, blocking=False)
                else:
                    chunk = self.child.read_nonblocking(4096, timeout=0.2)
                self.output += chunk
            except Exception as exc:
                # Terminal timeout/EOF are expected while polling. Other failures
                # must not be mistaken for a successful application check.
                if exc.__class__.__name__ not in ('TIMEOUT', 'EOF'):
                    raise
            if not self.alive():
                break
            time.sleep(0.05)
        raise AssertionError(f'Native terminal did not reach expected step: {text!r}')

    def stop(self):
        self.send('\x03')
        self.expect('Stopping KwaCart.', timeout=30)
        if os.name == 'nt':
            self.expect('Press any key', timeout=30)
            self.send('\r')
        deadline = time.monotonic() + 30
        while self.alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not self.alive(), 'launcher did not shut down'
        if os.name == 'nt':
            assert self.child.exitstatus == 0, 'batch launcher exit status'
        else:
            self.child.close()
            assert self.child.exitstatus == 0, 'command launcher exit status'

    def cleanup(self):
        if self.alive():
            self.send('\x03')
            time.sleep(2)
        if self.alive():
            self.child.terminate(force=True)


def windows_shim(folder):
    """A real executable, not a .cmd shim that would skip the caller's labels."""
    source = folder / 'shim.cs'
    source.write_text(r'''
using System;
using System.Diagnostics;
using System.IO;
class Shim {
  static string Quote(string s) { return "\"" + s.Replace("\"", "\\\"") + "\""; }
  static int Main(string[] args) {
    // Keep the forwarding shim alive while Python handles terminal Ctrl+C.
    Console.CancelKeyPress += (sender, e) => { e.Cancel = true; };
    string name = Path.GetFileNameWithoutExtension(
      Process.GetCurrentProcess().MainModule.FileName);
    string probe = name == "py" && args.Length > 0 ? args[0] : name;
    if (Environment.GetEnvironmentVariable("KWACART_SHIM_LOG") != null)
      File.AppendAllText(Environment.GetEnvironmentVariable("KWACART_SHIM_LOG"),
        probe + "|" + String.Join("|", args) + "\n");
    if (probe != Environment.GetEnvironmentVariable("KWACART_SHIM_ACCEPT")) return 1;
    if (Environment.GetEnvironmentVariable("KWACART_SHIM_REAL") == null)
      return Array.IndexOf(args, "-c") >= 0 ? 0 :
        (Environment.GetEnvironmentVariable("KWACART_SHIM_EXIT") == "7" ? 7 : 0);
    int start = name == "py" ? 1 : 0;
    string[] forwarded = new string[args.Length - start];
    for (int i = start; i < args.Length; i++) forwarded[i-start] = Quote(args[i]);
    var info = new ProcessStartInfo(Environment.GetEnvironmentVariable("KWACART_SHIM_REAL"),
      String.Join(" ", forwarded));
    info.UseShellExecute = false;
    var child = Process.Start(info);
    child.WaitForExit();
    return child.ExitCode;
  }
}
''', encoding='utf-8')
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler), '/nologo', '/out:' + str(folder / 'py.exe'), str(source)],
                   check=True, stdout=subprocess.DEVNULL)
    shutil.copy2(folder / 'py.exe', folder / 'python.exe')


def interpreter_path(folder, env):
    folder.mkdir()
    env['PATH'] = str(folder)
    if os.name == 'nt':
        windows_shim(folder)
        env['KWACART_SHIM_REAL'] = sys.executable
        env['KWACART_SHIM_ACCEPT'] = f'-{sys.version_info.major}.{sys.version_info.minor}'
    else:
        # dirname is the only external command used by the Mac wrapper.
        (folder / 'dirname').symlink_to('/usr/bin/dirname')
        (folder / f'python{sys.version_info.major}.{sys.version_info.minor}').symlink_to(sys.executable)


def wrapper_command(root, *args):
    if os.name == 'nt':
        return [os.environ['COMSPEC'], '/d', '/c', str(root / 'Start KwaCart.bat'), *args]
    return [str(root / 'Start KwaCart.command'), *args]


def wrapper_checks(root, work):
    """Execute each wrapper's selection, rejection, forwarding and error path."""
    folder = work / 'selection shims'
    folder.mkdir()
    env = os.environ.copy()
    env['PATH'] = str(folder)
    log = folder / 'calls.txt'
    env['KWACART_SHIM_LOG'] = str(log)
    if os.name == 'nt':
        windows_shim(folder)
        candidates = ['-3.13', '-3.14', '-3.12', '-3', 'python']
    else:
        (folder / 'dirname').symlink_to('/usr/bin/dirname')
        candidates = ['python3.13', 'python3.14', 'python3.12', 'python3', 'python']
        shim = '''#!/bin/sh
name=${0##*/}
printf '%s|' "$name" >> "$KWACART_SHIM_LOG"
printf '%s|' "$@" >> "$KWACART_SHIM_LOG"
printf '\\n' >> "$KWACART_SHIM_LOG"
[ "$name" = "$KWACART_SHIM_ACCEPT" ] || exit 1
[ "$1" = "-c" ] && exit 0
exit "${KWACART_SHIM_EXIT:-0}"
'''
        for candidate in candidates:
            file = folder / candidate
            file.write_text(shim, encoding='utf-8')
            file.chmod(0o755)
    for candidate in candidates:
        env['KWACART_SHIM_ACCEPT'] = candidate
        log.unlink(missing_ok=True)
        result = subprocess.run(wrapper_command(root, '--port', '8123', '--no-browser'),
                                cwd=work, env=env, input='\n', text=True,
                                capture_output=True, timeout=30)
        assert result.returncode == 0, 'wrapper selection failed'
        calls = log.read_text().splitlines()
        assert [c.split('|')[0] for c in calls[:-1]] == candidates[:candidates.index(candidate) + 1]
        assert calls[-1].startswith(candidate + '|') and 'start_kwacart.py' in calls[-1]
        assert '--port|8123|--no-browser' in calls[-1], 'wrapper lost arguments'
    env['KWACART_SHIM_ACCEPT'] = 'unsupported'
    result = subprocess.run(wrapper_command(root), cwd=work, env=env, input='\n',
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 1 and 'Python was not found' in result.stdout
    env['KWACART_SHIM_ACCEPT'] = candidates[0]
    env['KWACART_SHIM_EXIT'] = '7'
    result = subprocess.run(wrapper_command(root), cwd=work, env=env, input='\n',
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 7, 'wrapper swallowed launch error'
    # Also check truly missing commands, not only installed unsupported versions.
    for file in folder.iterdir():
        if file.name in ('py.exe', 'python.exe', *candidates):
            file.unlink()
    result = subprocess.run(wrapper_command(root), cwd=work, env=env, input='\n',
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 1 and 'Python was not found' in result.stdout
    print('PASS: native wrapper selection, arguments, missing/unsupported Python and failure exit.')


def check(archive):
    assert sys.platform in ('win32', 'darwin'), 'Run this check on native Windows or macOS'
    assert (3, 12) <= sys.version_info[:2] < (3, 15)
    with tempfile.TemporaryDirectory(prefix='KwaCart source check ') as directory:
        work = Path(directory)
        extracted = work / 'Extracted toolkit with spaces'
        extracted.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            assert not any(name.endswith(('.sqlite3', '.kwacart-local-key', '.env')) for name in names)
            mode = bundle.getinfo('kwacart/Start KwaCart.command').external_attr >> 16
            assert mode & 0o111, 'source ZIP lost Mac executable permission metadata'
        if os.name == 'nt':
            subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                            'Expand-Archive -LiteralPath $env:KWACART_ZIP -DestinationPath $env:KWACART_EXTRACT'],
                           env={**os.environ, 'KWACART_ZIP': str(archive),
                                'KWACART_EXTRACT': str(extracted)}, check=True)
        else:
            subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), str(extracted)], check=True)
        root = extracted / 'kwacart'
        if os.name != 'nt':
            assert os.access(root / 'Start KwaCart.command', os.X_OK), 'extracted command is not executable'
        assert not (root / '.kwacart-runtime').exists()
        wrapper_checks(root, work)
        hooks = work / 'CI hooks'
        hooks.mkdir()
        shutil.copy2(Path(__file__).with_name('source_check_hooks.py'), hooks / 'sitecustomize.py')
        browser = work / 'browser-ready.txt'
        env = os.environ.copy()
        # Do not inherit workspace/cloud configuration, Python packages or pip policy.
        for key in list(env):
            if key.startswith(('PYTHON', 'PIP_', 'DJANGO_', 'KWACART_')) or key in (
                'DATABASE_URL', 'CLOUDINARY_URL', 'SECRET_KEY', 'DYNO',
            ):
                env.pop(key)
        env.update(PYTHONPATH=str(hooks), PYTHONNOUSERSITE='1',
                   KWACART_CHECK_BROWSER=str(browser), PIP_DISABLE_PIP_VERSION_CHECK='1')
        interpreter_path(work / 'Chosen interpreter', env)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        email = f'ci-{secrets.token_hex(8)}@example.test'
        password = secrets.token_urlsafe(32) + '-8a!'
        child = Terminal(wrapper_command(root, '--port', str(port)), work, env)
        try:
            child.expect('Email:', timeout=900)
            child.send(email + '\r')
            child.expect('Password:')
            child.send(password + '\r')
            child.expect('Password (again):')
            child.send(password + '\r')
            child.expect('KwaCart is ready:', timeout=180)
            deadline = time.monotonic() + 10
            while not browser.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            assert browser.read_text() == base + '/', 'browser callback did not see HTTP 200'
            runtime = root / '.kwacart-runtime'
            python = runtime / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            version = subprocess.check_output([str(python), '-c',
                                               'import sys; print(sys.version_info[:2])'], env=env, text=True)
            assert version.strip() == str(sys.version_info[:2]), 'wrong private-runtime interpreter'
            subprocess.run([str(python), '-m', 'pip', 'check'], env=env, check=True)
            marker = runtime / 'kwacart-requirements.sha256'
            fingerprint = hashlib.sha256((root / 'requirements.txt').read_bytes()).hexdigest()
            assert marker.read_text() == fingerprint
            marker_time = marker.stat().st_mtime_ns
            key = (root / '.kwacart-local-key').read_bytes()
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar),
            )
            login = base + '/accounts/login/'
            page = opener.open(login).read().decode()
            token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
            result = opener.open(urllib.request.Request(login, data=urllib.parse.urlencode({
                'csrfmiddlewaretoken': token, 'username': email, 'password': password,
            }).encode(), headers={'Referer': login}))
            assert '/accounts/login' not in result.geturl(), 'real HTTP login failed'
            assert any(cookie.name == 'sessionid' for cookie in jar), 'login did not create session'
            assert opener.open(base + '/accounts/profile/').geturl() == base + '/accounts/profile/'
            with closing(sqlite3.connect(root / 'db.sqlite3')) as db:
                assert db.execute('SELECT is_superuser FROM accounts_user WHERE email=?',
                                  (email,)).fetchone() == (1,)
            child.stop()
            with socket.socket() as sock:
                assert sock.connect_ex(('127.0.0.1', port)) != 0, 'server still listening after shutdown'
            # Same port, folder and cookie jar; no sleep/reinstall between runs.
            env['KWACART_CHECK_OFFLINE'] = '1'
            browser.unlink()
            child = Terminal(wrapper_command(root, '--port', str(port)), work, env)
            child.expect('KwaCart is ready:', timeout=180)
            assert 'Create your first login' not in child.output
            assert 'Installing KwaCart packages' not in child.output
            assert (root / '.kwacart-local-key').read_bytes() == key
            assert marker.stat().st_mtime_ns == marker_time
            assert opener.open(base + '/accounts/profile/').geturl() == base + '/accounts/profile/'
            with closing(sqlite3.connect(root / 'db.sqlite3')) as db:
                assert db.execute('SELECT COUNT(*) FROM accounts_user').fetchone() == (1,)
                assert db.execute('SELECT email FROM accounts_user').fetchone() == (email,)
            child.stop()
        finally:
            child.cleanup()
        # TemporaryDirectory removal on Windows also catches leaked SQLite handles.
    print('PASS: native ZIP extraction, private install, interactive account, browser readiness, '
          'login, clean shutdown, offline immediate restart and retained account/session.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    check(parser.parse_args().archive.resolve())
