# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# Fluent тащим целиком (код + ресурсы qss/иконки + подмодули): иначе в exe
# тихий fallback в классику (проверено: бандл без qfluentwidgets).
_qf_datas, _qf_binaries, _qf_hidden = collect_all('qfluentwidgets')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_qf_binaries,
    datas=_qf_datas,
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'openpyxl',
        'odf',
        'odf.opendocument',
        'odf.table',
        'odf.text',
        'matplotlib',
        'matplotlib.backends.backend_agg',
        'qfluentwidgets',
        *_qf_hidden,
    ],
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
    [],
    exclude_binaries=True,
    name='LocalReviewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LocalReviewer',
)