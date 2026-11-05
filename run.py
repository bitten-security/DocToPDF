"""Frozen-app launcher (PyInstaller needs a top-level script with absolute imports)."""
import sys

from doctopdf.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
