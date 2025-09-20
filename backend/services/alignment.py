import os
import json
import subprocess
from typing import List, Dict, Any, Tuple, Optional

import requests
import re


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


def build_mapped_parts(transcript_text: str, recognized_words: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return mapping suitable for frontend rendering without client-side matching.

    Produces: { 'split_regex': pattern, 'parts_times': [ {start,end}|None, ... ] }
    where parts come from splitting the full transcript by the shared regex.
    Number tokens aggregate times across their expanded components.
    """
    parts = _split_transcript_parts(transcript_text)
    T, owners = _build_norm_sequence_from_parts(parts)
    R = [ _normalize_token((w.get('word') or '')) for w in recognized_words ]
    # Try anchored alignment first (assumes majority of transcript is correct)
    mapping = _anchored_alignment(T, R)
    # Fallback to block DP if coverage too low
    if mapping.count(-1) > max(0, int(len(mapping) * 0.35)):
        mapping = _dp_align_blocks(T, R)
    # Compute times per part index
    parts_times: List[Optional[Dict[str, float]]] = [None for _ in parts]
    # Gather per-part matched recognized indices
    from collections import defaultdict
    idxs_by_part: Dict[int, List[int]] = defaultdict(list)
    for t_idx, r_idx in enumerate(mapping):
        if r_idx < 0:
            continue
        part_idx, _ = owners[t_idx]
        if 0 <= r_idx < len(recognized_words):
            idxs_by_part[part_idx].append(r_idx)
    for p_idx, r_list in idxs_by_part.items():
        starts = [recognized_words[j].get('start') for j in r_list if recognized_words[j].get('start') is not None]
        ends = [recognized_words[j].get('end') for j in r_list if recognized_words[j].get('end') is not None]
        if starts and ends:
            parts_times[p_idx] = {'start': float(min(starts)), 'end': float(max(ends))}
    return { 'split_regex': _SPLIT_PATTERN, 'parts_times': parts_times }


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
    paragraphs: List[str] = []
    block: List[str] = []
    for line in transcript_text.splitlines():
        if line.strip() == "":
            if block:
                paragraphs.append(" ".join(block).strip())
                block = []
        else:
            block.append(line.strip())
    if block:
        paragraphs.append(" ".join(block).strip())

    # If no explicit paragraphs, use entire text as one
    if not paragraphs:
        paragraphs = [transcript_text.strip()]

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

        entries.append(
            {
                "index": idx,
                "start": start_val,
                "end": end_val,
                "text": para,
                "word_count": k,
                "comments": [],
            }
        )

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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
