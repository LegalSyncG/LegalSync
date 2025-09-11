import re
import json


def parse_transcript(text: str):
    entries = []
    blocks = re.split(r'\n\s*\n', text.strip())

    for idx, block in enumerate(blocks):
        match = re.match(r'\((\d+):(\d+)\s*-\s*(\d+):(\d+)\)\s*\n(.+)', block.strip(), re.DOTALL)
        if not match:
            continue

        min_start, sec_start, min_end, sec_end, paragraph_text = match.groups()
        start_time = int(min_start) * 60 + int(sec_start)
        end_time = int(min_end) * 60 + int(sec_end)

        words = paragraph_text.strip().split()
        word_count = len(words)

        entry = {
            "index": idx,
            "start": start_time,
            "end": end_time,
            "text": paragraph_text.strip(),
            "word_count": word_count,
            "comments": []  # will hold dicts with start_index, end_index, text
        }

        entries.append(entry)

    return entries


# Example usage
if __name__ == '__main__':
    with open("case_1.txt", "r") as f:
        raw_text = f.read()

    result = parse_transcript(raw_text)

    with open("transcript.json", "w") as f:
        json.dump(result, f, indent=2)
