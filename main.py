"""
main.py
Entry point for NotepadAI.

Usage:
    python main.py [path/to/your_file.py]

If no path is given, a file-picker dialog opens.
"""

import sys
import os
import tkinter as tk
from tkinter import filedialog, messagebox

from file_watcher import FileWatcher
from ai_engine import AIEngine
from ui_overlay import OverlayUI


def pick_file() -> str:
    """Open a minimal Tk file-picker and return the chosen path (or '' to abort)."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title="NotepadAI – Choose a Python file to watch",
        filetypes=[("Python files", "*.py"), ("All files", "*.*")],
    )
    root.destroy()
    return path


def main():
    # ── 1. Resolve target file ──────────────────────────────────────────
    if len(sys.argv) >= 2:
        filepath = sys.argv[1]
    else:
        filepath = pick_file()

    if not filepath:
        print("No file selected. Exiting.")
        sys.exit(0)

    filepath = os.path.abspath(filepath)

    # Create file if it doesn't exist yet
    if not os.path.exists(filepath):
        try:
            open(filepath, "w").close()
            print(f"Created new file: {filepath}")
        except OSError as exc:
            _fatal(f"Cannot create file:\n{filepath}\n\n{exc}")

    # ── 2. Instantiate components ───────────────────────────────────────
    ai_engine = AIEngine()

    # Placeholder callback — OverlayUI registers the real one after init
    def _placeholder(content: str):
        pass

    file_watcher = FileWatcher(filepath, _placeholder)

    # Build the UI (blocking Tk window created here, but mainloop not started yet)
    overlay = OverlayUI(filepath, ai_engine, file_watcher)

    # Wire the real callback now that overlay exists
    file_watcher.callback = overlay.on_file_changed

    # ── 3. Start watching ───────────────────────────────────────────────
    file_watcher.start()

    # ── 4. Open file in Notepad (Windows) ──────────────────────────────
    _open_in_notepad(filepath)

    # ── 5. Run UI (blocks until window closed) ──────────────────────────
    try:
        overlay.run()
    finally:
        file_watcher.stop()
        ai_engine.cancel()


def _open_in_notepad(filepath: str):
    """Launch Notepad with the target file (Windows only; silent on other OS)."""
    if sys.platform != "win32":
        return
    try:
        import subprocess
        subprocess.Popen(["notepad.exe", filepath])
    except Exception as exc:
        print(f"[NotepadAI] Could not open Notepad automatically: {exc}")


def _fatal(msg: str):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("NotepadAI – Fatal Error", msg)
    root.destroy()
    sys.exit(1)


if __name__ == "__main__":
    main()
