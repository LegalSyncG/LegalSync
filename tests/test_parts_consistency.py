
import sys
import os
import pytest
import json
from pathlib import Path


def test_mapped_parts_len_matches_parts_times_when_present():
    root = Path('uploads/personal')
    if not root.exists():
        pytest.skip('No uploads/personal folder in workspace')
    problems = []
    for user_dir in sorted(root.glob('*')):
        if not user_dir.is_dir():
            continue
        cases_dir = user_dir / 'cases'
        if not cases_dir.exists():
            continue
        for case_dir in sorted(cases_dir.glob('*')):
            align_path = case_dir / 'alignment.json'
            if not align_path.exists():
                continue
            with open(align_path, 'r', encoding='utf8') as f:
                payload = json.load(f)
            mapped = payload.get('mapped') if isinstance(payload, dict) else None
            if not isinstance(mapped, dict):
                continue
            parts = mapped.get('parts')
            parts_times = mapped.get('parts_times')
            if parts is not None:
                if not isinstance(parts_times, list) or len(parts) != len(parts_times):
                    problems.append(str(align_path))
    if problems:
        pytest.fail('Found alignment.json with parts/parts_times length mismatch: ' + ', '.join(problems))


