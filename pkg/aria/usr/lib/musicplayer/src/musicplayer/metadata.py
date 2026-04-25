"""Metadata extraction helpers built on Mutagen."""

from __future__ import annotations

import hashlib
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC

from musicplayer.constants import CACHE_HOME, COVER_FILENAMES
from musicplayer.models import Track


def _first_tag(tags: object, keys: tuple[str, ...], default: str = "") -> str:
    if not tags:
        return default
    for key in keys:
        if key not in tags:
            continue
        value = tags[key]
        if isinstance(value, list):
            if value:
                return str(value[0]).strip()
        if hasattr(value, "text") and value.text:
            return str(value.text[0]).strip()
        if hasattr(value, "value"):
            return str(value.value).strip()
        return str(value).strip()
    return default


def _parse_int(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(str(value).split("/")[0])
    except ValueError:
        return None


def extract_artwork(audio: object, source_path: Path) -> str:
    """Extract embedded or folder artwork into cache and return its path."""
    artwork_dir = CACHE_HOME / "artwork"
    artwork_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(audio, FLAC) and audio.pictures:
        picture: Picture = audio.pictures[0]
        digest = hashlib.sha256(f"{source_path}:{picture.type}".encode("utf-8")).hexdigest()
        suffix = ".png" if picture.mime.endswith("png") else ".jpg"
        target = artwork_dir / f"{digest}{suffix}"
        target.write_bytes(picture.data)
        return str(target)

    if getattr(audio, "tags", None):
        for key in audio.tags.keys():
            value = audio.tags[key]
            if isinstance(value, APIC):
                digest = hashlib.sha256(f"{source_path}:{key}".encode("utf-8")).hexdigest()
                suffix = ".png" if value.mime.endswith("png") else ".jpg"
                target = artwork_dir / f"{digest}{suffix}"
                target.write_bytes(value.data)
                return str(target)

    for filename in COVER_FILENAMES:
        candidate = source_path.parent / filename
        if candidate.exists():
            return str(candidate)

    return ""


def read_track_metadata(path: str) -> Track | None:
    """Read a supported audio file and map it to the Track model."""
    source = Path(path)
    audio = MutagenFile(source)
    if audio is None or audio.info is None:
        return None

    tags = getattr(audio, "tags", {}) or {}
    stat = source.stat()

    title = _first_tag(tags, ("TIT2", "\xa9nam", "TITLE"), source.stem)
    artist = _first_tag(tags, ("TPE1", "\xa9ART", "ARTIST"), "Unknown Artist")
    album = _first_tag(tags, ("TALB", "\xa9alb", "ALBUM"), "Unknown Album")
    album_artist = _first_tag(tags, ("TPE2", "aART", "ALBUMARTIST", "ALBUM ARTIST"), artist)
    genre = _first_tag(tags, ("TCON", "\xa9gen", "GENRE"), "")
    year = _parse_int(_first_tag(tags, ("TDRC", "\xa9day", "DATE", "YEAR")))
    track_number = _parse_int(_first_tag(tags, ("TRCK", "trkn", "TRACKNUMBER")))
    disc_number = _parse_int(_first_tag(tags, ("TPOS", "disk", "DISCNUMBER")))
    bpm = _parse_int(_first_tag(tags, ("TBPM", "BPM")))
    lyrics = _first_tag(tags, ("USLT::eng", "LYRICS", "\xa9lyr"))

    bitrate = int(getattr(audio.info, "bitrate", 0) / 1000) or None
    sample_rate = getattr(audio.info, "sample_rate", None)
    artwork_path = extract_artwork(audio, source)

    return Track(
        id=None,
        path=str(source),
        title=title,
        artist=artist,
        album=album,
        album_artist=album_artist,
        genre=genre,
        year=year,
        track_number=track_number,
        disc_number=disc_number,
        duration=float(getattr(audio.info, "length", 0.0)),
        bitrate=bitrate,
        sample_rate=sample_rate,
        bpm=bpm,
        musicbrainz_track_id=_first_tag(tags, ("MUSICBRAINZ_TRACKID", "MusicBrainz Track Id")),
        musicbrainz_album_id=_first_tag(tags, ("MUSICBRAINZ_ALBUMID", "MusicBrainz Album Id")),
        musicbrainz_artist_id=_first_tag(tags, ("MUSICBRAINZ_ARTISTID", "MusicBrainz Artist Id")),
        lyrics=lyrics,
        artwork_path=artwork_path,
        modified_ns=stat.st_mtime_ns,
    )
