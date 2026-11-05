# DocToPDF

Simple, clean document-to-PDF converter for Windows and Linux. Drop files, click **Convert**.

| Input | Engine |
|---|---|
| docx, doc, odt, rtf, xlsx, xls, ods, csv, pptx, ppt, odp | LibreOffice (headless) |
| png, jpg, bmp, gif, tiff, webp | Pillow (multi-page TIFF/GIF supported) |
| txt, md, html | Qt text engine (built in) |

LibreOffice is only needed for Office formats. The app detects it automatically
(PATH, standard install folders, or `DOCTOPDF_SOFFICE=/path/to/soffice`) and shows a banner if missing.

## Run
```bash
pip install -r requirements.txt
python -m doctopdf                      # GUI
python -m doctopdf a.docx dir/ -o out   # CLI (files/folders, --overwrite)
```

## Behavior
- Never overwrites by default: `report.pdf` -> `report (1).pdf`.
- Output is written to a temp file and moved into place, so failures leave nothing half-written.
- One bad file never stops a batch; each item shows ✓/✗ with the reason. Double-click a ✓ to open the PDF.
- LibreOffice runs with its own profile and a 180 s timeout, so it won't clash with an open LibreOffice.

## Test / Build
```bash
pip install -r requirements-dev.txt
pytest
python build.py     # standalone binary in dist/ (build on each target OS)
```

## Releases
Tag `vX.Y.Z` and push: GitHub Actions runs the tests, then attaches
`DocToPDF-Setup-X.Y.Z.exe` (Windows installer, Inno Setup) and `DocToPDF-linux-x86_64.tar.gz` to the release.
Local installer build (needs Inno Setup 6): `python build.py` then `iscc /DAppVersion=X.Y.Z installer\DocToPDF.iss`.
