import json
import os
import threading
import zipfile
from datetime import datetime
from io import BytesIO
from typing import Optional, List, Dict, Tuple

from flask import Blueprint, Response, jsonify, request, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from docx import Document
from docx.oxml.ns import qn

from database.session import db
from database.models import Files, Cases
from services.alignment import (
    build_paragraph_entries_from_alignment,
    write_json,
    _run_ffmpeg_to_wav,
    normalize_for_alignment,
    align_in_chunks,
    build_mapped_parts,
    _tokenize_words,
)
from services.whisper_asr import transcribe_with_whisper
from services.pdf_extract import extract_pdf_text_and_metadata
from xml.etree import ElementTree


cases_bp = Blueprint("cases", __name__)

WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W_NS = {"w": WORD_NAMESPACE}


def _get_user_id() -> int:
    identity = get_jwt_identity()
    return json.loads(identity)["id"]


def _case_dir(user_id: int, case_id: int) -> str:
    return os.path.join("uploads", "personal", str(user_id), "cases", str(case_id))


def _status_path(case_dir: str) -> str:
    return os.path.join(case_dir, "status.json")


def _write_status(case_dir: str, status: str, error: Optional[str] = None, progress: Optional[dict] = None) -> None:
    payload = {"status": status}
    if error:
        payload["error"] = error
    if progress:
        payload["progress"] = progress
    write_json(_status_path(case_dir), payload)


def _paragraph_has_page_break(paragraph) -> bool:
    try:
        element = paragraph._element
        if element.findall(".//w:br", _W_NS):
            for br in element.findall(".//w:br", _W_NS):
                br_type = br.get(qn("w:type"))
                if br_type == "page":
                    return True
        if element.findall(".//w:lastRenderedPageBreak", _W_NS):
            return True
        for run in paragraph.runs:
            run_el = run._element
            for br in run_el.findall(".//w:br", _W_NS):
                br_type = br.get(qn("w:type"))
                if br_type == "page":
                    return True
            if run_el.findall(".//w:lastRenderedPageBreak", _W_NS):
                return True
    except Exception:
        # Fallback: no break detected
        pass
    return False


def _extract_paragraph_text_with_breaks(paragraph) -> tuple[str, bool]:
    """Extract paragraph text preserving manual line breaks and detect page breaks.

    - Inserts "\n" for text-wrapping breaks (w:br without type or with type != 'page').
    - Detects page breaks (w:br with type='page' or w:lastRenderedPageBreak) and returns a flag.
    - Orders content according to underlying XML children to preserve break positions.
    """
    try:
        el = paragraph._element
    except Exception:
        # Fallback: no structured access; return plain text
        return (paragraph.text or ""), False

    has_page_break = False
    parts: list[str] = []

    # Iterate through runs preserving order of text and breaks
    for run in paragraph.runs:
        run_el = run._element
        for child in list(run_el):
            tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag == 't':
                # Text node
                txt = (child.text or '')
                parts.append(txt)
            elif tag == 'br':
                br_type = child.get(qn('w:type'))
                if br_type == 'page':
                    has_page_break = True
                else:
                    parts.append('\n')
            elif tag == 'lastRenderedPageBreak':
                has_page_break = True
        # In some documents, run.text holds text but children may not list <w:t>
        # Ensure we didn't miss trailing plain text
        if run.text and (not parts or not run.text.endswith(parts[-1])):
            # Avoid duplicating if already consumed from <w:t>
            parts.append(run.text)

    text = "".join(parts).strip()
    return text, has_page_break


def _detect_transcript_extension(file_storage) -> str:
    filename = (file_storage.filename or "").lower()
    ext = os.path.splitext(filename)[1]
    if not ext:
        mimetype = (file_storage.mimetype or "").lower()
        if mimetype == "text/plain":
            return ".txt"
        if "wordprocessingml" in mimetype:
            return ".docx"
        if "apple.pages" in mimetype or mimetype.endswith("/pages"):
            return ".pages"
        if mimetype == "application/pdf" or mimetype.endswith("/pdf"):
            return ".pdf"
    if ext.lower() == ".pdf":
        return ".pdf"
    return ext or ".txt"


