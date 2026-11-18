"""Filesystem-backed paper library.

Layout on disk::

    library/
      <project>/
        metadata.json      <- notes, tags, colours, groups, reading position
        some-paper.pdf
        another-paper.pdf

Projects are plain folders and papers are plain PDFs, so files dropped in by
hand (or synced by OneDrive) show up automatically. ``metadata.json`` is only
ever written through :class:`Library`, using atomic replace so a sync client
never sees a half-written file.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

import pymupdf as fitz  # PyMuPDF

METADATA_FILENAME = "metadata.json"
SCHEMA_VERSION = 1
PAPER_STATUSES = ("unread", "reading", "read")

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class LibraryError(Exception):
    """Base error for library problems; ``status_code`` maps to an HTTP status."""

    status_code = 400


class NotFound(LibraryError):
    """Requested project or paper does not exist."""

    status_code = 404


class Conflict(LibraryError):
    """Requested project or paper already exists."""

    status_code = 409


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (seconds precision)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_name(name: str) -> str:
    """Validate a project folder name or file name coming from the outside.

    Args:
        name: Raw name supplied by the client.

    Returns:
        The stripped name.

    Raises:
        LibraryError: If the name is empty, hidden, a path component, too long
            or contains characters that are illegal on Windows.
    """
    name = (name or "").strip()
    if not name or name in {".", ".."} or name.startswith("."):
        raise LibraryError("Invalid name.")
    if len(name) > 150 or _BAD_NAME_CHARS.search(name):
        raise LibraryError(f"Invalid characters in name: {name!r}")
    return name


def _validate_paper_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise a partial paper-metadata update.

    Args:
        patch: Fields to change. Unknown keys are rejected.

    Returns:
        A cleaned copy containing only validated fields.

    Raises:
        LibraryError: On unknown keys or invalid values.
    """
    out: dict[str, Any] = {}
    for key, value in patch.items():
        if key == "title":
            out[key] = (str(value).strip() or None) if value is not None else None
        elif key == "notes":
            out[key] = str(value)
        elif key == "group":
            out[key] = str(value).strip()[:80]
        elif key == "tags":
            tags = [str(t).strip()[:40] for t in value if str(t).strip()]
            out[key] = list(dict.fromkeys(tags))  # de-duplicate, keep order
        elif key == "color":
            if value is not None and not _HEX_COLOR.match(str(value)):
                raise LibraryError("color must be a #rrggbb value or null")
            out[key] = value
        elif key == "status":
            if value not in PAPER_STATUSES:
                raise LibraryError(f"status must be one of {PAPER_STATUSES}")
            out[key] = value
        elif key == "favorite":
            out[key] = bool(value)
        elif key == "reading_pos":
            out[key] = max(0, int(value))
        else:
            raise LibraryError(f"Unknown paper field: {key}")
    return out


