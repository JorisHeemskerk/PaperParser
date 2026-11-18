"""Runtime settings for PaperParser."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"


@dataclass(frozen=True)
class Settings:
    """Immutable application settings.

    Attributes:
        library_dir: Root directory; every sub-folder is a project holding PDFs.
        host: Interface the web server binds to (localhost only by default).
        port: TCP port of the web server.
        fake_tts: Use the built-in beep engine instead of Kokoro (UI development / no GPU).
        lead_seconds: How many seconds of audio the server may synthesise ahead of playback.
    """

    library_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    fake_tts: bool = False
    lead_seconds: float = 25.0