def _extract_text_from_plain(file_storage) -> str:
    file_storage.stream.seek(0)
    data = file_storage.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="ignore")


def _extract_text_from_docx(file_storage) -> Tuple[str, Dict[str, List[Dict[str, object]]]]:
    file_storage.stream.seek(0)
    data = file_storage.read()
    try:
        document = Document(BytesIO(data))
    except Exception as exc:
        raise ValueError("Unable to read DOCX document") from exc
    segments: List[Dict[str, object]] = []
    current_page = 1
    # Build a raw transcript preserving manual line breaks and page boundaries (as form feed)
    raw_parts: List[str] = []
    for paragraph in document.paragraphs:
        text, page_break = _extract_paragraph_text_with_breaks(paragraph)
        text = text.strip()
        if text:
            segments.append({"text": text, "page": current_page})
            if raw_parts:
                raw_parts.append("\n\n")  # paragraph separator
            raw_parts.append(text)
        if page_break or _paragraph_has_page_break(paragraph):
            # Insert a form feed to mark page boundary for downstream line/page mapping
            raw_parts.append("\n\f\n")
            current_page += 1

    joined = "".join(raw_parts).strip()
    return joined, {"paragraphs": segments}


def _extract_text_from_pdf(file_storage) -> Tuple[str, Dict[str, List[Dict[str, object]]]]:
    try:
        raw_text, meta = extract_pdf_text_and_metadata(file_storage)
    except Exception as exc:
        raise ValueError("Unable to read PDF document") from exc
    return raw_text, meta


def _extract_text_from_pages(file_storage) -> str:
    file_storage.stream.seek(0)
    data = file_storage.read()
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            xml_name = None
            preferred = ("index.xml", "Index.xml", "index.apxl", "Index.apxl")
            members = archive.namelist()
            for candidate in preferred:
                if candidate in members:
                    xml_name = candidate
                    break
            if not xml_name:
                xml_candidates = [name for name in members if name.lower().endswith(".xml")]
                if xml_candidates:
                    xml_name = xml_candidates[0]
            if not xml_name:
                raise ValueError("Unsupported .pages document: missing XML content")
            xml_bytes = archive.read(xml_name)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("Unable to open .pages document") from exc

    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise ValueError("Unable to parse .pages XML document") from exc

    paragraphs = []
    for element in root.iter():
        tag = element.tag.split("}")[-1]
        if tag in {"p", "paragraph"}:
            snippet = "".join(part.strip() for part in element.itertext())
            if snippet:
                paragraphs.append(snippet)
    if not paragraphs:
        # Fallback: gather all textual content
        texts = []
        for element in root.iter():
            snippet = (element.text or "").strip()
            if snippet:
                texts.append(snippet)
        if not texts:
            raise ValueError("No textual content found in .pages document")
        return "\n\n".join(texts).strip()
    return "\n\n".join(paragraphs).strip()


def _load_transcript_text(transcript_file, transcript_text: Optional[str]) -> Tuple[str, Dict[str, object]]:
    if transcript_file:
        ext = _detect_transcript_extension(transcript_file)
        if ext == ".docx":
            return _extract_text_from_docx(transcript_file)
        if ext == ".pdf":
            return _extract_text_from_pdf(transcript_file)
        if ext == ".pages":
            text = _extract_text_from_pages(transcript_file)
            return text, {}
        if ext == ".txt":
            text = _extract_text_from_plain(transcript_file)
            return text, {}
        # Common browser fallback: text/plain mimetype with no extension
        if ext in {"", None}:
            text = _extract_text_from_plain(transcript_file)
            return text, {}
        raise ValueError("Unsupported transcript file type. Upload TXT, DOCX, PDF, or Pages document.")
    if transcript_text:
        return transcript_text, {}
    return "", {}


