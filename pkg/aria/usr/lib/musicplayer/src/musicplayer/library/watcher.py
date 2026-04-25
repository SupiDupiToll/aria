"""Recursive directory monitoring using GIO file monitors."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from gi.repository import Gio, GLib


class LibraryWatcher:
    """Watches folders and notifies about file system changes."""

    def __init__(self, on_change: Callable[[str, str], None]) -> None:
        self.on_change = on_change
        self._monitors: dict[str, Gio.FileMonitor] = {}

    def watch_roots(self, roots: list[str]) -> None:
        """Replace watched roots."""
        self.clear()
        for root in roots:
            self._watch_tree(Path(root))

    def clear(self) -> None:
        """Stop all active monitors."""
        for monitor in self._monitors.values():
            monitor.cancel()
        self._monitors.clear()

    def _watch_tree(self, root: Path) -> None:
        if not root.exists():
            return
        for directory in [root, *[path for path in root.rglob("*") if path.is_dir()]]:
            self._watch_directory(directory)

    def _watch_directory(self, directory: Path) -> None:
        path = str(directory)
        if path in self._monitors:
            return
        try:
            monitor = Gio.File.new_for_path(path).monitor_directory(
                Gio.FileMonitorFlags.WATCH_MOVES,
                None,
            )
        except GLib.Error:
            return
        monitor.connect("changed", self._on_changed)
        self._monitors[path] = monitor

    def _on_changed(
        self,
        _monitor: Gio.FileMonitor,
        file: Gio.File,
        other_file: Gio.File | None,
        event_type: Gio.FileMonitorEvent,
    ) -> None:
        path = file.get_path()
        if not path:
            return

        if event_type in (
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.MOVED_IN,
        ):
            if Path(path).is_dir():
                self._watch_tree(Path(path))
            self.on_change("created", path)
        elif event_type in (
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.ATTRIBUTE_CHANGED,
        ):
            self.on_change("changed", path)
        elif event_type in (
            Gio.FileMonitorEvent.DELETED,
            Gio.FileMonitorEvent.MOVED_OUT,
        ):
            self.on_change("deleted", path)
            self._drop_monitor(path)
            if other_file and other_file.get_path():
                self.on_change("created", other_file.get_path())

    def _drop_monitor(self, path: str) -> None:
        if path in self._monitors:
            self._monitors[path].cancel()
            del self._monitors[path]
