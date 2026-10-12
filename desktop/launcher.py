"""Small native window owns a packaged WSGI child; no terminal is required."""
import argparse
import os
from pathlib import Path
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from .browser import open_system_browser
from .runtime import (
    data_directory, environment, exclusive_instance, mark_updated,
    prepare_update, resource_root,
)


def worker(port):
    # Windowed PyInstaller executables have no sys.stdout/sys.stderr even when
    # the parent supplies Windows handles. Give Django/logging real streams.
    log = Path(os.environ['KWACART_DATA_DIR']) / 'worker.log'
    if sys.stdout is None:
        sys.stdout = log.open('a', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = log.open('a', encoding='utf-8')
    import django
    django.setup()
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from waitress import create_server
    from django.conf import settings
    call_command('migrate', interactive=False, verbosity=0)
    call_command('collectstatic', interactive=False, verbosity=0)
    server = create_server(get_wsgi_application(), host='127.0.0.1', port=port, threads=4)
    mark_updated(Path(settings.DATA_DIR))
    parent = os.environ.get('KWACART_DESKTOP_PARENT')
    if parent:
        # A crashed/force-closed GUI must not leave a hidden server behind.
        def watch_parent():
            pid = int(parent)
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel.OpenProcess.restype = wintypes.HANDLE
                kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                handle = kernel.OpenProcess(0x00100000, False, pid)
                if handle:
                    kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
                    kernel.CloseHandle(handle)
            else:
                while os.getppid() == pid:
                    time.sleep(0.5)
            os._exit(0)
        threading.Thread(target=watch_parent, daemon=True).start()
    server.run()


def worker_command(port):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--desktop-worker', '--port', str(port)]
    return [sys.executable, str(resource_root() / 'start_kwacart.py'),
            '--desktop-worker', '--port', str(port)]


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def ready(process, port, timeout=120):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('The server could not start. See desktop.log in the data folder.')
        try:
            with opener.open(f'http://127.0.0.1:{port}/desktop/health/', timeout=1) as reply:
                if reply.read() == b'KwaCart ready':
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError('Startup timed out. See desktop.log in the data folder.')


def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def window(no_browser=False, smoke_test=False):
    import tkinter as tk
    from tkinter import ttk
    data = data_directory()
    app = tk.Tk()
    app.title('KwaCart')
    app.geometry('600x320')
    status = tk.StringVar(value='Preparing KwaCart. First startup may take a minute.')
    frame = ttk.Frame(app, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='KwaCart on this computer', font=('', 18, 'bold')).pack(anchor='w')
    ttk.Label(frame, textvariable=status, wraplength=540).pack(anchor='w', pady=16)
    ttk.Label(frame, text=f'Your saved work and backups:\n{data}', wraplength=540).pack(anchor='w')
    messages = queue.Queue()
    process = None
    url = None
    closing = threading.Event()

    def open_browser():
        if url:
            try:
                opened = open_system_browser(url)
            except (webbrowser.Error, OSError):
                opened = False
            if not opened:
                status.set('Browser did not open. Copy the address below into your browser.')

    address = ttk.Entry(frame)
    address.pack(fill='x', pady=8)
    open_button = ttk.Button(frame, text='Open KwaCart', command=open_browser, state='disabled')
    open_button.pack(anchor='w', pady=4)

    def start():
        nonlocal process
        try:
            with exclusive_instance(data):
                env = environment(data, secrets.token_urlsafe(32))
                env['KWACART_DESKTOP_PARENT'] = str(os.getpid())
                prepare_update(data)
                port = available_port()
                with (data / 'desktop.log').open('w', encoding='utf-8') as log:
                    process = subprocess.Popen(
                        worker_command(port), cwd=data, env=env,
                        stdout=log, stderr=log,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                    )
                    try:
                        ready(process, port)
                        messages.put(('ready', f'http://127.0.0.1:{port}/desktop/setup/?ticket='
                                      + env['KWACART_SETUP_TICKET']))
                        while not closing.wait(0.5):
                            if process.poll() is not None:
                                raise RuntimeError('KwaCart stopped unexpectedly. See desktop.log.')
                    finally:
                        stop(process)
        except Exception as exc:
            messages.put(('error', str(exc)))
        finally:
            messages.put(('stopped', ''))

    def poll():
        nonlocal url
        try:
            while True:
                event, text = messages.get_nowait()
                if event == 'ready' and not closing.is_set():
                    url = text
                    address.insert(0, text)
                    address.configure(state='readonly')
                    open_button.configure(state='normal')
                    status.set('Ready. Keep this window open while using KwaCart.')
                    if not no_browser:
                        open_browser()
                    if smoke_test:
                        (data / 'native-window-check.txt').write_text('ready')
                        app.after(500, close)
                elif event == 'error':
                    status.set(text)
                    open_button.configure(state='disabled')
                    if smoke_test:
                        (data / 'native-window-check-error.txt').write_text(text, encoding='utf-8')
                        app.after(100, close)
                elif event == 'stopped' and closing.is_set():
                    app.destroy()
                    return
        except queue.Empty:
            pass
        app.after(200, poll)

    thread = threading.Thread(target=start, daemon=True)

    def close():
        closing.set()
        open_button.configure(state='disabled')
        status.set('Stopping KwaCart. Your saved work will be kept.')
        if not thread.is_alive():
            app.destroy()

    ttk.Button(frame, text='Stop KwaCart', command=close).pack(anchor='w', pady=4)
    app.protocol('WM_DELETE_WINDOW', close)
    thread.start()
    poll()
    try:
        app.mainloop()
    finally:
        closing.set()
        thread.join(timeout=15)
        stop(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--desktop-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--smoke-test', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535.')
    if args.desktop_worker:
        worker(args.port)
    else:
        window(args.no_browser or args.smoke_test, args.smoke_test)
    return 0
