#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
APPDIR="${DIST_DIR}/Aria.AppDir"
OUTPUT_APPIMAGE="${DIST_DIR}/Aria-x86_64.AppImage"

LINUXDEPLOY="${LINUXDEPLOY:-/tmp/linuxdeploy.AppImage}"
APPIMAGETOOL="${APPIMAGETOOL:-/tmp/appimagetool.AppImage}"
RUNTIME_FILE="${RUNTIME_FILE:-/tmp/runtime-x86_64}"

PYTHON_BIN="/usr/bin/python3.14"
PYTHON_LIB_DIR="/usr/lib/python3.14"
PYTHON_SITE_PACKAGES="/usr/lib/python3.14/site-packages"
GI_TYPELIB_DIR="/usr/lib/girepository-1.0"
GIO_MODULE_DIR="/usr/lib/gio/modules"
GSTREAMER_PLUGIN_DIR="/usr/lib/gstreamer-1.0"
GLIB_SCHEMA_DIR="/usr/share/glib-2.0/schemas"
ICON_THEME_DIR="/usr/share/icons/hicolor"

need_file() {
    local path="$1"
    if [[ ! -e "${path}" ]]; then
        echo "Missing required file: ${path}" >&2
        exit 1
    fi
}

need_file "${LINUXDEPLOY}"
need_file "${APPIMAGETOOL}"
need_file "${RUNTIME_FILE}"
need_file "${PYTHON_BIN}"
need_file "${PYTHON_LIB_DIR}"
need_file "${PYTHON_SITE_PACKAGES}"
need_file "${GI_TYPELIB_DIR}"
need_file "${GIO_MODULE_DIR}"
need_file "${GSTREAMER_PLUGIN_DIR}"
need_file "${GLIB_SCHEMA_DIR}"

chmod +x "${LINUXDEPLOY}" "${APPIMAGETOOL}"

rm -rf "${APPDIR}"
mkdir -p \
    "${APPDIR}/usr/bin" \
    "${APPDIR}/usr/lib" \
    "${APPDIR}/usr/share/applications" \
    "${APPDIR}/usr/share/icons/hicolor/scalable/apps" \
    "${APPDIR}/usr/share/metainfo"

cp -a "${ROOT_DIR}/src" "${APPDIR}/usr/lib/musicplayer"
cp -a "${PYTHON_LIB_DIR}" "${APPDIR}/usr/lib/"
cp -a "${GI_TYPELIB_DIR}" "${APPDIR}/usr/lib/"
mkdir -p "${APPDIR}/usr/lib/gio"
cp -a "${GIO_MODULE_DIR}" "${APPDIR}/usr/lib/gio/"
cp -a "${GSTREAMER_PLUGIN_DIR}" "${APPDIR}/usr/lib/"
cp -a "${GLIB_SCHEMA_DIR}" "${APPDIR}/usr/share/glib-2.0"
cp -a "${ICON_THEME_DIR}/index.theme" "${APPDIR}/usr/share/icons/hicolor/"
cp -a "${PYTHON_BIN}" "${APPDIR}/usr/bin/python3"

cp "${ROOT_DIR}/data/org.example.MusicPlayer.desktop.in" \
    "${APPDIR}/usr/share/applications/org.example.Aria.desktop"
cp "${ROOT_DIR}/data/org.example.MusicPlayer.desktop.in" \
    "${APPDIR}/org.example.Aria.desktop"
cp "${ROOT_DIR}/data/org.example.MusicPlayer.metainfo.xml" \
    "${APPDIR}/usr/share/metainfo/org.example.Aria.appdata.xml"
cp "${ROOT_DIR}/data/icons/hicolor/scalable/apps/org.example.MusicPlayer.svg" \
    "${APPDIR}/usr/share/icons/hicolor/scalable/apps/org.example.Aria.svg"
cp "${ROOT_DIR}/data/icons/hicolor/scalable/apps/org.example.MusicPlayer.svg" \
    "${APPDIR}/org.example.Aria.svg"

find "${APPDIR}" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "${APPDIR}/usr/lib/python3.14" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
rm -rf "${APPDIR}/usr/lib/python3.14/test" "${APPDIR}/usr/lib/python3.14/idlelib"
rm -rf "${APPDIR}/usr/lib/python3.14/site-packages"
mkdir -p "${APPDIR}/usr/lib/python3.14/site-packages"

copy_python_dependency() {
    local name="$1"
    if [[ -d "${PYTHON_SITE_PACKAGES}/${name}" ]]; then
        cp -a "${PYTHON_SITE_PACKAGES}/${name}" "${APPDIR}/usr/lib/python3.14/site-packages/"
    elif [[ -f "${PYTHON_SITE_PACKAGES}/${name}" ]]; then
        cp -a "${PYTHON_SITE_PACKAGES}/${name}" "${APPDIR}/usr/lib/python3.14/site-packages/"
    else
        echo "Missing Python dependency in site-packages: ${name}" >&2
        exit 1
    fi
}

for dependency in \
    gi \
    requests \
    urllib3 \
    certifi \
    charset_normalizer \
    idna \
    mutagen
do
    copy_python_dependency "${dependency}"
done

cat > "${APPDIR}/usr/bin/aria" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
export PATH="${HERE}/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export PYTHONHOME="${HERE}"
export PYTHONPATH="${HERE}/lib/musicplayer/src:${HERE}/lib/python3.14/site-packages"
export GI_TYPELIB_PATH="${HERE}/lib/girepository-1.0"
export GIO_MODULE_DIR="${HERE}/lib/gio/modules"
export GSETTINGS_SCHEMA_DIR="${HERE}/share/glib-2.0/schemas"
export GST_PLUGIN_SYSTEM_PATH_1_0="${HERE}/lib/gstreamer-1.0"
export GST_PLUGIN_PATH_1_0="${HERE}/lib/gstreamer-1.0"
export XDG_DATA_DIRS="${HERE}/share${XDG_DATA_DIRS:+:${XDG_DATA_DIRS}}"
exec "${HERE}/bin/python3" -m musicplayer "$@"
EOF
chmod +x "${APPDIR}/usr/bin/aria"

cat > "${APPDIR}/AppRun" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
exec "${HERE}/usr/bin/aria" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

linuxdeploy_args=(
    --appimage-extract-and-run
    --appdir "${APPDIR}"
    --desktop-file "${APPDIR}/usr/share/applications/org.example.Aria.desktop"
    --icon-file "${APPDIR}/usr/share/icons/hicolor/scalable/apps/org.example.Aria.svg"
    --executable "${APPDIR}/usr/bin/python3"
    --executable "${APPDIR}/usr/bin/aria"
)

while IFS= read -r -d '' file; do
    linuxdeploy_args+=(--library "${file}")
done < <(find \
    "${APPDIR}/usr/lib/python3.14/site-packages" \
    "${APPDIR}/usr/lib/gio/modules" \
    "${APPDIR}/usr/lib/gstreamer-1.0" \
    -type f \( -name '*.so' -o -name '*.so.*' \) -print0)

"${LINUXDEPLOY}" "${linuxdeploy_args[@]}"

ARCH=x86_64 "${APPIMAGETOOL}" --appimage-extract-and-run \
    --runtime-file "${RUNTIME_FILE}" \
    "${APPDIR}" \
    "${OUTPUT_APPIMAGE}"

echo "Built ${OUTPUT_APPIMAGE}"
