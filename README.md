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

## Building the AppImage

To build the AppImage locally, follow these steps:

1.  **Install System Dependencies:**
    Ensure you have the necessary development libraries and Python packages installed. On Debian/Ubuntu-based systems, you might need:
    ```bash
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends 
      libgtk-4-dev 
      libadwaita-1-dev 
      python3-gi 
      python3-requests 
      python3-mutagen 
      python3-certifi 
      python3-idna 
      python3-charset-normalizer 
      gstreamer1.0-plugins-base 
      gstreamer1.0-plugins-good 
      gstreamer1.0-tools 
      gstreamer1.0-alsa 
      gstreamer1.0-pulseaudio 
      gstreamer1.0-gtk4 
      libgirepository1.0-dev 
      pkg-config 
      python3-setuptools # For potential build-time dependencies
    ```
    Note: Adjust Python and GStreamer package names as per your distribution.

2.  **Download AppImage Tools:**
    Download `linuxdeploy`, `appimagetool`, and `runtime` to `/tmp/` and make them executable:
    ```bash
    wget -O /tmp/linuxdeploy.AppImage https://github.com/linuxdeploy/linuxdeploy/releases/latest/download/linuxdeploy-x86_64.AppImage
    wget -O /tmp/appimagetool.AppImage https://github.com/AppImage/appimagetool/releases/latest/download/appimagetool-x86_64.AppImage
    wget -O /tmp/runtime-x86_64 https://github.com/AppImage/type2-runtime/releases/latest/download/runtime-x86_64
    chmod +x /tmp/linuxdeploy.AppImage /tmp/appimagetool.AppImage /tmp/runtime-x86_64
    ```

