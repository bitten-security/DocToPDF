"""Qt GUI: drop files, pick an output folder, convert."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from . import __version__
from .converters import (
    SUPPORTED_EXTS, ConversionError, backend_for, collect_files, convert, find_soffice,
)

STYLE = """
* { font-size: 13px; }
QMainWindow, QWidget#root { background: #f6f7f9; }
QLabel#title { font-size: 20px; font-weight: 600; color: #1f2430; }
QLabel#hint, QLabel#status { color: #6b7280; }
QLabel#banner { background: #fff4e5; color: #8a5300; border: 1px solid #ffd8a0;
                border-radius: 6px; padding: 8px 10px; }
QListWidget { background: white; border: 2px dashed #cfd4dc; border-radius: 10px; padding: 4px; }
QListWidget[hasItems="true"] { border: 1px solid #d9dde4; }
QListWidget::item { padding: 6px 8px; border-radius: 6px; }
QListWidget::item:selected { background: #e8efff; color: #1f2430; }
QLineEdit { background: white; border: 1px solid #d9dde4; border-radius: 6px; padding: 6px 8px; }
QPushButton { background: white; border: 1px solid #d9dde4; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { background: #eef1f6; }
QPushButton:disabled { color: #a0a6b1; }
QPushButton#primary { background: #2f6df6; color: white; border: none; font-weight: 600;
                      padding: 9px 22px; }
QPushButton#primary:hover { background: #2559d1; }
QPushButton#primary:disabled { background: #a9c0f5; }
QProgressBar { border: none; background: #e3e7ee; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #2f6df6; border-radius: 4px; }
"""

PATH_ROLE = 0x0100  # Qt.UserRole
OUT_ROLE = 0x0101


class Worker(QObject):
    """Converts files sequentially off the UI thread."""

    progress = Signal(int, bool, str)  # row, ok, message (output path or error)
    finished = Signal()

    def __init__(self, files: list[Path], out_dir: str | None, overwrite: bool):
        super().__init__()
        self._files, self._out, self._overwrite = files, out_dir, overwrite
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        for row, f in enumerate(self._files):
            if self._cancel:
                break
            try:
                res = convert(f, self._out, self._overwrite)
                self.progress.emit(row, True, str(res.output))
            except ConversionError as exc:
                self.progress.emit(row, False, str(exc))
            except Exception as exc:  # noqa: BLE001 - keep the batch going
                self.progress.emit(row, False, f"Unexpected error: {exc}")
        self.finished.emit()


class DropList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setProperty("hasItems", False)

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent  # type: ignore[assignment]

    def dropEvent(self, e: QDropEvent) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            e.acceptProposedAction()

    def paintEvent(self, e) -> None:  # centered placeholder when empty
        super().paintEvent(e)
        if self.count() == 0:
            from PySide6.QtGui import QColor, QPainter

            p = QPainter(self.viewport())
            p.setPen(QColor("#9aa1ad"))
            p.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                       "Drop files or folders here\nor use “Add files”")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DocToPDF")
        self.resize(640, 560)
        self._thread: QThread | None = None
        self._worker: Worker | None = None
        self._queued: set[Path] = set()

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        lay.addWidget(QLabel("DocToPDF", objectName="title"))
        lay.addWidget(QLabel("Convert documents, spreadsheets, slides, images and text to PDF.",
                             objectName="hint"))

        self.banner = QLabel(
            "LibreOffice not found: Office files (docx, xlsx, pptx, odt…) can't be converted. "
            "Images, text, Markdown and HTML still work.", objectName="banner")
        self.banner.setWordWrap(True)
        self.banner.setVisible(find_soffice() is None)
        lay.addWidget(self.banner)

        self.list = DropList()
        self.list.files_dropped.connect(self.add_paths)
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        b_add = QPushButton("Add files…")
        b_add.clicked.connect(self.pick_files)
        b_dir = QPushButton("Add folder…")
        b_dir.clicked.connect(self.pick_folder)
        b_rm = QPushButton("Remove")
        b_rm.clicked.connect(self.remove_selected)
        b_clear = QPushButton("Clear")
        b_clear.clicked.connect(self.clear)
        for b in (b_add, b_dir, b_rm, b_clear):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Save to:"))
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Same folder as each source file")
        out_row.addWidget(self.out_edit, 1)
        b_out = QPushButton("Browse…")
        b_out.clicked.connect(self.pick_output)
        out_row.addWidget(b_out)
        lay.addLayout(out_row)

        self.overwrite = QCheckBox("Overwrite existing PDFs (otherwise add “(1)”)")
        lay.addWidget(self.overwrite)

        self.bar = QProgressBar(textVisible=False)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        bottom = QHBoxLayout()
        self.status = QLabel("", objectName="status")
        bottom.addWidget(self.status, 1)
        self.go = QPushButton("Convert to PDF", objectName="primary")
        self.go.clicked.connect(self.toggle_run)
        self.go.setEnabled(False)
        bottom.addWidget(self.go)
        lay.addLayout(bottom)

        self.list.itemDoubleClicked.connect(self.open_result)

    # ---- list management ------------------------------------------------- #
    def add_paths(self, paths: list) -> None:
        if self._thread:
            return
        files = collect_files(paths)
        added = 0
        for f in files:
            key = f.resolve()
            if key in self._queued:
                continue
            self._queued.add(key)
            item = QListWidgetItem(f"{f.name}    —    {f.parent}")
            item.setData(PATH_ROLE, str(f))
            item.setToolTip(str(f))
            self.list.addItem(item)
            added += 1
        if added:
            self.status.setText(f"{added} file(s) added.")
        else:
            self.status.setText("No new supported files found.")
        self._refresh()

    def pick_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files", "", f"Supported ({exts})")
        if paths:
            self.add_paths(paths)

    def pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Add folder")
        if d:
            self.add_paths([d])

    def pick_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Output folder")
        if d:
            self.out_edit.setText(d)

    def remove_selected(self) -> None:
        if self._thread:
            return
        for it in self.list.selectedItems():
            self._queued.discard(Path(it.data(PATH_ROLE)).resolve())
            self.list.takeItem(self.list.row(it))
        self._refresh()

    def clear(self) -> None:
        if self._thread:
            return
        self.list.clear()
        self._queued.clear()
        self.status.setText("")
        self._refresh()

    def _refresh(self) -> None:
        self.list.setProperty("hasItems", self.list.count() > 0)
        self.list.style().unpolish(self.list)
        self.list.style().polish(self.list)
        self.list.viewport().update()
        self.go.setEnabled(self.list.count() > 0 and self._thread is None)

    # ---- conversion ------------------------------------------------------ #
    def toggle_run(self) -> None:
        if self._worker:  # running -> cancel
            self._worker.cancel()
            self.go.setEnabled(False)
            self.status.setText("Cancelling after current file…")
            return
        files = [Path(self.list.item(i).data(PATH_ROLE)) for i in range(self.list.count())]
        # Reset previous results
        for i, f in enumerate(files):
            self.list.item(i).setText(f"{f.name}    —    {f.parent}")
            self.list.item(i).setForeground(Qt.GlobalColor.black)
            self.list.item(i).setData(OUT_ROLE, None)
        self.bar.setRange(0, len(files))
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.go.setText("Cancel")
        self.status.setText(f"Converting 0/{len(files)}…")

        self._worker = Worker(files, self.out_edit.text().strip() or None,
                              self.overwrite.isChecked())
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.on_progress)
        self._worker.finished.connect(self.on_finished)
        self._thread.start()

    def on_progress(self, row: int, ok: bool, msg: str) -> None:
        item = self.list.item(row)
        name = Path(item.data(PATH_ROLE)).name
        if ok:
            item.setText(f"✓  {name}  →  {Path(msg).name}")
            item.setForeground(Qt.GlobalColor.darkGreen)
            item.setData(OUT_ROLE, msg)
            item.setToolTip(f"{msg}\n(double-click to open)")
        else:
            item.setText(f"✗  {name}  —  {msg}")
            item.setForeground(Qt.GlobalColor.darkRed)
            item.setToolTip(msg)
        self.bar.setValue(row + 1)
        self.status.setText(f"Converting {row + 1}/{self.bar.maximum()}…")

    def on_finished(self) -> None:
        total = self.bar.maximum()
        ok = sum(1 for i in range(self.list.count()) if self.list.item(i).data(OUT_ROLE))
        done = self.bar.value()
        self._thread.quit()
        self._thread.wait()
        self._thread = self._worker = None
        self.go.setText("Convert to PDF")
        self.status.setText(
            f"Done: {ok} converted" + (f", {done - ok} failed" if done > ok else "")
            + (f", {total - done} cancelled" if done < total else "")
            + ". Double-click a converted item to open it.")
        self._refresh()

    def open_result(self, item: QListWidgetItem) -> None:
        out = item.data(OUT_ROLE)
        if out and Path(out).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def closeEvent(self, e) -> None:
        if self._worker:
            self._worker.cancel()
            self._thread.quit()
            self._thread.wait(5000)
        super().closeEvent(e)


def run_gui() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DocToPDF")
    app.setApplicationVersion(__version__)
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    return app.exec()
