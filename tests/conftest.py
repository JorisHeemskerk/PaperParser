"""Shared test fixtures: synthetic PDFs and a temporary library."""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf as fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LEFT = (
    "Left column starts here and it keeps going for a few lines so that the "
    "block is reasonably wide. It contains an exam-\nple of a hyphenated word "
    "that breaks across lines. Then we cite prior work [1, 2] before ending."
)
RIGHT = (
    "Right column continues the paper with different content. See also "
    "(Smith et al., 2020) for details. This sentence finishes the paragraph."
)


def make_pdf(path: Path, pages: int = 4) -> Path:
    """Create a small two-column PDF with headers, page numbers and references.

    Args:
        path: Where to write the PDF.
        pages: Number of pages; the last page holds the reference list.

    Returns:
        ``path``.
    """
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=600, height=800)
        page.insert_text((200, 30), "Running Header Title", fontsize=9)
        page.insert_text((290, 780), str(i + 1), fontsize=9)
        if i == pages - 1:
            page.insert_textbox(fitz.Rect(50, 100, 550, 130), "References", fontsize=14)
            page.insert_textbox(fitz.Rect(50, 140, 550, 300), "[1] A. Author. Some paper. 2019.\n[2] B. Writer. Another. 2020.", fontsize=10)
        else:
            page.insert_textbox(fitz.Rect(50, 100, 550, 130), f"{i + 1} Section Title", fontsize=14)
            page.insert_textbox(fitz.Rect(50, 150, 290, 400), LEFT, fontsize=10)
            page.insert_textbox(fitz.Rect(310, 150, 550, 400), RIGHT, fontsize=10)
            page.insert_textbox(fitz.Rect(50, 420, 290, 520), "Second left block. " * 4, fontsize=10)
            page.insert_textbox(fitz.Rect(310, 420, 550, 520), "Second right block. " * 4, fontsize=10)
    doc.save(path)
    return path


@pytest.fixture()
def pdf_path(tmp_path: Path) -> Path:
    """A synthetic PDF in a temporary directory."""
    return make_pdf(tmp_path / "sample.pdf")
