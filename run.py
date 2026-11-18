#!/usr/bin/env python3
"""Start PaperParser.

Usage:
    python run.py                         # library in ./library, opens the browser
    python run.py --library D:\\Papers     # use another folder as the library
    python run.py --fake-tts              # demo beeps instead of Kokoro (UI development)
"""
from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from pathlib import Path

import uvicorn

from paperparser.config import Settings
from paperparser.server import create_app


def main() -> None:
    """Parse command-line options and run the web server."""
    parser = argparse.ArgumentParser(description="PaperParser - local paper library with read-along TTS.")
    parser.add_argument(
        "--library",
        default=os.environ.get("PAPERPARSER_LIBRARY", str(Path(__file__).parent.parent / "library")),
        help="Folder containing one sub-folder per project (default: ./library or $PAPERPARSER_LIBRARY).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: localhost only).")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--fake-tts", action="store_true", help="Use demo beeps instead of Kokoro.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab on start.")
    args = parser.parse_args()

    settings = Settings(library_dir=Path(args.library), host=args.host, port=args.port, fake_tts=args.fake_tts)
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print(f"PaperParser -> {url}\nLibrary     -> {settings.library_dir.resolve()}")
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
