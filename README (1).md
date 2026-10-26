# Duplicate File Finder

A Python desktop app that finds duplicate files by grouping candidates by file size and comparing SHA-256 hashes. It includes a Tkinter GUI, CSV export, background scanning, and a safer quarantine action instead of permanent deletion.

## Features

- Scan a folder and its subfolders
- Use file size as a fast first filter, then SHA-256 to verify content
- Display duplicate groups, paths, and file sizes
- Estimate extra-copy storage that could be reclaimed
- Export scan results to CSV
- Run scans in a background thread and cancel a running scan
- Move selected duplicates to a `.duplicate_finder_quarantine` folder rather than deleting them permanently
- Uses only the Python standard library; no database or third-party package required

## Requirements

- Python 3.10 or newer recommended
- Tkinter (included with most standard Windows Python installations)

## Run

1. Install Python from https://www.python.org/downloads/ if needed. On Windows, enable **Add Python to PATH** during setup.
2. Open a terminal in this folder.
3. Run:

   ```bash
   python main.py
   ```

## How duplicate detection works

1. Walk through the selected folder recursively.
2. Group files by their byte size. Files with different sizes cannot have identical contents.
3. Hash only groups containing two or more files using SHA-256.
4. Files with the same size and hash are reported as duplicates.

## Complexity

Let `N` be the number of files and `B` be the total number of bytes read while hashing same-size candidate files.

- Folder traversal and size grouping: expected `O(N)`
- Hashing: `O(B)`
- Additional memory: `O(N)` for file paths and groups

## Safety notes

- Review results before taking action.
- Quarantine moves files; it does not permanently delete them.
- Keep at least one copy of every duplicate group.
- Scanning may take time for very large folders or slow drives.
- This starter version does not follow symbolic links intentionally; behavior depends on `os.walk` defaults.

## Suggested improvements

- Add a restore-from-quarantine screen
- Add filters by extension and minimum file size
- Save scan history in CSV
- Add a theme selector and a packaging workflow with PyInstaller

## Project details

- Title: Duplicate File Finder
- Python concepts: file handling, dictionaries, functions, exception handling, hashing, threading, Tkinter GUI, CSV
