"""Playlist import and export helpers."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree


def import_playlist(path: str) -> list[str]:
    """Parse a simple M3U/M3U8/PLS/XSPF playlist into file paths."""
    source = Path(path)
    suffix = source.suffix.lower()
    text = source.read_text(encoding="utf-8", errors="ignore")

    if suffix in {".m3u", ".m3u8"}:
        return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]

    if suffix == ".pls":
        return [
            line.split("=", 1)[1].strip()
            for line in text.splitlines()
            if line.startswith("File")
        ]

    if suffix == ".xspf":
        root = ElementTree.fromstring(text)
        ns = {"x": "http://xspf.org/ns/0/"}
        paths: list[str] = []
        for location in root.findall(".//x:track/x:location", ns):
            value = location.text or ""
            if value.startswith("file://"):
                paths.append(value[7:])
        return paths

    return []


def export_m3u(path: str, tracks: list[str]) -> None:
    """Write queue paths as UTF-8 M3U."""
    payload = "#EXTM3U\n" + "\n".join(tracks) + "\n"
    Path(path).write_text(payload, encoding="utf-8")


def export_pls(path: str, tracks: list[str]) -> None:
    """Write a PLS playlist."""
    lines = ["[playlist]"]
    for index, track in enumerate(tracks, start=1):
        lines.append(f"File{index}={track}")
    lines.append(f"NumberOfEntries={len(tracks)}")
    lines.append("Version=2")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_xspf(path: str, tracks: list[str]) -> None:
    """Write a basic XSPF playlist."""
    playlist = ElementTree.Element("playlist", version="1", xmlns="http://xspf.org/ns/0/")
    track_list = ElementTree.SubElement(playlist, "trackList")
    for track in tracks:
        entry = ElementTree.SubElement(track_list, "track")
        location = ElementTree.SubElement(entry, "location")
        location.text = "file://" + quote(track)
    Path(path).write_text(
        ElementTree.tostring(playlist, encoding="unicode", xml_declaration=True),
        encoding="utf-8",
    )
