# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all


charset_datas, charset_binaries, charset_hiddenimports = collect_all('charset_normalizer')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=charset_binaries,
    datas=[
        ('web/dist/', 'front'),
        ('locales/', 'locales'),
    ] + ([('build-target.txt', '.')] if Path('build-target.txt').is_file() else []) + charset_datas,
    hiddenimports=charset_hiddenimports + ['anyio._backends._asyncio'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='taoSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['logo.ico'],
)
