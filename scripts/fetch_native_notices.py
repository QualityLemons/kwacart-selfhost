"""Collect unmodified native runtime licences at build time, never at launch."""
from pathlib import Path
import urllib.request

# CPython's complete licence also includes its bundled native third-party
# components. Tcl/Tk and platform libraries are independently attributed.
NOTICES = {
    'CPython 3.13 (including bundled component notices)':
        'https://raw.githubusercontent.com/python/cpython/v3.13.9/LICENSE',
    'Tcl 8.6':
        'https://raw.githubusercontent.com/tcltk/tcl/core-8-6-16/license.terms',
    'Tk 8.6':
        'https://raw.githubusercontent.com/tcltk/tk/core-8-6-16/license.terms',
    'OpenSSL 3':
        'https://raw.githubusercontent.com/openssl/openssl/openssl-3.0.18/LICENSE.txt',
    'libffi':
        'https://raw.githubusercontent.com/libffi/libffi/v3.4.6/LICENSE',
    'zlib':
        'https://raw.githubusercontent.com/madler/zlib/v1.3.1/LICENSE',
    'bzip2':
        'https://raw.githubusercontent.com/libarchive/bzip2/bzip2-1.0.8/LICENSE',
}


def main():
    parts = [
        'SQLite is in the public domain: https://www.sqlite.org/copyright.html\n'
        'Native libraries retain their respective terms. Component builds vary by OS.\n',
    ]
    for name, url in NOTICES.items():
        with urllib.request.urlopen(url, timeout=60) as response:
            text = response.read().decode('utf-8')
        parts.append(f'\n{name}\nSource: {url}\n\n{text}\n')
    target = Path(__file__).resolve().parent.parent / 'packaging/native-notices.txt'
    target.write_text(''.join(parts), encoding='utf-8')


if __name__ == '__main__':
    main()
