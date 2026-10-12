"""Native build from the clean public source, with bundled notices/source."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    if (ROOT / '.env').exists() or (ROOT / 'db.sqlite3').exists():
        raise SystemExit('Build only from a clean public checkout, not workspace data.')
    subprocess.run([sys.executable, 'scripts/build_source_release.py'], cwd=ROOT, check=True)
    notices = subprocess.check_output([
        sys.executable, '-m', 'piplicenses', '--format=plain-vertical',
        '--with-license-file', '--no-license-path', '--with-notice-file',
    ], cwd=ROOT, text=True)
    python_license = next((p for p in (
        Path(sys.base_prefix) / 'LICENSE.txt',
        Path(sys.base_prefix) / 'LICENSE',
        Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt',
    ) if p.is_file()), None)
    if python_license is None:
        raise SystemExit('Python licence missing; add the matching CPython LICENSE.txt to the runtime.')
    # Additional embedded native-library licences are supplied by the build
    # workflow from the pinned CPython/Tcl/Tk source distributions.
    native = ROOT / 'packaging/native-notices.txt'
    if not native.exists():
        raise SystemExit('Native runtime notices are missing.')
    (ROOT / 'THIRD_PARTY_NOTICES.txt').write_text(
        'Third-party distributions keep their original licences.\n\nPython:\n'
        + python_license.read_text(errors='replace') + '\n\n'
        + native.read_text() + '\n\n' + notices,
        encoding='utf-8',
    )
    (ROOT / 'SOURCE.txt').write_text(
        'KwaCart is free software, AGPL-3.0-only. See LICENSE and NOTICE.\n'
        'Exact corresponding source is included in kwacart-source.zip.\n'
        'Public repository: https://github.com/QualityLemons/kwacart-selfhost\n'
        f'Build commit: {os.environ.get("GITHUB_SHA", "local build")}\n',
    )
    # PyInstaller's Django hook otherwise chooses config.settings (an empty
    # package here). Inspect the same settings as the packaged worker, using
    # disposable build-only state, never a developer's key or database.
    with tempfile.TemporaryDirectory(prefix='kwacart-build-settings-') as data:
        env = os.environ.copy()
        for name in ('DATABASE_URL', 'CLOUDINARY_URL', 'SECRET_KEY'):
            env.pop(name, None)
        env.update(
            DJANGO_SETTINGS_MODULE='config.settings.desktop',
            KWACART_DATA_DIR=data, SECRET_KEY='build-only-not-a-user-key-' + 'x' * 40,
        )
        subprocess.run(
            [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
             'packaging/kwacart.spec'], cwd=ROOT, env=env, check=True,
        )
    # Documentation and notices also sit beside the app, not only inside it.
    for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.txt', 'SOURCE.txt'):
        shutil.copy2(ROOT / name, ROOT / 'dist/KwaCart')


if __name__ == '__main__':
    main()
