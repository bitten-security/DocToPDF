"""Build a standalone app for the current OS into dist/DocToPDF/ (one-folder build).
PyInstaller does not cross-compile: run on Windows for .exe, on Linux for the Linux binary.
Use `--onefile` for a single portable executable instead."""
import subprocess
import sys

EXCLUDES = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
            "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
            "PySide6.QtNetwork", "PySide6.QtSql", "PySide6.QtTest"]

mode = "--onefile" if "--onefile" in sys.argv else "--onedir"
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", mode, "--windowed",
       "--name", "DocToPDF", "--paths", ".", "--icon", "assets/icon.ico",
       "--add-data", "assets/icon.png" + (";" if sys.platform == "win32" else ":") + "assets",
       "run.py"]
for m in EXCLUDES:
    cmd += ["--exclude-module", m]
sys.exit(subprocess.call(cmd))
