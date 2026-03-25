# -*- mode: python ; coding: utf-8 -*-

tcl_root = r"C:\Users\eye2b\AppData\Local\Programs\Python\Python313\tcl"
dll_root = r"C:\Users\eye2b\AppData\Local\Programs\Python\Python313\DLLs"

datas = [
    (r"config.ini", "."),
    (rf"{tcl_root}\tcl8.6", "_tcl_data"),
    (rf"{tcl_root}\tk8.6", "_tk_data"),
]

binaries = [
    (rf"{dll_root}\_tkinter.pyd", "."),
    (rf"{dll_root}\tcl86t.dll", "."),
    (rf"{dll_root}\tk86t.dll", "."),
]

a = Analysis(
    ['src\\main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
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
    name='BizTeam_WorkRequestSplitter_portable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BizTeam_WorkRequestSplitter_portable',
)
