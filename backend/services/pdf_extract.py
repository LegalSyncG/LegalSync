import re
from io import BytesIO
from typing import Dict, Iterable, List, Optional, Tuple

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTTextLine


LINE_NUMBER_PATTERN = re.compile(r"^\s*\d{1,4}(?:[\.]?\s+|\s+)")


def _iter_text_lines(layout) -> Iterable[LTTextLine]:
    """Yield all text lines from a PDFMiner layout tree in reading order."""

    stack = [layout]
    while stack:
        node = stack.pop()
        if isinstance(node, LTTextLine):
            yield node
            continue
        if isinstance(node, LTTextContainer):
            for child in reversed(list(node)):
                stack.append(child)
        else:
            try:
                children = list(node)
            except TypeError:
                continue
            for child in reversed(children):
                stack.append(child)


def extract_pdf_text_and_metadata(file_storage) -> Tuple[str, Dict[str, List[Dict[str, object]]]]:
    """Extract text and paragraph metadata from an uploaded PDF document."""

    file_storage.stream.seek(0)
    data = file_storage.read()
    if not data:
        return "", {"paragraphs": []}

    stream = BytesIO(data)

    line_entries: List[Dict[str, object]] = []

    for page_number, layout in enumerate(extract_pages(stream), start=1):
        raw_lines: List[Dict[str, float | str]] = []
        for text_line in _iter_text_lines(layout):
            text = text_line.get_text()
            if text is None:
                continue
            cleaned = text.replace("\r", "").rstrip("\n")
            raw_lines.append({
                "y0": getattr(text_line, "y0", 0.0),
                "y1": getattr(text_line, "y1", 0.0),
                "x0": getattr(text_line, "x0", 0.0),
                "text": cleaned,
                "height": getattr(text_line, "height", getattr(text_line, "y1", 0.0) - getattr(text_line, "y0", 0.0)),
            })

        raw_lines.sort(key=lambda t: (-t["y1"], t["x0"]))

        non_empty = [entry for entry in raw_lines if entry["text"]]
        numbered_count = sum(1 for entry in non_empty if LINE_NUMBER_PATTERN.match(entry["text"]))
        strip_leading_numbers = numbered_count >= max(3, int(0.5 * len(non_empty)))

        line_number = 0
        prev_line_meta: Optional[Dict[str, float | str]] = None
        for line_meta in raw_lines:
            if prev_line_meta is not None:
                prev_bottom = float(prev_line_meta.get("y0", 0.0))
                current_top = float(line_meta.get("y1", 0.0))
                prev_height = float(prev_line_meta.get("height", 0.0)) or 1.0
                current_height = float(line_meta.get("height", 0.0)) or 1.0
                avg_height = (prev_height + current_height) / 2.0
                gap = prev_bottom - current_top
                if gap > avg_height * 0.6:
                    line_entries.append({
                        "page": page_number,
                        "line": None,
                        "text": "",
                    })

            text_value = line_meta["text"]
            if text_value and strip_leading_numbers:
                stripped = LINE_NUMBER_PATTERN.sub("", text_value, count=1)
                text_value = stripped.lstrip()

            if text_value:
                line_number += 1
                line_entries.append({
                    "page": page_number,
                    "line": line_number,
                    "text": text_value,
                })
            else:
                line_entries.append({
                    "page": page_number,
                    "line": None,
                    "text": "",
                })
            prev_line_meta = line_meta

    if not line_entries:
        return "", {"paragraphs": []}

    raw_parts: List[str] = []
    current_page = None
    for entry in line_entries:
        if entry["page"] != current_page:
            if current_page is not None:
                raw_parts.append("\n\f\n")
            current_page = entry["page"]
        raw_parts.append(entry["text"])
        raw_parts.append("\n")

    raw_text = "".join(raw_parts).rstrip()

    paragraphs: List[Dict[str, object]] = []
    block: List[str] = []
    block_page: Optional[int] = None
    prev_page: Optional[int] = None
    for record in line_entries:
        text = (record["text"] or "").strip()
        page = record["page"]
        if prev_page is not None and page != prev_page and block:
            paragraphs.append({"text": " ".join(block), "page": block_page})
            block = []
            block_page = None
        if text:
            if block_page is None:
                block_page = page
            block.append(text)
        else:
            if block:
                paragraphs.append({"text": " ".join(block), "page": block_page})
                block = []
                block_page = None
        prev_page = page

    if block:
        paragraphs.append({"text": " ".join(block), "page": block_page})

    return raw_text, {"paragraphs": paragraphs}
