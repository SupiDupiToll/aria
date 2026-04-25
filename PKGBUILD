pkgname=aria
pkgver=0.1.0
pkgrel=5
install=('aria.install')
pkgdesc="Aria, a native GTK4/libadwaita music player"
arch=('any')
url="https://example.org/aria"
license=('MIT')
depends=(
  'python'
  'python-gobject'
  'gtk4'
  'libadwaita'
  'gstreamer'
  'gst-plugins-base'
  'gst-plugins-good'
  'python-mutagen'
  'python-requests'
)
makedepends=('python-setuptools')
source=()
sha256sums=()

package() {
  install -Dm644 "$startdir/data/org.example.MusicPlayer.desktop.in" "$pkgdir/usr/share/applications/org.example.Aria.desktop"
  install -Dm644 "$startdir/data/org.example.MusicPlayer.metainfo.xml" "$pkgdir/usr/share/metainfo/org.example.Aria.metainfo.xml"
  install -Dm644 "$startdir/data/icons/hicolor/scalable/apps/org.example.MusicPlayer.svg" "$pkgdir/usr/share/icons/hicolor/scalable/apps/org.example.Aria.svg"
  install -d "$pkgdir/usr/lib/musicplayer"
  cp -r "$startdir/src" "$pkgdir/usr/lib/musicplayer/"
  install -Dm755 /dev/stdin "$pkgdir/usr/bin/aria" <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH=/usr/lib/musicplayer/src
exec /usr/bin/python -m musicplayer "$@"
EOF
}
