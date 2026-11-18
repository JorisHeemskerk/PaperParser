#!/usr/bin/env python3
"""Find out which Kokoro voices stay intelligible at high speed.

For every voice x speed the script synthesises a test passage, transcribes the
audio back with Whisper (faster-whisper) and reports the word error rate (WER).
Lower is better. It also saves every clip as a .wav so you can *listen* to the
shortlist: WER measures intelligibility, not how pleasant or tiring a voice is,
and Whisper is forgiving, so treat it as a filter, not a verdict.

Extra dependency (not in requirements.txt):
    pip install faster-whisper

Usage:
    python tools/voice_speed_benchmark.py
    python tools/voice_speed_benchmark.py --voices af_heart af_bella bf_emma --speeds 1.5 2 2.5 3
    python tools/voice_speed_benchmark.py --voices all --text-file my_paragraph.txt
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import soundfile as sf
import torch
from faster_whisper import WhisperModel
from kokoro import KModel, KPipeline

from paperparser.tts import KOKORO_VOICES


SAMPLE_RATE = 24000
DEFAULT_TEXT = (
    "We propose a transformer based architecture for long document summarization. "
    "Our method reduces memory consumption by 38 percent while improving ROUGE scores "
    "on three benchmark datasets. In Section 4, we analyze the effect of the attention "
    "window size, and we show that smaller windows degrade performance only marginally. "
    "Finally, we discuss limitations, including sensitivity to hyperparameters."
)
DEFAULT_VOICES = ["af_heart", "af_bella", "af_nicole", "af_sarah", "af_kore", "af_aoede",
                  "am_michael", "am_fenrir", "am_puck", "bf_emma"]


def normalize(text: str) -> list[str]:
    """Lower-case text and split it into plain words for WER scoring.

    Args:
        text: Raw text (reference or transcript).

    Returns:
        Words without punctuation. Hyphens split words ("state-of-the-art" -> 4 words).
    """
    return re.sub(r"[^a-z0-9% ]+", " ", text.lower().replace("-", " ")).split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Compute the word error rate between two texts.

    Args:
        reference: What should have been said.
        hypothesis: What the speech recogniser heard.

    Returns:
        ``(substitutions + deletions + insertions) / len(reference words)``;
        can exceed 1.0 when many extra words are inserted.
    """
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1] / len(ref)


def synthesize(pipelines: dict, make_pipeline, voice: str, speed: float, text: str) -> np.ndarray:
    """Synthesise a text with one voice at one speed.

    Args:
        pipelines: Cache of ``KPipeline`` objects keyed by language code (mutated).
        make_pipeline: Callable ``lang_code -> KPipeline``.
        voice: Kokoro voice id.
        speed: Kokoro speed multiplier.
        text: Text to speak.

    Returns:
        Mono float32 audio at 24 kHz.
    """
    lang = voice[0]
    if lang not in pipelines:
        pipelines[lang] = make_pipeline(lang)
    chunks = [r.audio.detach().cpu().numpy().reshape(-1) for r in pipelines[lang](text, voice=voice, speed=speed) if r.audio is not None]
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(1, dtype=np.float32)


def _add_nvidia_dll_dirs() -> None:
    """Make pip-installed CUDA 12 libraries (``nvidia-cublas-cu12`` etc.) visible on Windows.

    CTranslate2 (faster-whisper's engine) needs CUDA 12 DLLs such as
    ``cublas64_12.dll``; a system CUDA 13 install does not provide them. The pip
    packages put them in ``site-packages/nvidia/*/bin``, which Windows does not
    search by default.
    """
    if sys.platform != "win32":
        return
    import site

    for base in site.getsitepackages():
        for bin_dir in Path(base, "nvidia").glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def _default_whisper_factory(model_name: str, device: str):
    """Create a faster-whisper model.

    Args:
        model_name: Model size, e.g. ``small.en``.
        device: ``cuda`` or ``cpu``.

    Returns:
        A ``WhisperModel`` instance.
    """

    if device == "cuda":
        _add_nvidia_dll_dirs()
    return WhisperModel(model_name, device=device, compute_type="float16" if device == "cuda" else "int8")


