"""Application bootstrap."""

from musicplayer.application import MusicApplication


def main() -> int:
    """Run the GTK application."""
    app = MusicApplication()
    return app.run([])
