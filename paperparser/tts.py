"""Text-to-speech engines that return audio *and* per-word timings.

The key idea for read-along highlighting: the text sent to the engine is built
from PDF words (see :mod:`paperparser.pdftext`), each with a known character
span. The engine reports timestamps per token; :func:`align_words` maps those
back onto the PDF words by character offset, so the browser can highlight the
exact word being spoken.
"""
from __future__ import annotations

import bisect
import importlib.util
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Sequence

import numpy as np

from .config import Settings
from .pdftext import Segment

log = logging.getLogger("paperparser.tts")

SAMPLE_RATE = 24000


@dataclass(frozen=True)
class VoiceInfo:
    """A selectable voice preset.

    Attributes:
        id: Engine voice id (e.g. ``af_heart``).
        name: Human-friendly label.
        group: Group label for the UI (accent + gender).
    """

    id: str
    name: str
    group: str


@dataclass
class AudioChunk:
    """A piece of synthesised audio with word timings.

    Attributes:
        samples: Mono float32 samples in ``[-1, 1]``.
        sample_rate: Sample rate in Hz.
        word_times: ``(global_word_index, start_s, end_s)`` relative to the chunk start.
    """

    samples: np.ndarray
    sample_rate: int
    word_times: list[tuple[int, float, float]]

    @property
    def duration(self) -> float:
        """Chunk length in seconds."""
        return len(self.samples) / self.sample_rate


_KOKORO_VOICE_IDS = {
    "American · female": ["af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "af_alloy", "af_aoede",
                          "af_jessica", "af_kore", "af_nova", "af_river"],
    "American · male": ["am_adam", "am_michael", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_onyx",
                        "am_puck", "am_santa"],
    "British · female": ["bf_emma", "bf_isabella", "bf_alice", "bf_lily"],
    "British · male": ["bm_george", "bm_lewis", "bm_daniel", "bm_fable"],
}
KOKORO_VOICES: list[VoiceInfo] = [
    VoiceInfo(vid, vid[3:].capitalize(), group) for group, ids in _KOKORO_VOICE_IDS.items() for vid in ids
]
DEFAULT_VOICE = "af_heart"


# ------------------------------------------------------------------ alignment
def _interpolate_missing(times: list[tuple[float, float] | None], weights: Sequence[int], duration: float) -> list[tuple[float, float]]:
    """Fill words that received no timestamp by spreading time between known neighbours.

    Args:
        times: Per-word ``(start, end)`` or None when the engine gave nothing.
        weights: Per-word weight (character count) used to share out gaps.
        duration: Total chunk duration in seconds (right boundary of the last gap).

    Returns:
        A fully populated list of ``(start, end)`` tuples.
    """
    out = list(times)
    n, i = len(out), 0
    while i < n:
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < n and out[j] is None:
            j += 1
        left = out[i - 1][1] if i > 0 else 0.0
        right = out[j][0] if j < n else duration
        right = max(right, left)
        total = sum(max(weights[k], 1) for k in range(i, j))
        cursor = left
        for k in range(i, j):
            span = (right - left) * max(weights[k], 1) / total
            out[k] = (cursor, cursor + span)
            cursor += span
        i = j
    return out  # type: ignore[return-value]


