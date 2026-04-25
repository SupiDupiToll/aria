"""Lyrics loading and LRC parsing."""

from __future__ import annotations

import re
from pathlib import Path

import requests

from musicplayer.models import LyricLine, Track

LRC_PATTERN = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")


class LyricsService:
    """Resolves sidecar and embedded lyrics."""

    def __init__(self, lyrics_folder: str = "") -> None:
        self.lyrics_folder = lyrics_folder

    def update_folder(self, lyrics_folder: str) -> None:
        """Update the optional global lyrics folder."""
        self.lyrics_folder = lyrics_folder

    def load(self, track: Track) -> tuple[list[LyricLine], str]:
        """Load synchronized or plain lyrics for a track."""
        sidecar = self._find_sidecar(Path(track.path))
        if sidecar:
            return self.parse_lrc(sidecar.read_text(encoding="utf-8", errors="ignore")), ""
        return [], track.lyrics

    def _find_sidecar(self, path: Path) -> Path | None:
        direct = path.with_suffix(".lrc")
        if direct.exists():
            return direct
        if self.lyrics_folder:
            candidate = Path(self.lyrics_folder) / f"{path.stem}.lrc"
            if candidate.exists():
                return candidate
        return None

    def parse_lrc(self, text: str) -> list[LyricLine]:
        """Parse basic LRC timestamps."""
        lines: list[LyricLine] = []
        for raw in text.splitlines():
            match = LRC_PATTERN.match(raw.strip())
            if not match:
                continue
            minute, second, lyric = match.groups()
            lines.append(LyricLine(timestamp=int(minute) * 60 + float(second), text=lyric.strip()))
        lines.sort(key=lambda line: line.timestamp)
        return lines

    def fetch_and_store(self, track: Track) -> bool:
        """Fetch lyrics from lrclib.net and store them next to the audio file."""
        params = {
            "track_name": track.title,
            "artist_name": track.artist,
            "album_name": track.album,
        }
        response = requests.get("https://lrclib.net/api/get", params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()
        text = payload.get("syncedLyrics") or payload.get("plainLyrics") or ""
        if not text:
            return False
        sidecar = Path(track.path).with_suffix(".lrc")
        sidecar.write_text(text, encoding="utf-8")
        return True
