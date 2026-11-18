# PaperParser

A local, minimalist, Zotero-like paper library with a built-in PDF reader that
**reads papers aloud and highlights every word as it is spoken** (Kokoro TTS,
runs on your GPU, nothing leaves your machine).

## Quick start (Windows / PowerShell)

```powershell
python -m venv venv
venv\Scripts\activate

# 1. CUDA build of PyTorch FIRST (pick the command for your CUDA version at pytorch.org)
pip install torch --index-url https://download.pytorch.org/whl/cu121

# 2. everything else
pip install -r requirements.txt

python run.py
```

The browser opens at <http://localhost:8765>. The first start downloads the
Kokoro model (~330 MB) from Hugging Face; the sidebar shows *loading model…* →
*ready*. If Kokoro/PyTorch are not installed the app still runs with a **demo
beep engine** (same highlighting pipeline, no speech) and tells you so in the
sidebar.

> Kokoro needs `espeak-ng` for phonemisation. The `misaki[en]` dependency
> normally bundles it; if you get an espeak error, install
> [espeak-ng](https://github.com/espeak-ng/espeak-ng/releases) and restart.

Options: `python run.py --library "D:\Papers"` (or `$env:PAPERPARSER_LIBRARY`),
`--port 9000`, `--no-browser`, `--fake-tts`.

## Library layout

```
library/                    <- the "input directory" (default ./library)
  My Thesis/                <- one folder per project
    metadata.json           <- notes, tags, colours, groups, reading position
    attention-is-all-you-need.pdf
    bert.pdf
```

Drop PDFs into a project folder yourself (OneDrive-friendly: the app rescans
every 10 s and on window focus) or drag them onto the window / press *Upload*.
`metadata.json` is written atomically; a corrupt file is backed up as
`metadata.json.<timestamp>.bak` instead of being overwritten.

```jsonc
{
  "version": 1, "color": "#3b82f6", "description": "",
  "papers": {
    "bert.pdf": {
      "title": null, "notes": "free text…", "tags": ["nlp"], "color": "#ef4444",
      "group": "Background", "status": "reading", "favorite": true,
      "reading_pos": 1432, "added": "2026-11-18T12:10:30+00:00"
    }
  }
}
```

## Using it

| Action | How |
|---|---|
| Open a paper | click it in the list |
| Read aloud | ▶ / **Space**; **double-click any word** to start from there |
| Previous / next sentence | ⏮ ⏭ / **← →** |
| Voice, speed (0.5–2×) | player bar; changing them restarts seamlessly from the current word |
| Skip refs / citations / headers | **Refs**, **Cites**, **Headers** chips (citations = `[12]`, `(Smith et al., 2020)`) |
| Keep word in view | **Follow** chip |
| Notes, tags, colour, group, status, favourite | **Notes** button (right panel, autosaves) |

Reading position is saved per paper and restored when you reopen it.

## How the live highlighting works

1. **PyMuPDF** extracts every word with a page-normalised box, in reading order
   (two-column aware), flags running headers/footers, the reference list and
   inline citations, and joins words hyphenated across lines.
2. Text is cut into sentence-sized segments and sent to **Kokoro**, which
   returns audio plus a timestamp per token. Tokens are mapped back onto PDF
   words by character offset (`paperparser/tts.py::align_words`).
3. The server streams `[JSON word timings][int16 PCM]` frames over a WebSocket
   with flow control (it stays ~25 s ahead of playback).
4. The browser schedules the audio with the Web Audio API and highlights words
   from `AudioContext.currentTime`, so pausing/seeking/underruns never desync.
5. **PDF.js** (vendored in `static/vendor`, works offline) renders pages;
   highlights are percentage-positioned overlays, so they survive any zoom.

## Known limitations

- **Scanned PDFs** have no text layer: run `ocrmypdf in.pdf out.pdf` first.
- Heuristics (column order, header/reference detection) work well on typical
  LaTeX/journal PDFs; exotic layouts (sidebars, tables, equations) may read oddly.
- No text selection/search inside the viewer yet (canvas rendering only).
- Not tested on the real Kokoro model during development (no model download in
  the build sandbox): the alignment logic is unit-tested against Kokoro's
  documented token API and the whole UI/streaming path is tested end-to-end with
  the demo engine. If highlights drift on real speech, `align_words` is the
  place to look.

## Development

```powershell
pip install pytest httpx
pytest                      # library, extraction, alignment, REST + WebSocket tests
python run.py --fake-tts    # UI work without a GPU
```

```
paperparser/
  config.py    settings            library.py   projects/papers/metadata.json
  pdftext.py   words, flags, segments   tts.py   Kokoro + demo engines, alignment
  server.py    REST + /ws/read     static/      index.html, app.js, viewer.js, player.js, api.js, style.css
```

## Legacy: PDF/EPUB → `.m4b` audiobook

`pdf_to_audiobook.py` still works as before
(`python pdf_to_audiobook.py book.epub --voice af_bella`) and needs `ffmpeg` on
your PATH.

## Ideas for next

Text selection + search in the viewer, send a selected quote to the notes,
sentence-level tinting, BibTeX/DOI metadata lookup, export the read-aloud audio
of a paper as `.m4b`, summaries via a local LLM.
