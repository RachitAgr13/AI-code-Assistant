"""
file_watcher.py
Monitors a file for changes (triggered on Ctrl+S in Notepad)
and fires a callback with the new content.
"""

import os
import threading
import time

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False


class _PollingWatcher(threading.Thread):
    """Fallback file watcher using polling (no watchdog required)."""

    def __init__(self, filepath: str, callback):
        super().__init__(daemon=True)
        self.filepath = os.path.abspath(filepath)
        self.callback = callback
        self._stop_event = threading.Event()
        self._last_mtime = 0.0
        self._last_content = ""

    def run(self):
        while not self._stop_event.is_set():
            try:
                mtime = os.path.getmtime(self.filepath)
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    if content != self._last_content:
                        self._last_content = content
                        self.callback(content)
            except FileNotFoundError:
                pass
            except Exception:
                pass
            time.sleep(0.8)

    def stop(self):
        self._stop_event.set()


if WATCHDOG_AVAILABLE:
    class _WatchdogHandler(FileSystemEventHandler):
        def __init__(self, filepath: str, callback):
            super().__init__()
            self.filepath = os.path.abspath(filepath)
            self.callback = callback
            self._last_content = ""

        def on_modified(self, event):
            if os.path.abspath(event.src_path) == self.filepath:
                try:
                    with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    if content != self._last_content:
                        self._last_content = content
                        self.callback(content)
                except Exception:
                    pass


class FileWatcher:
    """
    Watches a single file and fires callback(content: str) on every change.
    Uses watchdog if available, otherwise falls back to polling.
    """

    def __init__(self, filepath: str, callback):
        self.filepath = os.path.abspath(filepath)
        self.callback = callback
        self._observer = None
        self._poll_thread = None

    # ------------------------------------------------------------------ #
    def start(self):
        if WATCHDOG_AVAILABLE:
            directory = os.path.dirname(self.filepath)
            handler = _WatchdogHandler(self.filepath, self.callback)
            self._observer = Observer()
            self._observer.schedule(handler, directory, recursive=False)
            self._observer.start()
        else:
            self._poll_thread = _PollingWatcher(self.filepath, self.callback)
            self._poll_thread.start()

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
        if self._poll_thread:
            self._poll_thread.stop()

    # Read current content immediately (used on startup)
    def read_current(self) -> str:
        try:
            with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def write(self, content: str):
        """Write content back to the file (used by English→Code apply)."""
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(content)
