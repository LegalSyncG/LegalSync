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
    for paragraph in document.paragraphs:
        text = (paragraph.text or "").strip()
        if text:
            segments.append({"text": text, "page": current_page})
        if _paragraph_has_page_break(paragraph):
            current_page += 1
    joined = "\n\n".join(seg["text"] for seg in segments if seg["text"]).strip()
    return joined, {"paragraphs": segments}


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
        raise ValueError("Unsupported transcript file type. Upload TXT, DOCX, or Pages document.")
    if transcript_text:
        return transcript_text, {}
    return "", {}


def _collect_external_comments(entries):
    results = []
    if not isinstance(entries, list):
        return results
    for idx, entry in enumerate(entries):
        entry_text = str(entry.get("text") or "")
        words = entry_text.split()
        comments = entry.get("comments") or []
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
            results.append(
                {
                    "paragraph_index": idx,
                    "start_word": start,
                    "end_word": bounded_end,
                    "length": length,
                    "selected_text": " ".join(selection).strip(),
                    "external_comment": ext_comment,
                }
            )
    return results


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
        lines.append(f"[{idx}] Paragraph {comment['paragraph_index'] + 1}, words {start_word}-{end_word} (length: {length})")
        lines.append(f"Text: '{selected}'")
        lines.append(f"External comment: '{external_note}'")
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
        document.add_paragraph(f"[{idx}] Paragraph {comment['paragraph_index'] + 1}, words {start_word}-{end_word} (length: {length})")
        document.add_paragraph(f"Text: '{selected}'")
        document.add_paragraph(f"External comment: '{external_note}'")
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
        except Exception:
            pass
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

    comments = _collect_external_comments(entries)
    if not comments:
        return jsonify({"error": "No external comments available"}), 400

    now = datetime.utcnow()
    generated = now.isoformat() + "Z"
    case_label = case.name or f"Case {case_id}"
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    base_name = f"case-{case_id}-external-comments-{timestamp}"

    if fmt == "txt":
        payload = _build_external_comments_text(case_label, comments, generated)
        response = Response(payload, mimetype="text/plain; charset=utf-8")
        response.headers["Content-Disposition"] = f'attachment; filename={base_name}.txt'
        return response
    if fmt in {"docx", "doc"}:
        buffer = _build_external_comments_docx(case_label, comments, generated)
        return send_file(
            buffer,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name=f"{base_name}.docx",
        )
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