def _normalize_location(raw_loc, entry_page):
    page = None
    line = None
    word_in_line = None
    if raw_loc and isinstance(raw_loc, dict):
        try:
            page = int(raw_loc.get("page")) if raw_loc.get("page") is not None else None
        except (TypeError, ValueError):
            page = None
        try:
            line = int(raw_loc.get("line_on_page")) if raw_loc.get("line_on_page") is not None else int(raw_loc.get("line")) if raw_loc.get("line") is not None else None
        except (TypeError, ValueError):
            line = None
        try:
            word_in_line = int(raw_loc.get("word_in_line")) if raw_loc.get("word_in_line") is not None else None
        except (TypeError, ValueError):
            word_in_line = None

    if page is None:
        page = entry_page if entry_page is not None else 1

    if line is None:
        line = None

    return {
        "page": page,
        "line": line,
        "word_in_line": word_in_line,
    }


def _parse_raw_tokens(raw_text: str):
    tokens = []
    page = 1
    line = 0
    word_in_line = 0
    line_pending = True
    idx = 0
    length = len(raw_text)

    def normalize(token):
        return ''.join(ch.lower() for ch in token if ch.isalpha() or ch.isdigit())

    while idx < length:
        ch = raw_text[idx]
        if ch == '\f':
            line_pending = True
            word_in_line = 0
            page += 1
            line = 0
            idx += 1
            continue
        if ch == '\n':
            line_pending = True
            word_in_line = 0
            idx += 1
            continue
        if ch.isspace():
            idx += 1
            continue

        start = idx
        while idx < length:
            ch2 = raw_text[idx]
            if ch2 in {'\f', '\n'} or ch2.isspace():
                break
            idx += 1
        token = raw_text[start:idx]
        if not token:
            continue
        if line_pending:
            line += 1
            line_pending = False
        normalized = normalize(token)
        if normalized:
            word_in_line += 1
        tokens.append({
            "value": token,
            "normalized": normalized,
            "page": page,
            "line": line if normalized else None,
            "word_in_line": word_in_line if normalized else None,
        })
    return tokens


def _build_locations_from_raw(entries, raw_text: str):
    if not raw_text:
        return None
    raw_tokens = _parse_raw_tokens(raw_text)
    raw_idx = 0
    locations_per_entry = []

    for entry in entries:
        entry_locations = []
        count = entry.get("word_count")
        if not isinstance(count, int) or count < 0:
            count = len(_tokenize_words(entry.get("text") or ""))
        for _ in range(count):
            matched = None
            while raw_idx < len(raw_tokens):
                candidate = raw_tokens[raw_idx]
                raw_idx += 1
                if candidate.get("normalized"):
                    matched = candidate
                    break
            if matched:
                entry_locations.append({
                    "page": matched.get("page"),
                    "line": matched.get("line"),
                    "word_in_line": matched.get("word_in_line"),
                })
            else:
                entry_locations.append({"page": entry.get("page"), "line": None, "word_in_line": None})
        locations_per_entry.append(entry_locations)

    return locations_per_entry