class Library:
    """A directory of projects, each a folder of PDFs plus a ``metadata.json``.

    Args:
        root: Library root; created if missing.
    """

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()
        self._lock = threading.RLock()
        self._info_cache: dict[tuple[str, int], dict[str, Any]] = {}

    # ------------------------------------------------------------------ paths
    def _project_dir(self, project: str) -> Path:
        """Resolve a project name to its directory.

        Args:
            project: Project folder name.

        Returns:
            Absolute path of the project directory.

        Raises:
            NotFound: If the project folder does not exist.
            LibraryError: If the name is invalid.
        """
        path = self.root / clean_name(project)
        if not path.is_dir():
            raise NotFound(f"Project not found: {project}")
        return path

    def paper_path(self, project: str, filename: str) -> Path:
        """Return the absolute path of a paper's PDF.

        Args:
            project: Project folder name.
            filename: PDF file name inside the project.

        Returns:
            Path to the existing PDF file.

        Raises:
            NotFound: If the file does not exist.
            LibraryError: If the name is invalid or not a PDF.
        """
        pdir = self._project_dir(project)
        name = clean_name(filename)
        if not name.lower().endswith(".pdf"):
            raise LibraryError("Only .pdf files are supported.")
        path = pdir / name
        if not path.is_file():
            raise NotFound(f"Paper not found: {filename}")
        return path

    # --------------------------------------------------------------- metadata
    def _load_meta(self, pdir: Path) -> dict[str, Any]:
        """Load a project's metadata, tolerating a missing or corrupt file.

        A corrupt file (e.g. a half-synced OneDrive conflict) is copied to a
        timestamped ``.bak`` before defaults are returned, so notes are never
        silently lost.

        Args:
            pdir: Project directory.

        Returns:
            The metadata dict with ``papers`` guaranteed to exist.
        """
        path = pdir / METADATA_FILENAME
        meta: dict[str, Any] = {}
        if path.is_file():
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(meta, dict):
                    raise ValueError("metadata root must be an object")
            except (ValueError, OSError):
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(path, pdir / f"{METADATA_FILENAME}.{stamp}.bak")
                meta = {}
        meta.setdefault("version", SCHEMA_VERSION)
        meta.setdefault("color", None)
        meta.setdefault("description", "")
        if not isinstance(meta.get("papers"), dict):
            meta["papers"] = {}
        return meta

    def _save_meta(self, pdir: Path, meta: dict[str, Any]) -> None:
        """Atomically write a project's metadata file.

        Args:
            pdir: Project directory.
            meta: Full metadata dict to persist.
        """
        fd, tmp = tempfile.mkstemp(dir=pdir, prefix=".metadata-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(meta, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, pdir / METADATA_FILENAME)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # ------------------------------------------------------------- pdf helpers
    def _pdf_info(self, path: Path) -> dict[str, Any]:
        """Read (and cache by mtime) the page count and embedded title of a PDF.

        Args:
            path: PDF file path.

        Returns:
            ``{"pages": int, "pdf_title": str | None}``; ``pages`` is 0 if the
            file cannot be opened.
        """
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns)
        if key in self._info_cache:
            return self._info_cache[key]
        info: dict[str, Any] = {"pages": 0, "pdf_title": None}
        try:
            with fitz.open(path) as doc:
                info["pages"] = doc.page_count
                title = (doc.metadata or {}).get("title") or ""
                title = title.strip()
                junk = title.lower().endswith((".pdf", ".tex", ".doc", ".docx")) or "microsoft word" in title.lower()
                if len(title) >= 5 and not junk:
                    info["pdf_title"] = title[:200]
        except Exception:  # noqa: BLE001 - corrupt PDFs must not break listing
            pass
        self._info_cache[key] = info
        return info

    def _paper_view(self, path: Path, entry: dict[str, Any] | None) -> dict[str, Any]:
        """Merge on-disk facts and stored metadata into one API object.

        Args:
            path: PDF file path.
            entry: Stored metadata for the paper, if any.

        Returns:
            Paper dict with defaults filled in.
        """
        stat = path.stat()
        view: dict[str, Any] = {
            "title": None,
            "notes": "",
            "tags": [],
            "color": None,
            "group": "",
            "status": "unread",
            "favorite": False,
            "reading_pos": 0,
            "added": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        }
        view.update(entry or {})
        info = self._pdf_info(path)
        view["filename"] = path.name
        view["size"] = stat.st_size
        view["pages"] = info["pages"]
        view["display_title"] = view["title"] or info["pdf_title"] or path.stem
        return view

    # ---------------------------------------------------------------- projects
    def list_projects(self) -> list[dict[str, Any]]:
        """List all projects (sub-folders not starting with ``.`` or ``_``).

        Returns:
            Projects sorted by name with colour, description and paper count.
        """
        projects = []
        for pdir in sorted(self.root.iterdir(), key=lambda p: p.name.lower()):
            if not pdir.is_dir() or pdir.name.startswith((".", "_")):
                continue
            with self._lock:
                meta = self._load_meta(pdir)
            count = sum(1 for f in pdir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf")
            projects.append(
                {"name": pdir.name, "color": meta["color"], "description": meta["description"], "paper_count": count}
            )
        return projects

    def create_project(self, name: str, color: str | None = None) -> dict[str, Any]:
        """Create a new project folder with an empty metadata file.

        Args:
            name: Folder name of the project.
            color: Optional ``#rrggbb`` accent colour.

        Returns:
            The created project summary.

        Raises:
            Conflict: If a project with that name already exists.
        """
        name = clean_name(name)
        if name.startswith("_"):
            raise LibraryError("Project names must not start with an underscore.")
        pdir = self.root / name
        if pdir.exists():
            raise Conflict(f"Project already exists: {name}")
        pdir.mkdir()
        with self._lock:
            meta = self._load_meta(pdir)
            if color is not None:
                meta["color"] = _validate_paper_patch({"color": color})["color"]
            self._save_meta(pdir, meta)
        return {"name": name, "color": meta["color"], "description": "", "paper_count": 0}

    def update_project(self, project: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Update a project's colour and/or description.

        Args:
            project: Project folder name.
            patch: Dict with optional ``color`` and ``description`` keys.

        Returns:
            The updated project summary.
        """
        pdir = self._project_dir(project)
        with self._lock:
            meta = self._load_meta(pdir)
            if "color" in patch:
                meta["color"] = _validate_paper_patch({"color": patch["color"]})["color"]
            if "description" in patch:
                meta["description"] = str(patch["description"] or "")[:500]
            self._save_meta(pdir, meta)
        count = sum(1 for f in pdir.iterdir() if f.suffix.lower() == ".pdf")
        return {"name": pdir.name, "color": meta["color"], "description": meta["description"], "paper_count": count}

    def get_project(self, project: str) -> dict[str, Any]:
        """Return a project with all of its papers.

        Args:
            project: Project folder name.

        Returns:
            ``{"name", "color", "description", "groups", "papers"}`` where
            papers are sorted by filename (the client sorts further).
        """
        pdir = self._project_dir(project)
        with self._lock:
            meta = self._load_meta(pdir)
        files = sorted(
            (f for f in pdir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"),
            key=lambda f: f.name.lower(),
        )
        papers = [self._paper_view(f, meta["papers"].get(f.name)) for f in files]
        groups = sorted({p["group"] for p in papers if p["group"]}, key=str.lower)
        return {
            "name": pdir.name,
            "color": meta["color"],
            "description": meta["description"],
            "groups": groups,
            "papers": papers,
        }

    # ------------------------------------------------------------------ papers
    def get_paper(self, project: str, filename: str) -> dict[str, Any]:
        """Return a single paper's merged view.

        Args:
            project: Project folder name.
            filename: PDF file name.

        Returns:
            The paper dict (see :meth:`_paper_view`).
        """
        path = self.paper_path(project, filename)
        with self._lock:
            meta = self._load_meta(path.parent)
        return self._paper_view(path, meta["papers"].get(path.name))

    def add_paper(self, project: str, filename: str, stream: BinaryIO) -> dict[str, Any]:
        """Store an uploaded PDF in a project.

        The upload is streamed to a temp file, checked for the ``%PDF`` magic
        bytes and renamed to a non-clashing name (``name (2).pdf``).

        Args:
            project: Project folder name.
            filename: Original file name of the upload.
            stream: Binary stream with the PDF bytes.

        Returns:
            The new paper's merged view.

        Raises:
            LibraryError: If the name is not a ``.pdf`` or the content is not a PDF.
        """
        pdir = self._project_dir(project)
        name = clean_name(Path(filename).name)
        if not name.lower().endswith(".pdf"):
            raise LibraryError(f"Not a PDF file: {name}")
        fd, tmp = tempfile.mkstemp(dir=pdir, prefix=".upload-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(stream, out)
            with open(tmp, "rb") as check:
                if check.read(1024).find(b"%PDF") < 0:
                    raise LibraryError(f"{name} does not look like a PDF.")
            with self._lock:
                stem, target, n = Path(name).stem, pdir / name, 2
                while target.exists():
                    target = pdir / f"{stem} ({n}).pdf"
                    n += 1
                os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return self.get_paper(project, target.name)

    def update_paper(self, project: str, filename: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Apply a validated partial update to a paper's metadata.

        Args:
            project: Project folder name.
            filename: PDF file name.
            patch: Fields to change (title, notes, tags, color, group, status,
                favorite, reading_pos).

        Returns:
            The updated paper view.
        """
        path = self.paper_path(project, filename)
        clean = _validate_paper_patch(patch)
        with self._lock:
            meta = self._load_meta(path.parent)
            entry = meta["papers"].setdefault(path.name, {})
            entry.setdefault("added", self._paper_view(path, None)["added"])
            entry.update(clean)
            self._save_meta(path.parent, meta)
            return self._paper_view(path, entry)
