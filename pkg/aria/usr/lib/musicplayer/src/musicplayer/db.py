"""SQLite persistence layer."""

from __future__ import annotations

import threading
import sqlite3
from pathlib import Path

from musicplayer.models import (
    AlbumSummary,
    ArtistSummary,
    FolderSummary,
    GenreSummary,
    PlaylistSummary,
    QueueEntry,
    Track,
)


class LibraryDatabase:
    """SQLite-backed metadata cache for fast startup."""

    LIKED_PLAYLIST_NAME = "Liked"

    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            cursor = self.connection.cursor()
            cursor.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS roots (
                path TEXT PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT NOT NULL,
                album_artist TEXT NOT NULL,
                genre TEXT NOT NULL,
                year INTEGER,
                track_number INTEGER,
                disc_number INTEGER,
                duration REAL NOT NULL,
                bitrate INTEGER,
                sample_rate INTEGER,
                bpm INTEGER,
                musicbrainz_track_id TEXT NOT NULL DEFAULT '',
                musicbrainz_album_id TEXT NOT NULL DEFAULT '',
                musicbrainz_artist_id TEXT NOT NULL DEFAULT '',
                lyrics TEXT NOT NULL DEFAULT '',
                artwork_path TEXT NOT NULL DEFAULT '',
                modified_ns INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );

            CREATE TABLE IF NOT EXISTS playlist_items (
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                track_path TEXT NOT NULL,
                PRIMARY KEY (playlist_id, position)
            );
                """
            )
            self.connection.commit()

    def set_roots(self, roots: list[str]) -> None:
        """Replace all configured library roots."""
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM roots")
            cursor.executemany("INSERT INTO roots(path) VALUES (?)", [(root,) for root in roots])
            self.connection.commit()

    def get_roots(self) -> list[str]:
        """Return configured library roots."""
        with self._lock:
            rows = self.connection.execute("SELECT path FROM roots ORDER BY path").fetchall()
        return [row["path"] for row in rows]

    def upsert_track(self, track: Track) -> None:
        """Insert or update a track entry."""
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO tracks (
                    path, title, artist, album, album_artist, genre, year, track_number,
                    disc_number, duration, bitrate, sample_rate, bpm,
                    musicbrainz_track_id, musicbrainz_album_id, musicbrainz_artist_id,
                    lyrics, artwork_path, modified_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    title=excluded.title,
                    artist=excluded.artist,
                    album=excluded.album,
                    album_artist=excluded.album_artist,
                    genre=excluded.genre,
                    year=excluded.year,
                    track_number=excluded.track_number,
                    disc_number=excluded.disc_number,
                    duration=excluded.duration,
                    bitrate=excluded.bitrate,
                    sample_rate=excluded.sample_rate,
                    bpm=excluded.bpm,
                    musicbrainz_track_id=excluded.musicbrainz_track_id,
                    musicbrainz_album_id=excluded.musicbrainz_album_id,
                    musicbrainz_artist_id=excluded.musicbrainz_artist_id,
                    lyrics=excluded.lyrics,
                    artwork_path=excluded.artwork_path,
                    modified_ns=excluded.modified_ns
                """,
                (
                    track.path,
                    track.title,
                    track.artist,
                    track.album,
                    track.album_artist,
                    track.genre,
                    track.year,
                    track.track_number,
                    track.disc_number,
                    track.duration,
                    track.bitrate,
                    track.sample_rate,
                    track.bpm,
                    track.musicbrainz_track_id,
                    track.musicbrainz_album_id,
                    track.musicbrainz_artist_id,
                    track.lyrics,
                    track.artwork_path,
                    track.modified_ns,
                ),
            ),
            self.connection.commit()

    def delete_track(self, path: str) -> None:
        """Delete a track by path."""
        with self._lock:
            self.connection.execute("DELETE FROM tracks WHERE path = ?", (path,))
            self.connection.commit()

    def delete_tracks_under_root(self, root: str) -> None:
        """Delete all tracks under a managed root path."""
        prefix = root.rstrip("/") + "/%"
        with self._lock:
            self.connection.execute("DELETE FROM tracks WHERE path LIKE ?", (prefix,))
            self.connection.commit()

    def get_track(self, path: str) -> Track | None:
        """Return a track by path."""
        with self._lock:
            row = self.connection.execute("SELECT * FROM tracks WHERE path = ?", (path,)).fetchone()
        return self._row_to_track(row) if row else None

    def iter_tracks(self, search: str = "") -> list[Track]:
        """Query tracks with optional full-text-like filtering."""
        if search:
            pattern = f"%{search.lower()}%"
            with self._lock:
                rows = self.connection.execute(
                    """
                    SELECT * FROM tracks
                    WHERE lower(title) LIKE ?
                       OR lower(artist) LIKE ?
                       OR lower(album) LIKE ?
                       OR lower(genre) LIKE ?
                    ORDER BY artist, album, disc_number, track_number, title
                    """,
                    (pattern, pattern, pattern, pattern),
                ).fetchall()
        else:
            with self._lock:
                rows = self.connection.execute(
                    """
                    SELECT * FROM tracks
                    ORDER BY artist, album, disc_number, track_number, title
                    """
                ).fetchall()
        return [self._row_to_track(row) for row in rows]

    def albums(self, search: str = "") -> list[AlbumSummary]:
        """Return album summaries."""
        query = """
            SELECT album, album_artist, MIN(year) AS year,
                   COUNT(*) AS track_count, MAX(artwork_path) AS artwork_path
            FROM tracks
        """
        params: tuple[str, ...] = ()
        if search:
            query += " WHERE lower(album) LIKE ? OR lower(album_artist) LIKE ?"
            pattern = f"%{search.lower()}%"
            params = (pattern, pattern)
        query += " GROUP BY album, album_artist ORDER BY album_artist, album"
        with self._lock:
            rows = self.connection.execute(query, params).fetchall()
        return [AlbumSummary(**dict(row)) for row in rows]

    def album_entries(self, album: str, album_artist: str) -> list[QueueEntry]:
        """Return all tracks for a single album in playback order."""
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT path, title, artist, album, duration, artwork_path
                FROM tracks
                WHERE album = ? AND album_artist = ?
                ORDER BY disc_number, track_number, title
                """,
                (album, album_artist),
            ).fetchall()
        return [QueueEntry(**dict(row)) for row in rows]

    def artists(self, search: str = "") -> list[ArtistSummary]:
        """Return artist summaries."""
        query = """
            SELECT artist, COUNT(DISTINCT album) AS album_count, COUNT(*) AS track_count
            FROM tracks
        """
        params: tuple[str, ...] = ()
        if search:
            query += " WHERE lower(artist) LIKE ?"
            params = (f"%{search.lower()}%",)
        query += " GROUP BY artist ORDER BY artist"
        with self._lock:
            rows = self.connection.execute(query, params).fetchall()
        return [ArtistSummary(**dict(row)) for row in rows]

    def genres(self, search: str = "") -> list[GenreSummary]:
        """Return genre summaries."""
        query = """
            SELECT genre, COUNT(*) AS track_count
            FROM tracks
            WHERE genre != ''
        """
        params: tuple[str, ...] = ()
        if search:
            query += " AND lower(genre) LIKE ?"
            params = (f"%{search.lower()}%",)
        query += " GROUP BY genre ORDER BY genre"
        with self._lock:
            rows = self.connection.execute(query, params).fetchall()
        return [GenreSummary(**dict(row)) for row in rows]

    def folders(self) -> list[FolderSummary]:
        """Return library roots with track counts."""
        roots = self.get_roots()
        summaries: list[FolderSummary] = []
        for root in roots:
            prefix = root.rstrip("/") + "/%"
            with self._lock:
                row = self.connection.execute(
                    "SELECT COUNT(*) AS track_count FROM tracks WHERE path LIKE ?",
                    (prefix,),
                ).fetchone()
            summaries.append(FolderSummary(root_path=root, track_count=row["track_count"] if row else 0))
        return summaries

    def queue_entries(self, paths: list[str]) -> list[QueueEntry]:
        """Return queue entries for a set of paths."""
        if not paths:
            return []
        placeholders = ", ".join("?" for _ in paths)
        with self._lock:
            rows = self.connection.execute(
                f"SELECT path, title, artist, album, duration, artwork_path FROM tracks WHERE path IN ({placeholders})",
                paths,
            ).fetchall()
        track_map = {row["path"]: QueueEntry(**dict(row)) for row in rows}
        return [track_map[path] for path in paths if path in track_map]

    def create_playlist(self, name: str, paths: list[str]) -> int:
        """Create a playlist and store track order."""
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute("INSERT INTO playlists(name) VALUES (?)", (name,))
            playlist_id = cursor.lastrowid
            self._replace_playlist_items(playlist_id, paths)
            self.connection.commit()
        return int(playlist_id)

    def create_empty_playlist(self, name: str) -> int:
        """Create an empty playlist."""
        return self.create_playlist(name, [])

    def ensure_playlist(self, name: str) -> int:
        """Return an existing playlist id or create it."""
        with self._lock:
            row = self.connection.execute("SELECT id FROM playlists WHERE name = ?", (name,)).fetchone()
            if row is not None:
                return int(row["id"])
            cursor = self.connection.cursor()
            cursor.execute("INSERT INTO playlists(name) VALUES (?)", (name,))
            self.connection.commit()
            return int(cursor.lastrowid)

    def rename_playlist(self, playlist_id: int, name: str) -> None:
        """Rename a playlist."""
        with self._lock:
            self.connection.execute("UPDATE playlists SET name = ? WHERE id = ?", (name, playlist_id))
            self.connection.commit()

    def delete_playlist(self, playlist_id: int) -> None:
        """Delete a playlist."""
        with self._lock:
            self.connection.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
            self.connection.commit()

    def list_playlists(self) -> list[PlaylistSummary]:
        """Return saved playlists with track counts."""
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT playlists.id, playlists.name, COUNT(playlist_items.track_path) AS track_count
                FROM playlists
                LEFT JOIN playlist_items ON playlist_items.playlist_id = playlists.id
                GROUP BY playlists.id, playlists.name
                ORDER BY CASE WHEN playlists.name = ? THEN 0 ELSE 1 END, lower(playlists.name)
                """
                ,
                (self.LIKED_PLAYLIST_NAME,),
            ).fetchall()
        return [PlaylistSummary(**dict(row)) for row in rows]

    def playlist_entries(self, playlist_id: int) -> list[QueueEntry]:
        """Load entries in playlist order."""
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT tracks.path, tracks.title, tracks.artist, tracks.album, tracks.duration, tracks.artwork_path
                FROM playlist_items
                JOIN tracks ON tracks.path = playlist_items.track_path
                WHERE playlist_items.playlist_id = ?
                ORDER BY playlist_items.position
                """,
                (playlist_id,),
            ).fetchall()
        return [QueueEntry(**dict(row)) for row in rows]

    def replace_playlist_entries(self, playlist_id: int, paths: list[str]) -> None:
        """Replace the contents of an existing playlist."""
        with self._lock:
            self._replace_playlist_items(playlist_id, paths)
            self.connection.commit()

    def playlist_name(self, playlist_id: int) -> str | None:
        """Return playlist name."""
        row = self.connection.execute("SELECT name FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
        return row["name"] if row else None

    def add_track_to_playlist(self, playlist_id: int, path: str) -> None:
        """Append a track to a playlist if it is not already present."""
        with self._lock:
            existing = self.connection.execute(
                "SELECT 1 FROM playlist_items WHERE playlist_id = ? AND track_path = ?",
                (playlist_id, path),
            ).fetchone()
            if existing is not None:
                return
            row = self.connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_position FROM playlist_items WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchone()
            next_position = int(row["next_position"]) if row is not None else 0
            self.connection.execute(
                "INSERT INTO playlist_items(playlist_id, position, track_path) VALUES (?, ?, ?)",
                (playlist_id, next_position, path),
            )
            self.connection.commit()

    def remove_track_from_playlist(self, playlist_id: int, path: str) -> None:
        """Remove a track from a playlist and close position gaps."""
        with self._lock:
            self.connection.execute(
                "DELETE FROM playlist_items WHERE playlist_id = ? AND track_path = ?",
                (playlist_id, path),
            )
            rows = self.connection.execute(
                "SELECT track_path FROM playlist_items WHERE playlist_id = ? ORDER BY position",
                (playlist_id,),
            ).fetchall()
            self._replace_playlist_items(playlist_id, [row["track_path"] for row in rows])
            self.connection.commit()

    def ensure_liked_playlist(self) -> int:
        """Return the id of the built-in liked playlist."""
        return self.ensure_playlist(self.LIKED_PLAYLIST_NAME)

    def _replace_playlist_items(self, playlist_id: int, paths: list[str]) -> None:
        self.connection.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (playlist_id,))
        self.connection.executemany(
            "INSERT INTO playlist_items(playlist_id, position, track_path) VALUES (?, ?, ?)",
            [(playlist_id, index, path) for index, path in enumerate(paths)],
        )

    def _row_to_track(self, row: sqlite3.Row) -> Track:
        return Track(**dict(row))
