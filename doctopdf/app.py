"""Tkinter GUI (runs on Windows 32/64-bit and Linux): drop files, pick a folder, convert."""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from . import __version__
from .converters import SUPPORTED_EXTS, ConversionError, collect_files, convert, find_soffice

try:  # drag & drop is optional: the app works without it
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # noqa: BLE001
    DND_FILES, TkinterDnD = None, None

BG, CARD, LINE = "#f6f7f9", "#ffffff", "#d9dde4"
TEXT, MUTED, ACCENT, ACCENT_D = "#1f2430", "#6b7280", "#2f6df6", "#2559d1"
OK, ERR = "#15803d", "#b91c1c"


def _icon_path() -> Path | None:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.png")
    return p if p.is_file() else None


class App:
    def __init__(self) -> None:
        self.root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
        self.root.title(f"DocToPDF {__version__}")
        self.root.geometry("700x600")
        self.root.minsize(560, 480)
        self.root.configure(bg=BG)
        self._set_icon()
        self._style()

        self.msgs: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.running = False
        self.done = self.total = 0
        self.queued: set[Path] = set()
        self.rows: dict[str, Path] = {}  # tree iid -> source path
        self.outputs: dict[str, str] = {}  # tree iid -> produced PDF

        self.out_var = tk.StringVar()
        self.over_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar()
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(100, self._poll)

    # ---- setup ------------------------------------------------------------ #
    def _set_icon(self) -> None:
        icon = _icon_path()
        if not icon:
            return
        try:
            if icon.suffix == ".ico":
                self.root.iconbitmap(default=str(icon))
            else:
                self.root.iconphoto(True, tk.PhotoImage(file=str(icon)))
        except tk.TclError:
            pass

    def _style(self) -> None:
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=TEXT)
        s.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Banner.TLabel", background="#fff4e5", foreground="#8a5300", padding=8)
        s.configure("TButton", background=CARD, foreground=TEXT, bordercolor=LINE,
                    lightcolor=CARD, darkcolor=CARD, padding=(12, 6), focuscolor=CARD)
        s.map("TButton", background=[("active", "#eef1f6")], foreground=[("disabled", "#a0a6b1")])
        s.configure("Primary.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT,
                    lightcolor=ACCENT, darkcolor=ACCENT, padding=(22, 8), font=("Segoe UI", 10, "bold"))
        s.map("Primary.TButton", background=[("active", ACCENT_D), ("disabled", "#a9c0f5")],
              foreground=[("disabled", "white")])
        s.configure("TCheckbutton", background=BG, foreground=TEXT, focuscolor=BG)
        s.configure("TEntry", fieldbackground=CARD, bordercolor=LINE, padding=5)
        s.configure("Horizontal.TProgressbar", troughcolor="#e3e7ee", background=ACCENT,
                    bordercolor="#e3e7ee", lightcolor=ACCENT, darkcolor=ACCENT, thickness=8)
        s.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
                    bordercolor=LINE, rowheight=28, borderwidth=0)
        s.map("Treeview", background=[("selected", "#e8efff")], foreground=[("selected", TEXT)])
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    def _build(self) -> None:
        f = ttk.Frame(self.root, padding=(20, 16))
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="DocToPDF", style="Title.TLabel").pack(anchor="w")
        ttk.Label(f, text="Convert documents, spreadsheets, slides, images and text to PDF.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))

        if find_soffice() is None:
            ttk.Label(f, text="LibreOffice not found: Office files (docx, xlsx, pptx, odt…) "
                      "can't be converted. Images, text, Markdown and HTML still work.",
                      style="Banner.TLabel", wraplength=640, justify="left").pack(fill="x", pady=(0, 10))

        # Bottom bar first so it never gets squeezed out when the window is small.
        bottom = ttk.Frame(f)
        bottom.pack(fill="x", pady=(12, 0), side="bottom")
        ttk.Label(bottom, textvariable=self.status_var, style="Muted.TLabel").pack(side="left")
        self.go = ttk.Button(bottom, text="Convert to PDF", style="Primary.TButton",
                             command=self.toggle_run, state="disabled")
        self.go.pack(side="right")
        self.progress = ttk.Progressbar(f, mode="determinate")  # packed only while running

        ttk.Checkbutton(f, text="Overwrite existing PDFs (otherwise add “(1)”)",
                        variable=self.over_var).pack(side="bottom", anchor="w", pady=(8, 0))
        ttk.Label(f, text="Leave empty to save next to each source file.",
                  style="Muted.TLabel").pack(side="bottom", anchor="w", pady=(2, 0))
        out = ttk.Frame(f)
        out.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Label(out, text="Save to:").pack(side="left")
        ttk.Entry(out, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(out, text="Browse…", command=self.pick_output).pack(side="left")

        bar = ttk.Frame(f)
        bar.pack(side="bottom", fill="x", pady=(10, 0))
        for text, cmd in (("Add files…", self.pick_files), ("Add folder…", self.pick_folder),
                          ("Remove", self.remove_selected), ("Clear", self.clear)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 8))

        box = tk.Frame(f, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(box, columns=("file", "result"), show="", selectmode="extended")
        self.tree.column("#0", width=0, stretch=False)
        self.tree.column("file", width=300, anchor="w")
        self.tree.column("result", width=300, anchor="w")
        self.tree.tag_configure("ok", foreground=OK)
        self.tree.tag_configure("err", foreground=ERR)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.hint = tk.Label(box, text="Drop files or folders here\nor use “Add files…”",
                             bg=CARD, fg="#9aa1ad", font=("Segoe UI", 11))
        self.hint.place(relx=0.5, rely=0.5, anchor="center")
        self.tree.bind("<Double-1>", self._open_result)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        if DND_FILES:
            for w in (self.tree, box, self.hint):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)

    # ---- list management --------------------------------------------------- #
    def _on_drop(self, event) -> None:
        self.add_paths(list(self.root.tk.splitlist(event.data)))

    def add_paths(self, paths: list[str]) -> None:
        if self.running:
            return
        added = 0
        for f in collect_files(paths):
            key = f.resolve()
            if key in self.queued:
                continue
            self.queued.add(key)
            iid = self.tree.insert("", "end", values=(f.name, str(f.parent)))
            self.rows[iid] = f
            added += 1
        self.status_var.set(f"{added} file(s) added." if added else "No new supported files found.")
        self._refresh()

    def pick_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTS))
        paths = filedialog.askopenfilenames(
            title="Add files", filetypes=[("Supported files", exts), ("All files", "*.*")])
        if paths:
            self.add_paths(list(paths))

    def pick_folder(self) -> None:
        d = filedialog.askdirectory(title="Add folder")
        if d:
            self.add_paths([d])

    def pick_output(self) -> None:
        d = filedialog.askdirectory(title="Output folder")
        if d:
            self.out_var.set(d)

    def remove_selected(self) -> None:
        if self.running:
            return
        for iid in self.tree.selection():
            self.queued.discard(self.rows.pop(iid).resolve())
            self.outputs.pop(iid, None)
            self.tree.delete(iid)
        self._refresh()

    def clear(self) -> None:
        if self.running:
            return
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        self.outputs.clear()
        self.queued.clear()
        self.status_var.set("")
        self._refresh()

    def _refresh(self) -> None:
        if self.rows:
            self.hint.place_forget()
        else:
            self.hint.place(relx=0.5, rely=0.5, anchor="center")
        self.go.configure(state="normal" if self.rows else "disabled")

    # ---- conversion --------------------------------------------------------- #
    def toggle_run(self) -> None:
        if self.running:
            self.cancel.set()
            self.go.configure(state="disabled")
            self.status_var.set("Cancelling after current file…")
            return
        iids = list(self.tree.get_children())
        for iid in iids:
            self.tree.item(iid, values=(self.rows[iid].name, str(self.rows[iid].parent)), tags=())
        self.outputs.clear()
        self.cancel.clear()
        self.running = True
        self.done, self.total = 0, len(iids)
        self.progress.configure(maximum=self.total, value=0)
        self.progress.pack(fill="x", pady=(10, 0), side="bottom", before=self.go.master)
        self.go.configure(text="Cancel")
        self.status_var.set(f"Converting 0/{self.total}…")
        jobs = [(iid, self.rows[iid]) for iid in iids]
        out = self.out_var.get().strip() or None
        threading.Thread(target=self._work, args=(jobs, out, self.over_var.get()),
                         daemon=True).start()

    def _work(self, jobs, out, overwrite) -> None:
        for iid, f in jobs:
            if self.cancel.is_set():
                break
            try:
                self.msgs.put((iid, True, str(convert(f, out, overwrite).output)))
            except ConversionError as exc:
                self.msgs.put((iid, False, str(exc)))
            except Exception as exc:  # noqa: BLE001 - keep the batch going
                self.msgs.put((iid, False, f"Unexpected error: {exc}"))
        self.msgs.put(None)

    def _poll(self) -> None:
        try:
            while True:
                msg = self.msgs.get_nowait()
                if msg is None:
                    self._finished()
                else:
                    self._progress(*msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _progress(self, iid: str, ok: bool, msg: str) -> None:
        if iid not in self.rows:
            return
        name = self.rows[iid].name
        if ok:
            self.outputs[iid] = msg
            self.tree.item(iid, values=(f"✓  {name}", f"→ {Path(msg).name}"), tags=("ok",))
        else:
            self.tree.item(iid, values=(f"✗  {name}", msg), tags=("err",))
        self.done += 1
        self.progress.configure(value=self.done)
        self.status_var.set(f"Converting {self.done}/{self.total}…")

    def _finished(self) -> None:
        ok = len(self.outputs)
        self.running = False
        self.go.configure(text="Convert to PDF", state="normal")
        self.progress.pack_forget()
        self.status_var.set(
            f"Done: {ok} converted"
            + (f", {self.done - ok} failed" if self.done > ok else "")
            + (f", {self.total - self.done} cancelled" if self.done < self.total else "")
            + ". Double-click a converted item to open it.")

    def _open_result(self, _event) -> None:
        out = self.outputs.get(self.tree.focus())
        if out and Path(out).is_file():
            try:
                if sys.platform == "win32":
                    os.startfile(out)  # noqa: S606
                else:
                    import subprocess

                    subprocess.Popen(["xdg-open", out])
            except OSError:
                pass

    def _close(self) -> None:
        self.cancel.set()
        self.root.destroy()


def run_gui() -> int:
    App().root.mainloop()
    return 0
