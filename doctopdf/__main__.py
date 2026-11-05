"""Entry point: no arguments opens the GUI; with file arguments runs headless."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .converters import ConversionError, collect_files, convert


def run_cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="doctopdf", description="Convert documents to PDF.")
    ap.add_argument("paths", nargs="+", help="files or folders")
    ap.add_argument("-o", "--out", help="output folder (default: next to each source)")
    ap.add_argument("--overwrite", action="store_true", help="replace existing PDFs")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    files = collect_files(args.paths)
    if not files:
        print("No supported files found.", file=sys.stderr)
        return 2
    failures = 0
    for f in files:
        try:
            res = convert(f, args.out, args.overwrite)
            print(f"OK    {f} -> {res.output}")
        except ConversionError as exc:
            failures += 1
            print(f"FAIL  {f}: {exc}", file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    if len(sys.argv) > 1:
        return run_cli(sys.argv[1:])
    from .app import run_gui

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
