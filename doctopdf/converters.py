"""Conversion core: turns supported documents into PDF.

Backends
  * image  -> Pillow (multi-frame TIFF/GIF become multi-page PDFs)
  * text   -> fpdf2 + bundled DejaVu fonts (txt, md, html); pure Python
  * office -> LibreOffice headless (doc/docx/odt/rtf/xls/xlsx/ods/ppt/pptx/odp/csv...)

Every conversion is written to a temp file first and moved into place, so a
failure never leaves a half-written PDF behind.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
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


def _asset_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets"


def _new_pdf():
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(True, 18)
    fonts = _asset_dir() / "fonts"
    for style, name in (("", "DejaVuSans"), ("B", "DejaVuSans-Bold"),
                        ("I", "DejaVuSans-Oblique"), ("BI", "DejaVuSans-BoldOblique")):
        pdf.add_font("DejaVu", style, str(fonts / f"{name}.ttf"))
    pdf.add_font("DejaVuMono", "", str(fonts / "DejaVuSansMono.ttf"))
    pdf.add_font("DejaVuMono", "B", str(fonts / "DejaVuSansMono-Bold.ttf"))
    pdf.set_font("DejaVu", size=11)
    pdf.add_page()
    return pdf


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _plain_to_pdf(text: str, dest: Path) -> None:
    pdf = _new_pdf()
    pdf.set_font("DejaVuMono", size=9.5)
    for line in _CTRL.sub("", text).expandtabs(4).splitlines() or [""]:
        pdf.multi_cell(0, 4.8, line or " ", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(dest))


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    ex = _TextExtractor()
    ex.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(ex.parts)).strip()


_DROP_BLOCKS = re.compile(r"<(script|style|head|svg|iframe|object|embed)\b.*?</\1\s*>", re.I | re.S)
_COMMENTS = re.compile(r"<!--.*?-->", re.S)
_IMG = re.compile(r"<img\b[^>]*>", re.I)
_SRC = re.compile(r"""src\s*=\s*(["'])(.*?)\1""", re.I | re.S)


def _sanitize_html(html: str, base_dir: Path) -> str:
    """Drop active content and never fetch remote images; keep local ones."""
    html = _COMMENTS.sub("", html)
    html = _DROP_BLOCKS.sub("", html)

    def fix_img(m: re.Match) -> str:
        src = _SRC.search(m.group(0))
        if not src:
            return ""
        ref = src.group(2).strip()
        if re.match(r"^[a-z][a-z0-9+.-]*:", ref, re.I) and not re.match(r"^[a-z]:[\\/]", ref, re.I):
            return ""  # http(s), data:, file:, ... are not loaded
        local = (base_dir / ref).resolve()
        if not local.is_file():
            return ""
        return f'<img src="{local}" width="400">'

    return _IMG.sub(fix_img, html)


def _html_to_pdf(html: str, dest: Path, base_dir: Path) -> None:
    html = _sanitize_html(html, base_dir)
    try:
        pdf = _new_pdf()
        from fpdf.fonts import FontFace

        mono = FontFace(family="DejaVuMono")
        pdf.write_html(html, tag_styles={"pre": mono, "code": mono})
        pdf.output(str(dest))
    except Exception:  # noqa: BLE001 - odd markup: fall back to readable plain text
        _plain_to_pdf(_html_to_text(html), dest)


def _text_to_pdf(src: Path, dest: Path) -> None:
    ext = src.suffix.lower()
    text = _read_text(src)
    if ext in (".md", ".markdown"):
        import markdown

        html = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
        _html_to_pdf(html, dest, src.parent)
    elif ext in (".html", ".htm"):
        _html_to_pdf(text, dest, src.parent)
    else:
        _plain_to_pdf(text, dest)


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
