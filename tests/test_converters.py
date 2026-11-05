import subprocess
from pathlib import Path

import pytest
from PIL import Image

from doctopdf import converters as c
from doctopdf.converters import ConversionError, collect_files, convert, unique_path


def is_pdf(p: Path) -> bool:
    return p.read_bytes()[:5] == b"%PDF-"


def test_image_png_and_transparency(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGBA", (50, 40), (255, 0, 0, 0)).save(src)
    res = convert(src)
    assert res.output == tmp_path / "a.pdf" and is_pdf(res.output)


def test_multiframe_tiff(tmp_path):
    src = tmp_path / "m.tif"
    frames = [Image.new("RGB", (30, 30), col) for col in ("red", "green", "blue")]
    frames[0].save(src, save_all=True, append_images=frames[1:])
    out = convert(src).output
    assert out.read_bytes().count(b"/Type /Page\n") + out.read_bytes().count(b"/Type /Page ") >= 3 \
        or out.read_bytes().count(b"/Type/Page") >= 3


@pytest.mark.parametrize("name,body", [
    ("n.txt", "olá mundo\nlinha 2"), ("n.md", "# Título\n\n- item\n"),
    ("n.html", "<h1>Hi</h1><p>text</p>"),
])
def test_text_backends(tmp_path, name, body):
    src = tmp_path / name
    src.write_text(body, encoding="utf-8")
    assert is_pdf(convert(src).output)


def test_cp1252_text(tmp_path):
    src = tmp_path / "x.txt"
    src.write_bytes("café".encode("cp1252"))
    assert is_pdf(convert(src).output)


def test_unique_name_and_overwrite(tmp_path):
    src = tmp_path / "d.txt"
    src.write_text("x")
    first = convert(src).output
    second = convert(src).output
    assert second.name == "d (1).pdf" and first.exists()
    third = convert(src, overwrite=True).output
    assert third == first


def test_out_dir_created(tmp_path):
    src = tmp_path / "d.txt"
    src.write_text("x")
    out = convert(src, tmp_path / "new" / "sub").output
    assert out.parent.name == "sub" and is_pdf(out)


def test_errors(tmp_path):
    with pytest.raises(ConversionError):
        convert(tmp_path / "missing.txt")
    bad = tmp_path / "f.xyz"
    bad.write_text("x")
    with pytest.raises(ConversionError):
        convert(bad)
    corrupt = tmp_path / "bad.png"
    corrupt.write_bytes(b"not an image")
    with pytest.raises(ConversionError):
        convert(corrupt)
    assert not list(tmp_path.glob(".doctopdf-*")), "temp files must be cleaned up"
    assert not (tmp_path / "bad.pdf").exists()


def test_collect_files(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.docx").write_text("x")
    (tmp_path / "sub" / "b.PNG").write_text("x")
    (tmp_path / "~$lock.docx").write_text("x")
    (tmp_path / "c.zip").write_text("x")
    got = {p.name for p in collect_files([tmp_path, tmp_path / "a.docx"])}
    assert got == {"a.docx", "b.PNG"}


def test_unique_path(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_text("x")
    assert unique_path(p).name == "a (1).pdf"


def test_office_missing_soffice(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "find_soffice", lambda: None)
    src = tmp_path / "a.docx"
    src.write_text("x")
    with pytest.raises(c.OfficeUnavailable):
        convert(src)


def test_office_failure_and_timeout(tmp_path, monkeypatch):
    src = tmp_path / "a.docx"
    src.write_text("x")
    monkeypatch.setattr(c, "find_soffice", lambda: "soffice")
    monkeypatch.setattr(c.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "boom"))
    with pytest.raises(ConversionError, match="boom"):
        convert(src)

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("soffice", 1)

    monkeypatch.setattr(c.subprocess, "run", timeout)
    with pytest.raises(ConversionError, match="timed out"):
        convert(src)


@pytest.mark.skipif(c.find_soffice() is None, reason="LibreOffice not installed")
def test_office_real(tmp_path):
    src = tmp_path / "r.rtf"
    src.write_text(r"{\rtf1\ansi Hello}")
    assert is_pdf(convert(src).output)


def test_html_sanitizing_and_unicode(tmp_path):
    src = tmp_path / "x.html"
    src.write_text(
        "<h1>Título ✓ → €</h1><script>alert(1)</script>"
        "<img src='http://127.0.0.1:9/x.png'><p>ok</p>", encoding="utf-8")
    assert is_pdf(convert(src).output)  # remote image must not be fetched (would raise/hang)


def test_malformed_html_falls_back(tmp_path):
    src = tmp_path / "bad.html"
    src.write_text("<p><b>unclosed <table><tr><td>x", encoding="utf-8")
    assert is_pdf(convert(src).output)


def test_markdown_table_and_code(tmp_path):
    src = tmp_path / "m.md"
    src.write_text("# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode €\n```\n", encoding="utf-8")
    assert is_pdf(convert(src).output)


def test_gui_smoke(tmp_path):
    import tkinter

    from doctopdf.app import App

    src = tmp_path / "g.txt"
    src.write_text("hello")
    try:
        app = App()
    except tkinter.TclError:
        pytest.skip("no display available")
    try:
        app.add_paths([str(src)])
        assert len(app.rows) == 1
        app.toggle_run()
        import time

        end = time.time() + 20
        while app.running and time.time() < end:
            app.root.update()
            time.sleep(0.05)
        assert not app.running and len(app.outputs) == 1
    finally:
        app.root.destroy()
