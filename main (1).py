import csv
import hashlib
import os
import queue
import shutil
import threading
import time
import tkinter as tk
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_NAME = "Duplicate File Finder"
CHUNK_SIZE = 1024 * 1024  # Read files in 1 MB chunks to limit memory use.


def format_size(size):
    """Convert bytes into a readable size string."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def sha256_file(path):
    """Return the SHA-256 digest of a file, reading it in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        while True:
            chunk = file.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicate_groups(root, events, cancel_event):
    """
    Find duplicate files by grouping candidates by size, then hashing them.
    Returns a list of groups; each group contains Path objects.
    """
    root = Path(root)
    by_size = defaultdict(list)
    scanned = 0
    errors = 0

    events.put(("status", "Finding files…"))
    for current, dirs, files in os.walk(root, onerror=lambda _e: None):
        if cancel_event.is_set():
            return [], scanned, errors
        # Avoid scanning our own quarantine folder if it is inside the chosen root.
        dirs[:] = [d for d in dirs if d != ".duplicate_finder_quarantine"]
        for filename in files:
            if cancel_event.is_set():
                return [], scanned, errors
            path = Path(current) / filename
            try:
                if path.is_file():
                    size = path.stat().st_size
                    by_size[size].append(path)
                    scanned += 1
            except (OSError, PermissionError):
                errors += 1
            if scanned % 100 == 0:
                events.put(("progress", scanned, f"Found {scanned} files…"))

    candidates = [paths for paths in by_size.values() if len(paths) > 1]
    hash_groups = defaultdict(list)
    total_candidates = sum(len(group) for group in candidates)
    done = 0

    events.put(("status", f"Hashing {total_candidates} same-size candidate files…"))
    for paths in candidates:
        for path in paths:
            if cancel_event.is_set():
                return [], scanned, errors
            try:
                digest = sha256_file(path)
                # Include size in the key as an additional consistency check.
                hash_groups[(path.stat().st_size, digest)].append(path)
            except (OSError, PermissionError):
                errors += 1
            done += 1
            if done % 5 == 0 or done == total_candidates:
                events.put(("progress", scanned, f"Checking duplicate candidates: {done}/{total_candidates}"))
    groups = [sorted(paths, key=lambda p: str(p).lower())
              for paths in hash_groups.values() if len(paths) > 1]
    groups.sort(key=lambda group: str(group[0]).lower())
    return groups, scanned, errors


