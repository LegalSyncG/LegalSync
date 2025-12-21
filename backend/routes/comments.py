import json
from flask import request, jsonify, Blueprint
from flask_jwt_extended import jwt_required, get_jwt_identity
from pathlib import Path

from backend.database.models import Cases, Files

TRANSCRIPTS_DIR = Path('data/transcripts')  # adjust as needed


comments_bp = Blueprint('comments', __name__)


def load_transcript_json(user_id, case_id):
    case = Cases.query.filter_by(owner_id=user_id, id=case_id).first()
    file = Files.query.filter_by(id=case.text_file).first()
    file_path = file.pathname
    if not file or not file_path:
        return None
    with open(file_path) as f:
        return json.load(f), file_path

def save_transcript_json(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        try:
            import os
            os.fsync(f.fileno())
        except OSError:
            pass

@comments_bp.route('/text/<int:case_id>/entry/<int:index>', methods=['PATCH'])
@jwt_required()
def update_entry(case_id, index):
    identity = get_jwt_identity()
    user_id = json.loads(identity)['id']

    data, file_path = load_transcript_json(user_id, case_id)
    if data is None:
        return {"error": "Transcript not found"}, 404

    if not (0 <= index < len(data)):
        return {"error": "Entry index out of bounds"}, 404

    updated_entry = request.get_json()
    if not updated_entry:
        return {"error": "No entry data provided"}, 400

    # Optionally validate structure of updated_entry here
    data[index] = updated_entry

    save_transcript_json(data, file_path)
    return jsonify({"success": True, "message": "Entry updated successfully"})
