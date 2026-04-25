"""Last.fm integration with offline queue persistence."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests

from musicplayer.constants import CACHE_HOME
from musicplayer.models import LastFMPanelData, LastFMProfile


@dataclass(slots=True)
class ScrobbleEvent:
    """Queued Last.fm scrobble payload."""

    artist: str
    track: str
    album: str
    album_artist: str
    duration: int
    timestamp: int


class LastFMService:
    """Small Last.fm client for scrobbling and dashboard reads."""

    API_ROOT = "https://ws.audioscrobbler.com/2.0/"
    AUTH_ROOT = "https://www.last.fm/api/auth/"

    def __init__(self, queue_path: Path | None = None) -> None:
        self.profile = LastFMProfile()
        self.queue_path = queue_path or (CACHE_HOME / "lastfm-scrobbles.json")
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        self.offline_queue = self._load_queue()

    def update_profile(self, profile: LastFMProfile) -> None:
        """Replace the active Last.fm profile."""
        self.profile = profile

    def configured(self) -> bool:
        """Return whether authenticated submission is available."""
        return bool(self.profile.api_key and self.profile.api_secret and self.profile.session_key)

    def build_auth_url(self) -> str:
        """Return the Last.fm web auth URL."""
        if not self.profile.api_key:
            return ""
        return f"{self.AUTH_ROOT}?{urlencode({'api_key': self.profile.api_key})}"

    def create_request_token(self) -> str:
        """Fetch a desktop-auth request token."""
        payload = self._signed_payload({"method": "auth.getToken"}, include_session=False)
        response = requests.post(self.API_ROOT, data=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        token = data.get("token", "")
        if not token:
            raise RuntimeError("Last.fm did not return an auth token.")
        return token

    def build_desktop_auth_url(self, token: str) -> str:
        """Return the desktop auth URL for an already issued token."""
        if not self.profile.api_key or not token:
            return ""
        return f"{self.AUTH_ROOT}?{urlencode({'api_key': self.profile.api_key, 'token': token})}"

    def create_session(self, token: str) -> dict:
        """Exchange a token for a session key."""
        payload = self._signed_payload({"method": "auth.getSession", "token": token}, include_session=False)
        response = requests.post(self.API_ROOT, data=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        session = data.get("session", {})
        self.profile.username = session.get("name", self.profile.username)
        self.profile.session_key = session.get("key", self.profile.session_key)
        return data

    def now_playing(self, artist: str, track: str, album: str, duration: int) -> None:
        """Send the current playing state."""
        if not self.configured():
            return
        payload = self._signed_payload(
            {
                "method": "track.updateNowPlaying",
                "artist": artist,
                "track": track,
                "album": album,
                "duration": str(duration),
            }
        )
        requests.post(self.API_ROOT, data=payload, timeout=15).raise_for_status()

    def love(self, artist: str, track: str) -> None:
        """Love a track."""
        self._simple_signed_call("track.love", artist, track)

    def unlove(self, artist: str, track: str) -> None:
        """Unlove a track."""
        self._simple_signed_call("track.unlove", artist, track)

    def queue_scrobble(
        self,
        artist: str,
        track: str,
        album: str,
        album_artist: str,
        duration: int,
        timestamp: int | None = None,
    ) -> None:
        """Queue a scrobble locally for later submission."""
        self.offline_queue.append(
            ScrobbleEvent(
                artist=artist,
                track=track,
                album=album,
                album_artist=album_artist,
                duration=duration,
                timestamp=timestamp or int(time.time()),
            )
        )
        self._save_queue()

    def flush_queue(self) -> int:
        """Submit all queued scrobbles."""
        if not self.configured() or not self.offline_queue:
            return 0
        submitted = 0
        pending = list(self.offline_queue)
        for event in pending:
            payload = self._signed_payload(
                {
                    "method": "track.scrobble",
                    "artist": event.artist,
                    "track": event.track,
                    "album": event.album,
                    "albumArtist": event.album_artist,
                    "duration": str(event.duration),
                    "timestamp": str(event.timestamp),
                }
            )
            try:
                requests.post(self.API_ROOT, data=payload, timeout=15).raise_for_status()
            except requests.RequestException:
                break
            self.offline_queue.pop(0)
            submitted += 1
        self._save_queue()
        return submitted

    def fetch_panel_data(self) -> LastFMPanelData:
        """Return recent scrobbles and top items for the configured user."""
        if not self.profile.api_key or not self.profile.username:
            return LastFMPanelData(recent=[], top_artists=[], top_albums=[])
        return LastFMPanelData(
            recent=self._public_call("user.getrecenttracks", limit="10").get("recenttracks", {}).get("track", []),
            top_artists=self._public_call("user.gettopartists", limit="8").get("topartists", {}).get("artist", []),
            top_albums=self._public_call("user.gettopalbums", limit="8").get("topalbums", {}).get("album", []),
        )

    def _public_call(self, method: str, **extra: str) -> dict:
        params = {
            "method": method,
            "format": "json",
            "api_key": self.profile.api_key,
            "user": self.profile.username,
        }
        params.update(extra)
        response = requests.get(self.API_ROOT, params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    def _simple_signed_call(self, method: str, artist: str, track: str) -> None:
        if not self.configured():
            return
        payload = self._signed_payload({"method": method, "artist": artist, "track": track})
        requests.post(self.API_ROOT, data=payload, timeout=15).raise_for_status()

    def _signed_payload(self, params: dict[str, str], include_session: bool = True) -> dict[str, str]:
        signed = dict(params)
        signed["api_key"] = self.profile.api_key
        if include_session and self.profile.session_key:
            signed["sk"] = self.profile.session_key
        signature_base = "".join(f"{key}{signed[key]}" for key in sorted(signed)) + self.profile.api_secret
        signed["api_sig"] = hashlib.md5(signature_base.encode("utf-8")).hexdigest()
        signed["format"] = "json"
        return signed

    def _load_queue(self) -> list[ScrobbleEvent]:
        if not self.queue_path.exists():
            return []
        data = json.loads(self.queue_path.read_text(encoding="utf-8"))
        return [ScrobbleEvent(**item) for item in data]

    def _save_queue(self) -> None:
        payload = [asdict(item) for item in self.offline_queue]
        self.queue_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
