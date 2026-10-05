# PyInstaller build for RollCall. Run: uv run pyinstaller rollcall.spec
#   macOS   -> dist/RollCall.app  (onedir inside the bundle; onefile .app is deprecated)
#   Windows -> dist/RollCall.exe  (a single file teachers can double-click)
import sys

from PyInstaller.utils.hooks import collect_data_files

datas = (
    collect_data_files("customtkinter")  # theme .json and font files
    + collect_data_files("docx")  # python-docx's blank document, used by the starter template
    + collect_data_files("docxtpl")
)

a = Analysis(
    ["src/rollcall/__main__.py"],
    pathex=["src"],
    datas=datas,
    excludes=["pytest"],
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        exclude_binaries=True,
        name="RollCall",
        console=False,
        argv_emulation=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="RollCall")
    app = BUNDLE(
        coll,
        name="RollCall.app",
        bundle_identifier="org.rollcall.app",
        info_plist={
            "CFBundleShortVersionString": "0.2.0",
            "NSHighResolutionCapable": True,
            # Shown when macOS asks the teacher to let RollCall control Word (for PDFs).
            "NSAppleEventsUsageDescription": "RollCall uses Microsoft Word to save your documents as PDFs.",
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name="RollCall",
        console=False,
    )
