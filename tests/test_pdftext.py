"""Tests for PDF word extraction, flagging and sentence segmentation."""
from __future__ import annotations

from paperparser.pdftext import (
    FLAG_CITATION, FLAG_CONTINUATION, FLAG_HEADER_FOOTER, FLAG_REFERENCES,
    extract_document, iter_segments, skip_mask,
)


def test_two_column_reading_order_and_hyphen_merge(pdf_path):
    doc = extract_document(pdf_path)
    text = " ".join(w.spoken for w in doc.words if not w.flags & FLAG_HEADER_FOOTER and w.page == 0 and w.spoken)
    assert text.index("Left column") < text.index("Second left block") < text.index("Right column")
    assert "example" in text and "exam-" not in text
    cont = [w for w in doc.words if w.flags & FLAG_CONTINUATION]
    assert cont and cont[0].raw == "ple" and cont[0].spoken == ""


def test_flags_headers_citations_references(pdf_path):
    doc = extract_document(pdf_path)
    by_raw = lambda raw: [w for w in doc.words if w.raw == raw]  # noqa: E731
    assert all(w.flags & FLAG_HEADER_FOOTER for w in by_raw("Running"))
    assert all(w.flags & FLAG_CITATION for w in by_raw("[1,") + by_raw("2]") if w.page == 0)
    assert all(w.flags & FLAG_CITATION for w in by_raw("(Smith"))
    assert doc.references_start is not None
    assert all(w.flags & FLAG_REFERENCES for w in doc.words[doc.references_start:])
    assert not any(w.flags & FLAG_REFERENCES for w in doc.words[: doc.references_start])


def test_segments_respect_skip_mask(pdf_path):
    doc = extract_document(pdf_path)
    segs = list(iter_segments(doc, 0, skip_mask()))
    text = " ".join(s.text for s in segs)
    assert "Running Header" not in text and "[1," not in text and "Smith" not in text and "Some paper" not in text
    assert all(s.text[a:b] == doc.words[i].spoken for s in segs for i, (a, b) in zip(s.indices, s.spans))
    assert all(len(s.text) < 420 for s in segs)
    unmasked = " ".join(s.text for s in iter_segments(doc, 0, 0))
    assert "Some paper" in unmasked and "Smith" in unmasked


def test_start_word_snaps_back_from_continuation(pdf_path):
    doc = extract_document(pdf_path)
    cont = next(i for i, w in enumerate(doc.words) if w.flags & FLAG_CONTINUATION)
    first = next(iter_segments(doc, cont, skip_mask()))
    assert first.indices[0] == cont - 1


def test_wire_format(pdf_path):
    wire = extract_document(pdf_path).to_wire()
    assert len(wire["pages"]) == 4 and all(len(w) == 6 for w in wire["words"])
    assert all(0 <= v <= 1 for w in wire["words"] for v in w[1:5])
