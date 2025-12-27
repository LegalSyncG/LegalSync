import json
from datetime import timedelta

from flask import Blueprint, request, jsonify, render_template
from backend.database.session import db
from flask_jwt_extended import create_access_token
import os
import re

from backend.routes.files import FileType, register_file, create_case
from backend.logger import logger 


def is_valid_email(email):
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w{2,}$'
    return re.match(pattern, email) is not None

# These are only two endpoints which create access token and identity
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/auth/signup', methods=['POST'])
def signup():
    data = request.get_json() or {}

    # Basic validation
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    from backend.database.models import User

    if User.query.filter_by(username=username).first():
        logger.error(f"Attempted signup with existing username: {username}")
        return jsonify({"error": "Username already exists"}), 400

    if len(username) > 80:
        logger.error(f"Attempted signup with too long username: {username}")
        return jsonify({"error": "Username is too long"}), 400

    user = User(username=username)
    email = data.get('email')
    if email:
        if not is_valid_email(email):
            logger.error(f"Attempted signup with invalid email: {email}")
            return jsonify({"error": "Invalid email"}), 400
        user.email = email
    logger.info(f"Creating new user: {username}")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    token = create_access_token(
        identity=json.dumps({"id": user.id, "username": user.username}),
        expires_delta=timedelta(days=1))
    cases = ['Sample Case 1', 'Sample Case 2']
    # Import create_case lazily to avoid circular imports during module import
    try:
        from backend.routes.files import create_case
        for i in [0, 1]:
            try:
                create_case(user.id, cases[i], i)
            except Exception:
                # Non-fatal: if creating sample case fails during tests, continue
                logger.error(f"Failed to create sample case {cases[i]} for user {username}")
                pass
    except Exception:
        pass
    return jsonify({"token": token}), 201  # Created

@auth_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    from backend.database.models import User
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        token = create_access_token(
            identity=json.dumps({"id": user.id, "username": user.username}),
            expires_delta=timedelta(days=1))
        logger.info(f"User logged in: {username}")
        return jsonify({"token": token}), 200  # Login successful
    logger.error(f"Failed login attempt for username: {username}")
    return jsonify({"error": "Invalid credentials"}), 401  # Unauthorized
