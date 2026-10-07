"""Export a clean source tree; never export environment data or Git history."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'dist' / 'kwacart-source'
SOURCE_DIRS = {
    'accounts', 'academy', 'archive', 'config', 'exporters', 'tools', 'templates',
    'static', 'library', 'tests',
}
ROOT_FILES = {
    'manage.py', 'requirements.txt', 'pytest.ini', 'LICENSE', 'LICENSE.md', 'NOTICE',
    'scripts/build_source_release.py', 'docs/SELF_HOSTING.md',
}
SECRET_PATTERNS = (
    re.compile(r'cloudinary://[^/\s]+:[^@\s]+@'),
    re.compile(r'\b(?:ghp_|github_pat_|sk_live_|sk_test_)[A-Za-z0-9_]{20,}'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
)


def main():
    files = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
        cwd=ROOT,
    ).decode().split('\0')
    selected = []
    for relative in set(files):
        path = Path(relative)
        if not relative or (path.parts[0] not in SOURCE_DIRS and relative not in ROOT_FILES):
            continue
        source = ROOT / path
        if not source.is_file() or source.is_symlink():
            continue
        content = source.read_bytes()
        text = content.decode('utf-8', errors='ignore')
        # A deliberately invalid fixture used to test cloud configuration.
        # Other matches, including matches in tests, still block the export.
        text = text.replace('cloudinary://key:secret@example', '')
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            raise SystemExit(f'Release blocked: credential-like content in {relative}.')
        selected.append(path)
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    for path in selected:
        target = OUTPUT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    shutil.copyfile(ROOT / 'docs' / 'SELF_HOSTING.md', OUTPUT / 'README.md')
    (OUTPUT / '.gitignore').write_text(
        '__pycache__/\n*.pyc\n*.sqlite3\n*.log\n.env\ninstance.env\nmedia/\n'
        'staticfiles/\ndata/\n.venv/\ndist/\n',
    )
    archive = ROOT / 'dist' / 'kwacart-source.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(OUTPUT.rglob('*')):
            if path.is_file():
                bundle.write(path, Path('kwacart') / path.relative_to(OUTPUT))
    print(f'Clean source tree: {OUTPUT.relative_to(ROOT)}')
    print(f'Source archive: {archive.relative_to(ROOT)}')
    print('Not published. Use clean Git history and verify the repository destination before uploading.')


if __name__ == '__main__':
    sys.exit(main())