3.  **Execute Build Steps Manually (Recommended):**
    Due to potential pathing issues with automated scripts, it's recommended to run the build steps manually from the project root directory.

    ```bash
    set -euo pipefail

    ROOT_DIR="$(pwd)"
    DIST_DIR="${ROOT_DIR}/dist"
    APPDIR="${DIST_DIR}/Aria.AppDir"
    OUTPUT_APPIMAGE="${DIST_DIR}/Aria-x86_64.AppImage"

    LINUXDEPLOY="/tmp/linuxdeploy.AppImage"
    APPIMAGETOOL="/tmp/appimagetool.AppImage"
    RUNTIME_FILE="/tmp/runtime-x86_64"

    # Dynamically determine Python paths (adjust if needed for your system)
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PYTHON_BIN="/usr/bin/python${PYTHON_VERSION}"
    PYTHON_LIB_DIR="/usr/lib/python${PYTHON_VERSION}"
    PYTHON_SITE_PACKAGES="/usr/lib/python${PYTHON_VERSION}/dist-packages" # Common on Ubuntu/Debian

    # Determine architecture-specific paths for GObject introspection, GIO, and GStreamer
    ARCH_TRIPLE=$(dpkg-architecture -q DEB_HOST_MULTIARCH || echo "x86_64-linux-gnu") # Fallback for non-Debian
    GI_TYPELIB_DIR="/usr/lib/${ARCH_TRIPLE}/girepository-1.0"
    GIO_MODULE_DIR="/usr/lib/${ARCH_TRIPLE}/gio/modules"
    GSTREAMER_PLUGIN_DIR="/usr/lib/${ARCH_TRIPLE}/gstreamer-1.0"

    GLIB_SCHEMA_DIR="/usr/share/glib-2.0/schemas"
    ICON_THEME_DIR="/usr/share/icons/hicolor"

    echo "Using Python Version: ${PYTHON_VERSION}"
    echo "PYTHON_BIN: ${PYTHON_BIN}"
    echo "PYTHON_LIB_DIR: ${PYTHON_LIB_DIR}"
    echo "PYTHON_SITE_PACKAGES: ${PYTHON_SITE_PACKAGES}"
    echo "GI_TYPELIB_DIR: ${GI_TYPELIB_DIR}"
    echo "GIO_MODULE_DIR: ${GIO_MODULE_DIR}"
    echo "GSTREAMER_PLUGIN_DIR: ${GSTREAMER_PLUGIN_DIR}"
    echo "ARCH_TRIPLE: ${ARCH_TRIPLE}"

    # Create AppDir structure
    rm -rf "${APPDIR}"
    mkdir -p 
        "${APPDIR}/usr/bin" 
        "${APPDIR}/usr/lib" 
        "${APPDIR}/usr/share/applications" 
        "${APPDIR}/usr/share/icons/hicolor/scalable/apps" 
        "${APPDIR}/usr/share/metainfo"

    # Copy application files and libraries
    cp -a "${ROOT_DIR}/src" "${APPDIR}/usr/lib/musicplayer"
    cp -a "${PYTHON_LIB_DIR}" "${APPDIR}/usr/lib/"
    # Remove problematic Python config directory (e.g., config-3.11-x86_64-linux-gnu)
    rm -rf "${APPDIR}/usr/lib/python${PYTHON_VERSION}/config-${PYTHON_VERSION/./-}-x86_64-linux-gnu"
    
    cp -a "${GI_TYPELIB_DIR}" "${APPDIR}/usr/lib/"
    mkdir -p "${APPDIR}/usr/lib/gio"
    cp -a "${GIO_MODULE_DIR}" "${APPDIR}/usr/lib/gio/"
    cp -a "${GSTREAMER_PLUGIN_DIR}" "${APPDIR}/usr/lib/"
    cp -a "${GLIB_SCHEMA_DIR}" "${APPDIR}/usr/share/glib-2.0"
    cp -a "${ICON_THEME_DIR}/index.theme" "${APPDIR}/usr/share/icons/hicolor/"
    cp -a "${PYTHON_BIN}" "${APPDIR}/usr/bin/python3"

    # Copy desktop integration files
    cp "${ROOT_DIR}/data/org.example.MusicPlayer.desktop.in" 
        "${APPDIR}/usr/share/applications/org.example.Aria.desktop"
    cp "${ROOT_DIR}/data/org.example.MusicPlayer.desktop.in" 
        "${APPDIR}/org.example.Aria.desktop"
    cp "${ROOT_DIR}/data/org.example.MusicPlayer.metainfo.xml" 
        "${APPDIR}/usr/share/metainfo/org.example.Aria.appdata.xml"
    cp "${ROOT_DIR}/data/icons/hicolor/scalable/apps/org.example.MusicPlayer.svg" 
        "${APPDIR}/usr/share/icons/hicolor/scalable/apps/org.example.Aria.svg"
    cp "${ROOT_DIR}/data/icons/hicolor/scalable/apps/org.example.MusicPlayer.svg" 
        "${APPDIR}/org.example.Aria.svg"

    # Clean up Python cache and unnecessary files
    find "${APPDIR}" -type d -name '__pycache__' -prune -exec rm -rf {} +
    find "${APPDIR}/usr/lib/python${PYTHON_VERSION}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
    rm -rf "${APPDIR}/usr/lib/python${PYTHON_VERSION}/test" "${APPDIR}/usr/lib/python${PYTHON_VERSION}/idlelib"
    rm -rf "${APPDIR}/usr/lib/python${PYTHON_VERSION}/site-packages"
    mkdir -p "${APPDIR}/usr/lib/python${PYTHON_VERSION}/site-packages"

    # Function to copy Python dependencies
    copy_python_dependency() {
        local name="$1"
        if [[ -d "${PYTHON_SITE_PACKAGES}/${name}" ]]; then
            cp -a "${PYTHON_SITE_PACKAGES}/${name}" "${APPDIR}/usr/lib/python${PYTHON_VERSION}/site-packages/"
        elif [[ -f "${PYTHON_SITE_PACKAGES}/${name}" ]]; then
            cp -a "${PYTHON_SITE_PACKAGES}/${name}" "${APPDIR}/usr/lib/python${PYTHON_VERSION}/site-packages/"
        else
            echo "Missing Python dependency in site-packages: ${name}" >&2
            exit 1
        fi
    }

    # Copy Python site-packages dependencies
    for dependency in gi requests urllib3 certifi charset_normalizer idna mutagen; do
        copy_python_dependency "${dependency}"
    done

    # Create the 'aria' launcher script
    cat > "${APPDIR}/usr/bin/aria" <<EOF_LAUNCHER
#!/usr/bin/env bash
set -euo pipefail
HERE="\$(cd "\$(dirname "\$(readlink -f "\${BASH_SOURCE[0]}")")/.." && pwd)"
export PATH="\${HERE}/bin:\${PATH}"
export LD_LIBRARY_PATH="\${HERE}/lib\${LD_LIBRARY_PATH:+:\${LD_LIBRARY_PATH}}"
export PYTHONHOME="\${HERE}"
export PYTHONPATH="\${HERE}/lib/musicplayer/src:\${HERE}/lib/python${PYTHON_VERSION}/site-packages"
export GI_TYPELIB_PATH="\${HERE}/lib/girepository-1.0"
export GIO_MODULE_DIR="\${HERE}/lib/gio/modules"
export GSETTINGS_SCHEMA_DIR="\${HERE}/share/glib-2.0/schemas"
export GST_PLUGIN_SYSTEM_PATH_1_0="\${HERE}/lib/gstreamer-1.0"
export GST_PLUGIN_PATH_1_0="\${HERE}/lib/gstreamer-1.0"
export XDG_DATA_DIRS="\${HERE}/share\${XDG_DATA_DIRS:+:\${XDG_DATA_DIRS}}"
exec "\${HERE}/bin/python3" -m musicplayer "\$@"
EOF_LAUNCHER
    chmod +x "${APPDIR}/usr/bin/aria"

    # Create the AppRun script
    cat > "${APPDIR}/AppRun" <<EOF_APPRUN
#!/usr/bin/env bash
set -euo pipefail
HERE="\$(cd "\$(dirname "\$(readlink -f "\${BASH_SOURCE[0]}")")" && pwd)"
exec "\${HERE}/usr/bin/aria" "\$@"
EOF_APPRUN
    chmod +x "${APPDIR}/AppRun"

    # Prepare linuxdeploy arguments
    linuxdeploy_args=(
        --appimage-extract-and-run
        --appdir "${APPDIR}"
        --desktop-file "${APPDIR}/usr/share/applications/org.example.Aria.desktop"
        --icon-file "${APPDIR}/usr/share/icons/hicolor/scalable/apps/org.example.Aria.svg"
        --executable "${APPDIR}/usr/bin/python3"
        --executable "${APPDIR}/usr/bin/aria"
    )

    # Collect libraries for linuxdeploy
    library_files=()
    while IFS= read -r -d '' file; do
        library_files+=(--library "${file}")
    done < <(find 
        "${APPDIR}/usr/lib/python${PYTHON_VERSION}/site-packages" 
        "${APPDIR}/usr/lib/gio/modules" 
        "${APPDIR}/usr/lib/gstreamer-1.0" 
        -type f \( -name '*.so' -o -name '*.so.*' \) -print0)

    # Run linuxdeploy
    "${LINUXDEPLOY}" "${linuxdeploy_args[@]}" "${library_files[@]}"

    # Build final AppImage
    ARCH=x86_64 "${APPIMAGETOOL}" --appimage-extract-and-run 
        --runtime-file "${RUNTIME_FILE}" 
        "${APPDIR}" 
        "${OUTPUT_APPIMAGE}"

    echo "Built AppImage: ${OUTPUT_APPIMAGE}"
    ```
