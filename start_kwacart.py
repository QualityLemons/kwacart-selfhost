"""Local-only KwaCart launcher for downloaded source on Windows, macOS and Linux."""
import argparse
import hashlib
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent


class LauncherError(Exception):
    pass


def run(command, root, env=None, capture=False):
    try:
        result = subprocess.run(
            command, cwd=root, env=env, check=True, text=True,
            stdout=subprocess.PIPE if capture else None,
        )
        return result.stdout.strip() if capture else ''
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LauncherError(
            'A setup step failed. Read the error above, check your internet '
            'connection and Python installation, then start KwaCart again.'
        ) from exc


def runtime_python(root, use_current=False):
    if use_current:
        return Path(sys.executable)
    runtime = root / '.kwacart-runtime'
    python = runtime / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('First launch: creating KwaCart’s private Python environment...', flush=True)
        try:
            venv.EnvBuilder(with_pip=True).create(runtime)
        except (OSError, subprocess.SubprocessError) as exc:
            raise LauncherError(
                'Could not create the local environment. Check that this folder '
                'is writable. On Linux, you may need your distribution’s python3-venv package.'
            ) from exc
    requirements = root / 'requirements.txt'
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = runtime / 'kwacart-requirements.sha256'
    if not marker.exists() or marker.read_text().strip() != fingerprint:
        print('Installing KwaCart packages. This needs internet and can take several minutes.',
              flush=True)
        run([str(python), '-m', 'pip', 'install', '-r', str(requirements)], root)
        marker.write_text(fingerprint)
    return python


def local_environment(root):
    env = os.environ.copy()
    # Never pick up a cloud deployment's storage/database or settings by accident.
    for key in ('CLOUDINARY_URL', 'DATABASE_URL', 'DYNO'):
        env.pop(key, None)
    env['DJANGO_SETTINGS_MODULE'] = 'config.settings.local'
    env['DEBUG'] = 'True'
    key_file = root / '.kwacart-local-key'
    if not key_file.exists():
        try:
            fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'w') as stream:
                stream.write(secrets.token_urlsafe(48))
    key = key_file.read_text().strip()
    if not key:
        raise LauncherError('The .kwacart-local-key file is empty. Restore it from your backup.')
    env['SECRET_KEY'] = key
    return env


def check_port(port):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        # A bind-only probe rejects TIME_WAIT after a normal shutdown. Check
        # for a live listener instead so restarting the same folder works.
        if sock.connect_ex(('127.0.0.1', port)) == 0:
            raise LauncherError(
                f'Port {port} is already in use. Close the other KwaCart window '
                f'or start with --port {port + 1 if port < 65535 else 8001}.'
            )


def wait_for_server(process, url, timeout=60):
    deadline = time.monotonic() + timeout
    # A localhost request must not be routed through an inherited HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LauncherError('KwaCart could not start. Read the server error above.')
        try:
            with opener.open(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    raise LauncherError('KwaCart did not become ready within a minute. Read the errors above.')


def launch(root, args):
    if not (3, 12) <= sys.version_info[:2] < (3, 15):
        raise LauncherError('Install Python 3.12, 3.13 or 3.14 first (3.13 recommended).')
    if not (root / 'manage.py').is_file() or not (root / 'requirements.txt').is_file():
        raise LauncherError('Extract the whole ZIP first. Keep the launcher beside manage.py.')
    check_port(args.port)
    print('\nKwaCart — run on this computer\nKeep this window open while using the toolkit.\n',
          flush=True)
    python = runtime_python(root, args.use_current_python)
    env = local_environment(root)
    manage = [str(python), str(root / 'manage.py')]
    print('Preparing your local database...', flush=True)
    run(manage + ['migrate', '--noinput'], root, env)
    existing_admin = run(manage + [
        'shell', '--verbosity', '0', '-c',
        'from django.contrib.auth import get_user_model; '
        'print(get_user_model().objects.filter(is_superuser=True, is_active=True).exists())',
    ], root, env, capture=True)
    if existing_admin.splitlines()[-1:] != ['True']:
        print('\nCreate your first login (an administrator). Use your own email and a password.'
              '\nPassword characters will not appear while you type — this is normal.\n',
              flush=True)
        run(manage + ['createsuperuser'], root, env)
        print('Your login has been created.', flush=True)
    url = f'http://127.0.0.1:{args.port}/'
    process = subprocess.Popen(
        manage + ['runserver', f'127.0.0.1:{args.port}', '--noreload'],
        cwd=root, env=env,
    )
    try:
        wait_for_server(process, url)
        print(f'\nKwaCart is ready: {url}'
              '\nClick Login in your browser and use the account you created.'
              '\nKeep this window open. Press Ctrl+C here to stop KwaCart.\n', flush=True)
        if not args.no_browser:
            try:
                opened = webbrowser.open(url)
            except (webbrowser.Error, OSError):
                opened = False
            if not opened:
                print(f'Could not open a browser automatically. Open {url} yourself.', flush=True)
        code = process.wait()
        if code:
            raise LauncherError('The KwaCart server stopped with an error. Read the output above.')
    except KeyboardInterrupt:
        print('\nStopping KwaCart. Your saved work stays in this folder.', flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    # A frozen executable is not a Python interpreter: never invoke it with
    # manage.py or pip arguments. Its child workers use an explicit dispatch.
    if getattr(sys, 'frozen', False) or '--desktop' in sys.argv or '--desktop-worker' in sys.argv:
        from desktop.launcher import main as desktop_main
        return desktop_main()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--use-current-python', action='store_true',
                        help='Advanced: use already installed packages instead of a private runtime.')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    try:
        launch(ROOT, args)
    except KeyboardInterrupt:
        print('\nSetup cancelled. Start KwaCart again when you are ready.')
    except (LauncherError, OSError) as exc:
        print(f'\nKwaCart could not open: {exc}\nSee the troubleshooting section in README.md.',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
