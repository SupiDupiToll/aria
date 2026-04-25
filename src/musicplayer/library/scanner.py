"""Recursive library scanner."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from musicplayer.constants import AUDIO_EXTENSIONS
from musicplayer.db import LibraryDatabase
from musicplayer.metadata import read_track_metadata


class LibraryScanner:
    """Scans folders and populates the metadata database."""

    def __init__(self, database: LibraryDatabase) -> None:
        self.database = database

    def iter_audio_files(self, root: str) -> list[Path]:
        """Return supported audio files under a root directory."""
        base = Path(root)
        if not base.exists():
            return []
        return [
            path
            for path in base.rglob("*")
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
        ]

    def scan_roots(self, roots: list[str], progress: Callable[[str], None] | None = None) -> None:
        """Perform a full metadata scan for configured roots."""
        for root in roots:
            for path in self.iter_audio_files(root):
                if progress:
                    progress(str(path))
                self.scan_file(str(path))

    def scan_file(self, path: str) -> None:
        """Index a single file if it is supported and parseable."""
        if Path(path).suffix.lower() not in AUDIO_EXTENSIONS:
            return
        track = read_track_metadata(path)
        if track is not None:
            self.database.upsert_track(track)

    def remove_file(self, path: str) -> None:
        """Delete a file from the database."""
        self.database.delete_track(path)
