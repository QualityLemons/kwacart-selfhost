"""Launch the system browser without leaking bundled shared-library paths."""
from contextlib import contextmanager
import os
import sys
import webbrowser


@contextmanager
def system_library_environment():
    saved = {}
    for name in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'):
        saved[name] = os.environ.get(name)
        original = os.environ.get(name + '_ORIG')
        if original:
            os.environ[name] = original
        else:
            os.environ.pop(name, None)
    dll_directory = None
    if os.name == 'nt' and getattr(sys, 'frozen', False):
        import ctypes
        dll_directory = ctypes.windll.kernel32.SetDllDirectoryW
        dll_directory.argtypes = [ctypes.c_wchar_p]
        dll_directory(None)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if dll_directory is not None:
            dll_directory(str(sys._MEIPASS))


def open_system_browser(url):
    with system_library_environment():
        return webbrowser.open(url)
