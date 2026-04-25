"""JSON-backed application settings."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from musicplayer.constants import CACHE_HOME, CONFIG_HOME, DATA_HOME
from musicplayer.models import LastFMProfile


@dataclass
class PlaybackState:
    """Persisted playback session state."""

    queue_paths: list[str] = field(default_factory=list)
    current_index: int = -1
    position_seconds: float = 0.0
    volume: float = 0.8
    mode: str = "normal"


@dataclass
class Settings:
    """User settings stored in the config file."""

    library_roots: list[str] = field(default_factory=list)
    lyrics_folder: str = ""
    replaygain_mode: str = "track"
    crossfade_seconds: int = 0
    normalize: bool = False
    resume_playback: bool = True
    remember_window_size: bool = True
    dark_mode: str = "system"
    database_path: str = str(DATA_HOME / "library.db")
    cache_dir: str = str(CACHE_HOME)
    window_width: int = 1280
    window_height: int = 840
    lastfm: LastFMProfile = field(default_factory=LastFMProfile)
    output_device_id: str = ""
    theme_override: str = "system"
    playback: PlaybackState = field(default_factory=PlaybackState)


class SettingsStore:
    """Reads and writes the settings document."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (CONFIG_HOME / "settings.json")
        for directory in (self.path.parent, DATA_HOME, CACHE_HOME):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError:
                continue

    def load(self) -> Settings:
        """Load settings from disk or return defaults."""
        if not self.path.exists():
            return Settings()

        data = json.loads(self.path.read_text(encoding="utf-8"))
        legacy_username = data.pop("lastfm_username", "")
        playback_data = data.get("playback", {})
        data["playback"] = PlaybackState(**playback_data)
        lastfm_data = data.get("lastfm", {})
        if legacy_username and "username" not in lastfm_data:
            lastfm_data["username"] = legacy_username
        data["lastfm"] = LastFMProfile(**lastfm_data)
        return Settings(**data)

    def save(self, settings: Settings) -> None:
        """Persist settings to disk."""
        payload: dict[str, Any] = asdict(settings)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
