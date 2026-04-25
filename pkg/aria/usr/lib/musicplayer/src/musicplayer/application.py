"""Adwaita application wiring."""

from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib

from musicplayer import APP_ID
from musicplayer.config import SettingsStore
from musicplayer.db import LibraryDatabase
from musicplayer.lastfm import LastFMService
from musicplayer.library.scanner import LibraryScanner
from musicplayer.library.watcher import LibraryWatcher
from musicplayer.lyrics import LyricsService
from musicplayer.mpris import MPRISService
from musicplayer.playback.player import PlaybackEngine
from musicplayer.playback.queue import PlayQueue
from musicplayer.ui.window import MusicWindow


class MusicApplication(Adw.Application):
    """Main application object."""

    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self.database = LibraryDatabase(self.settings.database_path)
        self.scanner = LibraryScanner(self.database)
        self.lyrics = LyricsService(self.settings.lyrics_folder)
        self.queue = PlayQueue()
        self.player = PlaybackEngine(self.queue, self.settings)
        self.lastfm = LastFMService()
        self.lastfm.update_profile(self.settings.lastfm)
        self.mpris = MPRISService(self.player)
        self.watcher = LibraryWatcher(self._on_library_change)
        self.window: MusicWindow | None = None
        self._scan_lock = threading.Lock()
        self.player.connect("about-to-scrobble", self._on_about_to_scrobble)
        self.player.connect("track-changed", self._on_track_changed)
        self._resume_seek_pending = self.settings.playback.position_seconds if self.settings.resume_playback else 0.0

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._restore_queue()
        self.watcher.watch_roots(self.settings.library_roots)
        self.mpris.start()
        self.set_accels_for_action("win.search", ["<Primary>f"])
        self.set_accels_for_action("win.shortcuts", ["<Primary>question"])
        self.set_accels_for_action("win.lyrics-fullscreen", ["l"])

    def do_activate(self) -> None:
        if self.window is None:
            self.window = MusicWindow(
                app=self,
                settings=self.settings,
                database=self.database,
                scanner=self.scanner,
                lyrics=self.lyrics,
                queue=self.queue,
                player=self.player,
                save_settings=self.save_settings,
                rescan=self.full_rescan,
                add_library_folder=self.add_library_folder,
                remove_library_folder=self.remove_library_folder,
                lastfm=self.lastfm,
            )
        self.window.present()

    def do_open(self, files: list[Gio.File], _n_files: int, _hint: str) -> None:
        self.activate()
        if self.window is None:
            return
        for file in files:
            path = file.get_path()
            if path:
                self.window.import_into_queue(path)

    def add_library_folder(self, path: str) -> None:
        """Add a root folder and scan it asynchronously."""
        if path not in self.settings.library_roots:
            self.settings.library_roots.append(path)
            self.database.set_roots(self.settings.library_roots)
            self.save_settings()
        self.watcher.watch_roots(self.settings.library_roots)
        self._scan_in_thread([path])

    def remove_library_folder(self, path: str) -> None:
        """Remove a managed root folder."""
        if path in self.settings.library_roots:
            self.settings.library_roots.remove(path)
            self.database.set_roots(self.settings.library_roots)
            self.database.delete_tracks_under_root(path)
            self.save_settings()
            self.watcher.watch_roots(self.settings.library_roots)
            if self.window:
                self.window._refresh_library()

    def full_rescan(self) -> None:
        """Scan all managed roots."""
        self._scan_in_thread(self.settings.library_roots)

    def _on_library_change(self, change: str, path: str) -> None:
        suffix = Path(path).suffix.lower()
        if change in {"created", "changed"}:
            threading.Thread(target=self._scan_file_and_refresh, args=(path,), daemon=True).start()
        elif change == "deleted":
            self.scanner.remove_file(path)
        if self.window and suffix:
            GLib.idle_add(self.window._refresh_library)

    def save_settings(self) -> None:
        """Persist current settings."""
        self.player.apply_settings(self.settings)
        self.lastfm.update_profile(self.settings.lastfm)
        self.settings_store.save(self.settings)

    def _restore_queue(self) -> None:
        entries = self.database.queue_entries(self.settings.playback.queue_paths)
        if entries:
            self.queue.replace(entries, self.settings.playback.current_index)
        self.player.set_volume(self.settings.playback.volume)
        self.player.mode = self.settings.playback.mode

    def _scan_in_thread(self, roots: list[str]) -> None:
        threading.Thread(target=self._scan_roots_job, args=(roots,), daemon=True).start()

    def _scan_roots_job(self, roots: list[str]) -> None:
        with self._scan_lock:
            self.scanner.scan_roots(roots)
        if self.window:
            GLib.idle_add(self.window._refresh_library)

    def _scan_file_and_refresh(self, path: str) -> None:
        with self._scan_lock:
            self.scanner.scan_file(path)
        if self.window:
            GLib.idle_add(self.window._refresh_library)

    def _on_about_to_scrobble(self, _player: PlaybackEngine, entry: object) -> None:
        track = self.database.get_track(entry.path)
        if track is None:
            return
        self.lastfm.queue_scrobble(
            artist=track.artist,
            track=track.title,
            album=track.album,
            album_artist=track.album_artist,
            duration=int(track.duration),
        )
        threading.Thread(target=self.lastfm.flush_queue, daemon=True).start()

    def _on_track_changed(self, _player: PlaybackEngine, entry: object) -> None:
        track = self.database.get_track(entry.path)
        if track is None:
            return
        if self._resume_seek_pending > 0:
            seek_position = self._resume_seek_pending
            self._resume_seek_pending = 0.0
            GLib.timeout_add(250, self._seek_after_restore, seek_position)
        threading.Thread(
            target=self._send_now_playing,
            args=(track.artist, track.title, track.album, int(track.duration)),
            daemon=True,
        ).start()

    def _send_now_playing(self, artist: str, title: str, album: str, duration: int) -> None:
        try:
            self.lastfm.now_playing(artist, title, album, duration)
        except Exception:
            return

    def _seek_after_restore(self, position: float) -> bool:
        self.player.seek(position)
        return False
