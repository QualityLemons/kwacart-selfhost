# Build only inside a sanitised source checkout, never the private workspace.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
datas = []
hidden = []
for name in ('django', 'accounts', 'academy', 'archive', 'tools',
             'exporters', 'config', 'desktop', 'cloudinary', 'cloudinary_storage',
             'whitenoise', 'waitress'):
    hidden += collect_submodules(name)
    datas += collect_data_files(name)
for name in ('templates', 'static', 'library'):
    datas.append((str(root / name), name))
for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.txt', 'SOURCE.txt'):
    datas.append((str(root / name), '.'))
# Include the exact corresponding source with every binary, offline as well.
datas.append((str(root / 'dist/kwacart-source.zip'), '.'))

a = Analysis(
    [str(root / 'start_kwacart.py')], pathex=[str(root)], datas=datas,
    hiddenimports=hidden, excludes=['playwright', 'pytest', 'gunicorn'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='KwaCart',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='KwaCart')
if sys.platform == 'darwin':
    app = BUNDLE(
        coll, name='KwaCart.app', bundle_identifier='org.kwacart.desktop',
        info_plist={
            'CFBundleShortVersionString': '1.0.1',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '13.0',
        },
    )
