"""Persistent playback queue."""

from __future__ import annotations

import random

from gi.repository import GObject

from musicplayer.models import QueueEntry


class PlayQueue(GObject.Object):
    """Maintains queue ordering and current selection."""

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "current-changed": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[QueueEntry] = []
        self.current_index = -1

    def replace(self, entries: list[QueueEntry], current_index: int = 0) -> None:
        self.entries = entries
        self.current_index = current_index if entries else -1
        self.emit("changed")
        self.emit("current-changed", self.current_index)

    def append(self, entry: QueueEntry) -> None:
        self.entries.append(entry)
        if self.current_index == -1:
            self.current_index = 0
            self.emit("current-changed", self.current_index)
        self.emit("changed")

    def extend(self, entries: list[QueueEntry]) -> None:
        """Append several entries while preserving current state."""
        self.entries.extend(entries)
        if self.current_index == -1 and entries:
            self.current_index = 0
            self.emit("current-changed", self.current_index)
        self.emit("changed")

    def clear(self) -> None:
        self.entries = []
        self.current_index = -1
        self.emit("changed")
        self.emit("current-changed", -1)

    def current(self) -> QueueEntry | None:
        if 0 <= self.current_index < len(self.entries):
            return self.entries[self.current_index]
        return None

    def next_index(self, mode: str) -> int:
        if not self.entries:
            return -1
        if mode == "shuffle":
            if len(self.entries) == 1:
                return self.current_index
            candidates = [index for index in range(len(self.entries)) if index != self.current_index]
            return random.choice(candidates)
        if mode == "repeat-one":
            return self.current_index
        next_index = self.current_index + 1
        if next_index < len(self.entries):
            return next_index
        return 0 if mode == "repeat-all" else -1

    def previous_index(self) -> int:
        if not self.entries:
            return -1
        return max(0, self.current_index - 1)

    def set_current(self, index: int) -> None:
        if index < -1 or index >= len(self.entries):
            return
        self.current_index = index
        self.emit("current-changed", index)
        self.emit("changed")

    def move(self, old_index: int, new_index: int) -> None:
        """Move an entry within the queue."""
        if not (0 <= old_index < len(self.entries) and 0 <= new_index < len(self.entries)):
            return
        entry = self.entries.pop(old_index)
        self.entries.insert(new_index, entry)
        if self.current_index == old_index:
            self.current_index = new_index
        elif old_index < self.current_index <= new_index:
            self.current_index -= 1
        elif new_index <= self.current_index < old_index:
            self.current_index += 1
        self.emit("changed")

    def remove(self, index: int) -> None:
        """Remove an entry from the queue."""
        if not (0 <= index < len(self.entries)):
            return
        self.entries.pop(index)
        if not self.entries:
            self.current_index = -1
        elif index < self.current_index:
            self.current_index -= 1
        elif index == self.current_index:
            self.current_index = min(index, len(self.entries) - 1)
            self.emit("current-changed", self.current_index)
        self.emit("changed")
