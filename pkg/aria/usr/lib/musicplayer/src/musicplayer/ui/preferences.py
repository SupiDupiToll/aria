"""Preferences dialog."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gtk

from musicplayer.config import Settings


class PreferencesDialog(Adw.PreferencesDialog):
    """Application preferences."""

    def __init__(
        self,
        parent: Gtk.Window,
        settings: Settings,
        on_change: Callable[[Settings], None],
        on_add_folder: Callable[[], None],
        on_remove_folder: Callable[[str], None],
        output_devices: list[tuple[str, str]],
    ) -> None:
        super().__init__()
        self._parent = parent
        self._settings = settings
        self._on_change = on_change
        self._on_add_folder = on_add_folder
        self._on_remove_folder = on_remove_folder
        self._folder_rows: list[Adw.ActionRow] = []

        general = Adw.PreferencesPage(title="General")
        library_group = Adw.PreferencesGroup(title="Library")
        self._folder_group = Adw.PreferencesGroup(title="Managed Folders")
        add_folder_row = Adw.ActionRow(title="Add Folder")
        add_folder_row.set_activatable(True)
        add_button = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER)
        add_button.connect("clicked", lambda *_args: self._on_add_folder())
        add_folder_row.add_suffix(add_button)
        add_folder_row.connect("activated", lambda *_args: self._on_add_folder())
        self._folder_group.add(add_folder_row)
        self._rebuild_folders()

        self._lyrics_row = Adw.EntryRow(title="Lyrics Folder", text=settings.lyrics_folder)
        self._lyrics_row.connect("notify::text", self._on_lyrics_changed)
        library_group.add(self._lyrics_row)

        playback_group = Adw.PreferencesGroup(title="Playback")
        self._crossfade = Adw.SpinRow.new_with_range(0, 12, 1)
        self._crossfade.set_title("Crossfade")
        self._crossfade.set_subtitle("Seconds")
        self._crossfade.set_value(settings.crossfade_seconds)
        self._crossfade.connect("notify::value", self._on_crossfade_changed)
        playback_group.add(self._crossfade)

        self._resume = Adw.SwitchRow(title="Resume Playback")
        self._resume.set_active(settings.resume_playback)
        self._resume.connect("notify::active", self._on_resume_changed)
        playback_group.add(self._resume)

        self._normalize = Adw.SwitchRow(title="Normalize Output")
        self._normalize.set_active(settings.normalize)
        self._normalize.connect("notify::active", self._on_normalize_changed)
        playback_group.add(self._normalize)

        self._replaygain_row = Adw.ComboRow(title="ReplayGain")
        replaygain_model = Gtk.StringList.new(["Track", "Album", "Off"])
        self._replaygain_row.set_model(replaygain_model)
        self._replaygain_row.set_selected({"track": 0, "album": 1, "off": 2}.get(settings.replaygain_mode, 0))
        self._replaygain_row.connect("notify::selected", self._on_replaygain_changed)
        playback_group.add(self._replaygain_row)

        output_group = Adw.PreferencesGroup(title="Audio Output")
        self._output_devices = output_devices
        self._output_row = Adw.ComboRow(title="Device")
        output_model = Gtk.StringList.new([name for _device_id, name in output_devices] or ["Default"])
        self._output_row.set_model(output_model)
        selected_device = next(
            (index for index, (device_id, _name) in enumerate(output_devices) if device_id == settings.output_device_id),
            0,
        )
        self._output_row.set_selected(selected_device)
        self._output_row.connect("notify::selected", self._on_output_changed)
        output_group.add(self._output_row)

        appearance_group = Adw.PreferencesGroup(title="Appearance")
        self._theme_row = Adw.ComboRow(title="Theme")
        theme_model = Gtk.StringList.new(["System", "Light", "Dark"])
        self._theme_row.set_model(theme_model)
        self._theme_row.set_selected({"system": 0, "light": 1, "dark": 2}.get(settings.theme_override, 0))
        self._theme_row.connect("notify::selected", self._on_theme_changed)
        appearance_group.add(self._theme_row)

        account = Adw.PreferencesPage(title="Last.fm")
        account_group = Adw.PreferencesGroup(title="Account")
        self._username_row = Adw.EntryRow(title="Username", text=settings.lastfm.username)
        self._username_row.connect("notify::text", self._on_lastfm_changed)
        self._api_key_row = Adw.PasswordEntryRow(title="API Key")
        self._api_key_row.set_text(settings.lastfm.api_key)
        self._api_key_row.connect("notify::text", self._on_lastfm_changed)
        self._api_secret_row = Adw.PasswordEntryRow(title="API Secret")
        self._api_secret_row.set_text(settings.lastfm.api_secret)
        self._api_secret_row.connect("notify::text", self._on_lastfm_changed)
        self._session_row = Adw.PasswordEntryRow(title="Session Key")
        self._session_row.set_text(settings.lastfm.session_key)
        self._session_row.connect("notify::text", self._on_lastfm_changed)
        account_group.add(self._username_row)
        account_group.add(self._api_key_row)
        account_group.add(self._api_secret_row)
        account_group.add(self._session_row)
        account.add(account_group)

        general.add(self._folder_group)
        general.add(library_group)
        general.add(playback_group)
        general.add(output_group)
        general.add(appearance_group)
        self.add(general)
        self.add(account)

    def present(self) -> None:
        """Present the dialog relative to its parent window."""
        super().present(self._parent)

    def _commit(self) -> None:
        self._on_change(self._settings)

    def _on_lyrics_changed(self, row: Adw.EntryRow, _pspec: object) -> None:
        self._settings.lyrics_folder = row.get_text()
        self._commit()

    def _on_crossfade_changed(self, row: Adw.SpinRow, _pspec: object) -> None:
        self._settings.crossfade_seconds = int(row.get_value())
        self._commit()

    def _on_resume_changed(self, row: Adw.SwitchRow, _pspec: object) -> None:
        self._settings.resume_playback = row.get_active()
        self._commit()

    def _on_normalize_changed(self, row: Adw.SwitchRow, _pspec: object) -> None:
        self._settings.normalize = row.get_active()
        self._commit()

    def _on_replaygain_changed(self, row: Adw.ComboRow, _pspec: object) -> None:
        self._settings.replaygain_mode = {0: "track", 1: "album", 2: "off"}.get(row.get_selected(), "track")
        self._commit()

    def _on_output_changed(self, row: Adw.ComboRow, _pspec: object) -> None:
        selected = row.get_selected()
        if 0 <= selected < len(self._output_devices):
            self._settings.output_device_id = self._output_devices[selected][0]
            self._commit()

    def _on_theme_changed(self, row: Adw.ComboRow, _pspec: object) -> None:
        self._settings.theme_override = {0: "system", 1: "light", 2: "dark"}.get(row.get_selected(), "system")
        self._commit()

    def _on_lastfm_changed(self, _row: Gtk.Widget, _pspec: object) -> None:
        self._settings.lastfm.username = self._username_row.get_text()
        self._settings.lastfm.api_key = self._api_key_row.get_text()
        self._settings.lastfm.api_secret = self._api_secret_row.get_text()
        self._settings.lastfm.session_key = self._session_row.get_text()
        self._commit()

    def refresh_folders(self) -> None:
        """Refresh the managed folders section after external changes."""
        self._rebuild_folders()

    def _rebuild_folders(self) -> None:
        for row in self._folder_rows:
            self._folder_group.remove(row)
        self._folder_rows.clear()

        for root in self._settings.library_roots:
            row = Adw.ActionRow(title=root)
            remove_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            remove_button.connect("clicked", self._on_remove_clicked, root)
            row.add_suffix(remove_button)
            self._folder_group.add(row)
            self._folder_rows.append(row)

    def _on_remove_clicked(self, _button: Gtk.Button, root: str) -> None:
        self._on_remove_folder(root)