def _collect_external_comments(entries, word_times_by_entry=None, computed_locations=None):
    results = []
    if not isinstance(entries, list):
        return results
    for idx, entry in enumerate(entries):
        entry_text = str(entry.get("text") or "")
        words = entry_text.split()
        comments = entry.get("comments") or []
        if computed_locations and idx < len(computed_locations):
            locations = computed_locations[idx] or []
        else:
            locations = entry.get("word_locations") or []
        times_for_entry = None
        if word_times_by_entry and idx < len(word_times_by_entry):
            times_for_entry = word_times_by_entry[idx]
        for comment in comments:
            ext_comment = (comment.get("external_comment") or "").strip()
            if not ext_comment:
                continue
            try:
                start = int(comment.get("start_word", 0))
            except (TypeError, ValueError):
                start = 0
            try:
                end = int(comment.get("end_word", start))
            except (TypeError, ValueError):
                end = start
            start = max(0, start)
            end = max(start, end)
            if words:
                max_index = len(words) - 1
                start = min(start, max_index)
                bounded_end = min(end, max_index)
                selection = words[start : bounded_end + 1]
            else:
                start = 0
                bounded_end = 0
                selection = []
            length = len(selection)

            def _fetch_location(word_index):
                loc = locations[word_index] if 0 <= word_index < len(locations) else None
                entry_page = entry.get("page")
                return _normalize_location(loc if isinstance(loc, dict) else None, entry_page)

            start_loc = _fetch_location(start)
            end_loc = _fetch_location(bounded_end)

            def _fetch_times(word_index):
                if not times_for_entry:
                    return {"start": None, "end": None}
                if 0 <= word_index < len(times_for_entry):
                    return times_for_entry[word_index]
                return {"start": None, "end": None}

            start_time = _fetch_times(start).get("start")
            end_time = _fetch_times(bounded_end).get("end")

            results.append(
                {
                    "paragraph_index": idx,
                    "start_word": start,
                    "end_word": bounded_end,
                    "length": length,
                    "selected_text": " ".join(selection).strip(),
                    "external_comment": ext_comment,
                    "page_start": start_loc.get("page"),
                    "page_end": end_loc.get("page"),
                    "line_start": start_loc.get("line"),
                    "line_end": end_loc.get("line"),
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )
    return results


def _load_alignment_word_times(entries, case_dir):
    alignment_path = os.path.join(case_dir, "alignment.json")
    if not os.path.isfile(alignment_path):
        return None
    try:
        with open(alignment_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    words = payload.get("words") if isinstance(payload, dict) else None
    if not isinstance(words, list):
        return None
    word_index = 0
    word_times = []
    for entry in entries:
        count = entry.get("word_count")
        if not isinstance(count, int) or count < 0:
            count = len(_tokenize_words(entry.get("text") or ""))
        entry_times = []
        for _ in range(count):
            if word_index < len(words):
                w = words[word_index] or {}
                entry_times.append({
                    "start": w.get("start"),
                    "end": w.get("end"),
                })
            else:
                entry_times.append({"start": None, "end": None})
            word_index += 1
        word_times.append(entry_times)
    return word_times


def _format_timestamp_range(start, end):
    def fmt(val):
        if val is None:
            return None
        try:
            seconds = float(val)
        except (TypeError, ValueError):
            return None
        if seconds < 0:
            seconds = 0
        total_minutes = int(seconds // 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return f"{hours:02d}:{minutes:02d}"

    start_str = fmt(start)
    end_str = fmt(end)
    if start_str and end_str and start_str != end_str:
        return f"{start_str} – {end_str}"
    return start_str or end_str or None


def _format_page_label(page_start, page_end):
    if page_start is None and page_end is None:
        return None
    if page_end is None or page_start == page_end:
        return f"Page {page_start or page_end}"
    return f"Pages {page_start}–{page_end}"


def _format_line_label(line_start, line_end):
    if line_start is None and line_end is None:
        return None
    if line_end is None or line_start == line_end:
        return f"Line {line_start or line_end}"
    return f"Lines {line_start}–{line_end}"


def _build_external_comments_text(case_label: str, comments, generated_iso: str) -> str:
    lines = [
        "External comments export",
        f"Case: {case_label}",
        f"Generated: {generated_iso}",
        "",
    ]
    for idx, comment in enumerate(comments, start=1):
        start_word = comment["start_word"] + 1
        end_word = comment["end_word"] + 1
        length = comment["length"]
        selected = comment["selected_text"].replace('"', "'")
        external_note = comment["external_comment"].replace('"', "'")
        location_bits = []
        page_label = _format_page_label(comment.get("page_start"), comment.get("page_end"))
        if page_label:
            location_bits.append(page_label)
        line_label = _format_line_label(comment.get("line_start"), comment.get("line_end"))
        if line_label:
            location_bits.append(line_label)
        location_str = ", ".join(location_bits) if location_bits else "Location unknown"
        words_span = f"words {start_word}-{end_word} (length: {length})"
        lines.append(f"{idx}) {location_str}, {words_span}")
        ts = _format_timestamp_range(comment.get("start_time"), comment.get("end_time"))
        if ts:
            lines.append(f"Timestamp: {ts}")
        else:
            lines.append("Timestamp: unavailable")
        lines.append(f"Text: '{selected}'")
        lines.append(f"Comment: '{external_note}'")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _build_external_comments_docx(case_label: str, comments, generated_iso: str) -> BytesIO:
    document = Document()
    document.add_heading("External comments export", level=1)
    document.add_paragraph(f"Case: {case_label}")
    document.add_paragraph(f"Generated: {generated_iso}")
    document.add_paragraph("")
    for idx, comment in enumerate(comments, start=1):
        start_word = comment["start_word"] + 1
        end_word = comment["end_word"] + 1
        length = comment["length"]
        selected = comment["selected_text"].replace('"', "'")
        external_note = comment["external_comment"].replace('"', "'")
        location_bits = []
        page_label = _format_page_label(comment.get("page_start"), comment.get("page_end"))
        if page_label:
            location_bits.append(page_label)
        line_label = _format_line_label(comment.get("line_start"), comment.get("line_end"))
        if line_label:
            location_bits.append(line_label)
        location_str = ", ".join(location_bits) if location_bits else "Location unknown"
        words_span = f"words {start_word}-{end_word} (length: {length})"
        document.add_paragraph(f"{idx}) {location_str}, {words_span}")
        ts = _format_timestamp_range(comment.get("start_time"), comment.get("end_time"))
        if ts:
            document.add_paragraph(f"Timestamp: {ts}")
        else:
            document.add_paragraph("Timestamp: unavailable")
        document.add_paragraph(f"Text: '{selected}'")
        document.add_paragraph(f"Comment: '{external_note}'")
        document.add_paragraph("")
    buffer = BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer


def _align_job(user_id: int, case_id: int, gentle_url: str) -> None:
    case_dir = _case_dir(user_id, case_id)
    audio_path = os.path.join(case_dir, "audio.mp3")
    transcript_txt = os.path.join(case_dir, "transcript.txt")
    alignment_path = os.path.join(case_dir, "alignment.json")
    transcript_json = os.path.join(case_dir, "transcript.json")

    try:
        _write_status(case_dir, "converting")
        wav_path = os.path.splitext(audio_path)[0] + ".wav"
        _run_ffmpeg_to_wav(audio_path, wav_path)

        # Prepare normalized transcript
        with open(transcript_txt, "r", encoding="utf-8", errors="ignore") as f:
            original_text = f.read()
        normalized_text = normalize_for_alignment(original_text)
        norm_path = os.path.join(case_dir, "transcript_norm.txt")
        with open(norm_path, "w", encoding="utf-8") as nf:
            nf.write(normalized_text)

        # Choose backend: Whisper (local) or Gentle (HTTP)
        backend = os.getenv("ASR_BACKEND", "gentle").lower()
        if backend == "whisper":
            _write_status(case_dir, "aligning")
            use_chunking = (os.getenv("WHISPER_CHUNKING", "false").lower() in {"1","true","yes"})
            if use_chunking:
                chunks_dir = os.path.join(case_dir, "chunks")
                def status_cb(phase: str, completed: int, total: int):
                    _write_status(case_dir, phase, progress=None)
                    path = _status_path(case_dir)
                    try:
                        data = {"status": phase, "total_chunks": total, "completed_chunks": completed}
                        write_json(path, data)
                    except Exception:
                        pass
                from services.whisper_asr import transcribe_with_whisper_chunked
                result = transcribe_with_whisper_chunked(
                    wav_path=wav_path,
                    work_dir=chunks_dir,
                    status_cb=status_cb,
                    model_size=os.getenv("WHISPER_MODEL"),
                    device=os.getenv("WHISPER_DEVICE"),
                    compute_type=os.getenv("WHISPER_COMPUTE"),
                    language=os.getenv("WHISPER_LANGUAGE"),
                )
            else:
                result = transcribe_with_whisper(
                    wav_path=wav_path,
                    model_size=os.getenv("WHISPER_MODEL"),
                    device=os.getenv("WHISPER_DEVICE"),
                    compute_type=os.getenv("WHISPER_COMPUTE"),
                    language=os.getenv("WHISPER_LANGUAGE"),
                )
        else:
            # Splitting stage (Gentle)
            _write_status(case_dir, "splitting")

            # Align in chunks with live status updates
            chunks_dir = os.path.join(case_dir, "chunks")

            def status_cb(phase: str, completed: int, total: int):
                _write_status(case_dir, phase, progress=None)
                # Persist counts for frontend progress
                path = _status_path(case_dir)
                try:
                    data = {"status": phase, "total_chunks": total, "completed_chunks": completed}
                    write_json(path, data)
                except Exception:
                    pass

            result = align_in_chunks(
                wav_path=wav_path,
                normalized_text=normalized_text,
                gentle_url=gentle_url,
                work_dir=chunks_dir,
                status_cb=status_cb,
            )
        write_json(alignment_path, result)

        _write_status(case_dir, "building")
        words = result.get("words", [])
        entries = build_paragraph_entries_from_alignment(original_text, words, normalized_text)
        # Attach mapped parts for precise karaoke timing
        try:
            mapped = build_mapped_parts(original_text, words)
            result["mapped"] = mapped
            write_json(alignment_path, result)
        except Exception as e:
            # If mapping fails, persist current alignment (best-effort) and mark case as failed.
            try:
                write_json(alignment_path, result)
            except Exception:
                pass
            # Record a concise error message and stop the job to avoid marking as 'done'
            try:
                _write_status(case_dir, "failed", error=(str(e)[:1000]))
            except Exception:
                pass
            return
        try:
            with open(transcript_json, "r", encoding="utf-8") as existing_fp:
                existing_entries = json.load(existing_fp)
        except Exception:
            existing_entries = None
        if isinstance(existing_entries, list):
            for idx, entry in enumerate(entries):
                if idx < len(existing_entries):
                    prev = existing_entries[idx]
                    if isinstance(prev, dict) and "page" in prev:
                        entry["page"] = prev.get("page")
        write_json(transcript_json, entries)

        _write_status(case_dir, "done")
    except Exception as e:
        _write_status(case_dir, "failed", error=str(e))


@cases_bp.route("/cases", methods=["POST"])
@jwt_required()
def create_case():
    user_id = _get_user_id()
    # Accept: multipart with fields: name, audio (mp3), transcript (txt) or transcript_text (str)
    name = request.form.get("name") or "New Case"
    name = name[:70]
    audio = request.files.get("audio")
    transcript_file = request.files.get("transcript")
    transcript_text = request.form.get("transcript_text")

    if not audio or (not transcript_file and not transcript_text):
        return jsonify({"error": "audio and transcript are required"}), 400

    # Persist placeholder Files and Case
    # Create case row with temporary file references; will update after saving
    # First create placeholder transcript file path
    placeholder_transcript_rel = os.path.join("uploads", "placeholder.json")
    transcript_files_row = Files(owner_id=user_id, name="transcript", pathname=placeholder_transcript_rel, can_edit=True)
    db.session.add(transcript_files_row)
    db.session.flush()

    audio_files_row = Files(owner_id=user_id, name="audio", pathname="", can_edit=False)
    db.session.add(audio_files_row)
    db.session.flush()

    new_case = Cases(owner_id=user_id, name=name, audio_file=audio_files_row.id, text_file=transcript_files_row.id)
    db.session.add(new_case)
    db.session.commit()

    case_dir = _case_dir(user_id, new_case.id)
    os.makedirs(case_dir, exist_ok=True)

    # Save audio
    audio_path = os.path.join(case_dir, "audio.mp3")
    audio.save(audio_path)

    # Save transcript.txt (normalizing DOCX/PAGES uploads to plain text)
    transcript_txt_path = os.path.join(case_dir, "transcript.txt")
    try:
        transcript_text_content, transcript_meta = _load_transcript_text(transcript_file, transcript_text)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with open(transcript_txt_path, "w", encoding="utf-8") as f:
        f.write(transcript_text_content)

    # Create initial transcript.json with null times for UI compatibility
    paragraphs_meta = (transcript_meta or {}).get("paragraphs")
    paragraphs: List[str] = []
    paragraph_pages: List[Optional[int]] = []
    if paragraphs_meta:
        for seg in paragraphs_meta:
            text = (seg.get("text") or "").strip()
            if text:
                paragraphs.append(text)
                page = seg.get("page")
                paragraph_pages.append(page if isinstance(page, int) else None)
    else:
        block = []
        for line in transcript_text_content.splitlines():
            if line.strip() == "":
                if block:
                    paragraphs.append(" ".join(block).strip())
                    paragraph_pages.append(None)
                    block = []
            else:
                block.append(line.strip())
        if block:
            paragraphs.append(" ".join(block).strip())
            paragraph_pages.append(None)
        if not paragraphs:
            paragraphs = [transcript_text_content.strip()]
            paragraph_pages.append(None)

    entries = []
    for idx, para in enumerate(paragraphs):
        page = paragraph_pages[idx] if idx < len(paragraph_pages) else None
        entries.append(
            {
                "index": idx,
                "start": None,
                "end": None,
                "text": para,
                "word_count": len(_tokenize_words(para)),
                "comments": [],
                "page": page,
            }
        )

    transcript_json_path = os.path.join(case_dir, "transcript.json")
    write_json(transcript_json_path, entries)

    # Update Files rows with real paths
    audio_files_row.pathname = audio_path
    transcript_files_row.pathname = transcript_json_path
    db.session.commit()

    # Write initial status
    _write_status(case_dir, "queued")

    # Background alignment
    gentle_url = os.getenv("GENTLE_URL", "http://localhost:8765")
    t = threading.Thread(target=_align_job, args=(user_id, new_case.id, gentle_url), daemon=True)
    t.start()

    return jsonify({"id": new_case.id, "name": new_case.name, "status": "queued"})


@cases_bp.route("/cases/<int:case_id>/status", methods=["GET"])
@jwt_required()
def case_status(case_id: int):
    user_id = _get_user_id()
    case_dir = _case_dir(user_id, case_id)
    status_file = _status_path(case_dir)
    if os.path.isfile(status_file):
        with open(status_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return jsonify(data)
    # Fallback: determine from files
    alignment_path = os.path.join(case_dir, "alignment.json")
    if os.path.isfile(alignment_path):
        return jsonify({"status": "done"})
    return jsonify({"status": "unknown"})


@cases_bp.route("/cases/<int:case_id>/progress", methods=["POST"])
@jwt_required()
def update_progress(case_id: int):
    """Optional hook to update fine-grained progress from an external aligner/log parser.
    Body: {"current": int, "total": int}
    """
    user_id = _get_user_id()
    # ensure ownership
    case = Cases.query.filter_by(owner_id=user_id, id=case_id).first()
    if not case:
        return jsonify({"error": "not found"}), 404
    data = request.get_json() or {}
    cur = int(data.get("current", 0))
    tot = int(data.get("total", 0))
    case_dir = _case_dir(user_id, case_id)
    # merge with existing status
    status_file = _status_path(case_dir)
    status = "aligning"
    if os.path.isfile(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                cur_json = json.load(f)
                status = cur_json.get("status", status)
        except Exception:
            pass
    _write_status(case_dir, status, progress={"current": cur, "total": tot})
    return jsonify({"ok": True})


@cases_bp.route("/cases/<int:case_id>/alignment", methods=["GET"])
@jwt_required()
def case_alignment(case_id: int):
    user_id = _get_user_id()
    case_dir = _case_dir(user_id, case_id)
    alignment_path = os.path.join(case_dir, "alignment.json")
    if not os.path.isfile(alignment_path):
        return jsonify({"error": "alignment not ready"}), 404
    with open(alignment_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    need_refresh = False
    mapped = payload.get("mapped") if isinstance(payload, dict) else None
    if not isinstance(mapped, dict):
        need_refresh = True
    else:
        parts_times = mapped.get("parts_times")
        if not isinstance(parts_times, list) or not parts_times:
            need_refresh = True
        else:
            stats = mapped.get("stats")
            if not isinstance(stats, dict) or "coverage" not in stats:
                need_refresh = True

    if need_refresh:
        transcript_txt = os.path.join(case_dir, "transcript.txt")
        if os.path.isfile(transcript_txt):
            try:
                with open(transcript_txt, "r", encoding="utf-8", errors="ignore") as tf:
                    transcript_text = tf.read()
                words = payload.get("words") if isinstance(payload, dict) else []
                mapped_updated = build_mapped_parts(transcript_text, words or [])
                payload["mapped"] = mapped_updated
                write_json(alignment_path, payload)
            except Exception as e:
                # Avoid leaving case stuck in 'building' — record failure so frontend won't wait forever
                try:
                    _write_status(case_dir, "failed", error=(str(e)[:1000]))
                except Exception:
                    pass

    return jsonify(payload)


@cases_bp.route("/cases/<int:case_id>/transcript", methods=["GET"])
@jwt_required()
def case_transcript_raw(case_id: int):
    user_id = _get_user_id()
    case_dir = _case_dir(user_id, case_id)
    transcript_txt = os.path.join(case_dir, "transcript.txt")
    if not os.path.isfile(transcript_txt):
        return jsonify({"error": "transcript not found"}), 404
    with open(transcript_txt, "r", encoding="utf-8", errors="ignore") as f:
        return jsonify({"text": f.read()})


@cases_bp.route("/cases/<int:case_id>/external-comments", methods=["GET"])
@jwt_required()
def export_external_comments(case_id: int):
    fmt = (request.args.get("format") or "docx").lower()
    user_id = _get_user_id()
    case = Cases.query.filter_by(owner_id=user_id, id=case_id).first()
    if not case:
        return jsonify({"error": "not found"}), 404

    case_dir = _case_dir(user_id, case_id)
    transcript_json_path = os.path.join(case_dir, "transcript.json")
    if not os.path.isfile(transcript_json_path):
        return jsonify({"error": "Transcript not found"}), 404

    with open(transcript_json_path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    word_times = _load_alignment_word_times(entries, case_dir)
    raw_transcript_path = os.path.join(case_dir, "transcript.txt")
    raw_text = ""
    if os.path.isfile(raw_transcript_path):
        with open(raw_transcript_path, "r", encoding="utf-8", errors="ignore") as rt:
            raw_text = rt.read()
    computed_locations = _build_locations_from_raw(entries, raw_text)
    comments = _collect_external_comments(entries, word_times, computed_locations)
    if not comments:
        return jsonify({"error": "No external comments available"}), 400

    now = datetime.utcnow()
    generated = now.strftime("%Y-%m-%d %H:%M")
    case_label = case.name or f"Case {case_id}"
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    base_name = f"case-{case_id}-external-comments-{timestamp}"

    if fmt == "txt":
        payload = _build_external_comments_text(case_label, comments, generated)
        response = Response(payload, mimetype="text/plain; charset=utf-8")
        response.headers["Content-Disposition"] = f'attachment; filename={base_name}.txt'
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response
    if fmt in {"docx", "doc"}:
        buffer = _build_external_comments_docx(case_label, comments, generated)
        resp = send_file(
            buffer,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name=f"{base_name}.docx",
        )
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        return resp
    return jsonify({"error": "Unsupported format"}), 400


@cases_bp.route("/cases/<int:case_id>", methods=["DELETE"])
@jwt_required()
def delete_case(case_id: int):
    import shutil

    user_id = _get_user_id()
    # Validate ownership
    case = Cases.query.filter_by(owner_id=user_id, id=case_id).first()
    if not case:
        return jsonify({"error": "not found"}), 404

    # Remove files on disk
    case_dir = _case_dir(user_id, case_id)
    if os.path.isdir(case_dir):
        shutil.rmtree(case_dir, ignore_errors=True)

    # Remove Files rows linked to this case
    audio_file = Files.query.filter_by(id=case.audio_file, owner_id=user_id).first()
    text_file = Files.query.filter_by(id=case.text_file, owner_id=user_id).first()
    if audio_file:
        db.session.delete(audio_file)
    if text_file:
        db.session.delete(text_file)

    # Remove Case row
    db.session.delete(case)
    db.session.commit()

    return jsonify({"ok": True})


@cases_bp.route("/cases/<int:case_id>", methods=["PATCH"])
@jwt_required()
def rename_case(case_id: int):
    user_id = _get_user_id()
    case = Cases.query.filter_by(owner_id=user_id, id=case_id).first()
    if not case:
        return jsonify({"error": "not found"}), 404
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    # Enforce 70 chars limit server-side too
    name = name[:70]
    case.name = name
    db.session.commit()
    return jsonify({"ok": True, "id": case.id, "name": case.name})
