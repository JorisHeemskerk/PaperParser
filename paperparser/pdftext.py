"""Extract speakable, position-aware words from a PDF.

Every word the PDF contains becomes a :class:`Word` with a page-normalised
bounding box, so the frontend can draw highlights independently of zoom. Words
that should usually not be read aloud (running headers, the reference list,
inline citations like ``[12]``) are *flagged*, not removed, so word indices stay
stable no matter which skip options the user toggles.
"""
from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pymupdf as fitz  # PyMuPDF

FLAG_REFERENCES = 1  # word lies in the bibliography
FLAG_CITATION = 2  # inline citation such as [3, 4] or (Smith et al., 2020)
FLAG_HEADER_FOOTER = 4  # repeating running header/footer or page number
FLAG_CONTINUATION = 8  # second half of a word hyphenated across a line break

_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st", "­": ""}
_HYPHENS = "-‐‑"
_REF_HEADING = re.compile(
    r"^\s*(?:\d+\.?|[IVX]+\.?)?\s*(references|bibliography|works cited|literature cited|reference list)\s*:?\s*$",
    re.I,
)
_PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.I)
_NUMERIC_CITE_PART = re.compile(r"^\d+[,;–\-]?$")
_YEAR = re.compile(r"\b(19|20)\d{2}[a-z]?\b")
_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*$")
_ABBREVIATIONS = {
    "e.g.", "i.e.", "al.", "fig.", "figs.", "eq.", "eqs.", "dr.", "mr.", "mrs.", "ms.", "vs.",
    "cf.", "etc.", "approx.", "no.", "sec.", "tab.", "ref.", "refs.", "prof.", "st.", "inc.", "ca.",
}


@dataclass(slots=True)
class Word:
    """One word of the document.

    Attributes:
        page: Zero-based page index.
        box: ``(x0, y0, x1, y1)`` normalised to the page size (0..1, y down).
        raw: Text exactly as extracted.
        spoken: Text to feed to the TTS engine; empty means "silent".
        flags: Bitmask of ``FLAG_*`` constants.
        block: Document-wide id of the text block the word belongs to.
    """

    page: int
    box: tuple[float, float, float, float]
    raw: str
    spoken: str
    flags: int = 0
    block: int = 0


@dataclass
class DocumentText:
    """All words of a PDF in reading order plus page geometry.

    Attributes:
        pages: ``(width, height)`` of every page in PDF points.
        words: Words in reading order.
        references_start: Index of the first bibliography word, if one was found.
    """

    pages: list[tuple[float, float]]
    words: list[Word]
    references_start: int | None = None

    def to_wire(self) -> dict:
        """Serialise to the compact JSON structure sent to the browser.

        Returns:
            ``{"pages": [{"w","h"}], "words": [[page,x0,y0,x1,y1,flags], ...],
            "references_start": int | None}``.
        """
        return {
            "pages": [{"w": round(w, 2), "h": round(h, 2)} for w, h in self.pages],
            "words": [[w.page, *(round(v, 4) for v in w.box), w.flags] for w in self.words],
            "references_start": self.references_start,
        }


@dataclass(slots=True)
class Segment:
    """A sentence-sized unit of text handed to the TTS engine.

    Attributes:
        indices: Global word indices actually spoken, in order.
        text: The words joined by single spaces.
        spans: ``(start, end)`` character offsets of each word inside ``text``.
    """

    indices: list[int]
    text: str
    spans: list[tuple[int, int]]


@dataclass
class _Block:
    """Internal: a PyMuPDF text block with its words grouped into lines."""

    page: int
    lines: list[list[tuple]] = field(default_factory=list)
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    skip_hf: bool = False

    @property
    def text(self) -> str:
        """All words of the block joined by spaces."""
        return " ".join(w[4] for line in self.lines for w in line)


# --------------------------------------------------------------------- helpers
def _to_spoken(raw: str) -> str:
    """Convert extracted text into something a TTS engine can pronounce.

    Replaces typographic ligatures and soft hyphens; words with no letters or
    digits (bullets, rules, lone symbols) become silent.

    Args:
        raw: Word text as extracted from the PDF.

    Returns:
        The speakable text, possibly empty.
    """
    text = raw
    for src, dst in _LIGATURES.items():
        text = text.replace(src, dst)
    text = re.sub(r"[\x00-\x1f]", "", text).strip()
    return text if any(c.isalnum() for c in text) else ""


