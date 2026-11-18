"""FastAPI application: library REST API, PDF serving and the read-aloud WebSocket."""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import threading
from contextlib import asynccontextmanager
from typing import Any, Literal

import numpy as np
from fastapi import FastAPI, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import STATIC_DIR, Settings
from .library import Library, LibraryError
from .pdftext import get_document, iter_segments, skip_mask
from .tts import DEFAULT_VOICE, AudioChunk, TTSEngine, create_engine, stream_segments

log = logging.getLogger("paperparser.server")


class ProjectCreate(BaseModel):
    """Body for creating a project."""

    name: str
    color: str | None = None


class ProjectPatch(BaseModel):
    """Body for updating a project (only sent fields change)."""

    color: str | None = None
    description: str | None = None


class PaperPatch(BaseModel):
    """Body for updating a paper's metadata (only sent fields change)."""

    title: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    color: str | None = None
    group: str | None = None
    status: Literal["unread", "reading", "read"] | None = None
    favorite: bool | None = None
    reading_pos: int | None = Field(default=None, ge=0)


class _Playback:
    """Per-stream bookkeeping used for flow control.

    Attributes:
        sent: Seconds of audio sent to the client so far.
        played: Seconds of audio the client reports as played.
    """

    def __init__(self) -> None:
        self.sent = 0.0
        self.played = 0.0