class Transcriber:
    """Whisper wrapper that falls back to the CPU when the GPU libraries are missing.

    Args:
        model_name: faster-whisper model size.
        device: Preferred device, ``cuda`` or ``cpu``.
        factory: Callable ``(model_name, device) -> model``; injectable for tests.
    """

    def __init__(self, model_name: str, device: str, factory=_default_whisper_factory) -> None:
        self.model_name, self.device, self._factory, self._model = model_name, device, factory, None

    def _run(self, wav: Path) -> str:
        """Transcribe one file with the current model (loading it lazily).

        Args:
            wav: Audio file path.

        Returns:
            The transcript text.
        """
        if self._model is None:
            self._model = self._factory(self.model_name, self.device)
        segments, _ = self._model.transcribe(str(wav), language="en", beam_size=5)
        return " ".join(seg.text for seg in segments)  # consumes the generator, so CUDA errors surface here

    def transcribe(self, wav: Path) -> str:
        """Transcribe a file, retrying once on the CPU if the GPU run fails.

        Args:
            wav: Audio file path.

        Returns:
            The transcript text.

        Raises:
            RuntimeError: If transcription fails on the CPU as well.
        """
        try:
            return self._run(wav)
        except RuntimeError as exc:
            if self.device == "cpu":
                raise
            print(f"  ! Whisper could not use the GPU ({exc}).\n"
                  "    Falling back to CPU (fine for this benchmark). For GPU Whisper: "
                  "pip install nvidia-cublas-cu12 nvidia-cudnn-cu12")
            self.device, self._model = "cpu", None
            return self._run(wav)


def main() -> None:
    """Run the benchmark and print/save the results."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voices", nargs="+", default=DEFAULT_VOICES, help="Voice ids, or 'all'.")
    ap.add_argument("--speeds", nargs="+", type=float, default=[1.0, 1.5, 2.0, 2.5, 3.0])
    ap.add_argument("--text-file", type=Path, help="Use your own passage (a paper paragraph works best).")
    ap.add_argument("--whisper-device", choices=["auto", "cuda", "cpu"], default="auto",
                    help="Where to run Whisper; 'auto' tries the GPU and falls back to the CPU.")
    ap.add_argument("--whisper", default="small.en", help="faster-whisper model (tiny.en/base.en/small.en/medium.en).")
    ap.add_argument("--out", type=Path, default=Path("voice_benchmark"), help="Output folder for wavs + results.csv.")
    args = ap.parse_args()

    voices = [v.id for v in KOKORO_VOICES] if args.voices == ["all"] else args.voices
    text = args.text_file.read_text(encoding="utf-8") if args.text_file else DEFAULT_TEXT
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device} | voices: {len(voices)} | speeds: {args.speeds}")

    model = KModel(repo_id="hexgrad/Kokoro-82M").to(device).eval()
    pipelines: dict = {}
    make = lambda lang: KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", model=model, device=device)  # noqa: E731
    whisper = Transcriber(args.whisper, device if args.whisper_device == "auto" else args.whisper_device)
    args.out.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[float, float]] = {}
    for voice in voices:
        results[voice] = {}
        for speed in args.speeds:
            audio = synthesize(pipelines, make, voice, speed, text)
            wav = args.out / f"{voice}_{speed:g}x.wav"
            sf.write(wav, audio, SAMPLE_RATE)
            wer = word_error_rate(text, whisper.transcribe(wav))
            results[voice][speed] = wer
            print(f"  {voice:12s} {speed:>4g}x  WER {wer * 100:5.1f}%  ({len(audio) / SAMPLE_RATE:5.1f}s audio)")

    header = f"{'voice':12s}" + "".join(f"{s:>8g}x" for s in args.speeds) + "    mean"
    print("\nWER % (lower = more intelligible), best first by mean over speeds >= 1.5x:\n" + header)
    fast = [s for s in args.speeds if s >= 1.5] or args.speeds
    for voice in sorted(voices, key=lambda v: np.mean([results[v][s] for s in fast])):
        row = "".join(f"{results[voice][s] * 100:8.1f}%" for s in args.speeds)
        print(f"{voice:12s}{row}  {np.mean([results[voice][s] for s in fast]) * 100:6.1f}%")

    with open(args.out / "results.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["voice", *[f"wer_{s:g}x" for s in args.speeds]])
        for voice in voices:
            w.writerow([voice, *[round(results[voice][s], 4) for s in args.speeds]])
    print(f"\nClips and results.csv saved in {args.out.resolve()} - listen to the top few!")


if __name__ == "__main__":
    main()