def _make_blocks(page: fitz.Page, page_no: int) -> list[_Block]:
    """Group a page's words into blocks and lines, in PyMuPDF's native order.

    Args:
        page: PyMuPDF page.
        page_no: Zero-based page index.

    Returns:
        Blocks with their lines and bounding boxes.
    """
    blocks: dict[int, _Block] = {}
    for w in page.get_text("words"):
        x0, y0, x1, y1, text, block_no, line_no, _ = w
        if not text.strip():
            continue
        blk = blocks.setdefault(block_no, _Block(page=page_no))
        while len(blk.lines) <= line_no:
            blk.lines.append([])
        blk.lines[line_no].append(w)
    for blk in blocks.values():
        blk.lines = [line for line in blk.lines if line]
        ws = [w for line in blk.lines for w in line]
        blk.bbox = (min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws), max(w[3] for w in ws))
    return list(blocks.values())


def _order_blocks(blocks: list[_Block], page_width: float) -> list[_Block]:
    """Put a page's blocks into reading order, handling two-column layouts.

    Single-column pages keep PyMuPDF's native order. If at least two blocks sit
    wholly in each half of the page the page is treated as two-column: blocks
    are read top-to-bottom, left column then right column, in "bands" separated
    by blocks that span both columns (titles, wide captions).

    Args:
        blocks: Blocks of one page in native order.
        page_width: Page width in points.

    Returns:
        The blocks in reading order.
    """
    mid, margin = page_width / 2, page_width * 0.04

    def side(b: _Block) -> str:
        if b.bbox[2] <= mid + margin:
            return "L"
        if b.bbox[0] >= mid - margin:
            return "R"
        return "F"

    sides = [side(b) for b in blocks]
    if sides.count("L") < 2 or sides.count("R") < 2:
        return blocks

    ordered: list[_Block] = []
    left: list[_Block] = []
    right: list[_Block] = []

    def flush() -> None:
        ordered.extend(sorted(left, key=lambda b: b.bbox[1]))
        ordered.extend(sorted(right, key=lambda b: b.bbox[1]))
        left.clear()
        right.clear()

    for b in sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0])):
        s = side(b)
        if s == "L":
            left.append(b)
        elif s == "R":
            right.append(b)
        else:
            flush()
            ordered.append(b)
    flush()
    return ordered


def _mark_headers_footers(pages_blocks: list[list[_Block]], sizes: list[tuple[float, float]]) -> None:
    """Flag blocks in the top/bottom margin that repeat across pages or are page numbers.

    Args:
        pages_blocks: Blocks per page (modified in place via ``skip_hf``).
        sizes: ``(width, height)`` per page in points.
    """

    def in_margin(b: _Block, height: float) -> bool:
        return b.bbox[3] <= height * 0.08 or b.bbox[1] >= height * 0.92

    def norm(text: str) -> str:
        return re.sub(r"\d+", "#", text.lower()).strip()

    counts: Counter[str] = Counter()
    for blocks, (_, h) in zip(pages_blocks, sizes):
        for key in {norm(b.text) for b in blocks if in_margin(b, h)}:
            counts[key] += 1
    n_pages = len(pages_blocks)
    threshold = max(3, math.ceil(0.35 * n_pages)) if n_pages >= 3 else 10**9
    for blocks, (_, h) in zip(pages_blocks, sizes):
        for b in blocks:
            if in_margin(b, h) and (_PAGE_NUMBER.match(b.text) or counts[norm(b.text)] >= threshold):
                b.skip_hf = True


