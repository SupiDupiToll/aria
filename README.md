# Aria

Aria is a native Linux music player built with GTK4, libadwaita, PyGObject, GStreamer, SQLite, and Mutagen.

It is designed as a local-first desktop player with a modern GNOME-style interface, fast library browsing, synced lyrics, artwork support, playlists, queue management, and Last.fm integration.

## Features

- Native GTK4/libadwaita UI
- Recursive music library scanning with persistent SQLite indexing
- Live library updates through filesystem watching
- Library views for tracks, albums, artists, genres, folders, playlists, queue, Last.fm, and now playing
- Cover art in the library and throughout playback views
- Larger clickable synced lyrics with auto-centering on the current line
- Fullscreen lyrics mode with cover art, title, and artist/album header
- Queue editing, playlist import/export, and saved playlists
- GStreamer playback with seeking, volume control, replaygain, normalization, and output-device selection
- MPRIS support for desktop media controls and `playerctl`
- Last.fm connect flow, now playing updates, scrobbling, loved tracks, and dashboard panels
- Drag-and-drop support for files, folders, and playlist imports

## Current UX Highlights

- Clicking a synced lyric line jumps playback to that timestamp
- The current lyric line stays centered while the song progresses
- Now Playing stays usable on small windows and scrolls when space is limited
- Fullscreen lyrics can be opened with `l`

## Development Dependencies

Required runtime packages on Arch Linux:

- `python-gobject`
- `gtk4`
- `libadwaita`
- `gstreamer`
- `gst-plugins-base`
- `gst-plugins-good`
- `python-mutagen`
- `python-requests`

Useful optional tools:

- `pytest`

## Run Locally

```bash
PYTHONPATH=src python -m musicplayer
```

## Packaging Notes

- Python imports still use the internal module name `musicplayer`
- Desktop branding, app metadata, package metadata, and launch command are branded as `Aria`

## Last.fm Setup

1. Open Settings and enter your Last.fm API key and API secret.
2. Go to the Last.fm tab and click `Connect`.
3. Approve access in the browser.
4. Return to Aria and click `I Approved It`.

## Status

Aria already includes the core local-player workflow and most of the visible desktop features. The codebase is organized so playback, metadata, lyrics, Last.fm, playlists, MPRIS, and library management remain separated and easy to extend.
