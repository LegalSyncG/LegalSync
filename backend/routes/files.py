import json
import os
import shutil
from enum import Enum

from flask import Response, request, jsonify
from flask_jwt_extended import verify_jwt_in_request, decode_token, jwt_required, get_jwt_identity
from database.session import db
from database.models import Files, Cases
from routes.profile import profile_bp

static_path = 'uploads/static/'
personal_path = 'uploads/personal/'

class FileType(Enum):
    Audio1 = 1
    Audio2 = 2
    Text1 = 3
    Text2 = 4

def register_file(user_id, file_type : FileType):
    config = {
        FileType.Audio1 : ('audio_1', f'{static_path}sound/case_1.mp3', False),
        FileType.Audio2 : ('audio_2', f'{static_path}sound/case_1.mp3', False),
        FileType.Text1 : ('text_1', f'{personal_path}{user_id}/case_1.txt', True),
        FileType.Text2 : ('text_2', f'{personal_path}{user_id}/case_2.txt', True)
    }
    if file_type not in config:
        raise ValueError("Unsupported file type")

    file_key, target_path, can_edit = config[file_type]

    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    if can_edit:
        source_index = 1 if file_type == FileType.Text1 else 2
        source_path = f'{static_path}docs/text_{source_index}.txt'
        shutil.copy(source_path, target_path)

    new_file = Files(
        owner_id=user_id,
        name = file_key,
        pathname=target_path,
        can_edit=can_edit
    )
    db.session.add(new_file)
    db.session.commit()
    return new_file

def create_case(user_id, name, nr):
    types = [[FileType.Audio1, FileType.Text1], [FileType.Audio2, FileType.Text2]]
    audio = register_file(user_id, types[nr][0])
    text = register_file(user_id, types[nr][1])
    new_case = Cases(
        owner_id=user_id,
        name=name,
        audio_file = audio.id,
        text_file = text.id
    )
    db.session.add(new_case)
    db.session.commit()

@profile_bp.route('/stream/<int:file_id>', methods=['GET'])
def stream_audio(file_id):
    token = request.args.get('token')
    if not token:
        return {"error": "Missing token"}, 401
    try:
        identity = decode_token(token)["sub"]
    except Exception:
        return {"error": "Invalid token"}, 401

    user_id = json.loads(identity)["id"]  # Assuming identity is JSON string
    file = Files.query.filter_by(id=file_id, owner_id=user_id).first()

    if not file or not os.path.isfile(file.pathname):
        return {"error": "File not found"}, 404

    path = file.pathname
    file_size = os.path.getsize(path)
    range_header = request.headers.get('Range', None)

    if range_header:
        byte_range = range_header.replace('bytes=', '').split('-')
        start = int(byte_range[0])
        end = int(byte_range[1]) if byte_range[1] else file_size - 1
        length = end - start + 1

        with open(path, 'rb') as f:
            f.seek(start)
            data = f.read(length)

        return Response(
            data,
            206,
            mimetype='audio/mpeg',
            headers={
                'Content-Range': f'bytes {start}-{end}/{file_size}',
                'Accept-Ranges': 'bytes',
                'Content-Length': str(length),
            },
        )
    else:
        return Response(
            open(path, 'rb'),
            200,
            mimetype='audio/mpeg',
            headers={
                'Content-Length': str(file_size),
                'Accept-Ranges': 'bytes'
            },
        )

@profile_bp.route('/text/<int:file_id>', methods=['GET'])
@jwt_required()
def get_text_content(file_id):
    identity = get_jwt_identity()
    user_id = json.loads(identity)['id']
    file = Files.query.filter_by(id=file_id, owner_id=user_id).first()

    if not file or not os.path.isfile(file.pathname):
        return {"error": "File not found"}, 404

    with open(file.pathname, 'r', encoding='utf-8') as f:
        contents = f.read()
    return jsonify({"content": contents})



