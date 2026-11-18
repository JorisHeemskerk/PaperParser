"""Tests for the filesystem library and metadata handling."""
from __future__ import annotations

import io
import json

import pytest

from paperparser.library import Conflict, Library, LibraryError, NotFound
from tests.conftest import make_pdf


@pytest.fixture()
def lib(tmp_path):
    """A library in a temp dir with one project containing one PDF."""
    library = Library(tmp_path / "lib")
    library.create_project("Thesis")
    make_pdf(library.root / "Thesis" / "a.pdf", pages=3)
    return library


def test_projects_and_dropped_files_are_discovered(lib):
    (lib.root / "Extra").mkdir()
    names = [p["name"] for p in lib.list_projects()]
    assert names == ["Extra", "Thesis"]
    paper = lib.get_project("Thesis")["papers"][0]
    assert paper["filename"] == "a.pdf" and paper["pages"] == 3 and paper["status"] == "unread"


def test_update_persists_to_metadata_file(lib):
    lib.update_paper("Thesis", "a.pdf", {"notes": "hello", "tags": ["x", "x", "y"], "color": "#ff0000", "group": "Intro"})
    meta = json.loads((lib.root / "Thesis" / "metadata.json").read_text(encoding="utf-8"))
    entry = meta["papers"]["a.pdf"]
    assert entry["notes"] == "hello" and entry["tags"] == ["x", "y"] and entry["group"] == "Intro"
    assert lib.get_project("Thesis")["groups"] == ["Intro"]


@pytest.mark.parametrize("patch", [{"color": "red"}, {"status": "done"}, {"nope": 1}])
def test_invalid_patch_rejected(lib, patch):
    with pytest.raises(LibraryError):
        lib.update_paper("Thesis", "a.pdf", patch)


@pytest.mark.parametrize("name", ["../evil", "a/b", "..", ".hidden", "bad:name"])
def test_path_traversal_rejected(lib, name):
    with pytest.raises(LibraryError):
        lib.get_project(name)
    with pytest.raises(LibraryError):
        lib.create_project(name)


def test_upload_dedupes_names_and_checks_magic(lib, tmp_path):
    data = (lib.root / "Thesis" / "a.pdf").read_bytes()
    added = lib.add_paper("Thesis", "a.pdf", io.BytesIO(data))
    assert added["filename"] == "a (2).pdf"
    with pytest.raises(LibraryError):
        lib.add_paper("Thesis", "fake.pdf", io.BytesIO(b"not a pdf"))
    assert not list((lib.root / "Thesis").glob(".upload-*"))


def test_corrupt_metadata_is_backed_up_not_lost(lib):
    meta = lib.root / "Thesis" / "metadata.json"
    meta.write_text("{ broken", encoding="utf-8")
    lib.get_project("Thesis")
    assert list((lib.root / "Thesis").glob("metadata.json.*.bak"))


def test_duplicate_project_and_missing_paper(lib):
    with pytest.raises(Conflict):
        lib.create_project("Thesis")
    with pytest.raises(NotFound):
        lib.paper_path("Thesis", "missing.pdf")
