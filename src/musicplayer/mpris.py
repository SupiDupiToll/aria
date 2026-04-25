"""Minimal MPRIS2 implementation using Gio D-Bus exports."""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")

from gi.repository import Gio, GLib

from musicplayer import APP_ID, APP_NAME
from musicplayer.playback.player import PlaybackEngine

INTROSPECTION_XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek">
      <arg type="x" name="Offset" direction="in"/>
    </method>
    <method name="SetPosition">
      <arg type="o" name="TrackId" direction="in"/>
      <arg type="x" name="Position" direction="in"/>
    </method>
    <method name="OpenUri">
      <arg type="s" name="Uri" direction="in"/>
    </method>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="read"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""


class MPRISService:
    """Export a basic MPRIS interface for media keys and playerctl."""

    def __init__(self, player: PlaybackEngine) -> None:
        self.player = player
        self.connection: Gio.DBusConnection | None = None
        self.registration_ids: list[int] = []
        self.owner_id = 0
        self.node_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        self.interfaces = {interface.name: interface for interface in self.node_info.interfaces}
        self.playback_status = "Stopped"
        self.metadata: dict[str, GLib.Variant] = {}
        self.position_us = 0

        self.player.connect("state-changed", self._on_state_changed)
        self.player.connect("track-changed", self._on_track_changed)
        self.player.connect("position-changed", self._on_position_changed)

    def start(self) -> None:
        """Acquire the MPRIS bus name and register objects."""
        self.owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            "org.mpris.MediaPlayer2.aria",
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            None,
            None,
        )

    def _on_bus_acquired(
        self,
        connection: Gio.DBusConnection,
        _name: str,
    ) -> None:
        self.connection = connection
        for interface in self.interfaces.values():
            registration_id = connection.register_object(
                "/org/mpris/MediaPlayer2",
                interface,
                self._handle_method_call,
                self._handle_get_property,
                self._handle_set_property,
            )
            self.registration_ids.append(registration_id)

    def _handle_method_call(
        self,
        connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
        *_args: object,
    ) -> None:
        if interface_name == "org.mpris.MediaPlayer2":
            if method_name == "Quit":
                application = Gio.Application.get_default()
                if application is not None:
                    application.quit()
            elif method_name == "Raise":
                application = Gio.Application.get_default()
                if application is not None and hasattr(application, "window") and application.window is not None:
                    application.window.present()
            invocation.return_value(None)
            return

        if method_name == "Next":
            self.player.next()
        elif method_name == "Previous":
            self.player.previous()
        elif method_name == "Pause":
            self.player.pause()
        elif method_name == "PlayPause":
            self.player.toggle()
        elif method_name == "Stop":
            self.player.stop()
        elif method_name == "Play":
            self.player.play()
        elif method_name == "Seek":
            offset = parameters.unpack()[0]
            self.player.seek(max(0.0, self.position_us / 1_000_000 + offset / 1_000_000))
        elif method_name == "SetPosition":
            _track_id, position = parameters.unpack()
            self.player.seek(max(0.0, position / 1_000_000))
        elif method_name == "OpenUri":
            uri = parameters.unpack()[0]
            if uri.startswith("file://"):
                self.player.playbin.set_property("uri", uri)
                self.player.play()
        invocation.return_value(None)

    def _handle_get_property(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        interface_name: str,
        property_name: str,
        *_args: object,
    ) -> GLib.Variant | None:
        if interface_name == "org.mpris.MediaPlayer2":
            values = {
                "CanQuit": GLib.Variant("b", True),
                "CanRaise": GLib.Variant("b", True),
                "HasTrackList": GLib.Variant("b", False),
                "Identity": GLib.Variant("s", APP_NAME),
                "SupportedUriSchemes": GLib.Variant("as", ["file"]),
                "SupportedMimeTypes": GLib.Variant(
                    "as",
                    ["audio/mpeg", "audio/flac", "audio/ogg", "audio/x-wav", "audio/mp4"],
                ),
            }
            return values.get(property_name)

        values = {
            "PlaybackStatus": GLib.Variant("s", self.playback_status),
            "LoopStatus": GLib.Variant("s", self._loop_status()),
            "Rate": GLib.Variant("d", 1.0),
            "Shuffle": GLib.Variant("b", self.player.mode == "shuffle"),
            "Metadata": GLib.Variant("a{sv}", self.metadata),
            "Volume": GLib.Variant("d", float(self.player.settings.playback.volume)),
            "Position": GLib.Variant("x", int(self.position_us)),
            "MinimumRate": GLib.Variant("d", 1.0),
            "MaximumRate": GLib.Variant("d", 1.0),
            "CanGoNext": GLib.Variant("b", True),
            "CanGoPrevious": GLib.Variant("b", True),
            "CanPlay": GLib.Variant("b", True),
            "CanPause": GLib.Variant("b", True),
            "CanSeek": GLib.Variant("b", True),
            "CanControl": GLib.Variant("b", True),
        }
        return values.get(property_name)

    def _handle_set_property(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        interface_name: str,
        property_name: str,
        value: GLib.Variant,
        *_args: object,
    ) -> bool:
        if interface_name != "org.mpris.MediaPlayer2.Player":
            return False
        if property_name == "Volume":
            self.player.set_volume(value.unpack())
            self._emit_properties_changed({"Volume": GLib.Variant("d", float(self.player.settings.playback.volume))})
            return True
        if property_name == "Shuffle":
            self.player.mode = "shuffle" if value.unpack() else "normal"
            self.player.settings.playback.mode = self.player.mode
            self._emit_properties_changed({"Shuffle": GLib.Variant("b", self.player.mode == "shuffle")})
            return True
        if property_name == "LoopStatus":
            unpacked = value.unpack()
            mode = {
                "None": "normal",
                "Track": "repeat-one",
                "Playlist": "repeat-all",
            }.get(unpacked, "normal")
            self.player.mode = mode
            self.player.settings.playback.mode = mode
            self._emit_properties_changed({"LoopStatus": GLib.Variant("s", self._loop_status())})
            return True
        return False

    def _on_state_changed(self, _player: PlaybackEngine, state: str) -> None:
        self.playback_status = {
            "playing": "Playing",
            "paused": "Paused",
            "stopped": "Stopped",
        }.get(state, "Stopped")
        self._emit_properties_changed({"PlaybackStatus": GLib.Variant("s", self.playback_status)})

    def _on_track_changed(self, _player: PlaybackEngine, entry: object) -> None:
        self.metadata = {
            "mpris:trackid": GLib.Variant("o", "/org/mpris/MediaPlayer2/track/current"),
            "xesam:title": GLib.Variant("s", entry.title),
            "xesam:artist": GLib.Variant("as", [entry.artist]),
            "xesam:album": GLib.Variant("s", entry.album),
            "mpris:length": GLib.Variant("x", int(entry.duration * 1_000_000)),
        }
        if entry.artwork_path:
            self.metadata["mpris:artUrl"] = GLib.Variant("s", GLib.filename_to_uri(entry.artwork_path, None))
        self._emit_properties_changed({"Metadata": GLib.Variant("a{sv}", self.metadata)})

    def _on_position_changed(self, _player: PlaybackEngine, position: float, _duration: float) -> None:
        self.position_us = int(position * 1_000_000)

    def _loop_status(self) -> str:
        if self.player.mode == "repeat-one":
            return "Track"
        if self.player.mode == "repeat-all":
            return "Playlist"
        return "None"

    def _emit_properties_changed(self, changed: dict[str, GLib.Variant]) -> None:
        if self.connection is None:
            return
        self.connection.emit_signal(
            None,
            "/org/mpris/MediaPlayer2",
            "org.freedesktop.DBus.Properties",
            "PropertiesChanged",
            GLib.Variant(
                "(sa{sv}as)",
                ("org.mpris.MediaPlayer2.Player", changed, []),
            ),
        )
