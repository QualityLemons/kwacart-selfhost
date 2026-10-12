"""CI-only instrumentation, copied as sitecustomize outside the source ZIP.

Do not install this in a user's runtime. It observes real browser readiness and
rejects network/package bootstrap during the second launch; it mocks neither
installation, Django, account creation nor HTTP login.
"""
import os
from pathlib import Path
import re
import socket
import sys
import urllib.request
import webbrowser


if os.environ.get('KWACART_CHECK_OFFLINE') == '1':
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def local_only(address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            raise RuntimeError('CI offline launch attempted external network access')

    def connect(self, address):
        local_only(address)
        return original_connect(self, address)

    def connect_ex(self, address):
        local_only(address)
        return original_connect_ex(self, address)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    def no_install(event, args):
        if event != 'subprocess.Popen':
            return
        command = args[1]
        if isinstance(command, (list, tuple)):
            installing = any(str(part) in ('pip', 'ensurepip') for part in command)
        else:
            # Windows audits the final command-line string, not the argv list.
            installing = bool(re.search(r'(?:^|\s)(?:pip|ensurepip)(?:\s|$)', str(command)))
        if installing:
            raise RuntimeError('CI offline launch attempted package installation')

    # An audit hook preserves the Popen class. Windows asyncio subclasses it;
    # replacing it with a function breaks Django imports before any networking.
    sys.addaudithook(no_install)


def browser_open(url, *args, **kwargs):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as response:
        assert response.status == 200, 'browser requested before HTTP readiness'
    Path(os.environ['KWACART_CHECK_BROWSER']).write_text(url, encoding='utf-8')
    return True


if os.environ.get('KWACART_CHECK_BROWSER'):
    webbrowser.open = browser_open
