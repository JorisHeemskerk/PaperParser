"""Tests for token-to-word timing alignment and the demo engine."""
from __future__ import annotations

from types import SimpleNamespace as Tok

from paperparser.pdftext import Segment
from paperparser.tts import FakeEngine, align_words


def make_segment(words, start_index=100):
    """Build a Segment from a word list with indices starting at ``start_index``."""
    text, spans = "", []
    for w in words:
        text += (" " if text else "")
        spans.append((len(text), len(text) + len(w)))
        text += w
    return Segment(list(range(start_index, start_index + len(words))), text, spans)


def test_alignment_maps_tokens_incl_punctuation_and_split_words():
    seg = make_segment(["Hello", "don't", "stop."])
    tokens = [
        Tok(text="Hello", start_ts=0.0, end_ts=0.4),
        Tok(text="don", start_ts=0.5, end_ts=0.7),   # one PDF word split into several tokens
        Tok(text="'t", start_ts=0.7, end_ts=0.9),
        Tok(text="stop", start_ts=1.0, end_ts=1.4),
        Tok(text=".", start_ts=None, end_ts=None),
    ]
    out = align_words(seg, seg.text, 0, tokens, 1.5)
    assert [i for i, _, _ in out] == [100, 101, 102]
    assert out[1][1:] == (0.5, 0.9) and out[2][1:] == (1.0, 1.4)


def test_alignment_interpolates_untimed_words_and_is_monotonic():
    seg = make_segment(["aa", "bbbb", "cc"])
    tokens = [Tok(text="aa", start_ts=0.0, end_ts=0.2), Tok(text="cc", start_ts=1.0, end_ts=1.2)]
    out = align_words(seg, seg.text, 0, tokens, 1.2)
    assert 0.2 <= out[1][1] < out[1][2] <= 1.0
    starts = [s for _, s, _ in out]
    assert starts == sorted(starts)


def test_alignment_without_tokens_is_proportional():
    seg = make_segment(["aa", "aaaaaa"])
    out = align_words(seg, seg.text, 0, None, 4.0)
    assert out[0][1:] == (0.0, 1.0) and out[1][1:] == (1.0, 4.0)


def test_alignment_second_chunk_offset():
    seg = make_segment(["One", "two", "three", "four"])
    split = seg.spans[2][0]
    out = align_words(seg, seg.text[split:], split, [Tok(text="three", start_ts=0.0, end_ts=0.5), Tok(text="four", start_ts=0.6, end_ts=1.0)], 1.0)
    assert [i for i, _, _ in out] == [102, 103]


def test_fake_engine_timings_cover_audio():
    seg = make_segment(["alpha", "beta"])
    chunk = next(FakeEngine().synthesize(seg, "af_heart", 1.0))
    assert [i for i, _, _ in chunk.word_times] == [100, 101]
    assert chunk.word_times[-1][2] <= chunk.duration
    fast = next(FakeEngine().synthesize(seg, "af_heart", 2.0))
    assert fast.duration < chunk.duration
