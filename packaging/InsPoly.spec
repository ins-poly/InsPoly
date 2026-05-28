# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


PROJECT_ROOT = Path(SPECPATH).parent.resolve()


def _datas() -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for relative in (
        "app/browser_ui.html",
        "app/browser_event_forensic_ui.html",
    ):
        source = PROJECT_ROOT / relative
        items.append((str(source), str(Path(relative).parent)))

    vendor_root = PROJECT_ROOT / "app" / "vendor" / "browser"
    for source in vendor_root.rglob("*"):
        if source.is_file():
            relative = source.relative_to(PROJECT_ROOT)
            items.append((str(source), str(relative.parent)))
    return items


a = Analysis(
    [str(PROJECT_ROOT / "app" / "macos_launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=_datas(),
    hiddenimports=[
        "app.browser_desktop",
        "app.event_forensic_desktop",
        "tools.ai_case_reviewer",
        "webview.platforms.cocoa",
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
    name="InsPoly",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    name="InsPoly",
)
app = BUNDLE(
    coll,
    name="InsPoly.app",
    icon=str(PROJECT_ROOT / "packaging" / "InsPoly.icns"),
    bundle_identifier="com.inspoly.desktop",
    info_plist={
        "CFBundleName": "InsPoly",
        "CFBundleDisplayName": "InsPoly",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
    },
)
