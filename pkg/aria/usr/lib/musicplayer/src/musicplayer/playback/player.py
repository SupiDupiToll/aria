"""GStreamer playback backend."""

from __future__ import annotations

import gi

gi.require_version("Gst", "1.0")

from gi.repository import GObject, Gst, GLib

from musicplayer.config import Settings
from musicplayer.models import QueueEntry
from musicplayer.playback.queue import PlayQueue

Gst.init(None)


class PlaybackEngine(GObject.Object):
    """Wrap playbin3 and expose player state to the UI."""

    __gsignals__ = {
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "position-changed": (GObject.SignalFlags.RUN_FIRST, None, (float, float)),
        "track-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "about-to-scrobble": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, queue: PlayQueue, settings: Settings) -> None:
        super().__init__()
        self.queue = queue
        self.settings = settings
        self.mode = settings.playback.mode
        self.playbin = Gst.ElementFactory.make("playbin3", "player")
        if self.playbin is None:
            raise RuntimeError("GStreamer playbin3 is not available")
        self._current_entry: QueueEntry | None = None
        self._gapless_transition = False
        self._scrobble_sent = False
        self._last_state = "stopped"
        self._fade_source_id = 0
        self._audio_filter = self._build_audio_filter()
        if self._audio_filter is not None:
            self.playbin.set_property("audio-filter", self._audio_filter)
        self.playbin.set_property("volume", 0.8)
        self._position_source = GLib.timeout_add(500, self._poll_position)
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        self.playbin.connect("about-to-finish", self._on_about_to_finish)
        self.queue.connect("current-changed", self._on_queue_changed)
        self.apply_settings(settings)

    def _on_queue_changed(self, _queue: PlayQueue, index: int) -> None:
        if index < 0:
            self.stop()
            return
        entry = self.queue.current()
        if entry is not None:
            self._set_uri(entry, reset_state=not self._gapless_transition)
            self._gapless_transition = False

    def _set_uri(self, entry: QueueEntry, reset_state: bool = True) -> None:
        if reset_state:
            self.playbin.set_state(Gst.State.NULL)
        self.playbin.set_property("uri", GLib.filename_to_uri(entry.path, None))
        self._current_entry = entry
        self._scrobble_sent = False
        self.emit("track-changed", entry)
        self._apply_crossfade_start()

    def play(self) -> None:
        self.playbin.set_state(Gst.State.PLAYING)
        self.emit("state-changed", "playing")
        self._last_state = "playing"

    def pause(self) -> None:
        self.playbin.set_state(Gst.State.PAUSED)
        self.emit("state-changed", "paused")
        self._last_state = "paused"

    def stop(self) -> None:
        self.playbin.set_state(Gst.State.NULL)
        self.emit("state-changed", "stopped")
        self._last_state = "stopped"

    def toggle(self) -> None:
        state = self.playbin.get_state(0).state
        if state == Gst.State.PLAYING:
            self.pause()
        else:
            self.play()

    def seek(self, seconds: float) -> None:
        self.playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            int(seconds * Gst.SECOND),
        )

    def next(self) -> None:
        next_index = self.queue.next_index(self.mode)
        if next_index >= 0:
            self.queue.set_current(next_index)
            if self._last_state != "playing":
                self.play()
        else:
            self.stop()

    def previous(self) -> None:
        previous_index = self.queue.previous_index()
        self.queue.set_current(previous_index)
        self.play()

    def set_volume(self, volume: float) -> None:
        self.playbin.set_property("volume", max(0.0, min(1.0, volume)))
        self.settings.playback.volume = max(0.0, min(1.0, volume))

    def apply_settings(self, settings: Settings) -> None:
        """Apply playback-related settings."""
        self.settings = settings
        self.mode = settings.playback.mode
        self.set_volume(settings.playback.volume)
        self._apply_output_device(settings.output_device_id)
        if self._audio_filter is not None:
            rgvolume = self._audio_filter.get_by_name("replaygain")
            if rgvolume is not None:
                rgvolume.set_property("album-mode", settings.replaygain_mode == "album")
                rgvolume.set_property("pre-amp", 0.0 if settings.replaygain_mode != "off" else 0.0)
            rglimiter = self._audio_filter.get_by_name("replaylimit")
            if rglimiter is not None:
                rglimiter.set_property("enabled", settings.normalize)

    def list_output_devices(self) -> list[tuple[str, str]]:
        """Return available audio sinks."""
        monitor = Gst.DeviceMonitor()
        monitor.add_filter("Audio/Sink", None)
        monitor.start()
        devices = []
        for device in monitor.get_devices():
            display_name = device.get_display_name()
            props = device.get_properties()
            device_id = ""
            if props is not None:
                device_id = props.get_string("device.id") or props.get_string("object.path") or display_name
            devices.append((device_id, display_name))
        monitor.stop()
        devices.sort(key=lambda item: item[1].lower())
        return devices

    def get_position(self) -> tuple[float, float]:
        success_position, position = self.playbin.query_position(Gst.Format.TIME)
        success_duration, duration = self.playbin.query_duration(Gst.Format.TIME)
        return (
            position / Gst.SECOND if success_position else 0.0,
            duration / Gst.SECOND if success_duration else 0.0,
        )

    def _poll_position(self) -> bool:
        position, duration = self.get_position()
        self.emit("position-changed", position, duration)
        if self._current_entry and duration > 0 and not self._scrobble_sent:
            threshold = min(max(duration * 0.5, 0.0), 240.0)
            if position >= threshold:
                self._scrobble_sent = True
                self.emit("about-to-scrobble", self._current_entry)
        return True

    def _on_bus_message(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        if message.type == Gst.MessageType.EOS:
            self.next()
        elif message.type == Gst.MessageType.ERROR:
            _error, debug = message.parse_error()
            print(f"GStreamer error: {debug}")

    def _on_about_to_finish(self, _playbin: Gst.Element) -> None:
        next_index = self.queue.next_index(self.mode)
        if next_index < 0:
            return
        entry = self.queue.entries[next_index]
        self._gapless_transition = True
        self.queue.set_current(next_index)
        self.playbin.set_property("uri", GLib.filename_to_uri(entry.path, None))

    def _apply_output_device(self, device_id: str) -> None:
        if not device_id:
            return
        sink = Gst.ElementFactory.make("pipewiresink", None) or Gst.ElementFactory.make("pulsesink", None)
        if sink is None:
            return
        sink_props = sink.list_properties()
        prop_names = {prop.name for prop in sink_props}
        if "device" in prop_names:
            sink.set_property("device", device_id)
        elif "target-object" in prop_names:
            sink.set_property("target-object", device_id)
        self.playbin.set_property("audio-sink", sink)

    def _apply_crossfade_start(self) -> None:
        if self._fade_source_id:
            GLib.source_remove(self._fade_source_id)
            self._fade_source_id = 0
        duration = max(0, self.settings.crossfade_seconds)
        target_volume = float(self.settings.playback.volume)
        if duration <= 0:
            self.playbin.set_property("volume", target_volume)
            return
        self.playbin.set_property("volume", 0.0)
        steps = max(1, duration * 10)
        increment = target_volume / steps

        def fade_step() -> bool:
            current = float(self.playbin.get_property("volume"))
            next_value = min(target_volume, current + increment)
            self.playbin.set_property("volume", next_value)
            if next_value >= target_volume:
                self._fade_source_id = 0
                return False
            return True

        self._fade_source_id = GLib.timeout_add(100, fade_step)

    def _build_audio_filter(self) -> Gst.Bin | None:
        rgvolume = Gst.ElementFactory.make("rgvolume", "replaygain")
        rglimiter = Gst.ElementFactory.make("rglimiter", "replaylimit")
        audioconvert = Gst.ElementFactory.make("audioconvert", "converter")
        if not (rgvolume and audioconvert):
            return None
        bin_ = Gst.Bin.new("musicplayer-audio-filter")
        bin_.add(rgvolume)
        bin_.add(audioconvert)
        if rglimiter is not None:
            bin_.add(rglimiter)
            rgvolume.link(rglimiter)
            rglimiter.link(audioconvert)
        else:
            rgvolume.link(audioconvert)
        sink_pad = rgvolume.get_static_pad("sink")
        src_pad = audioconvert.get_static_pad("src")
        if sink_pad is None or src_pad is None:
            return None
        bin_.add_pad(Gst.GhostPad.new("sink", sink_pad))
        bin_.add_pad(Gst.GhostPad.new("src", src_pad))
        return bin_
