"""Conversion core: turns supported documents into PDF.

Backends
  * image  -> Pillow (multi-frame TIFF/GIF become multi-page PDFs)
  * text   -> Qt text engine (txt, md, html) - no external dependency
  * office -> LibreOffice headless (doc/docx/odt/rtf/xls/xlsx/ods/ppt/pptx/odp/csv...)

Every conversion is written to a temp file first and moved into place, so a
failure never leaves a half-written PDF behind.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
TEXT_EXTS = {".txt", ".md", ".markdown", ".html", ".htm"}
OFFICE_EXTS = {
    ".doc", ".docx", ".odt", ".rtf", ".wpd",
    ".xls", ".xlsx", ".ods", ".csv",
    ".ppt", ".pptx", ".odp",
}
SUPPORTED_EXTS = IMAGE_EXTS | TEXT_EXTS | OFFICE_EXTS

OFFICE_TIMEOUT_S = 180


class ConversionError(Exception):
    """A conversion failed; the message is safe to show to the user."""


class OfficeUnavailable(ConversionError):
    """LibreOffice is needed for this file but was not found."""


def is_supported(path: Path | str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTS


def backend_for(path: Path | str) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in TEXT_EXTS:
        return "text"
    if ext in OFFICE_EXTS:
        return "office"
    raise ConversionError(f"Unsupported file type: {ext or '(no extension)'}")


# --------------------------------------------------------------------------- #
# LibreOffice discovery
# --------------------------------------------------------------------------- #
def find_soffice() -> str | None:
    override = os.environ.get("DOCTOPDF_SOFFICE")
    if override and Path(override).is_file():
        return override
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    candidates: list[str] = []
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                candidates.append(str(Path(base) / "LibreOffice" / "program" / "soffice.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    else:
        candidates += [
            "/usr/bin/soffice", "/usr/local/bin/soffice", "/opt/libreoffice/program/soffice",
            "/snap/bin/libreoffice", "/var/lib/flatpak/exports/bin/org.libreoffice.LibreOffice",
        ]
    return next((c for c in candidates if Path(c).is_file()), None)


def _profile_dir() -> Path:
    """Dedicated LibreOffice profile: avoids clashing with a running instance."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "DocToPDF" / "lo-profile"


# --------------------------------------------------------------------------- #
# Backends: each writes a PDF to `dest`
# --------------------------------------------------------------------------- #
def _image_to_pdf(src: Path, dest: Path) -> None:
    from PIL import Image, ImageOps

    try:
        with Image.open(src) as im:
            dpi = im.info.get("dpi", (150, 150))[0] or 150
            frames = []
            for i in range(getattr(im, "n_frames", 1)):
                im.seek(i)
                frame = ImageOps.exif_transpose(im.copy())
                if frame.mode in ("RGBA", "LA", "P"):
                    rgba = frame.convert("RGBA")
                    bg = Image.new("RGB", rgba.size, "white")
                    bg.paste(rgba, mask=rgba.split()[3])
                    frame = bg
                elif frame.mode != "RGB":
                    frame = frame.convert("RGB")
                frames.append(frame)
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types
        raise ConversionError(f"Could not read image: {exc}") from exc
    frames[0].save(dest, "PDF", save_all=True, append_images=frames[1:], resolution=float(dpi))


def _read_text(src: Path) -> str:
    raw = src.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _ensure_qt():
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QGuiApplication(sys.argv[:1])
    return app


def _text_to_pdf(src: Path, dest: Path) -> None:
    _ensure_qt()
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument

    ext = src.suffix.lower()
    text = _read_text(src)
    doc = QTextDocument()
    if ext in (".md", ".markdown"):
        doc.setMarkdown(text)
    elif ext in (".html", ".htm"):
        doc.setHtml(text)
    else:
        doc.setDefaultFont(QFont("Monospace", 10))
        doc.setPlainText(text)

    writer = QPdfWriter(str(dest))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(18, 18, 18, 18), QPageLayout.Unit.Millimeter)
    writer.setResolution(150)
    doc.setPageSize(writer.pageLayout().paintRectPixels(writer.resolution()).size().toSizeF())
    doc.print_(writer)


def _office_to_pdf(src: Path, dest: Path) -> None:
    soffice = find_soffice()
    if not soffice:
        raise OfficeUnavailable(
            "LibreOffice is required for this file type. Install it from "
            "libreoffice.org (or set DOCTOPDF_SOFFICE to soffice's path)."
        )
    profile = _profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="doctopdf-") as work:
        cmd = [
            soffice, "--headless", "--norestore", "--nologo", "--nodefault",
            f"-env:UserInstallation={profile.as_uri()}",
            "--convert-to", "pdf", "--outdir", work, str(src),
        ]
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=OFFICE_TIMEOUT_S, **kwargs
            )
        except subprocess.TimeoutExpired as exc:
            raise ConversionError(
                f"LibreOffice timed out after {OFFICE_TIMEOUT_S}s."
            ) from exc
        except OSError as exc:
            raise ConversionError(f"Could not start LibreOffice: {exc}") from exc
        produced = Path(work) / (src.stem + ".pdf")
        if proc.returncode != 0 or not produced.is_file():
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise ConversionError(
                "LibreOffice could not convert this file"
                + (f": {detail[-1]}" if detail else ".")
            )
        shutil.move(str(produced), str(dest))


_BACKENDS = {"image": _image_to_pdf, "text": _text_to_pdf, "office": _office_to_pdf}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def unique_path(path: Path) -> Path:
    """`a.pdf` -> `a (1).pdf` -> `a (2).pdf` ... without touching existing files."""
    if not path.exists():
        return path
    n = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


@dataclass(frozen=True)
class Result:
    source: Path
    output: Path


def convert(src: Path | str, out_dir: Path | str | None = None, overwrite: bool = False) -> Result:
    """Convert one file to PDF. Returns the final output path or raises ConversionError."""
    src = Path(src)
    if not src.is_file():
        raise ConversionError("File not found.")
    backend = backend_for(src)  # raises for unsupported types
    out_dir = Path(out_dir) if out_dir else src.parent
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConversionError(f"Cannot create output folder: {exc}") from exc

    final = out_dir / (src.stem + ".pdf")
    if not overwrite:
        final = unique_path(final)

    fd, tmp_name = tempfile.mkstemp(suffix=".pdf", prefix=".doctopdf-", dir=out_dir)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        _BACKENDS[backend](src, tmp)
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise ConversionError("Conversion produced an empty file.")
        os.replace(tmp, final)
    except ConversionError:
        raise
    except PermissionError as exc:
        raise ConversionError(f"Cannot write {final.name}: is it open in another program?") from exc
    except Exception as exc:  # noqa: BLE001 - never crash the batch on one bad file
        raise ConversionError(f"Unexpected error: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return Result(src, final)


def collect_files(paths: list[Path | str], recursive: bool = True) -> list[Path]:
    """Expand files/folders into a de-duplicated list of supported files."""
    seen: set[Path] = set()
    out: list[Path] = []
    for p in map(Path, paths):
        items = (
            sorted(p.rglob("*") if recursive else p.glob("*")) if p.is_dir() else [p]
        )
        for item in items:
            if item.is_file() and is_supported(item) and not item.name.startswith(("~$", ".")):
                key = item.resolve()
                if key not in seen:
                    seen.add(key)
                    out.append(item)
    return out
