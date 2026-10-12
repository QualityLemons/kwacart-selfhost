"""Persistent state, exclusive ownership and pre-migration backups."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import sys

VERSION = '1.0.0'


def resource_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))


def data_directory():
    override = os.environ.get('KWACART_DESKTOP_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        if not base.is_absolute():
            base = Path.home() / 'AppData' / 'Local'
        return base / 'KwaCart'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'KwaCart'
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    if not base.is_absolute():
        base = Path.home() / '.local/share'
    return base / 'kwacart'


def environment(data, ticket):
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = data / '.kwacart-local-key'
    if not key.exists():
        # Losing an existing key must not silently invalidate sessions/data.
        if (data / 'db.sqlite3').exists():
            raise RuntimeError('The local key is missing. Restore it from your backup.')
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_urlsafe(48))
    value = key.read_text().strip()
    if len(value) < 40:
        raise RuntimeError('The local key is damaged. Restore it from your backup.')
    env = os.environ.copy()
    for name in ('DATABASE_URL', 'CLOUDINARY_URL', 'DYNO', 'PYTHONPATH',
                 'KWACART_TRUST_PROXY_SSL'):
        env.pop(name, None)
    env.update(
        DJANGO_SETTINGS_MODULE='config.settings.desktop',
        SECRET_KEY=value, KWACART_DATA_DIR=str(data),
        KWACART_SETUP_TICKET=ticket,
    )
    return env


@contextmanager
def exclusive_instance(data):
    """OS locks release after crashes; never delete a lock another app owns."""
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    stream = (data / '.instance-lock').open('a+b')
    try:
        stream.seek(0)
        if sys.platform == 'win32':
            import msvcrt
            if not stream.read(1):
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        stream.close()
        raise RuntimeError('KwaCart is already running. Use its open window or close it first.') from exc
    try:
        yield
    finally:
        stream.close()


def prepare_update(data):
    marker = data / 'installed-version.json'
    old = json.loads(marker.read_text())['version'] if marker.exists() else None
    if old and tuple(map(int, old.split('.'))) > tuple(map(int, VERSION.split('.'))):
        raise RuntimeError('This app is older than your data. Reopen the newer version.')
    database = data / 'db.sqlite3'
    if old == VERSION or not database.exists():
        return
    backup = data / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True, mode=0o700)
    # SQLite backup handles journal/WAL state; the worker has not started yet.
    with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(backup / 'db.sqlite3')) as target:
        source.backup(target)
    shutil.copy2(data / '.kwacart-local-key', backup)
    if (data / 'media').exists():
        shutil.copytree(data / 'media', backup / 'media')
    if marker.exists():
        shutil.copy2(marker, backup)
    (backup / 'RESTORE.txt').write_text(
        'Stop KwaCart. Restore db.sqlite3, .kwacart-local-key and media together '
        'to the KwaCart data folder. Restore installed-version.json if present. '
        'Use the matching older application. Keep a copy of current data first.\n',
    )


def mark_updated(data):
    target = data / 'installed-version.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'version': VERSION}))
    temporary.replace(target)
