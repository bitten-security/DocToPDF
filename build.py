"""Build a standalone app for the current OS: `python build.py` -> dist/DocToPDF[.exe]
PyInstaller does not cross-compile: run this on Windows for .exe and on Linux for the Linux binary."""
import subprocess
import sys

EXCLUDES = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
            "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.Qt3DCore", "PySide6.QtMultimedia"]

cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
       "--name", "DocToPDF", "--paths", ".", "doctopdf/__main__.py"]
for m in EXCLUDES:
    cmd += ["--exclude-module", m]
sys.exit(subprocess.call(cmd))
