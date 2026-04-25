"""Application-wide constants."""

import os
from pathlib import Path

from musicplayer import APP_ID

AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".ogg",
    ".opus",
    ".m4a",
    ".wav",
    ".aac",
    ".ape",
    ".wv",
    ".mpc",
}

COVER_FILENAMES = (
    "cover.jpg",
    "cover.jpeg",
    "folder.jpg",
    "folder.jpeg",
    "Cover.jpg",
    "Folder.jpg",
    "cover.png",
    "folder.png",
)

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / APP_ID
CACHE_HOME = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / APP_ID
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / APP_ID