def _monotonic(times: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """Clamp timings to ``[0, duration]`` and make starts non-decreasing.

    Args:
        times: Per-word ``(start, end)``.
        duration: Chunk duration in seconds.

    Returns:
        Sanitised timings where ``start_i <= end_i`` and ``start_i >= start_{i-1}``.
    """
    out, prev = [], 0.0
    for s, e in times:
        s = min(max(s, prev), duration)
        e = min(max(e, s), duration)
        out.append((s, e))
        prev = s
    return out


def align_words(
    segment: Segment,
    chunk_text: str,
    chunk_offset: int,
    tokens: Iterable[Any] | None,
    duration: float,
) -> list[tuple[int, float, float]]:
    """Map engine token timestamps onto the PDF words of a segment.

    Tokens are located inside ``chunk_text`` by scanning forward for their text;
    the character offset decides which word they belong to. Words without any
    timed token are interpolated; with no usable timestamps at all, time is
    shared proportionally to word length.

    Args:
        segment: The segment that was synthesised.
        chunk_text: The part of ``segment.text`` this audio chunk covers.
        chunk_offset: Character offset of ``chunk_text`` within ``segment.text``.
        tokens: Engine tokens exposing ``text``, ``start_ts`` and ``end_ts``
            (timestamps in seconds relative to the chunk audio), or None.
        duration: Duration of the chunk's audio in seconds.

    Returns:
        ``(global_word_index, start_s, end_s)`` for every word inside the chunk.
    """
    chunk_end = chunk_offset + len(chunk_text)
    local = [k for k, (s, _) in enumerate(segment.spans) if chunk_offset <= s < chunk_end]
    if not local:
        return []
    starts = [segment.spans[k][0] for k in local]
    times: list[tuple[float, float] | None] = [None] * len(local)

    cursor = 0
    for tok in tokens or []:
        text = getattr(tok, "text", "") or ""
        if not text:
            continue
        pos = chunk_text.find(text, cursor)
        if pos < 0:
            pos = cursor
        else:
            cursor = pos + len(text)
        t0, t1 = getattr(tok, "start_ts", None), getattr(tok, "end_ts", None)
        if t0 is None:
            continue
        absolute = chunk_offset + pos + max(len(text) - 1, 0) // 2
        w = min(max(bisect.bisect_right(starts, absolute) - 1, 0), len(local) - 1)
        t1 = t0 if t1 is None else t1
        prev = times[w]
        times[w] = (t0, t1) if prev is None else (min(prev[0], t0), max(prev[1], t1))

    weights = [segment.spans[k][1] - segment.spans[k][0] for k in local]
    if all(t is None for t in times):
        total = sum(max(w, 1) for w in weights)
        cur, times = 0.0, []  # type: ignore[assignment]
        for w in weights:
            span = duration * max(w, 1) / total
            times.append((cur, cur + span))  # type: ignore[union-attr]
            cur += span
    final = _monotonic(_interpolate_missing(times, weights, duration), duration)
    return [(segment.indices[k], s, e) for k, (s, e) in zip(local, final)]


# -------------------------------------------------------------------- engines
class TTSEngine(ABC):
    """Interface every speech engine implements.

    Attributes:
        name: Short engine name shown in the UI.
        state: ``"loading"``, ``"ready"`` or ``"error"``.
        error: Error message when ``state == "error"``.
        note: Optional hint for the user (e.g. why the fallback engine is active).
        device: Compute device description.
    """

    name = "engine"
    state = "loading"
    error = ""
    note = ""
    device = "cpu"

    @abstractmethod
    def voices(self) -> list[VoiceInfo]:
        """Return the voice presets this engine offers."""

    @abstractmethod
    def warm_up(self) -> None:
        """Load models eagerly; sets :attr:`state`. Safe to call from a thread."""

    @abstractmethod
    def synthesize(self, segment: Segment, voice: str, speed: float) -> Iterator[AudioChunk]:
        """Synthesise one segment.

        Args:
            segment: Text and word spans to speak.
            voice: Voice id from :meth:`voices`.
            speed: Speed multiplier (1.0 = normal).

        Yields:
            One or more :class:`AudioChunk` with word timings.
        """


def stream_segments(engine: TTSEngine, segments: Iterable[Segment], voice: str, speed: float) -> Iterator[AudioChunk]:
    """Chain :meth:`TTSEngine.synthesize` over many segments.

    Args:
        engine: Engine to use.
        segments: Segments in reading order.
        voice: Voice id.
        speed: Speed multiplier.

    Yields:
        Audio chunks in reading order.
    """
    for seg in segments:
        yield from engine.synthesize(seg, voice, speed)


class KokoroEngine(TTSEngine):
    """Local Kokoro-82M engine (GPU if PyTorch can see one).

    One shared ``KModel`` backs a ``KPipeline`` per language code, created lazily.
    """

    name = "Kokoro"

    def __init__(self) -> None:
        self._lock = threading.Lock()  # one synthesis step at a time
        self._load_lock = threading.Lock()
        self._model: Any = None
        self._pipelines: dict[str, Any] = {}
        self._repo = "hexgrad/Kokoro-82M"

    def voices(self) -> list[VoiceInfo]:
        """Return the built-in English Kokoro presets."""
        return KOKORO_VOICES

    def _ensure_model(self) -> None:
        """Load PyTorch and the Kokoro model once (thread-safe)."""
        with self._load_lock:
            if self._model is not None:
                return
            import torch
            from kokoro import KModel

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.device = f"cuda ({torch.cuda.get_device_name(0)})" if device == "cuda" else "cpu"
            if device == "cpu":
                self.note = "CUDA not available to PyTorch - running on CPU (slower). See README for the GPU install."
            self._model = KModel(repo_id=self._repo).to(device).eval()
            self._device = device

    def _pipeline(self, voice: str) -> Any:
        """Return (creating if needed) the pipeline for a voice's language.

        Args:
            voice: Voice id; its first letter is the Kokoro language code.
        """
        self._ensure_model()
        lang = voice[0]
        with self._load_lock:
            if lang not in self._pipelines:
                from kokoro import KPipeline

                self._pipelines[lang] = KPipeline(
                    lang_code=lang, repo_id=self._repo, model=self._model, device=self._device
                )
            return self._pipelines[lang]

    def warm_up(self) -> None:
        """Load the model and run a tiny synthesis so the first Play is fast."""
        try:
            pipe = self._pipeline(DEFAULT_VOICE)
            with self._lock:
                for _ in pipe("Ready.", voice=DEFAULT_VOICE):
                    pass
            self.state = "ready"
        except Exception as exc:  # noqa: BLE001
            log.exception("Kokoro failed to load")
            self.state, self.error = "error", f"{type(exc).__name__}: {exc}"

    def synthesize(self, segment: Segment, voice: str, speed: float) -> Iterator[AudioChunk]:
        """Synthesise a segment with Kokoro, aligning token timestamps to words.

        Args:
            segment: Text and word spans to speak.
            voice: Kokoro voice id.
            speed: Speed multiplier passed to Kokoro.

        Yields:
            One chunk per Kokoro result (long segments may yield several).
        """
        pipe = self._pipeline(voice)
        it = iter(pipe(segment.text, voice=voice, speed=speed))
        cursor = 0
        while True:
            with self._lock:
                try:
                    result = next(it)
                except StopIteration:
                    return
            audio = result.audio
            if audio is None:
                continue
            samples = audio.detach().cpu().numpy().astype(np.float32).reshape(-1)
            graphemes = result.graphemes or ""
            offset = segment.text.find(graphemes, cursor)
            if offset < 0:
                offset = cursor
            cursor = offset + len(graphemes)
            duration = len(samples) / SAMPLE_RATE
            times = align_words(segment, graphemes, offset, result.tokens, duration)
            yield AudioChunk(samples, SAMPLE_RATE, times)


class FakeEngine(TTSEngine):
    """Dependency-free engine that "speaks" each word as a short tone.

    Used for UI development, tests and as a fallback when Kokoro is missing.
    Timings are exact, so the highlighting pipeline can be exercised end to end.
    """

    name = "Demo beeps"
    state = "ready"
    device = "none"

    def voices(self) -> list[VoiceInfo]:
        """Return a couple of fake voices (they differ only in pitch)."""
        return [VoiceInfo("af_heart", "Low beep", "Demo"), VoiceInfo("am_adam", "High beep", "Demo")]

    def warm_up(self) -> None:
        """Nothing to load."""

    def synthesize(self, segment: Segment, voice: str, speed: float) -> Iterator[AudioChunk]:
        """Generate one tone per word.

        Args:
            segment: Text and word spans.
            voice: Voice id (selects pitch).
            speed: Speed multiplier (shortens tones).

        Yields:
            A single chunk covering the whole segment.
        """
        base = 220.0 if voice == "af_heart" else 330.0
        parts: list[np.ndarray] = []
        times: list[tuple[int, float, float]] = []
        t = 0.0
        for k, (s, e) in enumerate(segment.spans):
            dur = (0.07 + 0.045 * (e - s)) / max(speed, 0.1)
            n = int(dur * SAMPLE_RATE)
            x = np.arange(n) / SAMPLE_RATE
            env = np.minimum(1.0, np.minimum(x, dur - x) * 60.0)
            parts.append((0.15 * env * np.sin(2 * np.pi * (base + 18 * (k % 5)) * x)).astype(np.float32))
            times.append((segment.indices[k], t, t + dur))
            t += dur
        gap = np.zeros(int(0.15 * SAMPLE_RATE), dtype=np.float32)
        yield AudioChunk(np.concatenate([*parts, gap]), SAMPLE_RATE, times)


def create_engine(settings: Settings) -> TTSEngine:
    """Choose the speech engine for this run.

    Args:
        settings: Application settings (``fake_tts`` forces the demo engine).

    Returns:
        A :class:`KokoroEngine` when ``kokoro`` and ``torch`` are importable,
        otherwise a :class:`FakeEngine` with an explanatory note.
    """
    if settings.fake_tts:
        return FakeEngine()
    if importlib.util.find_spec("kokoro") and importlib.util.find_spec("torch"):
        return KokoroEngine()
    engine = FakeEngine()
    engine.note = "Kokoro/PyTorch not installed - using demo beeps. See README to install the real voices."
    return engine
