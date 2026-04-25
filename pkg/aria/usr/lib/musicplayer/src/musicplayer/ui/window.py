"""Main application window."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")

from gi.repository import Adw, Gio, GLib, GObject, Gdk, Gtk, Pango

from musicplayer import APP_NAME
from musicplayer.artwork import dominant_color_css, load_pixbuf
from musicplayer.config import Settings
from musicplayer.db import LibraryDatabase
from musicplayer.lastfm import LastFMPanelData, LastFMService
from musicplayer.library.scanner import LibraryScanner
from musicplayer.lyrics import LyricsService
from musicplayer.models import PlaylistSummary, QueueEntry, Track
from musicplayer.playback.player import PlaybackEngine
from musicplayer.playback.queue import PlayQueue
from musicplayer.playlists import export_m3u, export_pls, export_xspf, import_playlist
from musicplayer.ui.preferences import PreferencesDialog


class MusicWindow(Adw.ApplicationWindow):
    """Primary application window."""

    def __init__(
        self,
        app: Adw.Application,
        settings: Settings,
        database: LibraryDatabase,
        scanner: LibraryScanner,
        lyrics: LyricsService,
        queue: PlayQueue,
        player: PlaybackEngine,
        save_settings: Callable[[], None],
        rescan: Callable[[], None],
        add_library_folder: Callable[[str], None],
        remove_library_folder: Callable[[str], None],
        lastfm: LastFMService,
    ) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.settings = settings
        self.database = database
        self.scanner = scanner
        self.lyrics = lyrics
        self.queue = queue
        self.player = player
        self.save_settings = save_settings
        self.rescan = rescan
        self.add_library_folder = add_library_folder
        self.remove_library_folder = remove_library_folder
        self.lastfm = lastfm

        self.current_track: Track | None = None
        self.selected_playlist_id: int | None = None
        self._hero_provider = Gtk.CssProvider()
        self._preferences_dialog: PreferencesDialog | None = None
        self._playlist_rows: dict[int, Adw.ActionRow] = {}
        self._fullscreen_lyrics_window: Gtk.Window | None = None
        self._fullscreen_lyrics_box: Gtk.Box | None = None
        self._fullscreen_lyrics_scroller: Gtk.ScrolledWindow | None = None
        self._fullscreen_lyrics_labels: list[Gtk.Label] = []
        self._fullscreen_cover: Gtk.Image | None = None
        self._fullscreen_title: Gtk.Label | None = None
        self._fullscreen_artist: Gtk.Label | None = None
        self._current_lyric_lines: list[tuple[float, str]] = []
        self._current_plain_lyrics: str = ""
        self._now_playing_play_button: Gtk.Button | None = None
        self._lyrics_scroller: Gtk.ScrolledWindow | None = None
        self._pending_lastfm_token: str = ""

        self.set_default_size(settings.window_width, settings.window_height)

        self.search_text = ""
        self.filter_model = Gtk.CustomFilter.new(self._filter_track)
        self.track_store = Gio.ListStore(item_type=GObject.Object)
        self.filter_list = Gtk.FilterListModel(model=self.track_store, filter=self.filter_model)
        self.selection = Gtk.SingleSelection(model=self.filter_list)

        self._build_ui()
        self._create_actions()
        self._setup_drop_target()
        self._apply_theme()
        self._refresh_library()
        self._refresh_lastfm()

        self.player.connect("position-changed", self._on_position_changed)
        self.player.connect("state-changed", self._on_player_state_changed)
        self.player.connect("track-changed", self._on_track_changed)
        self.queue.connect("changed", lambda *_args: self._refresh_queue())
        self.connect("close-request", self._on_close_request)

    def _build_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self.search_button = Gtk.ToggleButton(icon_name="system-search-symbolic", active=True)
        self.search_button.connect("toggled", self._on_search_toggle)
        header.pack_start(self.search_button)

        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.set_tooltip_text("Add music folder")
        add_button.connect("clicked", self._on_add_folder_clicked)
        header.pack_start(add_button)

        rescan_button = Gtk.Button(icon_name="view-refresh-symbolic")
        rescan_button.set_tooltip_text("Rescan library")
        rescan_button.connect("clicked", lambda *_args: self.rescan())
        header.pack_start(rescan_button)

        pref_button = Gtk.Button(icon_name="emblem-system-symbolic")
        pref_button.connect("clicked", self._on_preferences_clicked)
        header.pack_end(pref_button)

        self.search_entry = Gtk.SearchEntry(placeholder_text="Search library")
        self.search_entry.connect("search-changed", self._on_search_changed)

        split = Adw.NavigationSplitView()
        toolbar_view.set_content(split)

        self.stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE,
            transition_duration=250,
            vexpand=True,
            hexpand=True,
        )

        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        sidebar.set_vexpand(True)
        sidebar.set_hexpand(False)
        sidebar_page = Adw.NavigationPage(title="Browse")
        sidebar_page.set_child(sidebar)
        split.set_sidebar(sidebar_page)

        content_page = Adw.NavigationPage(title="Content")
        content_page.set_child(self.stack)
        split.set_content(content_page)

        self.stack.add_titled(self._build_library_view(), "Library", "Library")
        self.stack.add_titled(self._build_albums_view(), "Albums", "Albums")
        self.stack.add_titled(self._build_artists_view(), "Artists", "Artists")
        self.stack.add_titled(self._build_genres_view(), "Genres", "Genres")
        self.stack.add_titled(self._build_playlists_view(), "Playlists", "Playlists")
        self.stack.add_titled(self._build_folders_view(), "Folders", "Folders")
        self.stack.add_titled(self._build_queue_view(), "Queue", "Queue")
        self.stack.add_titled(self._build_lastfm_view(), "Last.fm", "Last.fm")
        self.stack.add_titled(self._build_now_playing_view(), "Now Playing", "Now Playing")
        self.stack.set_visible_child_name("Library")

        toolbar_view.add_bottom_bar(self._build_player_bar())

        overlay = Gtk.Overlay()
        overlay.set_child(toolbar_view)
        self.search_entry.set_halign(Gtk.Align.FILL)
        self.search_entry.set_valign(Gtk.Align.START)
        self.search_entry.set_margin_top(8)
        self.search_entry.set_margin_start(72)
        self.search_entry.set_margin_end(72)
        overlay.add_overlay(self.search_entry)
        self.set_content(overlay)

        css = Gtk.CssProvider()
        css.load_from_data(
            b"""
            .hero-panel {
                border-radius: 12px;
                padding: 24px;
                background: rgba(30, 30, 30, 0.12);
            }
            .lyrics-fullscreen {
                font-size: 42px;
                line-height: 1.35;
            }
            .lyrics-line {
                font-size: 24px;
                line-height: 1.45;
            }
            .lyrics-current,
            .lyrics-current-fullscreen {
                font-weight: 700;
                opacity: 1.0;
            }
            .lyrics-current {
                font-size: 28px;
            }
            .lyrics-past {
                opacity: 0.45;
            }
            .lyrics-past-fullscreen {
                opacity: 0.35;
            }
            .library-cell {
                font-size: 16px;
            }
            .library-primary {
                font-size: 18px;
                font-weight: 650;
            }
            .fullscreen-track-title {
                font-size: 30px;
                font-weight: 700;
            }
            .fullscreen-track-artist {
                font-size: 18px;
                opacity: 0.72;
            }
            """
        )
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            Gtk.StyleContext.add_provider_for_display(
                display,
                self._hero_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _build_library_view(self) -> Gtk.Widget:
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        columns = Gtk.ColumnView(model=self.selection, hexpand=True, vexpand=True)
        columns.append_column(self._artwork_column())
        columns.append_column(self._text_column("Title", lambda item: item.track.title, primary=True))
        columns.append_column(self._text_column("Artist", lambda item: item.track.artist))
        columns.append_column(self._text_column("Album", lambda item: item.track.album))
        columns.append_column(self._text_column("Year", lambda item: str(item.track.year or "")))
        columns.append_column(self._text_column("BPM", lambda item: str(item.track.bpm or "")))
        columns.append_column(self._text_column("Duration", lambda item: _format_duration(item.track.duration)))
        columns.connect("activate", self._on_track_activated)

        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroller.set_child(columns)
        root.append(scroller)
        return root

    def _build_albums_view(self) -> Gtk.Widget:
        self.album_flow = Gtk.FlowBox(
            max_children_per_line=6,
            selection_mode=Gtk.SelectionMode.NONE,
            row_spacing=12,
            column_spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.album_flow)
        return scroller

    def _build_artists_view(self) -> Gtk.Widget:
        self.artist_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.artist_list)
        return scroller

    def _build_genres_view(self) -> Gtk.Widget:
        self.genre_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.genre_list)
        return scroller

    def _build_folders_view(self) -> Gtk.Widget:
        self.folder_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.folder_list)
        return scroller

    def _build_playlists_view(self) -> Gtk.Widget:
        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        new_button = Gtk.Button(label="New Playlist")
        new_button.connect("clicked", self._on_new_playlist_clicked)
        save_button = Gtk.Button(label="Save Queue")
        save_button.connect("clicked", self._on_save_queue_playlist)
        import_button = Gtk.Button(label="Import")
        import_button.connect("clicked", self._on_import_playlist_clicked)
        export_button = Gtk.Button(label="Export")
        export_button.connect("clicked", self._on_export_playlist_clicked)
        rename_button = Gtk.Button(label="Rename")
        rename_button.connect("clicked", self._on_rename_playlist_clicked)
        delete_button = Gtk.Button(label="Delete")
        delete_button.connect("clicked", self._on_delete_playlist_clicked)
        load_button = Gtk.Button(label="Load")
        load_button.connect("clicked", self._on_load_playlist_clicked)
        for widget in (new_button, save_button, import_button, export_button, rename_button, delete_button, load_button):
            controls.append(widget)
        outer.append(controls)

        self.playlist_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["boxed-list"])
        self.playlist_list.connect("row-selected", self._on_playlist_selected)
        self.playlist_list.connect("row-activated", self._on_playlist_row_activated)
        outer.append(Gtk.ScrolledWindow(child=self.playlist_list, vexpand=True))
        return outer

    def _build_queue_view(self) -> Gtk.Widget:
        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        clear_button = Gtk.Button(label="Clear Queue")
        clear_button.connect("clicked", lambda *_args: self.queue.clear())
        playlist_button = Gtk.Button(label="Save as Playlist")
        playlist_button.connect("clicked", self._on_save_queue_playlist)
        for widget in (clear_button, playlist_button):
            controls.append(widget)
        controls.append(self._build_mode_selector())
        outer.append(controls)

        self.queue_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["boxed-list"])
        self.queue_list.connect("row-activated", self._on_queue_row_activated)
        outer.append(Gtk.ScrolledWindow(child=self.queue_list, vexpand=True))
        return outer

    def _build_lastfm_view(self) -> Gtk.Widget:
        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda *_args: self._refresh_lastfm())
        auth = Gtk.Button(label="Connect")
        auth.connect("clicked", self._on_open_lastfm_auth)
        disconnect = Gtk.Button(label="Disconnect")
        disconnect.connect("clicked", self._on_disconnect_lastfm)
        header.append(refresh)
        header.append(auth)
        header.append(disconnect)
        outer.append(header)

        self.lastfm_status = Gtk.Label(xalign=0, wrap=True)
        outer.append(self.lastfm_status)

        self.lastfm_recent = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.lastfm_top_artists = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.lastfm_top_albums = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])

        outer.append(Gtk.Label(label="Recent Scrobbles", xalign=0, css_classes=["title-4"]))
        outer.append(Gtk.ScrolledWindow(child=self.lastfm_recent, vexpand=True, min_content_height=140))
        outer.append(Gtk.Label(label="Top Artists", xalign=0, css_classes=["title-4"]))
        outer.append(Gtk.ScrolledWindow(child=self.lastfm_top_artists, vexpand=True, min_content_height=120))
        outer.append(Gtk.Label(label="Top Albums", xalign=0, css_classes=["title-4"]))
        outer.append(Gtk.ScrolledWindow(child=self.lastfm_top_albums, vexpand=True, min_content_height=120))
        return outer

    def _build_now_playing_view(self) -> Gtk.Widget:
        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=24,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )

        self.hero_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, css_classes=["hero-panel"])
        self.hero_box.set_name("hero-box")
        self.hero_art = Gtk.Image(pixel_size=220)
        self.hero_art.set_halign(Gtk.Align.CENTER)
        self.hero_box.append(self.hero_art)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.CENTER)
        info.set_hexpand(True)
        self.hero_title = Gtk.Label(label="Nothing playing", xalign=0, wrap=True, css_classes=["title-1"])
        self.hero_artist = Gtk.Label(label="", xalign=0, wrap=True, css_classes=["title-4"])
        self.hero_album = Gtk.Label(label="", xalign=0, wrap=True)

        hero_playback = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        prev_button = Gtk.Button(icon_name="media-skip-backward-symbolic")
        prev_button.connect("clicked", lambda *_args: self.player.previous())
        self._now_playing_play_button = Gtk.Button(icon_name="media-playback-start-symbolic")
        self._now_playing_play_button.connect("clicked", lambda *_args: self.player.toggle())
        next_button = Gtk.Button(icon_name="media-skip-forward-symbolic")
        next_button.connect("clicked", lambda *_args: self.player.next())
        for widget in (prev_button, self._now_playing_play_button, next_button):
            hero_playback.append(widget)

        hero_actions = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=2,
            row_spacing=8,
            column_spacing=8,
        )
        hero_actions.set_halign(Gtk.Align.START)
        fetch_lyrics = Gtk.Button(label="Fetch Lyrics")
        fetch_lyrics.connect("clicked", self._on_fetch_lyrics_clicked)
        love_button = Gtk.Button(label="Love")
        love_button.connect("clicked", self._on_love_clicked)
        unlove_button = Gtk.Button(label="Unlove")
        unlove_button.connect("clicked", self._on_unlove_clicked)
        fullscreen_button = Gtk.Button(label="Fullscreen Lyrics")
        fullscreen_button.connect("clicked", lambda *_args: self._present_fullscreen_lyrics())
        for widget in (fetch_lyrics, love_button, unlove_button, fullscreen_button):
            hero_actions.insert(widget, -1)
        info.append(self.hero_title)
        info.append(self.hero_artist)
        info.append(self.hero_album)
        info.append(hero_playback)
        info.append(hero_actions)
        self.hero_box.append(info)
        outer.append(self.hero_box)

        lyrics_frame = Gtk.Frame(hexpand=True, vexpand=True)
        self.lyrics_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=18,
            margin_bottom=18,
            margin_start=18,
            margin_end=18,
        )
        self._lyrics_scroller = Gtk.ScrolledWindow(child=self.lyrics_box, vexpand=True)
        lyrics_frame.set_child(self._lyrics_scroller)
        outer.append(lyrics_frame)
        return Gtk.ScrolledWindow(child=outer, vexpand=True, hexpand=True)

    def _build_player_bar(self) -> Gtk.Widget:
        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            margin_top=8,
            margin_bottom=8,
            margin_start=12,
            margin_end=12,
        )
        self.bar_art = Gtk.Image(pixel_size=48)
        box.append(self.bar_art)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        self.bar_title = Gtk.Label(label="Nothing queued", xalign=0)
        self.bar_artist = Gtk.Label(label="", xalign=0, css_classes=["dim-label"])
        text_box.append(self.bar_title)
        text_box.append(self.bar_artist)
        box.append(text_box)

        prev_button = Gtk.Button(icon_name="media-skip-backward-symbolic")
        prev_button.connect("clicked", lambda *_args: self.player.previous())
        self.play_button = Gtk.Button(icon_name="media-playback-start-symbolic")
        self.play_button.connect("clicked", lambda *_args: self.player.toggle())
        next_button = Gtk.Button(icon_name="media-skip-forward-symbolic")
        next_button.connect("clicked", lambda *_args: self.player.next())
        for widget in (prev_button, self.play_button, next_button):
            box.append(widget)

        self.position_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.position_scale.set_draw_value(False)
        self.position_scale.set_hexpand(True)
        self.position_scale.connect("change-value", self._on_seek)
        box.append(self.position_scale)

        self.volume = Gtk.VolumeButton()
        self.volume.set_value(self.settings.playback.volume)
        self.volume.connect("value-changed", self._on_volume_changed)
        box.append(self.volume)
        return box

    def _build_mode_selector(self) -> Gtk.Widget:
        selector = Gtk.DropDown.new_from_strings(["Normal", "Shuffle", "Repeat One", "Repeat All"])
        selector.set_selected(
            {"normal": 0, "shuffle": 1, "repeat-one": 2, "repeat-all": 3}.get(self.player.mode, 0)
        )
        selector.connect("notify::selected", self._on_mode_changed)
        return selector

    def _text_column(
        self,
        title: str,
        getter: Callable[[_TrackObject], str],
        primary: bool = False,
    ) -> Gtk.ColumnViewColumn:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_setup_text_item, primary)
        factory.connect("bind", self._on_bind_text_item, getter, primary)
        column = Gtk.ColumnViewColumn(title=title, factory=factory)
        column.set_expand(primary)
        if primary:
            column.set_fixed_width(280)
        return column

    def _artwork_column(self) -> Gtk.ColumnViewColumn:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_setup_artwork_item)
        factory.connect("bind", self._on_bind_artwork_item)
        column = Gtk.ColumnViewColumn(title="", factory=factory)
        column.set_fixed_width(88)
        return column

    def _on_setup_text_item(
        self,
        _factory: Gtk.SignalListItemFactory,
        list_item: Gtk.ListItem,
        primary: bool,
    ) -> None:
        label = Gtk.Label(xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_margin_top(10)
        label.set_margin_bottom(10)
        label.add_css_class("library-cell")
        if primary:
            label.add_css_class("library-primary")
        list_item.set_child(label)

    def _on_bind_text_item(
        self,
        _factory: Gtk.SignalListItemFactory,
        list_item: Gtk.ListItem,
        getter: Callable[[_TrackObject], str],
        primary: bool,
    ) -> None:
        item = list_item.get_item()
        if item is None:
            return
        text = getter(item)
        label = list_item.get_child()
        label.set_text(text)
        if primary:
            label.set_tooltip_text(text)

    def _on_setup_artwork_item(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        image = Gtk.Image(pixel_size=64)
        image.set_margin_top(6)
        image.set_margin_bottom(6)
        image.set_margin_start(6)
        image.set_margin_end(6)
        list_item.set_child(image)

    def _on_bind_artwork_item(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        item = list_item.get_item()
        if item is None:
            return
        image = list_item.get_child()
        pixbuf = load_pixbuf(item.track.artwork_path, 64)
        if pixbuf is not None:
            image.set_from_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
        else:
            image.set_from_icon_name("audio-x-generic-symbolic")

    def _create_actions(self) -> None:
        for name, callback in (
            ("rescan", lambda *_args: self.rescan()),
            ("search", lambda *_args: self.search_entry.grab_focus()),
            ("lyrics-fullscreen", lambda *_args: self._present_fullscreen_lyrics()),
            ("save-playlist", self._on_save_queue_playlist),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        self.shortcuts = Gtk.ShortcutsWindow(transient_for=self)
        section = Gtk.ShortcutsSection(title="General")
        group = Gtk.ShortcutsGroup(title="Global")
        for title, accel in (
            ("Search", "<Primary>f"),
            ("Play/Pause", "space"),
            ("Fullscreen Lyrics", "l"),
            ("Save Queue As Playlist", "<Primary>s"),
        ):
            group.add_shortcut(Gtk.ShortcutsShortcut(title=title, accelerator=accel))
        section.add_group(group)
        self.shortcuts.set_child(section)

        help_action = Gio.SimpleAction.new("shortcuts", None)
        help_action.connect("activate", lambda *_args: self.shortcuts.present())
        self.add_action(help_action)

    def _refresh_library(self) -> None:
        self.track_store.remove_all()
        for track in self.database.iter_tracks(self.search_text):
            self.track_store.append(_TrackObject(track))
        self._refresh_albums()
        self._refresh_artists()
        self._refresh_genres()
        self._refresh_folders()
        self._refresh_playlists()
        self._refresh_queue()
        if self._preferences_dialog is not None:
            self._preferences_dialog.refresh_folders()

    def _refresh_albums(self) -> None:
        while (child := self.album_flow.get_first_child()) is not None:
            self.album_flow.remove(child)
        for album in self.database.albums(self.search_text):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=164)
            image = Gtk.Image(pixel_size=144)
            pixbuf = load_pixbuf(album.artwork_path, 144)
            if pixbuf:
                image.set_from_pixbuf(pixbuf)
            card.append(image)
            card.append(Gtk.Label(label=album.album, xalign=0, wrap=True))
            card.append(Gtk.Label(label=album.album_artist, xalign=0, wrap=True, css_classes=["dim-label"]))
            button = Gtk.Button()
            button.set_has_frame(False)
            button.set_tooltip_text(f"Play album: {album.album}")
            button.set_child(card)
            button.connect("clicked", self._on_album_clicked, album.album, album.album_artist)
            self.album_flow.insert(button, -1)

    def _refresh_artists(self) -> None:
        while (child := self.artist_list.get_first_child()) is not None:
            self.artist_list.remove(child)
        for artist in self.database.artists(self.search_text):
            self.artist_list.append(
                Adw.ActionRow(
                    title=artist.artist,
                    subtitle=f"{artist.album_count} albums, {artist.track_count} tracks",
                )
            )

    def _refresh_genres(self) -> None:
        while (child := self.genre_list.get_first_child()) is not None:
            self.genre_list.remove(child)
        for genre in self.database.genres(self.search_text):
            self.genre_list.append(Adw.ActionRow(title=genre.genre, subtitle=f"{genre.track_count} tracks"))

    def _refresh_folders(self) -> None:
        while (child := self.folder_list.get_first_child()) is not None:
            self.folder_list.remove(child)
        for folder in self.database.folders():
            self.folder_list.append(Adw.ActionRow(title=folder.root_path, subtitle=f"{folder.track_count} tracks"))

    def _refresh_playlists(self) -> None:
        self.database.ensure_liked_playlist()
        while (child := self.playlist_list.get_first_child()) is not None:
            self.playlist_list.remove(child)
        self._playlist_rows.clear()
        for playlist in self.database.list_playlists():
            row = Adw.ActionRow(title=playlist.name, subtitle=f"{playlist.track_count} tracks")
            row.set_activatable(True)
            row.playlist_id = playlist.id
            self._playlist_rows[playlist.id] = row
            self.playlist_list.append(row)

    def _refresh_queue(self) -> None:
        while (child := self.queue_list.get_first_child()) is not None:
            self.queue_list.remove(child)
        for index, entry in enumerate(self.queue.entries):
            row = Adw.ActionRow(title=entry.title, subtitle=f"{entry.artist} - {entry.album}")
            row.set_activatable(True)
            row.queue_index = index
            up_button = Gtk.Button(icon_name="go-up-symbolic", valign=Gtk.Align.CENTER)
            down_button = Gtk.Button(icon_name="go-down-symbolic", valign=Gtk.Align.CENTER)
            remove_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            up_button.connect("clicked", self._on_queue_move_clicked, index, max(index - 1, 0))
            down_button.connect("clicked", self._on_queue_move_clicked, index, min(index + 1, len(self.queue.entries) - 1))
            remove_button.connect("clicked", self._on_queue_remove_clicked, index)
            row.add_suffix(up_button)
            row.add_suffix(down_button)
            row.add_suffix(remove_button)
            self.queue_list.append(row)

    def _refresh_lastfm(self) -> None:
        if self.lastfm.configured() and self.settings.lastfm.username:
            self.lastfm_status.set_text(f"Signed in as {self.settings.lastfm.username}")
        elif self.settings.lastfm.api_key and self.settings.lastfm.api_secret:
            self.lastfm_status.set_text("Last.fm ready. Click Connect to finish login.")
        else:
            self.lastfm_status.set_text("Add your Last.fm API key and secret in Settings first.")
        threading.Thread(target=self._load_lastfm_data, daemon=True).start()

    def _load_lastfm_data(self) -> None:
        try:
            data = self.lastfm.fetch_panel_data()
        except Exception as exc:
            GLib.idle_add(self.lastfm_status.set_text, f"Last.fm refresh failed: {exc}")
            return
        GLib.idle_add(self._populate_lastfm, data)

    def _populate_lastfm(self, data: LastFMPanelData) -> bool:
        for box in (self.lastfm_recent, self.lastfm_top_artists, self.lastfm_top_albums):
            while (child := box.get_first_child()) is not None:
                box.remove(child)

        for item in data.recent:
            artist = item.get("artist", {}).get("#text", "")
            title = item.get("name", "")
            album = item.get("album", {}).get("#text", "")
            self.lastfm_recent.append(Adw.ActionRow(title=title, subtitle=f"{artist} - {album}"))
        for item in data.top_artists:
            self.lastfm_top_artists.append(
                Adw.ActionRow(title=item.get("name", ""), subtitle=f"Playcount {item.get('playcount', '')}")
            )
        for item in data.top_albums:
            artist = item.get("artist", {}).get("name", "")
            self.lastfm_top_albums.append(
                Adw.ActionRow(title=item.get("name", ""), subtitle=f"{artist} - {item.get('playcount', '')}")
            )
        return False

    def _filter_track(self, item: GObject.Object) -> bool:
        if not self.search_text:
            return True
        haystack = " ".join(
            (
                item.track.title,
                item.track.artist,
                item.track.album,
                item.track.album_artist,
                item.track.genre,
                str(item.track.year or ""),
                str(item.track.bpm or ""),
            )
        ).lower()
        return self.search_text in haystack

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.search_text = entry.get_text().strip().lower()
        self.filter_model.changed(Gtk.FilterChange.DIFFERENT)
        self._refresh_library()

    def _on_track_activated(self, _view: Gtk.ColumnView, position: int) -> None:
        queue_entries: list[QueueEntry] = []
        for index in range(self.filter_list.get_n_items()):
            obj = self.filter_list.get_item(index)
            if obj is not None:
                queue_entries.append(_queue_from_track(obj.track))
        self.queue.replace(queue_entries, position)
        self.player.play()
        self.stack.set_visible_child_name("Now Playing")

    def _on_album_clicked(self, _button: Gtk.Button, album: str, album_artist: str) -> None:
        entries = self.database.album_entries(album, album_artist)
        if not entries:
            return
        self.queue.replace(entries, 0)
        self.player.play()
        self.stack.set_visible_child_name("Now Playing")

    def _on_queue_row_activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        child = row.get_child()
        index = getattr(child, "queue_index", None)
        if isinstance(index, int):
            self.queue.set_current(index)
            self.player.play()

    def _on_queue_move_clicked(self, _button: Gtk.Button, old_index: int, new_index: int) -> None:
        self.queue.move(old_index, new_index)

    def _on_queue_remove_clicked(self, _button: Gtk.Button, index: int) -> None:
        self.queue.remove(index)

    def _on_track_changed(self, _player: PlaybackEngine, entry: QueueEntry) -> None:
        self.bar_title.set_text(entry.title)
        self.bar_artist.set_text(entry.artist)
        self.hero_title.set_text(entry.title)
        self.hero_artist.set_text(entry.artist)
        self.hero_album.set_text(entry.album)

        pixbuf = load_pixbuf(entry.artwork_path, 240)
        if pixbuf:
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self.hero_art.set_from_paintable(texture)
            self.bar_art.set_from_paintable(texture)
        else:
            self.hero_art.set_icon_name("media-optical-symbolic")
            self.bar_art.set_icon_name("media-optical-symbolic")

        self.current_track = self.database.get_track(entry.path)
        self._refresh_lyrics()
        self._update_hero_color(entry.artwork_path)

    def _refresh_lyrics(self) -> None:
        while (child := self.lyrics_box.get_first_child()) is not None:
            self.lyrics_box.remove(child)
        self._current_lyric_lines = []
        self._current_plain_lyrics = ""
        if self.current_track is None:
            return
        lines, plain = self.lyrics.load(self.current_track)
        if lines:
            self._current_lyric_lines = [(line.timestamp, line.text or " ") for line in lines]
            for line in lines:
                label = self._build_lyric_label(
                    line.text or " ",
                    "lyrics-line",
                    line.timestamp,
                    xalign=0.5,
                    justify=Gtk.Justification.CENTER,
                )
                self.lyrics_box.append(label)
        elif plain:
            self._current_plain_lyrics = plain
            for raw in plain.splitlines():
                label = self._build_lyric_label(raw, "lyrics-line", xalign=0, justify=Gtk.Justification.LEFT)
                self.lyrics_box.append(label)
        else:
            label = self._build_lyric_label("No lyrics found", "lyrics-line", xalign=0, justify=Gtk.Justification.LEFT)
            self.lyrics_box.append(label)
        self._refresh_fullscreen_lyrics()
        position, _duration = self.player.get_position()
        self._sync_lyrics(position)

    def _on_position_changed(self, _player: PlaybackEngine, position: float, duration: float) -> None:
        self.position_scale.set_range(0, max(duration, 1))
        self.position_scale.set_value(position)
        self._sync_lyrics(position)
        self.settings.playback.position_seconds = position

    def _on_player_state_changed(self, _player: PlaybackEngine, state: str) -> None:
        self._sync_play_buttons(state)

    def _sync_lyrics(self, position: float) -> None:
        current: Gtk.Widget | None = None
        child = self.lyrics_box.get_first_child()
        while child is not None:
            timestamp = getattr(child, "timestamp", None)
            if isinstance(timestamp, (float, int)):
                if timestamp <= position:
                    current = child
                    child.set_css_classes(["lyrics-line", "lyrics-past"])
                else:
                    child.set_css_classes(["lyrics-line"])
            child = child.get_next_sibling()
        if current is not None:
            current.set_css_classes(["lyrics-line", "lyrics-current"])
            self._center_lyric_line(current, self._lyrics_scroller, self.lyrics_box)
        self._sync_fullscreen_lyrics(position)

    def _on_seek(self, _scale: Gtk.Scale, _scroll: Gtk.ScrollType, value: float) -> bool:
        self.player.seek(value)
        return False

    def _sync_play_buttons(self, state: str) -> None:
        icon_name = "media-playback-pause-symbolic" if state == "playing" else "media-playback-start-symbolic"
        self.play_button.set_icon_name(icon_name)
        if self._now_playing_play_button is not None:
            self._now_playing_play_button.set_icon_name(icon_name)

    def _build_lyric_label(
        self,
        text: str,
        css_class: str,
        timestamp: float | None = None,
        *,
        xalign: float,
        justify: Gtk.Justification,
    ) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=xalign, wrap=True, justify=justify)
        label.add_css_class(css_class)
        if timestamp is not None:
            label.timestamp = timestamp
            gesture = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
            gesture.connect("released", self._on_lyric_clicked, timestamp)
            label.add_controller(gesture)
        return label

    def _on_lyric_clicked(
        self,
        _gesture: Gtk.GestureClick,
        _n_press: int,
        _x: float,
        _y: float,
        timestamp: float,
    ) -> None:
        self.player.seek(max(0.0, timestamp))

    def _center_lyric_line(
        self,
        label: Gtk.Widget,
        scroller: Gtk.ScrolledWindow | None,
        container: Gtk.Widget | None,
    ) -> None:
        if scroller is None or container is None:
            return

        def apply_scroll() -> bool:
            if not label.get_mapped():
                return False
            translated = label.translate_coordinates(container, 0, 0)
            if translated is None:
                return False
            _x, y = translated
            adjustment = scroller.get_vadjustment()
            page_size = adjustment.get_page_size()
            upper = adjustment.get_upper()
            target = y + label.get_allocated_height() / 2 - page_size / 2
            max_value = max(0.0, upper - page_size)
            adjustment.set_value(max(0.0, min(target, max_value)))
            return False

        GLib.idle_add(apply_scroll)

    def _on_volume_changed(self, _button: Gtk.VolumeButton, value: float) -> None:
        self.player.set_volume(value)
        self.settings.playback.volume = value

    def _on_mode_changed(self, dropdown: Gtk.DropDown, _pspec: object) -> None:
        self.player.mode = {0: "normal", 1: "shuffle", 2: "repeat-one", 3: "repeat-all"}.get(
            dropdown.get_selected(),
            "normal",
        )
        self.settings.playback.mode = self.player.mode
        self.save_settings()

    def _on_preferences_clicked(self, _button: Gtk.Button) -> None:
        self._preferences_dialog = PreferencesDialog(
            self,
            self.settings,
            self._on_settings_changed,
            self._on_add_folder_clicked_from_preferences,
            self._remove_folder_and_refresh,
            self.player.list_output_devices(),
        )
        self._preferences_dialog.present()

    def _on_settings_changed(self, settings: Settings) -> None:
        self.lyrics.update_folder(settings.lyrics_folder)
        self.player.apply_settings(settings)
        self.lastfm.update_profile(settings.lastfm)
        self._apply_theme()
        self.save_settings()
        self._refresh_lastfm()

    def _apply_theme(self) -> None:
        style_manager = Adw.StyleManager.get_default()
        if self.settings.theme_override == "light":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif self.settings.theme_override == "dark":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def _on_add_folder_clicked(self, _button: Gtk.Button) -> None:
        self._show_folder_dialog()

    def _on_add_folder_clicked_from_preferences(self) -> None:
        self._show_folder_dialog()

    def _show_folder_dialog(self) -> None:
        dialog = Gtk.FileDialog(title="Add Music Folder")
        dialog.select_folder(self, None, self._on_folder_selected)

    def _on_folder_selected(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        path = folder.get_path()
        if path:
            self.add_library_folder(path)
            self._refresh_library()

    def _remove_folder_and_refresh(self, path: str) -> None:
        self.remove_library_folder(path)
        self._refresh_library()

    def _on_save_queue_playlist(self, *_args) -> None:
        if not self.queue.entries:
            return
        default_name = datetime.now().strftime("Queue %Y-%m-%d %H:%M")
        self._prompt_text("Save Playlist", default_name, self._create_playlist_from_queue)

    def _on_new_playlist_clicked(self, _button: Gtk.Button) -> None:
        self._prompt_text("New Playlist", "", self._create_empty_playlist)

    def _create_empty_playlist(self, name: str) -> None:
        if not name.strip():
            return
        try:
            self.database.create_empty_playlist(name.strip())
        except sqlite3.IntegrityError:
            self.lastfm_status.set_text("A playlist with that name already exists.")
            return
        self._refresh_playlists()
        self.stack.set_visible_child_name("Playlists")

    def _create_playlist_from_queue(self, name: str) -> None:
        if not name.strip():
            return
        try:
            self.database.create_playlist(name.strip(), [entry.path for entry in self.queue.entries])
        except sqlite3.IntegrityError:
            self.lastfm_status.set_text("A playlist with that name already exists.")
            return
        self._refresh_playlists()
        self.stack.set_visible_child_name("Playlists")

    def _on_import_playlist_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Import Playlist")
        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        file_filter = Gtk.FileFilter()
        file_filter.add_suffix("m3u")
        file_filter.add_suffix("m3u8")
        file_filter.add_suffix("pls")
        file_filter.add_suffix("xspf")
        file_filter.set_name("Playlists")
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.open(self, None, self._on_playlist_imported)

    def _on_playlist_imported(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        path = file.get_path()
        if not path:
            return
        imported_paths = import_playlist(path)
        if imported_paths:
            try:
                self.database.create_playlist(Path(path).stem, imported_paths)
            except sqlite3.IntegrityError:
                self.lastfm_status.set_text("A playlist with that name already exists.")
                return
            self._refresh_playlists()

    def _on_export_playlist_clicked(self, _button: Gtk.Button) -> None:
        if self.selected_playlist_id is None:
            return
        dialog = Gtk.FileDialog(title="Export Playlist")
        dialog.save(self, None, self._on_playlist_export_path)

    def _on_playlist_export_path(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return
        path = file.get_path()
        if not path or self.selected_playlist_id is None:
            return
        entries = self.database.playlist_entries(self.selected_playlist_id)
        tracks = [entry.path for entry in entries]
        suffix = Path(path).suffix.lower()
        if suffix in {".m3u", ".m3u8", ""}:
            export_m3u(path if suffix else f"{path}.m3u", tracks)
        elif suffix == ".pls":
            export_pls(path, tracks)
        elif suffix == ".xspf":
            export_xspf(path, tracks)

    def _on_rename_playlist_clicked(self, _button: Gtk.Button) -> None:
        if self.selected_playlist_id is None:
            return
        current_name = self.database.playlist_name(self.selected_playlist_id) or ""
        self._prompt_text("Rename Playlist", current_name, self._rename_selected_playlist)

    def _rename_selected_playlist(self, name: str) -> None:
        if self.selected_playlist_id is None or not name.strip():
            return
        if self.database.playlist_name(self.selected_playlist_id) == self.database.LIKED_PLAYLIST_NAME:
            self.lastfm_status.set_text("The Liked playlist cannot be renamed.")
            return
        try:
            self.database.rename_playlist(self.selected_playlist_id, name.strip())
        except sqlite3.IntegrityError:
            self.lastfm_status.set_text("A playlist with that name already exists.")
            return
        self._refresh_playlists()

    def _on_delete_playlist_clicked(self, _button: Gtk.Button) -> None:
        if self.selected_playlist_id is None:
            return
        if self.database.playlist_name(self.selected_playlist_id) == self.database.LIKED_PLAYLIST_NAME:
            self.lastfm_status.set_text("The Liked playlist is built in and cannot be deleted.")
            return
        self.database.delete_playlist(self.selected_playlist_id)
        self.selected_playlist_id = None
        self._refresh_playlists()

    def _on_load_playlist_clicked(self, _button: Gtk.Button) -> None:
        self._load_selected_playlist()

    def _on_playlist_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            self.selected_playlist_id = None
            return
        child = row.get_child()
        if isinstance(child, Adw.ActionRow):
            playlist_id = getattr(child, "playlist_id", None)
            self.selected_playlist_id = playlist_id if isinstance(playlist_id, int) else None

    def _on_playlist_row_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        child = row.get_child()
        if isinstance(child, Adw.ActionRow):
            playlist_id = getattr(child, "playlist_id", None)
            if isinstance(playlist_id, int):
                self.selected_playlist_id = playlist_id
                self._load_selected_playlist()

    def _load_selected_playlist(self) -> None:
        if self.selected_playlist_id is None:
            return
        entries = self.database.playlist_entries(self.selected_playlist_id)
        self.queue.replace(entries, 0 if entries else -1)
        self.stack.set_visible_child_name("Queue")

    def _on_open_lastfm_auth(self, _button: Gtk.Button) -> None:
        if not self.settings.lastfm.api_key or not self.settings.lastfm.api_secret:
            self.lastfm_status.set_text("Configure Last.fm API key and secret in Settings first.")
            return
        self.lastfm_status.set_text("Requesting Last.fm authorization...")
        threading.Thread(target=self._start_lastfm_auth_flow, daemon=True).start()

    def _start_lastfm_auth_flow(self) -> None:
        try:
            token = self.lastfm.create_request_token()
            url = self.lastfm.build_desktop_auth_url(token)
        except Exception as exc:
            GLib.idle_add(self.lastfm_status.set_text, f"Last.fm auth start failed: {exc}")
            return
        self._pending_lastfm_token = token
        GLib.idle_add(self._present_lastfm_auth_dialog, url)

    def _present_lastfm_auth_dialog(self, url: str) -> bool:
        launcher = Gtk.UriLauncher.new(url)
        launcher.launch(self, None, None)

        dialog = Gtk.Dialog(title="Connect Last.fm", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("I Approved It", Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        box.append(
            Gtk.Label(
                label="A browser window was opened. Approve access on Last.fm, then click 'I Approved It'.",
                xalign=0,
                wrap=True,
            )
        )
        content.append(box)

        def on_response(inner_dialog: Gtk.Dialog, response: int) -> None:
            inner_dialog.destroy()
            if response == Gtk.ResponseType.OK and self._pending_lastfm_token:
                self.lastfm_status.set_text("Finishing Last.fm login...")
                threading.Thread(
                    target=self._finish_lastfm_auth_flow,
                    args=(self._pending_lastfm_token,),
                    daemon=True,
                ).start()
            else:
                self._pending_lastfm_token = ""

        dialog.connect("response", on_response)
        dialog.present()
        return False

    def _finish_lastfm_auth_flow(self, token: str) -> None:
        try:
            self.lastfm.create_session(token)
        except Exception as exc:
            self._pending_lastfm_token = ""
            GLib.idle_add(self.lastfm_status.set_text, f"Last.fm login failed: {exc}")
            return
        self._pending_lastfm_token = ""
        self.settings.lastfm.username = self.lastfm.profile.username
        self.settings.lastfm.session_key = self.lastfm.profile.session_key
        GLib.idle_add(self._complete_lastfm_auth_success)

    def _complete_lastfm_auth_success(self) -> bool:
        self.save_settings()
        self._refresh_lastfm()
        return False

    def _on_disconnect_lastfm(self, _button: Gtk.Button) -> None:
        self._pending_lastfm_token = ""
        self.settings.lastfm.username = ""
        self.settings.lastfm.session_key = ""
        self.lastfm.update_profile(self.settings.lastfm)
        self.save_settings()
        self._refresh_lastfm()

    def _on_fetch_lyrics_clicked(self, _button: Gtk.Button) -> None:
        if self.current_track is None:
            return
        threading.Thread(target=self._fetch_lyrics_background, args=(self.current_track,), daemon=True).start()

    def _fetch_lyrics_background(self, track: Track) -> None:
        try:
            fetched = self.lyrics.fetch_and_store(track)
        except Exception as exc:
            GLib.idle_add(self.lastfm_status.set_text, f"Lyrics fetch failed: {exc}")
            return
        if fetched:
            GLib.idle_add(self._refresh_lyrics)

    def _on_love_clicked(self, _button: Gtk.Button) -> None:
        if self.current_track is None:
            return
        liked_playlist_id = self.database.ensure_liked_playlist()
        self.database.add_track_to_playlist(liked_playlist_id, self.current_track.path)
        self._refresh_playlists()
        threading.Thread(
            target=self.lastfm.love,
            args=(self.current_track.artist, self.current_track.title),
            daemon=True,
        ).start()

    def _on_unlove_clicked(self, _button: Gtk.Button) -> None:
        if self.current_track is None:
            return
        liked_playlist_id = self.database.ensure_liked_playlist()
        self.database.remove_track_from_playlist(liked_playlist_id, self.current_track.path)
        self._refresh_playlists()
        threading.Thread(
            target=self.lastfm.unlove,
            args=(self.current_track.artist, self.current_track.title),
            daemon=True,
        ).start()

    def _prompt_text(self, title: str, value: str, callback: Callable[[str], None]) -> None:
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("OK", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        entry = Gtk.Entry(text=value, activates_default=True, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        dialog.set_default_response(Gtk.ResponseType.OK)
        content.append(entry)

        def on_response(inner_dialog: Gtk.Dialog, response: int) -> None:
            if response == Gtk.ResponseType.OK:
                callback(entry.get_text())
            inner_dialog.destroy()

        dialog.connect("response", on_response)
        dialog.present()

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        width, height = self.get_default_size()
        self.settings.window_width = width
        self.settings.window_height = height
        self.settings.playback.current_index = self.queue.current_index
        self.settings.playback.queue_paths = [entry.path for entry in self.queue.entries]
        self.save_settings()
        return False

    def _on_search_toggle(self, button: Gtk.ToggleButton) -> None:
        self.search_entry.set_visible(button.get_active())
        if button.get_active():
            self.search_entry.grab_focus()

    def _present_fullscreen_lyrics(self) -> None:
        if self.current_track is None:
            return
        if self._fullscreen_lyrics_window is None:
            self._fullscreen_lyrics_window = Gtk.Window(
                application=self.get_application(),
                title="Lyrics",
                decorated=False,
                resizable=True,
            )
            self._fullscreen_lyrics_window.set_default_size(1200, 900)
            self._fullscreen_lyrics_window.connect("close-request", self._on_fullscreen_lyrics_close_request)
            self._fullscreen_lyrics_window.add_controller(self._fullscreen_key_controller())

            header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            header.set_halign(Gtk.Align.CENTER)
            self._fullscreen_cover = Gtk.Image(pixel_size=180)
            self._fullscreen_cover.set_halign(Gtk.Align.CENTER)
            self._fullscreen_title = Gtk.Label(xalign=0.5, wrap=True, justify=Gtk.Justification.CENTER)
            self._fullscreen_title.add_css_class("fullscreen-track-title")
            self._fullscreen_artist = Gtk.Label(xalign=0.5, wrap=True, justify=Gtk.Justification.CENTER)
            self._fullscreen_artist.add_css_class("fullscreen-track-artist")
            header.append(self._fullscreen_cover)
            header.append(self._fullscreen_title)
            header.append(self._fullscreen_artist)

            self._fullscreen_lyrics_scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
            self._fullscreen_lyrics_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self._fullscreen_lyrics_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            self._fullscreen_lyrics_box.set_valign(Gtk.Align.CENTER)
            self._fullscreen_lyrics_scroller.set_child(self._fullscreen_lyrics_box)
            outer = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=24,
                margin_top=48,
                margin_bottom=48,
                margin_start=80,
                margin_end=80,
            )
            outer.append(header)
            outer.append(self._fullscreen_lyrics_scroller)
            self._fullscreen_lyrics_window.set_child(outer)

        self._refresh_fullscreen_lyrics()
        self._fullscreen_lyrics_window.present()
        self._fullscreen_lyrics_window.fullscreen()

    def _fullscreen_key_controller(self) -> Gtk.EventControllerKey:
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_fullscreen_key_pressed)
        return controller

    def _on_fullscreen_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._close_fullscreen_lyrics()
            return True
        return False

    def _on_fullscreen_lyrics_close_request(self, _window: Gtk.Window) -> bool:
        self._fullscreen_lyrics_window = None
        self._fullscreen_lyrics_box = None
        self._fullscreen_lyrics_scroller = None
        self._fullscreen_lyrics_labels = []
        self._fullscreen_cover = None
        self._fullscreen_title = None
        self._fullscreen_artist = None
        return False

    def _close_fullscreen_lyrics(self) -> None:
        if self._fullscreen_lyrics_window is not None:
            self._fullscreen_lyrics_window.close()

    def _refresh_fullscreen_lyrics(self) -> None:
        if self._fullscreen_lyrics_box is None:
            return
        if self.current_track is not None:
            if self._fullscreen_title is not None:
                self._fullscreen_title.set_text(self.current_track.title or "Nothing playing")
            if self._fullscreen_artist is not None:
                artist_line = self.current_track.artist
                if self.current_track.album:
                    artist_line = f"{artist_line} - {self.current_track.album}"
                self._fullscreen_artist.set_text(artist_line)
            if self._fullscreen_cover is not None:
                pixbuf = load_pixbuf(self.current_track.artwork_path, 180)
                if pixbuf is not None:
                    self._fullscreen_cover.set_from_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
                else:
                    self._fullscreen_cover.set_from_icon_name("media-optical-symbolic")
        while (child := self._fullscreen_lyrics_box.get_first_child()) is not None:
            self._fullscreen_lyrics_box.remove(child)
        self._fullscreen_lyrics_labels = []
        if self._current_lyric_lines:
            for timestamp, text in self._current_lyric_lines:
                label = self._build_lyric_label(
                    text,
                    "lyrics-fullscreen",
                    timestamp,
                    xalign=0.5,
                    justify=Gtk.Justification.CENTER,
                )
                label.set_margin_top(6)
                label.set_margin_bottom(6)
                self._fullscreen_lyrics_box.append(label)
                self._fullscreen_lyrics_labels.append(label)
        elif self._current_plain_lyrics:
            for raw in self._current_plain_lyrics.splitlines():
                label = self._build_lyric_label(raw, "lyrics-fullscreen", xalign=0.5, justify=Gtk.Justification.CENTER)
                label.set_margin_top(6)
                label.set_margin_bottom(6)
                self._fullscreen_lyrics_box.append(label)
                self._fullscreen_lyrics_labels.append(label)
        else:
            label = self._build_lyric_label(
                "No lyrics found",
                "lyrics-fullscreen",
                xalign=0.5,
                justify=Gtk.Justification.CENTER,
            )
            self._fullscreen_lyrics_box.append(label)
            self._fullscreen_lyrics_labels.append(label)
        if self._fullscreen_lyrics_labels:
            self._center_lyric_line(self._fullscreen_lyrics_labels[0], self._fullscreen_lyrics_scroller, self._fullscreen_lyrics_box)

    def _sync_fullscreen_lyrics(self, position: float) -> None:
        if not self._fullscreen_lyrics_labels or not self._current_lyric_lines:
            return
        current_index = 0
        for index, (timestamp, _text) in enumerate(self._current_lyric_lines):
            if timestamp <= position:
                current_index = index
        for index, label in enumerate(self._fullscreen_lyrics_labels):
            classes = ["lyrics-fullscreen"]
            if index < current_index:
                classes.insert(0, "lyrics-past-fullscreen")
            elif index == current_index:
                classes.insert(0, "lyrics-current-fullscreen")
            label.set_css_classes(classes)
        self._center_lyric_line(
            self._fullscreen_lyrics_labels[current_index],
            self._fullscreen_lyrics_scroller,
            self._fullscreen_lyrics_box,
        )

    def _update_hero_color(self, artwork_path: str) -> None:
        color = dominant_color_css(artwork_path)
        self._hero_provider.load_from_data(
            f"#hero-box {{ background: linear-gradient(to bottom right, {color}, rgba(28, 28, 28, 0.08)); }}".encode("utf-8")
        )

    def _setup_drop_target(self) -> None:
        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        target.connect("drop", self._on_drop_files)
        self.add_controller(target)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_drop_files(self, _target: Gtk.DropTarget, file_list: Gdk.FileList, _x: float, _y: float) -> bool:
        if file_list is None:
            return False
        added_entries: list[QueueEntry] = []
        for file in file_list.get_files():
            path = file.get_path()
            if not path:
                continue
            if Path(path).is_dir():
                self.add_library_folder(path)
            else:
                targets = import_playlist(path) if Path(path).suffix.lower() in {".m3u", ".m3u8", ".pls", ".xspf"} else [path]
                added_entries.extend(self.database.queue_entries(targets))
        if added_entries:
            self.queue.extend(added_entries)
        self._refresh_library()
        return True

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if state & Gdk.ModifierType.CONTROL_MASK and keyval == Gdk.KEY_f:
            self.search_entry.grab_focus()
            return True
        if state & Gdk.ModifierType.CONTROL_MASK and keyval == Gdk.KEY_question:
            self.shortcuts.present()
            return True
        if state & Gdk.ModifierType.CONTROL_MASK and keyval == Gdk.KEY_s:
            self._on_save_queue_playlist()
            return True
        if keyval in (Gdk.KEY_space, Gdk.KEY_KP_Space):
            self.player.toggle()
            return True
        if keyval in (Gdk.KEY_l, Gdk.KEY_L):
            self._present_fullscreen_lyrics()
            return True
        if keyval == Gdk.KEY_Escape and self.is_fullscreen():
            self.unfullscreen()
            return True
        return False

    def import_into_queue(self, path: str) -> None:
        """Import a playlist or single file into the queue."""
        targets = import_playlist(path) if Path(path).suffix.lower() in {".m3u", ".m3u8", ".pls", ".xspf"} else [path]
        entries = self.database.queue_entries(targets)
        self.queue.extend(entries)


class _TrackObject(GObject.Object):
    """Wrapper so GTK list models can carry track instances."""

    def __init__(self, track: Track) -> None:
        super().__init__()
        self.track = track


def _format_duration(seconds: float) -> str:
    minutes = int(seconds) // 60
    remainder = int(seconds) % 60
    return f"{minutes}:{remainder:02d}"


def _queue_from_track(track: Track) -> QueueEntry:
    return QueueEntry(
        path=track.path,
        title=track.title,
        artist=track.artist,
        album=track.album,
        duration=track.duration,
        artwork_path=track.artwork_path,
    )
