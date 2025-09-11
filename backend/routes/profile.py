import json
import os
from flask import Blueprint, Response, request
from database.models import Files, Cases

profile_bp = Blueprint('profile', __name__)

from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

@profile_bp.route('/files', methods=['GET'])
@jwt_required()
def get_files():
    identity = get_jwt_identity()
    user_data = json.loads(identity)
    user_id = user_data['id']
    files = Files.query.filter_by(owner_id=user_id).all()
    result = [{"id": f.id, "name": f.name} for f in files]
    return jsonify(result)

@profile_bp.route('/cases', methods=['GET'])
@jwt_required()
def get_cases():
    identity = get_jwt_identity()
    user_id = json.loads(identity)['id']
    cases = Cases.query.filter_by(owner_id=user_id).all()
    result = [{"id":case.id, "name":case.name} for case in cases]
    return jsonify(result)

@profile_bp.route('/cases/<int:id>', methods=['GET'])
@jwt_required()
def get_case(id):
    identity = get_jwt_identity()
    user_id = json.loads(identity)['id']
    cases = Cases.query.filter_by(owner_id=user_id, id = id).all()
    if not cases:
        return jsonify({"message": "Case is not owned by this user"}), 401
    cases = cases[0]
    return jsonify({"id": cases.id, "name": cases.name, "audio_file": cases.audio_file, "text_file": cases.text_file})
