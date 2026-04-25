"""Regression tests for non-UI services."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from musicplayer.config import SettingsStore
from musicplayer.db import LibraryDatabase
from musicplayer.lastfm import LastFMService
from musicplayer.lyrics import LyricsService
from musicplayer.models import LastFMProfile, Track
from musicplayer.playlists import export_m3u, export_pls, export_xspf, import_playlist


class CoreTests(unittest.TestCase):
    def test_lrc_parser(self) -> None:
        lyrics = LyricsService("")
        lines = lyrics.parse_lrc("[00:01.50]First\n[00:10.00]Second")
        self.assertEqual(2, len(lines))
        self.assertEqual(1.5, lines[0].timestamp)
        self.assertEqual("Second", lines[1].text)

    def test_config_legacy_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "lastfm_username": "legacy-user",
                        "playback": {"queue_paths": [], "current_index": -1, "position_seconds": 0.0, "volume": 0.5, "mode": "normal"},
                    }
                ),
                encoding="utf-8",
            )
            settings = SettingsStore(path).load()
            self.assertEqual("legacy-user", settings.lastfm.username)

    def test_playlist_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            m3u = Path(tmpdir) / "list.m3u"
            pls = Path(tmpdir) / "list.pls"
            xspf = Path(tmpdir) / "list.xspf"
            tracks = ["/music/a.mp3", "/music/b.flac"]
            export_m3u(str(m3u), tracks)
            export_pls(str(pls), tracks)
            export_xspf(str(xspf), tracks)
            self.assertEqual(tracks, import_playlist(str(m3u)))
            self.assertEqual(tracks, import_playlist(str(pls)))
            self.assertEqual(tracks, import_playlist(str(xspf)))

    def test_database_playlist_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = LibraryDatabase(str(Path(tmpdir) / "library.db"))
            track = Track(
                id=None,
                path="/music/song.mp3",
                title="Song",
                artist="Artist",
                album="Album",
                album_artist="Artist",
                genre="Rock",
                year=2020,
                track_number=1,
                disc_number=1,
                duration=123.0,
                bitrate=320,
                sample_rate=44100,
                bpm=120,
                musicbrainz_track_id="",
                musicbrainz_album_id="",
                musicbrainz_artist_id="",
                lyrics="",
                artwork_path="",
                modified_ns=1,
            )
            db.upsert_track(track)
            playlist_id = db.create_playlist("Test", [track.path])
            self.assertEqual("Test", db.playlist_name(playlist_id))
            self.assertEqual(1, len(db.playlist_entries(playlist_id)))
            db.rename_playlist(playlist_id, "Renamed")
            self.assertEqual("Renamed", db.playlist_name(playlist_id))
            db.delete_playlist(playlist_id)
            self.assertEqual([], db.list_playlists())

    def test_lastfm_queue_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = Path(tmpdir) / "scrobbles.json"
            service = LastFMService(queue_path)
            service.update_profile(
                LastFMProfile(username="user", api_key="key", api_secret="secret", session_key="session")
            )
            service.queue_scrobble("Artist", "Track", "Album", "Artist", 200, timestamp=1234)
            self.assertTrue(queue_path.exists())
            reloaded = LastFMService(queue_path)
            self.assertEqual(1, len(reloaded.offline_queue))
            self.assertEqual("Track", reloaded.offline_queue[0].track)


if __name__ == "__main__":
    unittest.main()