def _block_words(blk: _Block, size: tuple[float, float], block_id: int) -> list[Word]:
    """Convert a block to :class:`Word` objects, merging line-break hyphenation.

    ``exam-`` / ``ple`` becomes one spoken word ``example`` on the first part;
    the second part stays in the list (so it can be highlighted) but is silent
    and flagged :data:`FLAG_CONTINUATION`.

    Args:
        blk: The block to convert.
        size: Page ``(width, height)`` in points.
        block_id: Document-wide id assigned to all words of the block.

    Returns:
        Words of the block in line order.
    """
    pw, ph = size
    base = FLAG_HEADER_FOOTER if blk.skip_hf else 0
    words: list[Word] = []
    pending_continuation = False
    for li, line in enumerate(blk.lines):
        for wi, w in enumerate(line):
            x0, y0, x1, y1, raw = w[:5]
            box = (x0 / pw, y0 / ph, x1 / pw, y1 / ph)
            if pending_continuation and wi == 0:
                words.append(Word(blk.page, box, raw, "", base | FLAG_CONTINUATION, block_id))
                pending_continuation = False
            else:
                words.append(Word(blk.page, box, raw, _to_spoken(raw), base, block_id))
        if li + 1 < len(blk.lines):
            last, nxt = words[-1], blk.lines[li + 1][0][4]
            if len(last.raw) >= 3 and last.raw[-1] in _HYPHENS and last.raw[-2].isalpha() and nxt[:1].islower():
                stem = last.spoken[:-1]
                # "state-of-the-" + "art" keeps its hyphens; "exam-" + "ple" loses the break hyphen
                joined = (last.spoken if any(h in stem for h in _HYPHENS) else stem) + _to_spoken(nxt)
                last.spoken = joined.replace("\u2010", "-").replace("\u2011", "-")
                pending_continuation = True
    return words


def _flag_citations(words: list[Word]) -> None:
    """Flag inline citations: ``[1]``, ``[1, 2]``, ``[3-5]`` and ``(Smith et al., 2020)``.

    Args:
        words: Document words (flags are modified in place).
    """
    i, n = 0, len(words)
    while i < n:
        t = words[i].raw
        if t.startswith("["):
            j = i
            while j < n and j - i < 8 and not words[j].raw.rstrip(".,;:").endswith("]"):
                j += 1
            if j < n and j - i < 8:
                parts = [words[k].raw.strip("[]") for k in range(i, j + 1)]
                if all(_NUMERIC_CITE_PART.match(p + ("" if p else "0")) or p == "" for p in parts):
                    for k in range(i, j + 1):
                        words[k].flags |= FLAG_CITATION
                    i = j + 1
                    continue
        elif t.startswith("(") and len(t) > 1 and t[1].isupper():
            j = i
            while j < n and j - i < 12 and not re.search(r"\)[.,;:]*$", words[j].raw):
                j += 1
            if j < n and j - i < 12:
                span = " ".join(words[k].raw for k in range(i, j + 1))
                if _YEAR.search(span) and re.search(r"et al|&|\band\b|,", span):
                    for k in range(i, j + 1):
                        words[k].flags |= FLAG_CITATION
                    i = j + 1
                    continue
        i += 1


def _find_references(pages_blocks: list[list[_Block]], first_index: list[list[int]], total: int) -> int | None:
    """Locate the start of the bibliography.

    Looks for a line that is just "References" / "Bibliography" etc. and takes
    the last such line that sits in the final 65% of the document.

    Args:
        pages_blocks: Ordered blocks per page.
        first_index: Global index of each block's first word, parallel to ``pages_blocks``.
        total: Total word count.

    Returns:
        Word index of the heading, or None.
    """
    best: int | None = None
    for blocks, idxs in zip(pages_blocks, first_index):
        for blk, start in zip(blocks, idxs):
            offset = 0
            for line in blk.lines:
                text = " ".join(w[4] for w in line)
                if _REF_HEADING.match(text) and total and start + offset >= 0.35 * total:
                    best = start + offset
                offset += len(line)
    return best


