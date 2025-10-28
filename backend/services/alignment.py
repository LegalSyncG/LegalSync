import os
import json
import subprocess
import re
import unicodedata
import difflib
from dataclasses import dataclass
from math import inf
from typing import List, Dict, Any, Tuple, Optional, Iterable, Set
from collections import defaultdict

import requests


def ffprobe_duration_seconds(path: str) -> float:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def detect_silences(wav_path: str, noise: str = "-35dB", min_silence: float = 0.35) -> List[Dict[str, float]]:
    """Run ffmpeg silencedetect and return list of {start, end} for silences."""
    cmd = [
        "ffmpeg",
        "-i",
        wav_path,
        "-af",
        f"silencedetect=noise={noise}:d={min_silence}",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    text = proc.stderr
    silences = []
    starts = []
    for line in text.splitlines():
        if "silence_start:" in line:
            m = re.search(r"silence_start:\s*([0-9.]+)", line)
            if m:
                starts.append(float(m.group(1)))
        elif "silence_end:" in line:
            m = re.search(r"silence_end:\s*([0-9.]+)", line)
            if m:
                end = float(m.group(1))
                if starts:
                    silences.append({"start": starts[-1], "end": end})
    return silences


def plan_chunks(
    duration: float,
    silences: List[Dict[str, float]],
    target: float = 20.0,
    min_len: float = 5.0,
    max_len: float = 45.0,
    overlap: float = 0.8,
) -> List[Dict[str, float]]:
    """Return chunk list: {start, end, read_start, read_end} in seconds.
    Działa dobrze nawet bez ciszy: wówczas tnie co max_len aż do końca.
    """
    silence_ends = sorted({s["end"] for s in silences if 0.0 < s.get("end", 0.0) < duration})
    chunks: List[Dict[str, float]] = []
    pos = 0.0
    # prosty pętla aż do końca pliku
    while pos < duration - 1e-3:
        window_max = min(pos + max_len, duration)
        # kandydaci ciszy w [pos+min_len, window_max]
        min_allowed = pos + min_len
        cand = [t for t in silence_ends if min_allowed <= t <= window_max]
        if cand:
            # wybierz najbliżej targetu
            target_end = pos + target
            end = min(cand, key=lambda t: abs(t - target_end))
        else:
            # brak ciszy — utnij na max_len lub końcu
            end = window_max
        read_start = max(0.0, pos - (overlap if pos > 0 else 0.0))
        read_end = min(duration, end + (overlap if end < duration else 0.0))
        chunks.append({"start": pos, "end": end, "read_start": read_start, "read_end": read_end})
        try:
            print(f"INFO:root:plan chunk {len(chunks)}: {pos:.2f}-{end:.2f} (read {read_start:.2f}-{read_end:.2f})")
        except Exception:
            pass
        pos = end
    return chunks


def _save_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _extract_wav_segment(src_wav: str, out_wav: str, start: float, end: float) -> None:
    """Accurate segment extraction: place -ss after -i to avoid keyframe drift."""
    duration = max(0.0, end - start)
    cmd = [
        "ffmpeg",
        "-y",
        "-i", src_wav,
        "-ss", str(start),
        "-t", str(duration),
        "-ac", "1",
        "-ar", "16000",
        out_wav,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _run_ffmpeg_to_wav(src_audio: str, dst_wav: str) -> None:
    """Convert audio to 16kHz mono WAV using ffmpeg."""
    os.makedirs(os.path.dirname(dst_wav), exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        src_audio,
        "-ac",
        "1",
        "-ar",
        "16000",
        dst_wav,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _tokenize_words(text: str) -> List[str]:
    """Simple Unicode-aware word tokenizer for counting/mapping."""
    tokens: List[str] = []
    buf: List[str] = []
    for ch in text:
        if ch.isalpha() or ch == "'":
            buf.append(ch)
        else:
            if buf:
                tokens.append("".join(buf))
                buf = []
    if buf:
        tokens.append("".join(buf))
    return tokens


_SPLIT_PATTERN = r"([\\p{L}']+|[0-9][0-9.,–—-]*)"  # for frontend hint only


def _normalize_token(tok: str) -> str:
    # Keep Unicode letters and apostrophe; drop others. Lowercase with Unicode.
    t = tok.lower()
    return "".join(ch for ch in t if (ch.isalpha() or ch == "'"))


def _expand_number_token(token: str) -> List[str]:
    """Expand number token to words similar to normalize_for_alignment mapping.
    Handles digits, decimal point, and dashes.
    """
    digit_map = {
        '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
        '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine'
    }
    s = token.replace(',', '')
    out: List[str] = []
    for ch in s:
        if ch in digit_map:
            out.append(digit_map[ch])
        elif ch == '.' or ch == '·':
            out.append('point')
        elif ch in {'-', '–', '—'}:
            out.append('dash')
    return out


def _split_transcript_parts(text: str) -> List[str]:
    # Unicode-aware splitter: groups of letters (any alphabet) and groups of numeric tokens
    parts: List[str] = []
    buf: List[str] = []
    mode: Optional[str] = None  # 'alpha' | 'num' | None
    number_chars = set("0123456789.,–—-")
    for ch in text:
        if ch.isalpha() or ch == "'":
            if mode != 'alpha':
                if buf:
                    parts.append("".join(buf))
                buf = []
                mode = 'alpha'
            buf.append(ch)
        elif ch in number_chars:
            if mode != 'num':
                if buf:
                    parts.append("".join(buf))
                buf = []
                mode = 'num'
            buf.append(ch)
        else:
            if buf:
                parts.append("".join(buf))
                buf = []
            mode = None
            parts.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _build_norm_sequence_from_parts(parts: List[str]) -> Tuple[List[str], List[Tuple[int, Optional[int]]]]:
    """Return (norm_tokens, owners) where owners[i] = (part_index, sub_index or None).
    Alpha tokens create one norm token; numeric tokens expand into multiple norm tokens.
    """
    norm_tokens: List[str] = []
    owners: List[Tuple[int, Optional[int]]] = []
    for idx, part in enumerate(parts):
        if not part:
            continue
        if re.fullmatch(r"[A-Za-z']+", part or ""):
            norm_tokens.append(_normalize_token(part))
            owners.append((idx, None))
        elif re.fullmatch(r"[0-9][0-9.,–—-]*", part or ""):
            exp = _expand_number_token(part)
            for si, w in enumerate(exp):
                norm_tokens.append(_normalize_token(w))
                owners.append((idx, si))
        else:
            # non-word parts ignored in norm sequence
            pass
    return norm_tokens, owners


def _dp_align_blocks(T: List[str], R: List[str], block_size: int = 160, extra: int = 80) -> List[int]:
    """Align T to R using blockwise edit-distance DP, return mapping of len(T) -> index in R or -1.
    Splitting to keep memory/time reasonable on large transcripts.
    """
    def dp_map(subT: List[str], subR: List[str]) -> List[int]:
        n, m = len(subT), len(subR)
        # small dynamic programming edit-distance table
        score = [[0]*(m+1) for _ in range(n+1)]
        back = [[0]*(m+1) for _ in range(n+1)]  # 0 diag, 1 up (del T), 2 left (ins T)
        for i in range(1, n+1):
            score[i][0] = i; back[i][0] = 1
        for j in range(1, m+1):
            score[0][j] = j; back[0][j] = 2
        for i in range(1, n+1):
            Ti = subT[i-1]
            for j in range(1, m+1):
                cost = 0 if Ti == subR[j-1] else 1
                v = score[i-1][j-1] + cost; d = 0
                up = score[i-1][j] + 1
                if up < v:
                    v = up; d = 1
                left = score[i][j-1] + 1
                if left < v:
                    v = left; d = 2
                score[i][j] = v; back[i][j] = d
        # backtrack
        mapping = [-1]*n
        i, j = n, m
        while i > 0 or j > 0:
            d = back[i][j]
            if i > 0 and j > 0 and d == 0:
                mapping[i-1] = j-1
                i -= 1; j -= 1
            elif i > 0 and (j == 0 or d == 1):
                mapping[i-1] = -1
                i -= 1
            else:
                j -= 1
        return mapping

    out = [-1]*len(T)
    r_start = 0
    Rlen = len(R)
    for t0 in range(0, len(T), block_size):
        t1 = min(len(T), t0 + block_size)
        subT = T[t0:t1]
        win_len = min(Rlen - r_start, len(subT)*2 + extra)
        r_end = r_start + max(0, win_len)
        subR = R[r_start:r_end]
        mapping = dp_map(subT, subR)
        last = -1
        for i, mj in enumerate(mapping):
            if mj >= 0:
                out[t0 + i] = r_start + mj
                last = r_start + mj
        if last >= 0:
            r_start = max(last + 1 - 8, r_start)
        else:
            r_start = min(Rlen, r_start + len(subT))
    return out


@dataclass
class RecognizedToken:
    norm: str
    variants: Tuple[str, ...]
    orig_index: int
    start: Optional[float]
    end: Optional[float]
    raw: str
    span: Tuple[int, int]
    is_composite: bool = False


@dataclass
class AlignmentToken:
    norm: str
    variants: Tuple[str, ...]
    part_idx: int
    raw: str


@dataclass
class AnchorCandidate:
    t_idx: int
    r_idx: int
    length: int
    weight: float


_MATCH_VARIANT_COST = 0.18
_MATCH_FUZZY_BASE = 0.4
_MATCH_MISMATCH = 0.7
_DELETE_COST = 0.9
_INSERT_COST = 0.9
_BAND_MIN = 6
_BAND_MAX = 140
_ANCHOR_MIN_SCORE = 2.4


def _strip_diacritics(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def _token_variants(norm: str, raw: Optional[str] = None) -> Tuple[str, ...]:
    variants = set()
    if norm:
        variants.add(norm)
    if raw:
        stripped = _normalize_token(_strip_diacritics(raw.lower()))
        if stripped:
            variants.add(stripped)
    if norm.endswith("s") and len(norm) > 4:
        variants.add(norm[:-1])
    if norm.endswith("es") and len(norm) > 5:
        variants.add(norm[:-2])
    if norm.endswith("ing") and len(norm) > 5:
        variants.add(norm[:-3])
    if norm.endswith("ed") and len(norm) > 4:
        variants.add(norm[:-2])
    variants = {v for v in variants if v}
    return tuple(sorted(variants))


def _levenshtein_distance(a: str, b: str, limit: int = 2) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        min_curr = curr[0]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            val = prev[j] + 1
            ins = curr[j - 1] + 1
            if ins < val:
                val = ins
            sub = prev[j - 1] + cost
            if sub < val:
                val = sub
            curr.append(val)
            if val < min_curr:
                min_curr = val
        if min_curr > limit:
            return limit + 1
        prev = curr
    return prev[-1]


def _identify_speaker_parts(parts: List[str]) -> set[int]:
    speaker_indices: set[int] = set()
    last_break = -1
    for idx, part in enumerate(parts):
        if part == "\n":
            last_break = idx
            continue
        if part != ":":
            continue
        block_start = last_break + 1
        j = idx - 1
        candidate_idxs: List[int] = []
        valid = True
        while j >= block_start:
            seg = parts[j]
            if seg.strip() == "":
                j -= 1
                continue
            if not re.fullmatch(r"[A-Za-z][A-Za-z']*", seg or ""):
                valid = False
                break
            if not seg[0].isupper():
                valid = False
                break
            candidate_idxs.append(j)
            j -= 1
        if not candidate_idxs or not valid:
            continue
        # verify content appears after colon on the same line
        k = idx + 1
        has_content = False
        while k < len(parts):
            seg = parts[k]
            if seg == "\n":
                break
            if seg.strip() == "":
                k += 1
                continue
            if re.fullmatch(r"[A-Za-z0-9']+", seg or ""):
                has_content = True
            break
        if not has_content:
            continue
        for cidx in candidate_idxs:
            speaker_indices.add(cidx)
    return speaker_indices


def _segment_known_token(norm: str, vocab: set[str]) -> Optional[List[str]]:
    """Attempt to split a compound transcript token into known pieces from Whisper vocabulary."""
    if norm in vocab:
        return None
    n = len(norm)
    if n < 6:
        return None
    # try bipartition
    for split in range(2, n - 1):
        left = norm[:split]
        right = norm[split:]
        if left in vocab and right in vocab:
            return [left, right]
    # try tripartition
    for split1 in range(2, n - 2):
        for split2 in range(split1 + 1, n - 1):
            parts = [norm[:split1], norm[split1:split2], norm[split2:]]
            if all(p in vocab for p in parts):
                return parts
    return None


def _build_recognized_token_sequence(
    recognized_words: List[Dict[str, Any]],
    transcript_terms: Optional[Set[str]] = None,
    max_compound_len: int = 3,
) -> Tuple[List[RecognizedToken], set[str]]:
    """Preprocess Whisper output into normalized tokens and build a vocabulary of variants."""
    base_tokens: List[RecognizedToken] = []
    vocab: set[str] = set()
    for idx, w in enumerate(recognized_words):
        raw = (w.get("word") or "").strip()
        norm = _normalize_token(raw)
        if not norm and raw:
            stripped = _strip_diacritics(raw.lower())
            norm = _normalize_token(stripped)
        # If still no norm but raw looks like a number, expand into per-digit words
        if not norm and re.fullmatch(r"[0-9][0-9.,–—-]*", raw or ""):
            exp = _expand_number_token(raw)
            for si, wnorm in enumerate(exp):
                v = _token_variants(wnorm, raw)
                token = RecognizedToken(
                    norm=wnorm,
                    variants=v if v else (wnorm,),
                    orig_index=idx,
                    start=w.get("start"),
                    end=w.get("end"),
                    raw=raw.lower(),
                    span=(idx, idx),
                    is_composite=False,
                )
                base_tokens.append(token)
                vocab.update(token.variants or (token.norm,))
            continue
        if not norm:
            continue
        variants = _token_variants(norm, raw)
        token = RecognizedToken(
            norm=norm,
            variants=variants if variants else (norm,),
            orig_index=idx,
            start=w.get("start"),
            end=w.get("end"),
            raw=raw.lower(),
            span=(idx, idx),
            is_composite=False,
        )
        base_tokens.append(token)
        vocab.update(token.variants or (token.norm,))
    if not transcript_terms:
        return base_tokens, vocab

    tokens: List[RecognizedToken] = []
    n = len(base_tokens)
    i = 0
    while i < n:
        best_len = 0
        combined_norm = ""
        if transcript_terms:
            max_len = min(max_compound_len, n - i)
            for length in range(max_len, 1, -1):
                segment = base_tokens[i : i + length]
                merged_norm = "".join(tok.norm for tok in segment)
                if merged_norm and merged_norm in transcript_terms:
                    raw_has_nonalpha = any(
                        any(ch.isalpha() is False and ch != "'" for ch in (tok.raw or ""))
                        for tok in segment
                    )
                    if raw_has_nonalpha:
                        best_len = length
                        combined_norm = merged_norm
                        segment_has_nonalpha = True
                        break
        if best_len > 1:
            segment = base_tokens[i : i + best_len]
            start_idx = segment[0].span[0]
            end_idx = segment[-1].span[1]
            start_time = segment[0].start
            end_time = segment[-1].end
            raw_concat = "".join((recognized_words[j].get("word") or "") for j in range(start_idx, end_idx + 1))
            variants = {combined_norm}
            variants.add(_normalize_token(raw_concat))
            hyphen_variant = _normalize_token("-".join(tok.norm for tok in segment))
            if hyphen_variant:
                variants.add(hyphen_variant)
            variants = tuple(sorted({v for v in variants if v}))
            token = RecognizedToken(
                norm=combined_norm,
                variants=variants if variants else (combined_norm,),
                orig_index=start_idx,
                start=start_time,
                end=end_time,
                raw=raw_concat.lower(),
                span=(start_idx, end_idx),
                is_composite=True,
            )
            tokens.append(token)
            vocab.update(token.variants)
            i += best_len
        else:
            tokens.append(base_tokens[i])
            i += 1
    return tokens, vocab


def _build_transcript_alignment_tokens(
    parts: List[str],
    recognized_vocab: set[str],
) -> Tuple[List[AlignmentToken], List[int]]:
    """Tokenize user transcript while skipping speaker labels and expanding compounds/numbers."""
    tokens: List[AlignmentToken] = []
    owners: List[int] = []
    speaker_indices = _identify_speaker_parts(parts)
    for idx, part in enumerate(parts):
        if not part:
            continue
        if idx in speaker_indices:
            continue
        if re.fullmatch(r"[A-Za-z']+", part or ""):
            norm = _normalize_token(part)
            if not norm:
                continue
            pieces = _segment_known_token(norm, recognized_vocab) or [norm]
            for piece in pieces:
                variants = _token_variants(piece, part)
                tokens.append(AlignmentToken(norm=piece, variants=variants if variants else (piece,), part_idx=idx, raw=part))
                owners.append(idx)
        elif re.fullmatch(r"[0-9][0-9.,–—-]*", part or ""):
            expanded = _expand_number_token(part)
            for exp in expanded:
                norm = _normalize_token(exp)
                if not norm:
                    continue
                variants = _token_variants(norm, exp)
                tokens.append(AlignmentToken(norm=norm, variants=variants if variants else (norm,), part_idx=idx, raw=part))
                owners.append(idx)
    return tokens, owners


def _collect_ngram_positions(seq: List[str], n: int) -> Dict[Tuple[str, ...], List[int]]:
    out: Dict[Tuple[str, ...], List[int]] = defaultdict(list)
    if n <= 0 or len(seq) < n:
        return out
    for i in range(len(seq) - n + 1):
        ngram = tuple(seq[i : i + n])
        out[ngram].append(i)
    return out


def _generate_anchor_candidates(
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
    n_values: Iterable[int] = (5, 4, 3),
) -> List[AnchorCandidate]:
    """Harvest rare n-gram matches as potential monotonic anchors."""
    candidates: Dict[Tuple[int, int, int], AnchorCandidate] = {}
    t_norms = [tok.norm for tok in transcript_tokens]
    r_norms = [tok.norm for tok in recognized_tokens]
    for n in n_values:
        t_map = _collect_ngram_positions(t_norms, n)
        r_map = _collect_ngram_positions(r_norms, n)
        for ngram, t_positions in t_map.items():
            r_positions = r_map.get(ngram)
            if not r_positions:
                continue
            if len(r_positions) > 6 or len(t_positions) > 6:
                continue
            base_weight = (n * 1.6) / (len(r_positions) + len(t_positions))
            for ti in t_positions:
                for rj in r_positions:
                    key = (ti, rj, n)
                    cand = AnchorCandidate(t_idx=ti, r_idx=rj, length=n, weight=base_weight)
                    prev = candidates.get(key)
                    if prev is None or cand.weight > prev.weight:
                        candidates[key] = cand
    return list(candidates.values())


def _generate_unique_anchor_candidates(
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
    n: int,
) -> List[AnchorCandidate]:
    """Return anchors for n-grams that appear exactly once in both sequences."""
    if n <= 0:
        return []
    t_norms = [tok.norm for tok in transcript_tokens]
    r_norms = [tok.norm for tok in recognized_tokens]
    t_map = _collect_ngram_positions(t_norms, n)
    r_map = _collect_ngram_positions(r_norms, n)
    anchors: List[AnchorCandidate] = []
    for ngram, t_positions in t_map.items():
        if len(t_positions) != 1:
            continue
        r_positions = r_map.get(ngram)
        if not r_positions or len(r_positions) != 1:
            continue
        ti = t_positions[0]
        rj = r_positions[0]
        anchors.append(AnchorCandidate(t_idx=ti, r_idx=rj, length=n, weight=float(n) * 10.0))
    return anchors


def _strict_anchor_chain(
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
) -> List[AnchorCandidate]:
    """Build monotonic anchor chain from unique 5/4/3-grams to stabilize alignment."""
    candidates: List[AnchorCandidate] = []
    for n in (5, 4, 3):
        candidates.extend(_generate_unique_anchor_candidates(transcript_tokens, recognized_tokens, n))
    if not candidates:
        return []
    candidates.sort(key=lambda c: (-c.length, c.r_idx, c.t_idx))
    chain = _select_anchor_chain(candidates)
    if not chain:
        return []
    ratio = len(recognized_tokens) / max(1, len(transcript_tokens))
    filtered: List[AnchorCandidate] = []
    last_t_end = -1
    last_r_end = -1
    for anchor in sorted(chain, key=lambda c: (c.r_idx, c.t_idx)):
        if anchor.t_idx <= last_t_end or anchor.r_idx <= last_r_end:
            continue
        predicted = anchor.t_idx * ratio
        if abs(anchor.r_idx - predicted) > max(45, 0.25 * predicted):
            continue
        filtered.append(anchor)
        last_t_end = anchor.t_idx + anchor.length - 1
        last_r_end = anchor.r_idx + anchor.length - 1
    return filtered


def _sequence_matcher_anchors(
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
    min_size: int = 5,
) -> List[AnchorCandidate]:
    """Use difflib to locate long common subsequences as anchors."""
    if not transcript_tokens or not recognized_tokens:
        return []
    t_norms = [tok.norm for tok in transcript_tokens]
    r_norms = [tok.norm for tok in recognized_tokens]
    matcher = difflib.SequenceMatcher(None, t_norms, r_norms, autojunk=False)
    blocks = matcher.get_matching_blocks()
    anchors: List[AnchorCandidate] = []
    ratio = len(recognized_tokens) / max(1, len(transcript_tokens))
    for block in blocks:
        if block.size is None or block.size < min_size:
            continue
        predicted = block.a * ratio
        if abs(block.b - predicted) > max(40, predicted * 0.22):
            continue
        anchors.append(
            AnchorCandidate(
                t_idx=block.a,
                r_idx=block.b,
                length=block.size,
                weight=float(block.size) * 8.0,
            )
        )
    anchors.sort(key=lambda a: a.t_idx)
    filtered: List[AnchorCandidate] = []
    last_t = -1
    last_r = -1
    for anchor in anchors:
        if anchor.t_idx <= last_t or anchor.r_idx <= last_r:
            continue
        filtered.append(anchor)
        last_t = anchor.t_idx + anchor.length - 1
        last_r = anchor.r_idx + anchor.length - 1
    return filtered


def _windowed_ngram_chain(
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
    n: int = 5,
    window: int = 80,
    step: int = 1,
) -> List[AnchorCandidate]:
    """Scan transcript for n-grams that appear near the predicted position in recognition."""
    if n <= 0 or not transcript_tokens or not recognized_tokens:
        return []
    t_norms = [tok.norm for tok in transcript_tokens]
    r_norms = [tok.norm for tok in recognized_tokens]
    if len(t_norms) < n or len(r_norms) < n:
        return []
    t_map = _collect_ngram_positions(t_norms, n)
    r_map = _collect_ngram_positions(r_norms, n)
    ratio = len(recognized_tokens) / max(1, len(transcript_tokens))
    anchors: List[AnchorCandidate] = []
    last_r = -1
    i = 0
    while i <= len(t_norms) - n:
        ngram = tuple(t_norms[i : i + n])
        r_positions = r_map.get(ngram)
        if r_positions:
            predicted = int(round(i * ratio))
            # Filter candidates near predicted location and respecting monotonicity
            valid = [r for r in r_positions if r > last_r and abs(r - predicted) <= window]
            if valid:
                chosen = min(valid, key=lambda r: (abs(r - predicted), r))
                anchors.append(AnchorCandidate(t_idx=i, r_idx=chosen, length=n, weight=float(n) * 5.0))
                last_r = chosen + n - 1
                i += max(n, step)
                continue
        i += max(1, step)
    return anchors


def _sequence_matcher_full_mapping(
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
) -> List[int]:
    n = len(transcript_tokens)
    if n == 0:
        return []
    m = len(recognized_tokens)
    if m == 0:
        return [-1] * n
    t_norms = [tok.norm for tok in transcript_tokens]
    r_norms = [tok.norm for tok in recognized_tokens]
    matcher = difflib.SequenceMatcher(None, t_norms, r_norms, autojunk=False)
    mapping = [-1] * n
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            span = min(i2 - i1, j2 - j1)
            for offset in range(span):
                mapping[i1 + offset] = j1 + offset
        else:
            subT = transcript_tokens[i1:i2]
            subR = recognized_tokens[j1:j2]
            if not subT or not subR:
                continue
            est_band = abs((i2 - i1) - (j2 - j1)) + 40
            sub_map = _banded_align_subsequence(subT, subR, initial_band=min(_BAND_MAX, max(_BAND_MIN, est_band)))
            last_r = -1
            for local_i, local_j in sorted(sub_map.items()):
                g_r = j1 + local_j
                if g_r <= last_r:
                    continue
                mapping[i1 + local_i] = g_r
                last_r = g_r
    return mapping


def _refine_drift_segments(
    mapping: List[int],
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
    ratio: float,
    threshold: float = 75.0,
    sustain: int = 12,
) -> List[int]:
    """Detect long stretches where mapping drifts far from predicted index and realign locally."""
    n = len(mapping)
    if n == 0 or not recognized_tokens:
        return mapping
    refined = mapping[:]
    m = len(recognized_tokens)

    def find_prev(idx: int) -> Optional[int]:
        for j in range(idx - 1, -1, -1):
            mj = refined[j]
            if mj >= 0:
                return mj
        return None

    def find_next(idx: int) -> Optional[int]:
        for j in range(idx + 1, n):
            mj = refined[j]
            if mj >= 0:
                return mj
        return None

    segments: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i, mj in enumerate(mapping):
        if mj < 0:
            continue
        expected = i * ratio
        if abs(mj - expected) > threshold:
            if start is None:
                start = i
            end = i
        else:
            if start is not None and end - start + 1 >= sustain:
                segments.append((start, end))
            start = None
    if start is not None:
        segments.append((start, n - 1))

    if not segments:
        return refined

    for t_start, t_end in segments:
        prev_r = find_prev(t_start)
        next_r = find_next(t_end)
        window_margin = int(max(30, threshold * 0.6))
        if prev_r is not None:
            r_lo = max(0, prev_r - window_margin)
        else:
            r_lo = max(0, int(t_start * ratio) - window_margin)
        if next_r is not None:
            r_hi = min(m, next_r + window_margin)
        else:
            r_hi = min(m, int((t_end + 1) * ratio) + window_margin)
        if r_lo >= r_hi:
            continue
        local = _banded_align_subsequence(
            transcript_tokens[t_start : t_end + 1],
            recognized_tokens[r_lo:r_hi],
            initial_band=min(90, window_margin + 40),
        )
        if not local:
            continue
        last_r = -1
        for offset, mj in local.items():
            g_r = r_lo + mj
            if g_r < r_lo or g_r >= r_hi:
                continue
            if g_r <= last_r:
                continue
            refined[t_start + offset] = g_r
            last_r = g_r
    return refined


def _prefer_local_monotonic_matches(
    mapping: List[int],
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
    recognized_words: List[Dict[str, Any]],
    max_search: int = 40,
) -> List[int]:
    """Post-process mapping to prefer locally nearest recognized token by time and enforce monotonicity.

    This tries to avoid mapping a transcript token to a late re-occurrence of the same word
    far ahead in the recording. It scans forward from the last assigned recognized index and
    picks the earliest matching recognized token with a valid timing within a small search window.
    """
    if not transcript_tokens or not recognized_tokens:
        return mapping
    n = len(mapping)
    m = len(recognized_tokens)
    prev_r = -1
    last_end = None
    for t_i in range(n):
        t_norm = transcript_tokens[t_i].norm if t_i < len(transcript_tokens) else None
        # search candidates starting from prev_r+1 up to a limited window
        start_j = prev_r + 1
        end_j = min(m - 1, start_j + max_search)
        candidates: List[Tuple[int, Optional[float]]] = []
        for j in range(start_j, end_j + 1):
            try:
                if recognized_tokens[j].norm != t_norm:
                    continue
            except Exception:
                continue
            # determine approximate start time for this recognized token
            start_time: Optional[float] = None
            span = getattr(recognized_tokens[j], 'span', None)
            if span and isinstance(span, tuple) and span[0] is not None:
                si = span[0]
                if 0 <= si < len(recognized_words):
                    start_time = recognized_words[si].get('start')
            if start_time is None:
                oi = getattr(recognized_tokens[j], 'orig_index', None)
                if oi is not None and 0 <= oi < len(recognized_words):
                    start_time = recognized_words[oi].get('start')
            candidates.append((j, start_time))

        chosen = None
        if candidates:
            # Prefer the earliest candidate that is not earlier than last_end (if last_end known)
            if last_end is not None:
                ge = [c for c in candidates if c[1] is not None and c[1] >= last_end - 1e-3]
                if ge:
                    chosen = min(ge, key=lambda c: c[1])
            if chosen is None:
                # fallback: choose candidate with earliest start_time, or lowest index
                with_time = [c for c in candidates if c[1] is not None]
                if with_time:
                    chosen = min(with_time, key=lambda c: c[1])
                else:
                    chosen = min(candidates, key=lambda c: c[0])

        if chosen:
            new_r = chosen[0]
            mapping[t_i] = new_r
            prev_r = new_r
            # update last_end from candidate's span end if available
            span = getattr(recognized_tokens[new_r], 'span', None)
            end_time = None
            if span and isinstance(span, tuple) and span[1] is not None:
                ei = span[1]
                if 0 <= ei < len(recognized_words):
                    end_time = recognized_words[ei].get('end')
            if end_time is None:
                oi = getattr(recognized_tokens[new_r], 'orig_index', None)
                if oi is not None and 0 <= oi < len(recognized_words):
                    end_time = recognized_words[oi].get('end')
            if end_time is not None:
                last_end = end_time
            elif chosen[1] is not None:
                last_end = chosen[1]
        else:
            # no candidate found in window, if existing mapping is forward of prev_r keep it
            r_existing = mapping[t_i]
            if r_existing is not None and r_existing > prev_r:
                prev_r = r_existing
                # update last_end from existing mapping
                span = getattr(recognized_tokens[r_existing], 'span', None)
                if span and isinstance(span, tuple) and span[1] is not None:
                    ei = span[1]
                    if 0 <= ei < len(recognized_words):
                        last_end = recognized_words[ei].get('end')
    return mapping


def _force_earliest_greedy_mapping(
    mapping: List[int],
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
) -> List[int]:
    """Greedy pass: for each transcript token pick the earliest recognized token >= prev_r+1
    that matches (prefer exact/variant, fallback to fuzzy). This enforces monotonic earliest mapping
    and avoids jumping to later re-occurrences of the same phrase.
    """
    n = len(mapping)
    m = len(recognized_tokens)
    if n == 0 or m == 0:
        return mapping
    prev_r = -1
    for t_i in range(n):
        # if already mapped and monotonic, accept and advance
        r_existing = mapping[t_i] if t_i < len(mapping) else -1
        if r_existing is not None and r_existing >= 0 and r_existing > prev_r:
            prev_r = r_existing
            continue
        chosen = None
        # first pass: exact or variant
        for r in range(prev_r + 1, m):
            try:
                cost, qual = _pair_cost(transcript_tokens[t_i], recognized_tokens[r])
            except Exception:
                continue
            if qual in ("exact", "variant"):
                chosen = r
                break
        # second pass: fuzzy allowed
        if chosen is None:
            for r in range(prev_r + 1, m):
                try:
                    cost, qual = _pair_cost(transcript_tokens[t_i], recognized_tokens[r])
                except Exception:
                    continue
                if qual == "fuzzy":
                    chosen = r
                    break
        if chosen is not None:
            mapping[t_i] = chosen
            prev_r = chosen
        else:
            # leave as -1; do not advance prev_r
            mapping[t_i] = -1
    return mapping


def _force_earliest_monotonic_mapping(
    mapping: List[int],
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
    recognized_words: List[Dict[str, Any]],
    max_cost: float = 0.8,
) -> List[int]:
    """Enforce monotonic mapping that picks the earliest acceptable recognized token for each transcript token.

    For each transcript token in order, search from prev_r+1 forward for the earliest recognized token
    that is an acceptable match (based on _pair_cost) and prefer recognized tokens that have timing info.
    This avoids mapping to a later re-occurrence when an earlier occurrence exists.
    """
    n = len(mapping)
    m = len(recognized_tokens)
    if n == 0 or m == 0:
        return mapping
    new_map = [-1] * n
    prev_r = -1
    for t_i in range(n):
        t_tok = transcript_tokens[t_i] if t_i < len(transcript_tokens) else None
        if t_tok is None:
            continue
        # if existing mapping is >= prev_r+1 and acceptable, keep it
        existing = mapping[t_i] if t_i < len(mapping) else -1
        if existing is not None and existing >= prev_r + 1 and existing < m:
            cost, quality = _pair_cost(t_tok, recognized_tokens[existing])
            if cost <= max_cost:
                new_map[t_i] = existing
                prev_r = existing
                continue

        chosen = -1
        chosen_has_time = False
        # predicted index (where token likely belongs) used to prefer nearby candidates
        ratio = m / max(1, n)
        predicted = int(round(t_i * ratio))
        window = max(20, int(max(40, predicted * 0.18)))
        # 1) try exact/variant with timing within window
        for j in range(prev_r + 1, m):
            if j < predicted - window or j > predicted + window:
                continue
            r_tok = recognized_tokens[j]
            cost, quality = _pair_cost(t_tok, r_tok)
            if cost > max_cost:
                continue
            if quality not in ('exact', 'variant'):
                continue
            # check timing availability
            has_time = False
            sp = getattr(r_tok, 'span', None)
            if sp and isinstance(sp, tuple) and sp[0] is not None and sp[1] is not None:
                si, ei = sp
                if 0 <= si < len(recognized_words) and 0 <= ei < len(recognized_words):
                    s = recognized_words[si].get('start')
                    e = recognized_words[ei].get('end')
                    if s is not None and e is not None:
                        has_time = True
            oi = getattr(r_tok, 'orig_index', None)
            if not has_time and oi is not None and 0 <= oi < len(recognized_words):
                if recognized_words[oi].get('start') is not None:
                    has_time = True
            if has_time:
                chosen = j
                chosen_has_time = True
                break
        if chosen == -1:
            # 2) earliest exact/variant with time (no window constraint)
            for j in range(prev_r + 1, m):
                r_tok = recognized_tokens[j]
                cost, quality = _pair_cost(t_tok, r_tok)
                if cost > max_cost:
                    continue
                if quality not in ('exact', 'variant'):
                    continue
                has_time = False
                sp = getattr(r_tok, 'span', None)
                if sp and isinstance(sp, tuple) and sp[0] is not None and sp[1] is not None:
                    si, ei = sp
                    if 0 <= si < len(recognized_words) and 0 <= ei < len(recognized_words):
                        s = recognized_words[si].get('start')
                        e = recognized_words[ei].get('end')
                        if s is not None and e is not None:
                            has_time = True
                oi = getattr(r_tok, 'orig_index', None)
                if not has_time and oi is not None and 0 <= oi < len(recognized_words):
                    if recognized_words[oi].get('start') is not None:
                        has_time = True
                if has_time:
                    chosen = j
                    chosen_has_time = True
                    break
        if chosen == -1:
            # 3) earliest exact/variant regardless of timing
            for j in range(prev_r + 1, m):
                r_tok = recognized_tokens[j]
                cost, quality = _pair_cost(t_tok, r_tok)
                if cost > max_cost:
                    continue
                if quality in ('exact', 'variant'):
                    chosen = j
                    break
        if chosen == -1:
            # 4) fallback to fuzzy within window with timing
            for j in range(prev_r + 1, m):
                if j < predicted - window or j > predicted + window:
                    continue
                r_tok = recognized_tokens[j]
                cost, quality = _pair_cost(t_tok, r_tok)
                if cost > max_cost:
                    continue
                if quality == 'fuzzy':
                    # check timing
                    has_time = False
                    sp = getattr(r_tok, 'span', None)
                    if sp and isinstance(sp, tuple) and sp[0] is not None and sp[1] is not None:
                        si, ei = sp
                        if 0 <= si < len(recognized_words) and 0 <= ei < len(recognized_words):
                            s = recognized_words[si].get('start')
                            e = recognized_words[ei].get('end')
                            if s is not None and e is not None:
                                has_time = True
                    oi = getattr(r_tok, 'orig_index', None)
                    if not has_time and oi is not None and 0 <= oi < len(recognized_words):
                        if recognized_words[oi].get('start') is not None:
                            has_time = True
                    if has_time:
                        chosen = j
                        chosen_has_time = True
                        break
        if chosen == -1:
            # 5) final fallback: first fuzzy
            for j in range(prev_r + 1, m):
                r_tok = recognized_tokens[j]
                cost, quality = _pair_cost(t_tok, r_tok)
                if cost <= max_cost and quality == 'fuzzy':
                    chosen = j
                    break

        if chosen != -1:
            new_map[t_i] = chosen
            prev_r = chosen
        else:
            new_map[t_i] = -1
    return new_map


def _select_anchor_chain(candidates: List[AnchorCandidate]) -> List[AnchorCandidate]:
    """Pick a weighted increasing subsequence of anchors that maximizes coverage."""
    if not candidates:
        return []
    candidates = sorted(candidates, key=lambda c: (c.r_idx, c.t_idx))
    n = len(candidates)
    scores = [cand.weight for cand in candidates]
    prev = [-1] * n
    best_score = float("-inf")
    best_idx = -1
    for i in range(n):
        ti_start = candidates[i].t_idx
        ti_end = ti_start + candidates[i].length - 1
        ri_start = candidates[i].r_idx
        ri_end = ri_start + candidates[i].length - 1
        for j in range(i):
            tj_start = candidates[j].t_idx
            tj_end = tj_start + candidates[j].length - 1
            rj_start = candidates[j].r_idx
            rj_end = rj_start + candidates[j].length - 1
            if tj_end >= ti_start or rj_end >= ri_start:
                continue
            gap_t = ti_start - tj_end - 1
            gap_r = ri_start - rj_end - 1
            penalty = 0.08 * abs(gap_t - gap_r) + 0.02 * max(0, gap_t - 40) + 0.02 * max(0, gap_r - 40)
            score = scores[j] + candidates[i].weight - penalty
            if score > scores[i]:
                scores[i] = score
                prev[i] = j
        if scores[i] > best_score:
            best_score = scores[i]
            best_idx = i
    if best_idx == -1 or best_score < _ANCHOR_MIN_SCORE:
        return []
    chain: List[AnchorCandidate] = []
    cur = best_idx
    while cur != -1:
        chain.append(candidates[cur])
        cur = prev[cur]
    chain.reverse()
    # ensure strictly increasing order in transcript indices
    chain.sort(key=lambda c: c.t_idx)
    return chain


def _pair_cost(t_token: AlignmentToken, r_token: RecognizedToken) -> Tuple[float, str]:
    if not t_token.norm or not r_token.norm:
        return (_MATCH_MISMATCH, "mismatch")
    if t_token.norm == r_token.norm:
        return (0.0, "exact")
    t_variants = set(t_token.variants)
    r_variants = set(r_token.variants)
    if t_variants & r_variants:
        return (_MATCH_VARIANT_COST, "variant")
    dist = _levenshtein_distance(t_token.norm, r_token.norm, limit=2)
    if dist <= 2:
        return (_MATCH_FUZZY_BASE + 0.1 * dist, "fuzzy")
    return (_MATCH_MISMATCH, "mismatch")


def _banded_align_subsequence(
    sub_transcript: List[AlignmentToken],
    sub_recognized: List[RecognizedToken],
    initial_band: Optional[int] = None,
) -> Dict[int, int]:
    """Needleman–Wunsch in a Sakoe–Chiba band to align two short token sequences."""
    n = len(sub_transcript)
    m = len(sub_recognized)
    if n == 0 or m == 0:
        return {}
    base_band = initial_band or max(_BAND_MIN, abs(n - m) + 4, int(max(n, m) * 0.35))
    band = min(_BAND_MAX, max(_BAND_MIN, base_band))
    attempts = 0
    back: Dict[Tuple[int, int], Tuple[int, int, str, Optional[str]]] = {}
    while attempts < 3 and band <= _BAND_MAX:
        size = 2 * band + 3
        prev_cost = [inf] * size
        prev_cost[band] = 0.0
        back.clear()
        back[(0, 0)] = (0, 0, "S", None)
        for j in range(1, min(m, band) + 1):
            idx = j - 0 + band
            prev_cost[idx] = j * _INSERT_COST + 0.04 * j
            back[(0, j)] = (0, j - 1, "I", None)
        success = True
        for i in range(1, n + 1):
            curr_cost = [inf] * size
            j_min = max(0, i - band)
            j_max = min(m, i + band)
            row_has_value = False
            for j in range(j_min, j_max + 1):
                band_idx = j - i + band
                if not (0 <= band_idx < size):
                    continue
                best_cost = inf
                best_prev: Optional[Tuple[int, int, str, Optional[str]]] = None
                # match / substitution
                if j > 0:
                    prev_idx = band_idx
                    if 0 <= prev_idx < size and prev_cost[prev_idx] < inf:
                        pair_cost, quality = _pair_cost(sub_transcript[i - 1], sub_recognized[j - 1])
                        cost = prev_cost[prev_idx] + pair_cost
                        if cost < best_cost:
                            best_cost = cost
                            best_prev = (i - 1, j - 1, "M", quality)
                # deletion (skip transcript token)
                prev_idx = band_idx + 1
                if 0 <= prev_idx < size and prev_cost[prev_idx] < inf:
                    cost = prev_cost[prev_idx] + _DELETE_COST + 0.05
                    if cost < best_cost:
                        best_cost = cost
                        best_prev = (i - 1, j, "D", None)
                # insertion (skip recognized token)
                prev_idx = band_idx - 1
                if 0 <= prev_idx < size and curr_cost[prev_idx] < inf:
                    cost = curr_cost[prev_idx] + _INSERT_COST + 0.04
                    if cost < best_cost:
                        best_cost = cost
                        best_prev = (i, j - 1, "I", None)
                if best_prev is not None and best_cost < inf:
                    curr_cost[band_idx] = best_cost
                    back[(i, j)] = best_prev
                    row_has_value = True
            if not row_has_value:
                success = False
                break
            prev_cost = curr_cost
        end_idx = m - n + band
        if not success or not (0 <= end_idx < size):
            attempts += 1
            band = min(_BAND_MAX, band * 2)
            continue
        if prev_cost[end_idx] == inf:
            attempts += 1
            band = min(_BAND_MAX, band * 2)
            continue
        mapping: Dict[int, int] = {}
        i, j = n, m
        seen = set()
        while (i, j) in back:
            prev_i, prev_j, op, quality = back[(i, j)]
            if op == "M" and quality != "mismatch":
                if prev_i not in seen:
                    mapping[prev_i] = prev_j
                    seen.add(prev_i)
            if (prev_i, prev_j) == (i, j):
                break
            i, j = prev_i, prev_j
            if i == 0 and j == 0:
                break
        # ensure monotonicity
        ordered = sorted(mapping.items())
        last_r = -1
        valid = True
        for _, r_idx in ordered:
            if r_idx <= last_r:
                valid = False
                break
            last_r = r_idx
        if not valid:
            attempts += 1
            band = min(_BAND_MAX, band * 2)
            continue
        return mapping
    return {}


def _align_segment_range(
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
    mapping: List[int],
    t_lo: int,
    t_hi: int,
    r_lo: int,
    r_hi: int,
    margin: int = 4,
) -> None:
    """Align a transcript span against a bounded chunk of recognized tokens and update mapping."""
    if t_lo >= t_hi:
        return
    if r_lo >= r_hi:
        return
    adj_lo = max(0, r_lo - margin)
    adj_hi = min(len(recognized_tokens), r_hi + margin)
    if adj_lo >= adj_hi:
        return
    local = _banded_align_subsequence(
        transcript_tokens[t_lo:t_hi],
        recognized_tokens[adj_lo:adj_hi],
    )
    for local_t, local_r in local.items():
        g_t = t_lo + local_t
        if not (0 <= g_t < len(mapping)):
            continue
        if mapping[g_t] != -1:
            continue
        g_r = adj_lo + local_r
        if r_lo < r_hi:
            if g_r < r_lo or g_r >= r_hi:
                continue
        if 0 <= g_r < len(recognized_tokens):
            mapping[g_t] = g_r


def _compute_anchor_mapping(
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
    anchors: List[AnchorCandidate],
    margin: int = 4,
) -> List[int]:
    """Combine anchor matches with banded DP in the gaps to map transcript tokens to Whisper indices."""
    mapping = [-1] * len(transcript_tokens)
    if not transcript_tokens or not recognized_tokens:
        return mapping
    if not anchors:
        _align_segment_range(
            transcript_tokens,
            recognized_tokens,
            mapping,
            0,
            len(transcript_tokens),
            0,
            len(recognized_tokens),
            margin=margin,
        )
        return mapping
    prev_t_end = -1
    prev_r_end = -1
    for anchor in anchors:
        t_start = anchor.t_idx
        r_start = anchor.r_idx
        if t_start > prev_t_end + 1 and r_start > prev_r_end + 1:
            _align_segment_range(
                transcript_tokens,
                recognized_tokens,
                mapping,
                prev_t_end + 1,
                t_start,
                prev_r_end + 1,
                r_start,
                margin=margin,
            )
        # apply anchor span
        for offset in range(anchor.length):
            t_idx = t_start + offset
            r_idx = r_start + offset
            if t_idx >= len(transcript_tokens) or r_idx >= len(recognized_tokens):
                break
            mapping[t_idx] = r_idx
        prev_t_end = min(len(transcript_tokens) - 1, t_start + anchor.length - 1)
        prev_r_end = min(len(recognized_tokens) - 1, r_start + anchor.length - 1)
    if prev_t_end < len(transcript_tokens) - 1 and prev_r_end < len(recognized_tokens) - 1:
        _align_segment_range(
            transcript_tokens,
            recognized_tokens,
            mapping,
            prev_t_end + 1,
            len(transcript_tokens),
            prev_r_end + 1,
            len(recognized_tokens),
            margin=margin,
        )
    return mapping


def _global_alignment_with_band(
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
    ratio: float,
    band: int,
) -> Optional[List[int]]:
    n = len(transcript_tokens)
    m = len(recognized_tokens)
    if n == 0:
        return []
    if m == 0:
        return [-1] * n

    def clamp_center(val: float) -> int:
        return max(0, min(m, int(round(val))))

    back: Dict[Tuple[int, int], Tuple[int, int, str, Optional[str]]] = {}
    prev_cost: List[float] = []
    prev_range: Tuple[int, int] = (0, -1)
    prev_best_j = 0

    for i in range(0, n + 1):
        if i == 0:
            center = 0
        else:
            diag_pred = i * ratio
            local_pred = prev_best_j + ratio
            center = clamp_center(0.6 * diag_pred + 0.4 * local_pred)

        j_min = max(0, center - band)
        j_max = min(m, center + band)
        if prev_range[1] >= prev_range[0]:
            j_min = min(j_min, max(0, prev_range[0] - band // 3))
            j_max = max(j_max, min(m, prev_range[1] + band // 3))
        if i == n:
            j_max = m
            j_min = max(0, min(j_min, m - band))
        if j_min > j_max:
            return None

        size = j_max - j_min + 1
        curr_cost = [float("inf")] * size
        curr_best_cost = float("inf")
        curr_best_j: Optional[int] = None
        center_penalty_ref = center

        if i == 0:
            # Base row: cost grows by insertion penalty
            for offset, j in enumerate(range(j_min, j_max + 1)):
                if offset == 0 and j == 0:
                    cost = 0.0
                    parent = (0, 0, "S", None)
                else:
                    if offset > 0 and curr_cost[offset - 1] < float("inf"):
                        cost = curr_cost[offset - 1] + _INSERT_COST + 0.04
                    else:
                        cost = j * _INSERT_COST + 0.04 * j
                    parent = (0, j - 1, "I", None)
                curr_cost[offset] = cost
                back[(0, j)] = parent
                if cost < curr_best_cost:
                    curr_best_cost = cost
                    curr_best_j = j
            prev_cost = curr_cost
            prev_range = (j_min, j_max)
            prev_best_j = curr_best_j if curr_best_j is not None else 0
            continue

        row_has_value = False
        for offset, j in enumerate(range(j_min, j_max + 1)):
            best_cost = float("inf")
            best_parent: Optional[Tuple[int, int, str, Optional[str]]] = None

            # Diagonal move (match/substitution)
            if j > 0 and prev_range[0] <= j - 1 <= prev_range[1]:
                prev_idx = (j - 1) - prev_range[0]
                base_cost = prev_cost[prev_idx]
                if base_cost < float("inf"):
                    pair_cost, quality = _pair_cost(transcript_tokens[i - 1], recognized_tokens[j - 1])
                    pos_pen = 0.02 * abs(j - center_penalty_ref)
                    cost = base_cost + pair_cost + pos_pen
                    if cost < best_cost:
                        best_cost = cost
                        best_parent = (i - 1, j - 1, "M", quality)

            # Deletion in transcript (skip transcript token)
            if prev_range[0] <= j <= prev_range[1]:
                prev_idx = j - prev_range[0]
                base_cost = prev_cost[prev_idx]
                if base_cost < float("inf"):
                    cost = base_cost + _DELETE_COST + 0.05
                    if cost < best_cost:
                        best_cost = cost
                        best_parent = (i - 1, j, "D", None)

            # Insertion (skip recognized token)
            if offset > 0:
                base_cost = curr_cost[offset - 1]
                if base_cost < float("inf"):
                    cost = base_cost + _INSERT_COST + 0.04
                    if cost < best_cost:
                        best_cost = cost
                        best_parent = (i, j - 1, "I", None)

            if best_parent is None:
                continue
            curr_cost[offset] = best_cost
            back[(i, j)] = best_parent
            row_has_value = True
            if best_cost < curr_best_cost:
                curr_best_cost = best_cost
                curr_best_j = j

        if not row_has_value:
            return None
        prev_cost = curr_cost
        prev_range = (j_min, j_max)
        if curr_best_j is not None:
            prev_best_j = curr_best_j

    final_range = prev_range
    final_costs = prev_cost
    best_j = prev_best_j
    if (n, best_j) not in back:
        best_cost = float("inf")
        chosen_j: Optional[int] = None
        for offset, j in enumerate(range(final_range[0], final_range[1] + 1)):
            cost = final_costs[offset]
            if cost < best_cost and (n, j) in back:
                best_cost = cost
                chosen_j = j
        if chosen_j is None:
            return None
        best_j = chosen_j

    mapping = [-1] * n
    i, j = n, best_j
    seen: set[Tuple[int, int]] = set()
    while True:
        state = back.get((i, j))
        if state is None:
            return None
        prev_i, prev_j, op, quality = state
        if op == "M" and quality != "mismatch":
            if 0 <= prev_i < n:
                mapping[prev_i] = prev_j
        if prev_i == i and prev_j == j:
            break
        i, j = prev_i, prev_j
        if (i, j) in seen:
            break
        seen.add((i, j))
        if i == 0 and j == 0:
            break
    return mapping


def _global_monotonic_mapping(
    transcript_tokens: List[AlignmentToken],
    recognized_tokens: List[RecognizedToken],
    initial_band: Optional[int] = None,
) -> List[int]:
    n = len(transcript_tokens)
    if n == 0:
        return []
    m = len(recognized_tokens)
    if m == 0:
        return [-1] * n
    ratio = m / max(1, n)
    base_band = initial_band or max(_BAND_MIN, int(40 + abs(m - n) * 0.05))
    base_band = min(_BAND_MAX, base_band)
    attempts = 0
    while attempts < 4:
        band = min(_BAND_MAX, base_band * (2 ** attempts))
        mapping = _global_alignment_with_band(transcript_tokens, recognized_tokens, ratio, band)
        if mapping is not None:
            return mapping
        attempts += 1
    return [-1] * n


def build_mapped_parts(transcript_text: str, recognized_words: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return mapping suitable for frontend rendering without client-side matching.

    Produces: { 'split_regex': pattern, 'parts_times': [ {start,end}|None, ... ] }
    where parts come from splitting the full transcript by the shared regex.
    Number tokens aggregate times across their expanded components.
    """
    parts = _split_transcript_parts(transcript_text)
    transcript_terms: Set[str] = set()
    for part in parts:
        if re.fullmatch(r"[A-Za-z']+", part or ""):
            norm = _normalize_token(part)
            if norm:
                transcript_terms.add(norm)
    recognized_tokens, recognized_vocab = _build_recognized_token_sequence(recognized_words, transcript_terms)
    transcript_tokens, owners = _build_transcript_alignment_tokens(parts, recognized_vocab)
    global_mapping = _global_monotonic_mapping(transcript_tokens, recognized_tokens)

    def _coverage(seq: List[int]) -> float:
        if not seq:
            return 0.0
        aligned = sum(1 for val in seq if val >= 0)
        return aligned / len(seq)

    mapping = global_mapping
    method = "global"
    global_coverage = _coverage(global_mapping)
    seqmatch_full_mapping = _sequence_matcher_full_mapping(transcript_tokens, recognized_tokens)
    seqmatch_full_coverage = _coverage(seqmatch_full_mapping)
    if seqmatch_full_coverage >= max(global_coverage + 0.005, 0.9) or (
        seqmatch_full_coverage >= global_coverage - 0.015 and seqmatch_full_coverage >= 0.95
    ):
        mapping = seqmatch_full_mapping
        method = "seqmatch-full"
        global_coverage = seqmatch_full_coverage
    # --- fallback: jeśli pokrycie globalne niskie, spróbuj blokowego DP (_dp_align_blocks) ---
    try:
        if global_coverage < 0.88 and transcript_tokens and recognized_tokens:
            t_norms = [t.norm for t in transcript_tokens]
            r_norms = [r.norm for r in recognized_tokens]
            dp_mapping = _dp_align_blocks(t_norms, r_norms, block_size=200, extra=80)
            dp_cov = _coverage(dp_mapping)
            # zaakceptuj gdy jest zauważalnie lepsze
            if dp_cov > global_coverage + 0.02:
                mapping = dp_mapping
                method = "dp-blocks"
                global_coverage = dp_cov
    except Exception:
        # fallback nie powinien przerwać procesu alignowania
        pass
    chosen_anchors: List[AnchorCandidate] = []
    strict_coverage: Optional[float] = None
    window_coverage: Optional[float] = None
    seqmatch_coverage: Optional[float] = None
    adaptive_coverage: Optional[float] = None

    if transcript_tokens and recognized_tokens:
        strict_anchors = _strict_anchor_chain(transcript_tokens, recognized_tokens)
        if strict_anchors:
            strict_mapping = _compute_anchor_mapping(transcript_tokens, recognized_tokens, strict_anchors, margin=2)
            strict_coverage = _coverage(strict_mapping)
            if strict_coverage >= max(global_coverage + 0.01, 0.92):
                mapping = strict_mapping
                method = "anchor-strict"
                global_coverage = strict_coverage
                chosen_anchors = strict_anchors

    if transcript_tokens and recognized_tokens and global_coverage < 0.995:
        for n in (5, 4):
            window_anchors = _windowed_ngram_chain(transcript_tokens, recognized_tokens, n=n, window=60, step=2)
            if not window_anchors or len(window_anchors) < 2:
                continue
            window_mapping = _compute_anchor_mapping(transcript_tokens, recognized_tokens, window_anchors, margin=3)
            cov = _coverage(window_mapping)
            if cov >= global_coverage:
                mapping = window_mapping
                method = f"anchor-window-{n}"
                global_coverage = cov
                chosen_anchors = window_anchors
                window_coverage = cov
                break

    if transcript_tokens and recognized_tokens and global_coverage < 0.995:
        seqmatch_anchors = _sequence_matcher_anchors(transcript_tokens, recognized_tokens)
        if seqmatch_anchors:
            seqmatch_mapping = _compute_anchor_mapping(transcript_tokens, recognized_tokens, seqmatch_anchors, margin=3)
            seqmatch_coverage = _coverage(seqmatch_mapping)
            if seqmatch_coverage and seqmatch_coverage >= global_coverage:
                mapping = seqmatch_mapping
                method = "anchor-seqmatch"
                global_coverage = seqmatch_coverage
                chosen_anchors = seqmatch_anchors

    if method != "global" and chosen_anchors:
        pass
    elif transcript_tokens and recognized_tokens:
        adaptive_anchors = _select_anchor_chain(_generate_anchor_candidates(transcript_tokens, recognized_tokens))
        if adaptive_anchors:
            adaptive_mapping = _compute_anchor_mapping(transcript_tokens, recognized_tokens, adaptive_anchors)
            adaptive_coverage = _coverage(adaptive_mapping)
            if adaptive_coverage and adaptive_coverage > global_coverage + 0.02:
                mapping = adaptive_mapping
                method = "anchor-adaptive"
                global_coverage = adaptive_coverage
                chosen_anchors = adaptive_anchors

    # snapshot mapping before local refinement so we can compare candidates later
    mapping_pre_refine = mapping[:] if mapping is not None else [-1] * len(transcript_tokens)
    mapping = _refine_drift_segments(mapping, transcript_tokens, recognized_tokens, len(recognized_tokens) / max(1, len(transcript_tokens)))
    # Prefer local monotonic matches to avoid matching to later re-occurrences of the same word
    try:
        mapping = _prefer_local_monotonic_matches(mapping, transcript_tokens, recognized_tokens, recognized_words=recognized_words)
    except Exception:
        pass
    # snapshot after prefer-local pass
    try:
        mapping_after_prefer = mapping[:] if mapping is not None else [-1] * len(transcript_tokens)
    except Exception:
        mapping_after_prefer = [-1] * len(transcript_tokens)
    try:
        mapping = _force_earliest_monotonic_mapping(mapping, transcript_tokens, recognized_tokens, recognized_words)
    except Exception:
        pass
    # snapshot after force-earliest pass
    try:
        mapping_after_force = mapping[:] if mapping is not None else [-1] * len(transcript_tokens)
    except Exception:
        mapping_after_force = [-1] * len(transcript_tokens)

    # Helper: estimate parts_times from a mapping and count nulls for word/number parts
    def _parts_times_from_mapping(mapping_in: List[int]) -> List[Optional[Dict[str, float]]]:
        pt: List[Optional[Dict[str, float]]] = [None for _ in parts]
        idxs_by_part: Dict[int, List[int]] = defaultdict(list)
        for t_idx, r_idx in enumerate(mapping_in):
            if r_idx is None or r_idx < 0:
                continue
            if not (0 <= r_idx < len(recognized_tokens)):
                continue
            r_tok = recognized_tokens[r_idx]
            span = getattr(r_tok, 'span', None)
            start_idx = end_idx = None
            if span and isinstance(span, tuple) and len(span) >= 2 and span[0] is not None:
                start_idx, end_idx = span
            else:
                oi = getattr(r_tok, 'orig_index', None)
                if oi is not None and 0 <= oi < len(recognized_words):
                    start_idx = end_idx = oi
            if start_idx is None:
                continue
            for base_idx in range(max(0, start_idx), min(len(recognized_words), end_idx + 1)):
                idxs_by_part[owners[t_idx]].append(base_idx)
        for p_idx, r_list in idxs_by_part.items():
            starts = [recognized_words[j].get('start') for j in r_list if recognized_words[j].get('start') is not None]
            ends = [recognized_words[j].get('end') for j in r_list if recognized_words[j].get('end') is not None]
            if starts and ends:
                pt[p_idx] = {"start": float(min(starts)), "end": float(max(ends))}
        return pt

    # Only consider word/number parts when counting nulls
    is_word_part = [bool(re.fullmatch(r"[A-Za-z']+", p or "") or re.fullmatch(r"[0-9][0-9.,–—-]*", p or "")) for p in parts]
    try:
        current_parts = _parts_times_from_mapping(mapping)
        current_nulls = sum(1 for i, p in enumerate(current_parts) if is_word_part[i] and p is None)
    except Exception:
        current_nulls = float('inf')

    # Monotonic greedy mapping: pick earliest acceptable recognized token for each transcript token
    def _monotonic_greedy_mapping(transcript_tokens, recognized_tokens) -> List[int]:
        nT = len(transcript_tokens)
        nR = len(recognized_tokens)
        out = [-1] * nT
        prev_r = -1
        for ti in range(nT):
            t_tok = transcript_tokens[ti]
            for j in range(prev_r + 1, nR):
                r_tok = recognized_tokens[j]
                cost, _ = _pair_cost(t_tok, r_tok)
                if cost <= _MATCH_FUZZY_BASE + 0.15:
                    out[ti] = j
                    prev_r = j
                    break
        return out

    try:
        greedy_map = _monotonic_greedy_mapping(transcript_tokens, recognized_tokens)
        greedy_parts = _parts_times_from_mapping(greedy_map)
        greedy_nulls = sum(1 for i, p in enumerate(greedy_parts) if is_word_part[i] and p is None)
        if greedy_nulls < current_nulls:
            mapping = greedy_map
            # note: parts_times will be recomputed below from mapping
            method = 'monotonic-greedy'
    except Exception:
        pass

    # Final candidate selection: pick mapping that minimizes nulls for word/number parts
    try:
        candidates = [
            ("pre_refine", mapping_pre_refine),
            ("after_prefer", mapping_after_prefer),
            ("after_force", mapping_after_force),
            ("post_candidate", mapping),
            ("greedy", greedy_map if 'greedy_map' in locals() else None),
        ]
        # Also consider earliest-monotonic transformed variants of key candidates
        try:
            em_pre = _force_earliest_monotonic_mapping(mapping_pre_refine[:], transcript_tokens, recognized_tokens, recognized_words)
            candidates.append(("pre_refine_earliest", em_pre))
        except Exception:
            pass
        try:
            em_after = _force_earliest_monotonic_mapping(mapping_after_prefer[:], transcript_tokens, recognized_tokens, recognized_words)
            candidates.append(("after_prefer_earliest", em_after))
        except Exception:
            pass
        best = None
        best_nulls = None
        best_cov = None
        for name, cand in candidates:
            if cand is None:
                continue
            try:
                pt = _parts_times_from_mapping(cand)
                nulls = sum(1 for i, p in enumerate(pt) if is_word_part[i] and p is None)
                # coverage
                cov = sum(1 for v in cand if v >= 0) / max(1, len(cand))
                # predicted-position deviation as tie-breaker: lower is better
                ratio = len(recognized_tokens) / max(1, len(transcript_tokens))
                dev = 0.0
                dev_count = 0
                for i, v in enumerate(cand):
                    if v is None or v < 0:
                        continue
                    predicted = i * ratio
                    dev += abs(v - predicted)
                    dev_count += 1
                avg_dev = dev / dev_count if dev_count > 0 else float('inf')
            except Exception:
                continue
            if best is None:
                best = (name, cand)
                best_nulls = nulls
                best_cov = cov
                best_dev = avg_dev
            else:
                better = False
                if nulls < best_nulls:
                    better = True
                elif nulls == best_nulls:
                    # prefer higher coverage
                    if cov > best_cov + 1e-6:
                        better = True
                    elif abs(cov - best_cov) <= 1e-6 and avg_dev < best_dev:
                        better = True
                if better:
                    best = (name, cand)
                    best_nulls = nulls
                    best_cov = cov
                    best_dev = avg_dev
        if best is not None and best[1] is not None:
            mapping = best[1]
            method = f"chosen-{best[0]}"
    except Exception:
        pass

        # Additional lightweight refine: catch isolated wrong mappings by running
        # a local realignment pass with a tighter threshold. This helps correct
        # single-token mistakes that jumped to distant re-occurrences.
        try:
            mapping = _refine_drift_segments(mapping, transcript_tokens, recognized_tokens, len(recognized_tokens) / max(1, len(transcript_tokens)), threshold=20.0, sustain=1)
            method = method + "+refine-tight"
        except Exception:
            pass

    aligned_tokens = sum(1 for idx in mapping if idx >= 0)
    coverage = _coverage(mapping)
    # debug: include token counts for easier triage
    t_count = len(transcript_tokens)
    r_count = len(recognized_tokens)
    parts_times: List[Optional[Dict[str, float]]] = [None for _ in parts]
    idxs_by_part: Dict[int, List[int]] = defaultdict(list)
    for t_idx, r_idx in enumerate(mapping):
        if r_idx < 0:
            continue
        part_idx = owners[t_idx]
        if not (0 <= r_idx < len(recognized_tokens)):
            continue
        span = recognized_tokens[r_idx].span
        start_idx, end_idx = span
        if start_idx is None or end_idx is None:
            continue
        for base_idx in range(max(0, start_idx), min(len(recognized_words), end_idx + 1)):
            idxs_by_part[part_idx].append(base_idx)
    for p_idx, r_list in idxs_by_part.items():
        starts = [
            recognized_words[j].get("start")
            for j in r_list
            if recognized_words[j].get("start") is not None
        ]
        ends = [
            recognized_words[j].get("end")
            for j in r_list
            if recognized_words[j].get("end") is not None
        ]
        if starts and ends:
            parts_times[p_idx] = {"start": float(min(starts)), "end": float(max(ends))}
    # Second pass: fill missing parts_times using mapping -> recognized_tokens; prefer earliest monotonic recognized tokens with real timings
    prev_assigned_r = -1
    last_end_time_for_parts: Optional[float] = None
    m_rec = len(recognized_tokens)
    for idx, part in enumerate(parts):
        if parts_times[idx] is not None:
            continue
        if not part:
            continue
        if not (re.fullmatch(r"[A-Za-z']+", part or "") or re.fullmatch(r"[0-9][0-9.,–—-]*", part or "")):
            continue
        token_idxs = [i for i, owner in enumerate(owners) if owner == idx]
        collected_starts: List[float] = []
        collected_ends: List[float] = []
        for t_i in token_idxs:
            if t_i < 0 or t_i >= len(mapping):
                continue
            r_i = mapping[t_i]
            found = False

            # 1) Direct mapping with valid span
            if r_i is not None and 0 <= r_i < m_rec:
                r_tok = recognized_tokens[r_i]
                span = getattr(r_tok, 'span', None)
                if span and isinstance(span, tuple) and span[0] is not None and span[1] is not None:
                    s_idx, e_idx = span
                    s_times = [recognized_words[j].get('start') for j in range(max(0, s_idx), min(len(recognized_words), e_idx + 1)) if recognized_words[j].get('start') is not None]
                    e_times = [recognized_words[j].get('end') for j in range(max(0, s_idx), min(len(recognized_words), e_idx + 1)) if recognized_words[j].get('end') is not None]
                    if s_times and e_times:
                        collected_starts.extend(s_times)
                        collected_ends.extend(e_times)
                        found = True
                        prev_assigned_r = max(prev_assigned_r, r_i)
                        # update last_end_time
                        last_end_time_for_parts = float(max(e_times)) if e_times else last_end_time_for_parts
                        continue
                # fallback to orig_index
                oi = getattr(r_tok, 'orig_index', None)
                if oi is not None and 0 <= oi < len(recognized_words):
                    s = recognized_words[oi].get('start')
                    e = recognized_words[oi].get('end')
                    if s is not None and e is not None:
                        collected_starts.append(s)
                        collected_ends.append(e)
                        found = True
                        prev_assigned_r = max(prev_assigned_r, r_i)
                        last_end_time_for_parts = float(e)
                        continue

            # 2) Greedy earliest search forward from prev_assigned_r+1 for same norm with real timing
            t_norm = transcript_tokens[t_i].norm if t_i < len(transcript_tokens) else None
            if t_norm:
                for j in range(max(0, prev_assigned_r + 1), m_rec):
                    try:
                        if recognized_tokens[j].norm != t_norm:
                            continue
                    except Exception:
                        continue
                    rt = recognized_tokens[j]
                    sp = getattr(rt, 'span', None)
                    s_times = []
                    e_times = []
                    if sp and isinstance(sp, tuple) and sp[0] is not None and sp[1] is not None:
                        si, ei = sp
                        s_times = [recognized_words[k].get('start') for k in range(max(0, si), min(len(recognized_words), ei + 1)) if recognized_words[k].get('start') is not None]
                        e_times = [recognized_words[k].get('end') for k in range(max(0, si), min(len(recognized_words), ei + 1)) if recognized_words[k].get('end') is not None]
                    else:
                        oi = getattr(rt, 'orig_index', None)
                        if oi is not None and 0 <= oi < len(recognized_words):
                            s = recognized_words[oi].get('start')
                            e = recognized_words[oi].get('end')
                            if s is not None and e is not None:
                                s_times = [s]
                                e_times = [e]
                    if s_times and e_times:
                        # prefer candidate not earlier than last_end_time_for_parts if available
                        cand_start = min(s_times)
                        if last_end_time_for_parts is None or cand_start >= last_end_time_for_parts - 1e-3:
                            collected_starts.extend(s_times)
                            collected_ends.extend(e_times)
                            prev_assigned_r = j
                            last_end_time_for_parts = float(max(e_times))
                            found = True
                            break
                if found:
                    continue

            # 3) original backward search (earlier occurrence) up to window
            search_from = (r_i if (r_i is not None and r_i >= 0) else prev_assigned_r if prev_assigned_r >= 0 else 0)
            for j in range(search_from, max(-1, search_from - 60), -1):
                if j < 0 or j >= m_rec:
                    continue
                rt = recognized_tokens[j]
                sp = getattr(rt, 'span', None)
                if sp and isinstance(sp, tuple) and sp[0] is not None and sp[1] is not None:
                    s_idx, e_idx = sp
                    s_times = [recognized_words[k].get('start') for k in range(max(0, s_idx), min(len(recognized_words), e_idx + 1)) if recognized_words[k].get('start') is not None]
                    e_times = [recognized_words[k].get('end') for k in range(max(0, s_idx), min(len(recognized_words), e_idx + 1)) if recognized_words[k].get('end') is not None]
                    if s_times and e_times:
                        collected_starts.extend(s_times)
                        collected_ends.extend(e_times)
                        prev_assigned_r = j
                        last_end_time_for_parts = float(max(e_times))
                        found = True
                        break
            if found:
                continue

            # 4) as last resort search forward up to a limited window
            sf = (r_i if (r_i is not None and r_i >= 0) else prev_assigned_r if prev_assigned_r >= 0 else 0)
            for j in range(sf + 1, min(m_rec, sf + 60)):
                rt = recognized_tokens[j]
                sp = getattr(rt, 'span', None)
                if sp and isinstance(sp, tuple) and sp[0] is not None and sp[1] is not None:
                    s_idx, e_idx = sp
                    s_times = [recognized_words[k].get('start') for k in range(max(0, s_idx), min(len(recognized_words), e_idx + 1)) if recognized_words[k].get('start') is not None]
                    e_times = [recognized_words[k].get('end') for k in range(max(0, s_idx), min(len(recognized_words), e_idx + 1)) if recognized_words[k].get('end') is not None]
                    if s_times and e_times:
                        collected_starts.extend(s_times)
                        collected_ends.extend(e_times)
                        prev_assigned_r = j
                        last_end_time_for_parts = float(max(e_times))
                        break
        if collected_starts and collected_ends:
            parts_times[idx] = {"start": float(min(collected_starts)), "end": float(max(collected_ends))}
    stats = {
        "token_count": len(mapping),
        "aligned_tokens": aligned_tokens,
        "coverage": coverage,
        "method": method,
        "global_coverage": global_coverage,
        "seqmatch_full_coverage": seqmatch_full_coverage,
        "strict_coverage": strict_coverage,
        "window_coverage": window_coverage,
        "seqmatch_coverage": seqmatch_coverage,
        "adaptive_coverage": adaptive_coverage,
        "anchor_count": len(chosen_anchors),
        "transcript_token_count": t_count,
        "recognized_token_count": r_count,
    }
    # Include the exact `parts` sequence used by the backend so the frontend
    # can use the identical tokenization (avoids JS/Python regex incompatibilities).
    try:
        out_parts = parts
    except Exception:
        out_parts = None
    return {
        "split_regex": _SPLIT_PATTERN,
        "parts": out_parts,
        "parts_times": parts_times,
        "stats": stats,
    }


def _dp_map(subT: List[str], subR: List[str]) -> List[int]:
    n, m = len(subT), len(subR)
    if n == 0:
        return []
    if m == 0:
        return [-1] * n
    score = [[0] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = i; back[i][0] = 1
    for j in range(1, m + 1):
        score[0][j] = j; back[0][j] = 2
    for i in range(1, n + 1):
        Ti = subT[i - 1]
        for j in range(1, m + 1):
            cost = 0 if Ti == subR[j - 1] else 1
            v = score[i - 1][j - 1] + cost; d = 0
            up = score[i - 1][j] + 1
            if up < v:
                v = up; d = 1
            left = score[i][j - 1] + 1
            if left < v:
                v = left; d = 2
            score[i][j] = v; back[i][j] = d
    mapping = [-1] * n
    i, j = n, m
    while i > 0 or j > 0:
        d = back[i][j]
        if i > 0 and j > 0 and d == 0:
            mapping[i - 1] = j - 1
            i -= 1; j -= 1
        elif i > 0 and (j == 0 or d == 1):
            mapping[i - 1] = -1
            i -= 1
        else:
            j -= 1
    return mapping


def _anchored_alignment(
    T: List[str],
    R: List[str],
    step: Optional[int] = None,
    window: Optional[int] = None,
    n_max: Optional[int] = None,
    n_min: Optional[int] = None,
    allow_unigram_fallback: Optional[bool] = None,
) -> List[int]:
    """Anchor-based mapping with dynamic n-grams.

    - Co N-te słowo T[i] szukamy kotwicy w R w oknie ±window wokół przewidywanego indeksu i*ratio.
    - Najpierw próbujemy kotwic o długości n in [n_max..n_min], następnie opcjonalnie unigram.
    - Pomiędzy kotwicami robimy lekkie DP (_dp_map).
    """
    nT, nR = len(T), len(R)
    mapping = [-1] * nT
    if nT == 0 or nR == 0:
        return mapping
    step = step or int(os.getenv('ANCHOR_STEP', '10'))
    window = window or int(os.getenv('ANCHOR_WINDOW', '3'))
    n_max = n_max or int(os.getenv('ANCHOR_N_MAX', '5'))
    n_min = n_min or int(os.getenv('ANCHOR_N_MIN', '2'))
    allow_unigram_fallback = (
        allow_unigram_fallback
        if allow_unigram_fallback is not None
        else os.getenv('ANCHOR_ALLOW_UNIGRAM', '1').lower() in {'1', 'true', 'yes'}
    )
    ratio = nR / max(1, nT)

    anchors: List[Tuple[int, int]] = []
    prev_r = -1
    i = 0
    while i < nT:
        r0 = int(round(i * ratio))
        rmin = max(prev_r + 1, r0 - window)
        rmax = min(nR - 1, r0 + window)
        best_anchor = None  # (r, n)

        # Try multi-gram anchors from n_max down to n_min
        for n in range(max(2, n_max), max(1, n_min) - 1, -1):
            if i + n > nT:
                continue
            # collect candidates r where R[r:r+n] == T[i:i+n]
            local_best = None
            for r in range(rmin, rmax + 1):
                if r + n > nR:
                    continue
                # respect monotonic increase
                if r <= prev_r:
                    continue
                match = True
                for k in range(n):
                    if R[r + k] != T[i + k]:
                        match = False
                        break
                if match:
                    # pick nearest to predicted r0
                    if local_best is None or abs(r - r0) < abs(local_best - r0):
                        local_best = r
            if local_best is not None:
                best_anchor = (local_best, n)
                break  # prefer longest successful n

        # Fallback to unigram near predicted index
        if best_anchor is None and allow_unigram_fallback:
            cands = [r for r in range(rmin, rmax + 1) if r > prev_r and R[r] == T[i]]
            if cands:
                rr = min(cands, key=lambda rr: abs(rr - r0))
                best_anchor = (rr, 1)

        if best_anchor is not None:
            rr, n = best_anchor
            anchors.append((i, rr))
            prev_r = rr
        i += step

    # try force last token as anchor if close to end
    if nT > 4 and nR > 4:
        # Try multi-gram at tail first
        t_last = nT - 1
        r_target = nR - 1
        rmin_tail = max(prev_r + 1, r_target - max(8, window * 2))
        rmax_tail = nR - 1
        done_tail = False
        for n in range(max(2, n_max), max(1, n_min) - 1, -1):
            i0 = max(0, nT - n)
            for r in range(rmin_tail, rmax_tail + 1):
                if r + n > nR:
                    continue
                if r <= prev_r:
                    continue
                ok = True
                for k in range(n):
                    if R[r + k] != T[i0 + k]:
                        ok = False
                        break
                if ok:
                    anchors.append((i0, r))
                    done_tail = True
                    break
            if done_tail:
                break
        if not done_tail:
            cands = [r for r in range(rmin_tail, rmax_tail + 1) if r > prev_r and R[r] == T[t_last]]
            if cands:
                rr = min(cands, key=lambda rr: abs(rr - r_target))
                anchors.append((t_last, rr))

    # Align segments between anchors
    prev_t = -1; prev_r = -1
    for (ta, ra) in anchors:
        t0 = prev_t + 1; t1 = ta
        r0 = prev_r + 1; r1 = ra
        if t1 > t0 and r1 >= r0:
            sub_map = _dp_map(T[t0:t1], R[r0:r1])
            for k, mj in enumerate(sub_map):
                if mj >= 0:
                    mapping[t0 + k] = r0 + mj
        mapping[ta] = ra
        prev_t, prev_r = ta, ra

    # Tail segment
    t0 = prev_t + 1; r0 = prev_r + 1
    if t0 < nT and r0 < nR:
        sub_map = _dp_map(T[t0:nT], R[r0:nR])
        for k, mj in enumerate(sub_map):
            if mj >= 0:
                mapping[t0 + k] = r0 + mj
    return mapping


def normalize_for_alignment(text: str) -> str:
    """Normalize transcript for alignment (conservative):
    - lowercase
    - replace numeric tokens with per-digit words; '.' -> point; dashes -> dash
    - preserve original line breaks, collapse internal spaces per line
    This keeps token counts predictable and avoids guessing formats like years.
    """
    digit_map = {
        '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
        '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine'
    }

    def per_digit_words(s: str) -> str:
        s = s.replace(',', '')
        out: List[str] = []
        for ch in s:
            if ch in digit_map:
                out.append(digit_map[ch])
            elif ch == '.' or ch == '·':
                out.append('point')
            elif ch in {'-', '–', '—'}:
                out.append('dash')
        return " ".join(out)

    def repl(m: re.Match) -> str:
        return per_digit_words(m.group(0))

    lowered = text.lower()
    lowered = re.sub(r"\b[\d][\d.,\-–—]*\b", repl, lowered)
    # Collapse spaces within each line, but preserve newlines to keep paragraph boundaries
    lines = [" ".join(line.split()) for line in lowered.splitlines()]
    return "\n".join(lines)


def build_paragraph_entries_from_alignment(
    transcript_text: str,
    alignment_words: List[Dict[str, Any]],
    normalized_text: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Build paragraph-level entries compatible with existing UI from alignment words.

    - Splits transcript into paragraphs by blank lines.
    - For each paragraph, uses the number of tokens to slice the alignment words sequentially.
    - Computes start/end as min/max over successful tokens; if none, leaves as None.
    - Preserves original paragraph text.
    """
    def _normalize_token_for_locations(token: str) -> str:
        return "".join(ch.lower() for ch in token if ch.isalpha() or ch.isdigit())

    page_pattern = re.compile(r"^\s*Page\s+(\d+)\b", re.IGNORECASE)
    paragraphs: List[str] = []
    paragraph_word_locations: List[List[Dict[str, Optional[int]]]] = []
    paragraph_pages: List[Optional[int]] = []

    block_lines: List[str] = []
    block_locations: List[Dict[str, Optional[int]]] = []
    current_page = 1
    line_on_page = 0

    def finalize_block():
        if not block_lines:
            return
        paragraph_text = " ".join(block_lines).strip()
        paragraphs.append(paragraph_text)
        paragraph_word_locations.append(list(block_locations))
        first_page = block_locations[0].get("page") if block_locations else None
        paragraph_pages.append(first_page)
        block_lines.clear()
        block_locations.clear()

    for raw_line in transcript_text.splitlines():
        # Handle explicit form-feed page breaks preserved from import
        if raw_line.strip() == "\f":
            # Close current paragraph block before page turn
            finalize_block()
            current_page += 1
            line_on_page = 0
            continue

        line = raw_line.replace("\r", "").strip()
        if not line:
            finalize_block()
            continue
        page_match = page_pattern.match(line)
        if page_match:
            try:
                current_page = int(page_match.group(1))
            except ValueError:
                pass
            line_on_page = 0
            finalize_block()
            continue

        line_on_page += 1
        tokens = re.findall(r"\S+", line)
        word_in_line = 0
        for token in tokens:
            normalized = _normalize_token_for_locations(token)
            if normalized:
                word_in_line += 1
            block_locations.append(
                {
                    "page": current_page,
                    "line_on_page": line_on_page,
                    "word_in_line": word_in_line if word_in_line else None,
                }
            )
        block_lines.append(line)

    finalize_block()

    # If no explicit paragraphs, use entire text as one
    if not paragraphs:
        cleaned = transcript_text.strip()
        paragraphs = [cleaned] if cleaned else [""]
        paragraph_word_locations = [[]]
        paragraph_pages = [1]

    entries: List[Dict[str, Any]] = []
    cursor = 0

    # If normalized provided, split to normalized paragraphs in the same way
    norm_paragraphs: List[str] = []
    if normalized_text is not None:
        block = []
        for line in normalized_text.splitlines():
            if line.strip() == "":
                if block:
                    norm_paragraphs.append(" ".join(block).strip())
                    block = []
            else:
                block.append(line.strip())
        if block:
            norm_paragraphs.append(" ".join(block).strip())
        if not norm_paragraphs:
            norm_paragraphs = [normalized_text.strip()]

    for idx, para in enumerate(paragraphs):
        norm_para = norm_paragraphs[idx] if normalized_text is not None and idx < len(norm_paragraphs) else para
        tokens = _tokenize_words(norm_para)
        k = len(tokens)
        slice_words = alignment_words[cursor : cursor + k] if k > 0 else []
        cursor += k

        starts = [w.get("start") for w in slice_words if w.get("case") == "success" and w.get("start") is not None]
        ends = [w.get("end") for w in slice_words if w.get("case") == "success" and w.get("end") is not None]

        start_val = min(starts) if starts else None
        end_val = max(ends) if ends else None

        entry_payload: Dict[str, Any] = {
            "index": idx,
            "start": start_val,
            "end": end_val,
            "text": para,
            "word_count": k,
            "comments": [],
        }
        if idx < len(paragraph_word_locations):
            entry_payload["word_locations"] = paragraph_word_locations[idx]
        if idx < len(paragraph_pages) and paragraph_pages[idx] is not None:
            entry_payload["page"] = paragraph_pages[idx]

        entries.append(entry_payload)

    return entries


def align_with_gentle(audio_path: str, transcript_path: str, gentle_url: str, already_wav: bool = False) -> Dict[str, Any]:
    """Call Gentle HTTP API to perform forced alignment and return JSON result.
    Set already_wav=True to skip conversion.
    """
    # Convert to WAV for more stable results
    if already_wav:
        wav_path = audio_path
    else:
        wav_path = os.path.splitext(audio_path)[0] + ".wav"
        _run_ffmpeg_to_wav(audio_path, wav_path)

    with open(wav_path, "rb") as af, open(transcript_path, "rb") as tf:
        files = {
            "audio": (os.path.basename(wav_path), af, "audio/wav"),
            "transcript": (os.path.basename(transcript_path), tf, "text/plain"),
        }
        # async=false to wait for alignment in one request
        url = gentle_url.rstrip("/") + "/transcriptions?async=false"
        resp = requests.post(url, files=files, timeout=600)
        resp.raise_for_status()
        return resp.json()


def align_in_chunks(
    wav_path: str,
    normalized_text: str,
    gentle_url: str,
    work_dir: str,
    status_cb=None,
    noise: str = "-35dB",
    min_silence: float = 0.35,
    target: float = 20.0,
    min_len: float = 5.0,
    max_len: float = 45.0,
    overlap: float = 0.8,
) -> Dict[str, Any]:
    """Chunked alignment. Returns a Gentle-like result with words merged across chunks."""
    duration = ffprobe_duration_seconds(wav_path)
    silences = detect_silences(wav_path, noise=noise, min_silence=min_silence)
    chunks = plan_chunks(duration, silences, target, min_len, max_len, overlap)

    # Tokenize normalized text and build array for slicing
    tokens = re.findall(r"[A-Za-z']+", normalized_text)
    total_tokens = len(tokens)

    total_chunks = max(1, len(chunks))
    completed = 0
    if status_cb:
        status_cb("aligning", completed, total_chunks)
    try:
        print(f"INFO:root:total chunks: {total_chunks}")
    except Exception:
        pass

    merged_words: List[Dict[str, Any]] = []
    cur_index = 0

    # Prepare directories
    os.makedirs(work_dir, exist_ok=True)

    for idx, ch in enumerate(chunks):
        # Determine predicted token window for this chunk
        chunk_dur = max(0.01, ch["end"] - ch["start"])
        predicted = max(1, int(round(total_tokens * (chunk_dur / max(0.01, duration)))))
        margin = max(30, int(predicted * 0.3))
        win_start = cur_index
        win_end = min(total_tokens, win_start + predicted + margin)
        window_tokens = tokens[win_start:win_end]
        window_text = " ".join(window_tokens)

        # Extract wav for chunk
        chunk_wav = os.path.join(work_dir, f"chunk_{idx:04d}.wav")
        _extract_wav_segment(wav_path, chunk_wav, ch["read_start"], ch["read_end"])

        # Save transcript window
        chunk_txt = os.path.join(work_dir, f"chunk_{idx:04d}.txt")
        _save_text(chunk_txt, window_text)

        def run_and_map(win_tokens: List[str], txt_path: str) -> tuple[List[Dict[str, Any]], int]:
            try:
                res0 = align_with_gentle(chunk_wav, txt_path, gentle_url, already_wav=True)
            except Exception:
                return [], -1
            words0 = res0.get("words", [])
            # Greedy map success words to token indices to find last anchor
            last_idx = -1
            tpos = 0
            for w in words0:
                if w.get("case") != "success":
                    continue
                ww = (w.get("word") or "").lower()
                # advance tpos until match
                while tpos < len(win_tokens) and win_tokens[tpos] != ww:
                    tpos += 1
                if tpos >= len(win_tokens):
                    break
                last_idx = tpos
                tpos += 1
            return words0, last_idx

        words, last_anchor = run_and_map(window_tokens, chunk_txt)
        # Retry with larger window if anchors are too few
        anchor_ok = last_anchor >= max(3, int(predicted * 0.05))
        if not anchor_ok:
            larger_end = min(total_tokens, win_start + predicted + margin * 2)
            larger_tokens = tokens[win_start:larger_end]
            larger_txt = os.path.join(work_dir, f"chunk_{idx:04d}_retry.txt")
            _save_text(larger_txt, " ".join(larger_tokens))
            words, last_anchor = run_and_map(larger_tokens, larger_txt)
            window_tokens = larger_tokens
            win_end = larger_end

        if last_anchor >= 0:
            # Advance to just after last anchor, with small backtrack for safety
            back = 8
            cur_index = min(total_tokens, win_start + last_anchor + 1 - back if (win_start + last_anchor + 1 - back) > win_start else win_start + last_anchor + 1)
        else:
            # No anchors at all: conservative shift by half predicted
            cur_index = min(total_tokens, cur_index + max(1, predicted // 2))

        # Merge words with global timing; prefer earlier chunk in overlap
        left_bound = ch["start"]
        right_bound = ch["end"]
        last_end = merged_words[-1]["end"] if merged_words else 0.0
        for w in words:
            s = w.get("start")
            e = w.get("end")
            if s is None or e is None:
                continue
            gs = ch["read_start"] + float(s)
            ge = ch["read_start"] + float(e)
            if ge <= left_bound - 1e-3:
                continue
            if gs < left_bound:
                gs = left_bound
            if ge > right_bound:
                ge = right_bound
            # Enforce global monotonicity across chunks to limit drift effects
            if gs < last_end:
                shift = last_end - gs
                gs += shift
                ge += shift
            if ge <= gs:
                continue
            merged_words.append(
                {
                    "word": w.get("word"),
                    "case": w.get("case"),
                    "start": gs,
                    "end": ge,
                    "conf": w.get("conf"),
                }
            )
            last_end = ge

        completed += 1
        if status_cb:
            status_cb("aligning", completed, total_chunks)
        try:
            succ = sum(1 for w in words if w.get("case") == "success")
            print(f"INFO:root:{completed}/{total_chunks} (chunk succ={succ}, win={win_end-win_start})")
        except Exception:
            pass

    return {"words": merged_words}


def write_json(path: str, payload: Any) -> None:
    # Atomic write: write to a temporary file in the same directory and replace.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dirn = os.path.dirname(path) or "."
    # use a temp name that won't collide
    tmp_path = os.path.join(dirn, f".{os.path.basename(path)}.tmp")
    # write and fsync to ensure data hits disk before replacing
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            # On some platforms (or in tests) fsync may fail; ignore to keep behavior robust
            pass
    # atomic replace
    try:
        os.replace(tmp_path, path)
    except Exception:
        # Fallback: try an unlink of target and rename
        try:
            if os.path.exists(path):
                os.remove(path)
            os.rename(tmp_path, path)
        except Exception:
            # Final fallback: attempt a plain write (best-effort)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