def _pcm16(chunk: AudioChunk) -> bytes:
    """Convert float audio to little-endian int16 PCM bytes.

    Args:
        chunk: Audio chunk with float32 samples in ``[-1, 1]``.

    Returns:
        Raw PCM bytes.
    """
    return (np.clip(chunk.samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def _next_or_none(it: Any) -> Any:
    """Advance an iterator, returning None at exhaustion (for use in a thread).

    Args:
        it: Any iterator.
    """
    return next(it, None)


def create_app(settings: Settings) -> FastAPI:
    """Build the PaperParser FastAPI app.

    Args:
        settings: Runtime settings (library directory, TTS options, ...).

    Returns:
        A configured :class:`fastapi.FastAPI` instance.
    """
    # Browsers reject ES-module scripts with a wrong MIME type, and on Windows
    # Python takes MIME types from the registry, which is often wrong for .js/.mjs.
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/javascript", ".mjs")

    library = Library(settings.library_dir)
    engine: TTSEngine = create_engine(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        threading.Thread(target=engine.warm_up, name="tts-warmup", daemon=True).start()
        yield

    app = FastAPI(title="PaperParser", lifespan=lifespan)
    app.state.library, app.state.engine = library, engine

    @app.exception_handler(LibraryError)
    async def _library_error(_: Request, exc: LibraryError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.middleware("http")
    async def _no_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # ------------------------------------------------------------------ meta
    @app.get("/api/status")
    async def status() -> dict:
        """Report engine state, device, hint and library location."""
        return {
            "engine": engine.name,
            "state": engine.state,
            "error": engine.error,
            "note": engine.note,
            "device": engine.device,
            "library": str(library.root),
            "default_voice": DEFAULT_VOICE,
        }

    @app.get("/api/voices")
    async def voices() -> list[dict]:
        """List the voice presets of the active engine."""
        return [{"id": v.id, "name": v.name, "group": v.group} for v in engine.voices()]

    # -------------------------------------------------------------- projects
    @app.get("/api/projects")
    async def list_projects() -> list[dict]:
        """List all projects."""
        return await run_in_threadpool(library.list_projects)

    @app.post("/api/projects", status_code=201)
    async def create_project(body: ProjectCreate) -> dict:
        """Create a project folder."""
        return await run_in_threadpool(library.create_project, body.name, body.color)

    @app.patch("/api/projects/{project}")
    async def patch_project(project: str, body: ProjectPatch) -> dict:
        """Update a project's colour/description."""
        return await run_in_threadpool(library.update_project, project, body.model_dump(exclude_unset=True))

    @app.get("/api/projects/{project}")
    async def get_project(project: str) -> dict:
        """Return a project with all its papers (rescans the folder each time)."""
        return await run_in_threadpool(library.get_project, project)

    # ---------------------------------------------------------------- papers
    @app.post("/api/projects/{project}/papers", status_code=201)
    async def upload_papers(project: str, files: list[UploadFile] = File(...)) -> dict:
        """Upload one or more PDFs; returns the stored papers and per-file errors."""
        added, errors = [], []
        for f in files:
            try:
                added.append(await run_in_threadpool(library.add_paper, project, f.filename or "", f.file))
            except LibraryError as exc:
                if exc.status_code == 404:
                    raise
                errors.append({"filename": f.filename, "detail": str(exc)})
        return {"added": added, "errors": errors}

    @app.patch("/api/projects/{project}/papers/{filename}")
    async def patch_paper(project: str, filename: str, body: PaperPatch) -> dict:
        """Update a paper's notes, tags, colour, group, status, ..."""
        return await run_in_threadpool(library.update_paper, project, filename, body.model_dump(exclude_unset=True))

    @app.get("/api/projects/{project}/papers/{filename}/pdf")
    async def paper_pdf(project: str, filename: str) -> FileResponse:
        """Serve the PDF file."""
        path = await run_in_threadpool(library.paper_path, project, filename)
        return FileResponse(path, media_type="application/pdf")

    @app.get("/api/projects/{project}/papers/{filename}/words")
    async def paper_words(project: str, filename: str) -> dict:
        """Return word boxes/flags for highlighting and click-to-read."""
        path = await run_in_threadpool(library.paper_path, project, filename)
        doc = await run_in_threadpool(get_document, path)
        return doc.to_wire()

    # ------------------------------------------------------------ read aloud
    async def stream_reading(ws: WebSocket, req: dict, state: _Playback) -> None:
        """Synthesise from a start word and push audio+timing frames to the client.

        Frame protocol: a JSON ``chunk`` message (id, sample_rate, duration,
        words=[[index,start,end],...]) immediately followed by one binary
        frame of int16 PCM. A final ``end`` message marks completion.

        Args:
            ws: Accepted WebSocket.
            req: The client's ``start`` message.
            state: Flow-control state shared with the receive loop.
        """
        loop = asyncio.get_running_loop()
        gen = None
        try:
            path = await run_in_threadpool(library.paper_path, req.get("project", ""), req.get("file", ""))
            doc = await run_in_threadpool(get_document, path)
            skip = req.get("skip") or {}
            mask = skip_mask(skip.get("references", True), skip.get("citations", True), skip.get("headers", True))
            voice = req.get("voice") if req.get("voice") in {v.id for v in engine.voices()} else DEFAULT_VOICE
            speed = min(max(float(req.get("speed", 1.0)), 0.5), 3.5)
            if engine.state != "ready":
                await ws.send_json({"type": "status", "message": "Loading voice model…"})
            gen = stream_segments(engine, iter_segments(doc, int(req.get("start_word", 0)), mask), voice, speed)
            chunk_id = 0
            while True:
                while state.sent - state.played > settings.lead_seconds:
                    await asyncio.sleep(0.15)
                chunk = await loop.run_in_executor(None, _next_or_none, gen)
                if chunk is None:
                    break
                await ws.send_json(
                    {
                        "type": "chunk",
                        "id": chunk_id,
                        "sample_rate": chunk.sample_rate,
                        "duration": round(chunk.duration, 4),
                        "words": [[i, round(s, 4), round(e, 4)] for i, s, e in chunk.word_times],
                    }
                )
                await ws.send_bytes(_pcm16(chunk))
                state.sent += chunk.duration
                chunk_id += 1
            await ws.send_json({"type": "end"})
        except asyncio.CancelledError:
            raise
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001 - report to the UI instead of dying silently
            log.exception("read-aloud stream failed")
            try:
                await ws.send_json({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            except Exception:  # noqa: BLE001
                pass
        finally:
            if gen is not None:
                try:
                    gen.close()
                except ValueError:  # generator still busy in its worker thread; it ends on its own
                    pass

    @app.websocket("/ws/read")
    async def ws_read(ws: WebSocket) -> None:
        """Read-aloud session. Client messages: ``start``, ``pos`` (played seconds), ``stop``."""
        await ws.accept()
        task: asyncio.Task | None = None
        state = _Playback()

        async def cancel() -> None:
            nonlocal task
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            task = None

        try:
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type")
                if kind == "start":
                    await cancel()
                    state = _Playback()
                    task = asyncio.create_task(stream_reading(ws, msg, state))
                elif kind == "pos":
                    state.played = float(msg.get("t", 0.0))
                elif kind == "stop":
                    await cancel()
        except WebSocketDisconnect:
            pass
        finally:
            await cancel()

    # ---------------------------------------------------------------- static
    @app.get("/")
    async def index() -> FileResponse:
        """Serve the single-page frontend."""
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