class DuplicateFileFinder(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1120x720")
        self.minsize(900, 600)
        self.configure(bg="#f3f5f9")

        self.root_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Choose a folder to begin.")
        self.summary_var = tk.StringVar(value="No scan results yet.")
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker = None
        self.groups = []
        self.scanned_count = 0
        self.error_count = 0
        self.group_for_item = {}
        self.item_paths = {}
        self._setup_style()
        self._build_ui()
        self.after(100, self._process_events)

    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f3f5f9")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f3f5f9", foreground="#1f2937", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground="#111827")
        style.configure("Sub.TLabel", foreground="#667085", font=("Segoe UI", 10))
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 9), background="#ffffff", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(12, 8))
        style.configure("TButton", padding=(10, 7))

    def _build_ui(self):
        outer = ttk.Frame(self, padding=22)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text="Duplicate File Finder", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Find identical files, review storage usage, and safely quarantine extra copies.",
                  style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

        picker = ttk.Frame(outer, style="Card.TFrame", padding=14)
        picker.pack(fill="x", pady=(0, 12))
        ttk.Label(picker, text="Folder to scan", background="#ffffff", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        line = ttk.Frame(picker, style="Card.TFrame")
        line.pack(fill="x", pady=(8, 0))
        entry = ttk.Entry(line, textvariable=self.root_var)
        entry.pack(side="left", fill="x", expand=True, ipady=5)
        ttk.Button(line, text="Browse…", command=self._browse).pack(side="left", padx=(8, 0))
        self.scan_button = ttk.Button(line, text="Scan for Duplicates", style="Accent.TButton", command=self._start_scan)
        self.scan_button.pack(side="left", padx=(8, 0))
        self.cancel_button = ttk.Button(line, text="Cancel", command=self._cancel_scan, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))

        stats = ttk.Frame(outer)
        stats.pack(fill="x", pady=(0, 12))
        self.stat_files = self._stat_card(stats, "FILES SCANNED", "0")
        self.stat_groups = self._stat_card(stats, "DUPLICATE GROUPS", "0")
        self.stat_dupes = self._stat_card(stats, "EXTRA COPIES", "0")
        self.stat_space = self._stat_card(stats, "POTENTIAL SPACE TO FREE", "0 B")

        results = ttk.Frame(outer, style="Card.TFrame", padding=12)
        results.pack(fill="both", expand=True)
        top = ttk.Frame(results, style="Card.TFrame")
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Scan results", background="#ffffff", font=("Segoe UI", 12, "bold")).pack(side="left")
        ttk.Button(top, text="Export CSV", command=self._export_csv).pack(side="right")
        ttk.Button(top, text="Quarantine selected", command=self._quarantine_selected).pack(side="right", padx=(0, 8))
        ttk.Label(results, text="Each group contains files with identical size and SHA-256 content hash.",
                  background="#ffffff", foreground="#667085").pack(anchor="w", pady=(0, 8))

        columns = ("group", "name", "size", "path")
        self.tree = ttk.Treeview(results, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("group", text="Group")
        self.tree.heading("name", text="File name")
        self.tree.heading("size", text="Size")
        self.tree.heading("path", text="Full path")
        self.tree.column("group", width=75, anchor="center", stretch=False)
        self.tree.column("name", width=190)
        self.tree.column("size", width=100, anchor="e", stretch=False)
        self.tree.column("path", width=580)
        scrollbar = ttk.Scrollbar(results, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(12, 0))
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=190)
        self.progress.pack(side="left", padx=(0, 12))
        ttk.Label(footer, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        ttk.Label(footer, textvariable=self.summary_var, style="Sub.TLabel").pack(side="right")

    def _stat_card(self, parent, label, value):
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        card.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Label(card, text=label, background="#ffffff", foreground="#667085",
                  font=("Segoe UI", 8, "bold")).pack(anchor="w")
        number = ttk.Label(card, text=value, background="#ffffff", foreground="#111827",
                           font=("Segoe UI", 16, "bold"))
        number.pack(anchor="w", pady=(5, 0))
        return number

    def _browse(self):
        folder = filedialog.askdirectory(title="Choose folder to scan")
        if folder:
            self.root_var.set(folder)

    def _start_scan(self):
        root = self.root_var.get().strip()
        if not root or not Path(root).is_dir():
            messagebox.showerror("Invalid folder", "Please choose an existing folder to scan.")
            return
        if self.worker and self.worker.is_alive():
            return
        self._clear_results()
        self.cancel_event.clear()
        self.scan_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.start(12)
        self.status_var.set("Starting scan…")
        self.summary_var.set("")
        self.worker = threading.Thread(target=self._scan_worker, args=(root,), daemon=True)
        self.worker.start()

    def _scan_worker(self, root):
        try:
            groups, scanned, errors = find_duplicate_groups(root, self.events, self.cancel_event)
            self.events.put(("complete", groups, scanned, errors, self.cancel_event.is_set()))
        except Exception as exc:
            self.events.put(("fatal", str(exc)))

    def _cancel_scan(self):
        self.cancel_event.set()
        self.status_var.set("Cancelling scan…")

    def _process_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "status":
                    self.status_var.set(event[1])
                elif kind == "progress":
                    self.stat_files.configure(text=str(event[1]))
                    self.status_var.set(event[2])
                elif kind == "complete":
                    _, groups, scanned, errors, cancelled = event
                    self.groups = groups
                    self.scanned_count = scanned
                    self.error_count = errors
                    self._render_groups()
                    self.progress.stop()
                    self.scan_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    if cancelled:
                        self.status_var.set("Scan cancelled.")
                    else:
                        self.status_var.set("Scan completed.")
                    self.summary_var.set(f"{errors} file access error(s)" if errors else "No file access errors")
                elif kind == "fatal":
                    self.progress.stop()
                    self.scan_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.status_var.set("Scan failed.")
                    messagebox.showerror("Scan error", event[1])
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.groups = []
        self.group_for_item.clear()
        self.item_paths.clear()
        for label in (self.stat_files, self.stat_groups, self.stat_dupes, self.stat_space):
            label.configure(text="0")

    def _render_groups(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.group_for_item.clear()
        self.item_paths.clear()
        extra_copies = 0
        recoverable = 0
        for group_index, paths in enumerate(self.groups, start=1):
            # The first path is kept as the representative; only the remaining copies
            # are counted as reclaimable if they are quarantined.
            extra_copies += len(paths) - 1
            try:
                recoverable += (len(paths) - 1) * paths[0].stat().st_size
            except OSError:
                pass
            for index, path in enumerate(paths):
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                item = self.tree.insert("", "end", values=(f"Group {group_index}", path.name,
                                                            format_size(size), str(path)))
                self.group_for_item[item] = group_index - 1
                self.item_paths[item] = path
        self.stat_files.configure(text=str(self.scanned_count))
        self.stat_groups.configure(text=str(len(self.groups)))
        self.stat_dupes.configure(text=str(extra_copies))
        self.stat_space.configure(text=format_size(recoverable))
        if not self.groups:
            self.status_var.set("No duplicate files found." if self.scanned_count else "No files scanned.")
        else:
            self.status_var.set(f"Found {len(self.groups)} duplicate group(s). Review before quarantining.")

    def _export_csv(self):
        if not self.groups:
            messagebox.showinfo("No results", "Run a scan with duplicate results before exporting.")
            return
        destination = filedialog.asksaveasfilename(
            title="Export scan results", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=f"duplicate_scan_{datetime.now():%Y%m%d_%H%M%S}.csv")
        if not destination:
            return
        try:
            with open(destination, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(["group", "file_name", "size_bytes", "path", "sha256"])
                for group_index, group in enumerate(self.groups, start=1):
                    for path in group:
                        try:
                            size = path.stat().st_size
                            digest = sha256_file(path)
                        except OSError:
                            size, digest = "", "unavailable"
                        writer.writerow([group_index, path.name, size, str(path), digest])
            messagebox.showinfo("Export complete", f"CSV report saved to:\n{destination}")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    def _quarantine_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Select files", "Select one or more duplicate files in the results table first.")
            return
        selected_paths = [self.item_paths[item] for item in selected if item in self.item_paths]
        # Do not allow removing every copy from any duplicate group.
        selected_groups = defaultdict(list)
        for item in selected:
            if item in self.group_for_item and item in self.item_paths:
                selected_groups[self.group_for_item[item]].append(self.item_paths[item])
        for group_index, paths in selected_groups.items():
            remaining = [p for p in self.groups[group_index] if p not in paths]
            if not remaining:
                messagebox.showwarning("Keep one copy",
                    "Your selection would quarantine every copy in at least one group. Keep at least one copy of each file.")
                return
        if not messagebox.askyesno("Confirm quarantine",
            f"Move {len(selected_paths)} selected file(s) into a quarantine folder?\n\n"
            "This does not permanently delete them, but paths will change. Continue only if you have reviewed the selection."):
            return

        moved = 0
        failures = []
        for path in selected_paths:
            try:
                if not path.exists():
                    failures.append(f"{path}: file no longer exists")
                    continue
                quarantine = path.parent / ".duplicate_finder_quarantine"
                quarantine.mkdir(exist_ok=True)
                target = quarantine / path.name
                if target.exists():
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    target = quarantine / f"{path.stem}_{stamp}{path.suffix}"
                shutil.move(str(path), str(target))
                moved += 1
            except (OSError, shutil.Error) as exc:
                failures.append(f"{path}: {exc}")

        message = f"Moved {moved} file(s) to quarantine."
        if failures:
            message += "\n\nSome files could not be moved:\n" + "\n".join(failures[:5])
        messagebox.showinfo("Quarantine result", message)
        self._start_scan()

if __name__ == "__main__":
    app = DuplicateFileFinder()
    app.mainloop()
