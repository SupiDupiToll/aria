"""Shared data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Track:
    """Track metadata stored in the library."""

    id: int | None
    path: str
    title: str
    artist: str
    album: str
    album_artist: str
    genre: str
    year: int | None
    track_number: int | None
    disc_number: int | None
    duration: float
    bitrate: int | None
    sample_rate: int | None
    bpm: int | None
    musicbrainz_track_id: str
    musicbrainz_album_id: str
    musicbrainz_artist_id: str
    lyrics: str
    artwork_path: str
    modified_ns: int


@dataclass(slots=True)
class AlbumSummary:
    """Aggregated album view model."""

    album: str
    album_artist: str
    year: int | None
    track_count: int
    artwork_path: str


@dataclass(slots=True)
class ArtistSummary:
    """Aggregated artist view model."""

    artist: str
    album_count: int
    track_count: int


@dataclass(slots=True)
class GenreSummary:
    """Aggregated genre view model."""

    genre: str
    track_count: int


@dataclass(slots=True)
class FolderSummary:
    """Aggregated root folder view model."""

    root_path: str
    track_count: int


@dataclass(slots=True)
class PlaylistSummary:
    """Saved playlist metadata."""

    id: int
    name: str
    track_count: int


@dataclass(slots=True)
class QueueEntry:
    """Playback queue entry."""

    path: str
    title: str
    artist: str
    album: str
    duration: float
    artwork_path: str


@dataclass(slots=True)
class LyricLine:
    """Time-coded lyric line."""

    timestamp: float
    text: str


@dataclass(slots=True)
class LastFMProfile:
    """Stored Last.fm credentials and profile."""

    username: str = ""
    api_key: str = ""
    api_secret: str = ""
    session_key: str = ""


@dataclass(slots=True)
class LastFMPanelData:
    """Data shown in the Last.fm panel."""

    recent: list[dict]
    top_artists: list[dict]
    top_albums: list[dict]
