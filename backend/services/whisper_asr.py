from __future__ import annotations

import os
from typing import Dict, Any, List, Callable, Optional


def transcribe_with_whisper(
    wav_path: str,
    model_size: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
    language: str | None = None,
) -> Dict[str, Any]:
    """Transcribe WAV using faster-whisper and return Gentle-like {"words": [...]}.

    - Uses word-level timestamps; builds a flat list of words with start/end.
    - Keeps shape compatible with the rest of the pipeline (case: "success").
    
    Environment overrides if args are None:
      WHISPER_MODEL (default: "small")
      WHISPER_DEVICE (default: "cpu")
      WHISPER_COMPUTE (default: "int8" on CPU, "float16" on GPU)
      WHISPER_LANGUAGE (optional, e.g. "pl")
    """
    # Lazy import to avoid mandatory dependency when using Gentle
    from faster_whisper import WhisperModel

    model_size = model_size or os.getenv("WHISPER_MODEL", "small")
    device = device or os.getenv("WHISPER_DEVICE", "cpu")
    if compute_type is None:
        # Reasonable defaults
        compute_type = os.getenv("WHISPER_COMPUTE") or ("int8" if device == "cpu" else "float16")
    language = language or os.getenv("WHISPER_LANGUAGE")  # None => auto-detect

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    words_out: List[Dict[str, Any]] = []

    # Transcribe; word_timestamps gives per-word start/end
    segments, info = model.transcribe(
        wav_path,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        language=language,
    )

    for seg in segments:
        for w in getattr(seg, "words", []) or []:
            # Some words may lack times; skip those
            if w.start is None or w.end is None:
                continue
            text = (w.word or "").strip()
            if not text:
                continue
            words_out.append(
                {
                    "word": text,
                    "case": "success",
                    "start": float(w.start),
                    "end": float(w.end),
                    "conf": float(getattr(w, "probability", 0.0)) if hasattr(w, "probability") else None,
                }
            )

    return {"words": words_out}


def transcribe_with_whisper_chunked(
    wav_path: str,
    work_dir: Optional[str] = None,
    status_cb: Optional[Callable[[str, int, int], None]] = None,
    model_size: Optional[str] = None,
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
    language: Optional[str] = None,
    noise: str = "-35dB",
    min_silence: float = 0.35,
    target: float = 20.0,
    min_len: float = 5.0,
    max_len: float = 45.0,
    overlap: float = 0.8,
) -> Dict[str, Any]:
    from faster_whisper import WhisperModel
    from .alignment import (
        ffprobe_duration_seconds,
        detect_silences,
        plan_chunks,
        _extract_wav_segment,
    )
    import os

    model_size = model_size or os.getenv("WHISPER_MODEL", "small")
    device = device or os.getenv("WHISPER_DEVICE", "cpu")
    if compute_type is None:
        compute_type = os.getenv("WHISPER_COMPUTE") or ("int8" if device == "cpu" else "float16")
    language = language or os.getenv("WHISPER_LANGUAGE")

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    duration = ffprobe_duration_seconds(wav_path)
    silences = detect_silences(wav_path, noise=noise, min_silence=min_silence)
    chunks = plan_chunks(duration, silences, target, min_len, max_len, overlap)
    total = max(1, len(chunks))
    completed = 0
    if status_cb:
        status_cb("aligning", completed, total)

    merged: List[Dict[str, Any]] = []
    if work_dir:
        os.makedirs(work_dir, exist_ok=True)

    for idx, ch in enumerate(chunks):
        read_start = ch["read_start"]
        read_end = ch["read_end"]
        out_wav = os.path.join(work_dir or os.path.dirname(wav_path), f"chunk_{idx:04d}.wav")
        _extract_wav_segment(wav_path, out_wav, read_start, read_end)

        segments, info = model.transcribe(
            out_wav,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            language=language,
        )

        left = ch["start"]
        right = ch["end"]
        last_end = merged[-1]["end"] if merged else 0.0
        for seg in segments:
            for w in getattr(seg, "words", []) or []:
                if w.start is None or w.end is None:
                    continue
                gs = read_start + float(w.start)
                ge = read_start + float(w.end)
                if ge <= left - 1e-3:
                    continue
                if gs < left:
                    gs = left
                if ge > right:
                    ge = right
                if gs < last_end:
                    shift = last_end - gs
                    gs += shift
                    ge += shift
                if ge <= gs:
                    continue
                text = (w.word or "").strip()
                if not text:
                    continue
                merged.append({
                    "word": text,
                    "case": "success",
                    "start": gs,
                    "end": ge,
                    "conf": float(getattr(w, "probability", 0.0)) if hasattr(w, "probability") else None,
                })
                last_end = ge

        completed += 1
        if status_cb:
            status_cb("aligning", completed, total)

    return {"words": merged}
