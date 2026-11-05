"""Build a standalone app for the current OS/Python architecture.

Output: dist/<label>/DocToPDF/   (label = x64 | x86 | linux)
Use `--onefile` for a single executable (dist/<label>/DocToPDF[.exe]).
PyInstaller does not cross-compile: run with a 32-bit Python to get an x86 build.
"""
import struct
import subprocess
import sys

BITS = struct.calcsize("P") * 8
LABEL = ("x64" if BITS == 64 else "x86") if sys.platform == "win32" else "linux"
SEP = ";" if sys.platform == "win32" else ":"

mode = "--onefile" if "--onefile" in sys.argv else "--onedir"
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", mode, "--windowed",
       "--name", "DocToPDF", "--paths", ".", "--icon", "assets/icon.ico",
       "--add-data", f"assets{SEP}assets",
       "--distpath", f"dist/{LABEL}", "--workpath", f"build/{LABEL}",
       "--collect-all", "tkinterdnd2",
       "run.py"]
for m in ("numpy", "cryptography", "matplotlib", "pandas", "scipy", "PySide6", "PyQt5", "PyQt6",
          "IPython", "pytest", "setuptools"):
    cmd += ["--exclude-module", m]
print(f"Building DocToPDF for {LABEL} ({BITS}-bit)")
sys.exit(subprocess.call(cmd))