# ------------------------------------------------------------------ public API
def extract_document(pdf_path: Path) -> DocumentText:
    """Extract all words of a PDF in reading order with flags and geometry.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        A :class:`DocumentText`. Scanned PDFs without a text layer yield zero words.
    """
    with fitz.open(pdf_path) as doc:
        sizes = [(p.rect.width, p.rect.height) for p in doc]
        pages_blocks = [_order_blocks(_make_blocks(p, i), sizes[i][0]) for i, p in enumerate(doc)]
    _mark_headers_footers(pages_blocks, sizes)

    words: list[Word] = []
    first_index: list[list[int]] = []
    block_id = 0
    for blocks, size in zip(pages_blocks, sizes):
        idxs = []
        for blk in blocks:
            idxs.append(len(words))
            words.extend(_block_words(blk, size, block_id))
            block_id += 1
        first_index.append(idxs)

    ref_start = _find_references(pages_blocks, first_index, len(words))
    if ref_start is not None:
        for w in words[ref_start:]:
            w.flags |= FLAG_REFERENCES
    _flag_citations(words)
    return DocumentText(pages=sizes, words=words, references_start=ref_start)


def skip_mask(references: bool = True, citations: bool = True, headers: bool = True) -> int:
    """Build the flag mask of word categories to skip when reading aloud.

    Args:
        references: Skip the bibliography.
        citations: Skip inline citations.
        headers: Skip running headers, footers and page numbers.

    Returns:
        Bitmask to test against :attr:`Word.flags`.
    """
    return (FLAG_REFERENCES if references else 0) | (FLAG_CITATION if citations else 0) | (
        FLAG_HEADER_FOOTER if headers else 0
    )


def _ends_sentence(spoken: str) -> bool:
    """Return True if a spoken word ends a sentence (and is not an abbreviation).

    Args:
        spoken: Word text.
    """
    if not _SENTENCE_END.search(spoken):
        return False
    low = spoken.lower()
    return low not in _ABBREVIATIONS and not re.fullmatch(r"[A-Z]\.", spoken)


def iter_segments(
    doc: DocumentText,
    start_word: int = 0,
    mask: int = 0,
    max_chars: int = 380,
) -> Iterator[Segment]:
    """Yield sentence-sized segments of speakable text starting at a word.

    A segment ends at sentence punctuation, at a paragraph/heading boundary
    (unless the sentence visibly continues in the next block), or when it grows
    past ``max_chars`` (preferring a comma/semicolon as the cut point).

    Args:
        doc: Extracted document.
        start_word: Global index to start reading from (hyphen halves are
            snapped back to their first part).
        mask: Flags to skip, see :func:`skip_mask`.
        max_chars: Soft upper bound on segment length.

    Yields:
        :class:`Segment` objects in reading order.
    """
    words = doc.words
    start = max(0, min(start_word, len(words)))
    while start > 0 and start < len(words) and words[start].flags & FLAG_CONTINUATION:
        start -= 1

    cur: list[int] = []

    def build(indices: list[int]) -> Segment:
        text, spans = "", []
        for i in indices:
            if text:
                text += " "
            spans.append((len(text), len(text) + len(words[i].spoken)))
            text += words[i].spoken
        return Segment(indices, text, spans)

    def length(indices: list[int]) -> int:
        return sum(len(words[i].spoken) + 1 for i in indices)

    for i in range(start, len(words)):
        w = words[i]
        if w.flags & mask or not w.spoken:
            continue
        if cur:
            prev = words[cur[-1]]
            if w.block != prev.block and (_ends_sentence(prev.spoken) or not w.spoken[:1].islower()):
                yield build(cur)
                cur = []
        cur.append(i)
        if _ends_sentence(w.spoken):
            yield build(cur)
            cur = []
        elif length(cur) > max_chars:
            cut = next((k for k in range(len(cur) - 1, len(cur) // 3, -1) if words[cur[k]].spoken[-1:] in ",;:"), None)
            if cut is None:
                cut = len(cur) - 1
            yield build(cur[: cut + 1])
            cur = cur[cut + 1 :]
    if cur:
        yield build(cur)


# --------------------------------------------------------------------- caching
_CACHE: dict[str, tuple[int, DocumentText]] = {}
_CACHE_LOCK = threading.Lock()


def get_document(pdf_path: Path) -> DocumentText:
    """Return the extracted document, cached by file path and modification time.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        The (possibly cached) :class:`DocumentText`.
    """
    key, mtime = str(pdf_path), pdf_path.stat().st_mtime_ns
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    doc = extract_document(pdf_path)
    with _CACHE_LOCK:
        if len(_CACHE) >= 8:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = (mtime, doc)
    return doc
