#!/usr/bin/env python3
"""
Small helper: read an existing alignment.json and try to fill missing parts_times
using the same logic added to build_mapped_parts. This doesn't re-run ASR.
"""
import json
import os
import re
from typing import List, Dict, Any, Optional

INPUT = os.path.join(os.getcwd(), 'uploads', 'personal', '1', 'cases', '52', 'alignment.json')
BACKUP = INPUT + '.bak'

with open(INPUT, 'r', encoding='utf-8') as f:
    payload = json.load(f)

mapped = payload.get('mapped') or payload
parts = mapped.get('split_regex') and []  # not needed here
# We need transcript parts and owners: but alignment.json does not contain owners; we'll
# rely on transcript_norm.txt and the backend logic only to split parts similarly.

TRANSCRIPT_NORM = os.path.join(os.getcwd(), 'uploads', 'personal', '1', 'cases', '52', 'transcript_norm.txt')
TRANSCRIPT = os.path.join(os.getcwd(), 'uploads', 'personal', '1', 'cases', '52', 'transcript.txt')

if not os.path.exists(TRANSCRIPT_NORM):
    # fallback to transcript.txt
    txt_path = TRANSCRIPT
else:
    txt_path = TRANSCRIPT_NORM

with open(txt_path, 'r', encoding='utf-8') as f:
    transcript_text = f.read()

# reuse split regex from backend.services.alignment (approximation)
SPLIT_RE = re.compile(r"([\\p{L}']+|[0-9][0-9.,–—-]*)")
# Python's re does not support \p{L}; use a fallback splitting by words/punctuation
parts = re.findall(r"([A-Za-z']+|[0-9][0-9.,–—-]*)|\\n|\\s+|\\S", transcript_text)
# Above is noisy but acceptable for mapping tokens to parts

words = payload.get('words', [])
recognized_words = words

# Reconstruct recognized_tokens and transcript_tokens owners similar to backend

def normalize_token(tok: str) -> str:
    return ''.join(ch for ch in tok.lower() if (ch.isalpha() or ch == "'"))

# Build recognized_tokens: a simple list of dicts with norm and span (each word maps to itself)
recognized_tokens = []
for idx, w in enumerate(recognized_words):
    raw = (w.get('word') or '').strip().lower()
    norm = normalize_token(raw)
    recognized_tokens.append({'norm': norm, 'variants': [norm], 'orig_index': idx, 'span': (idx, idx)})

# Build transcript alignment tokens and owners
owners: List[int] = []
transcript_tokens: List[str] = []
for idx, part in enumerate(parts):
    if not part:
        continue
    if re.fullmatch(r"[A-Za-z']+", part or ""):
        norm = normalize_token(part)
        if not norm:
            continue
        transcript_tokens.append(norm)
        owners.append(idx)
    elif re.fullmatch(r"[0-9][0-9.,–—-]*", part or ""):
        # expand digits per digit to words — approximate
        for ch in part:
            if ch.isdigit():
                transcript_tokens.append(ch)
                owners.append(idx)

# Load mapping if available from payload (mapping may not be stored; we try to build mapping via seqmatch)
mapped_parts = mapped.get('parts_times')

# We'll do a simple greedy mapping: for each transcript token, find next recognized token with same norm
rnorms = [rt['norm'] for rt in recognized_tokens]
mapping = [-1] * len(transcript_tokens)
ri = 0
for ti, t in enumerate(transcript_tokens):
    while ri < len(rnorms) and rnorms[ri] != t:
        ri += 1
    if ri < len(rnorms) and rnorms[ri] == t:
        mapping[ti] = ri
        ri += 1

# Now fill parts_times using mapping and recognized_words
parts_times = mapped_parts or [None] * (max(owners) + 1 if owners else 0)
for idx_part in range(len(parts_times)):
    if parts_times[idx_part] is not None:
        continue
    token_idxs = [i for i, owner in enumerate(owners) if owner == idx_part]
    starts = []
    ends = []
    for t_i in token_idxs:
        r_i = mapping[t_i] if 0 <= t_i < len(mapping) else -1
        if r_i is None or r_i < 0 or r_i >= len(recognized_words):
            continue
        s = recognized_words[r_i].get('start')
        e = recognized_words[r_i].get('end')
        if s is not None and e is not None:
            starts.append(s); ends.append(e)
    if starts and ends:
        parts_times[idx_part] = {'start': min(starts), 'end': max(ends)}

# Backup and write
with open(BACKUP, 'w', encoding='utf-8') as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

mapped['parts_times'] = parts_times
payload['mapped'] = mapped
with open(INPUT, 'w', encoding='utf-8') as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

# report
nulls_before = sum(1 for p in mapped.get('parts_times', []) if p is None)
print('updated alignment written to', INPUT)
print('nulls after update:', sum(1 for p in parts_times if p is None))
