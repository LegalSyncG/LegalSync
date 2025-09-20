import json
from datetime import timedelta

from flask import Blueprint, request, jsonify, render_template
from database.session import db
from database.models import User
from flask_jwt_extended import create_access_token
import os
import re

from routes.files import FileType, register_file, create_case


def is_valid_email(email):
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w{2,}$'
    return re.match(pattern, email) is not None

# These are only two endpoints which create access token and identity
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/auth/signup', methods=['POST'])
def signup():
    data = request.get_json()

    if User.query.filter_by(username=data['username']).first():
        return jsonify({"error": "Username already exists"}), 400

    if len(data['username']) > 80:
        return jsonify({"error": "Username is too long"}), 400

    user = User(username=data['username'])
    if 'email' in data:
        if not is_valid_email(data['email']):
            return jsonify({"error": "Invalid email"}), 400
        user.email = data['email']
    user.set_password(data['password'])
    db.session.add(user)
    db.session.commit()

    token = create_access_token(
        identity=json.dumps({"id": user.id, "username": user.username}),
        expires_delta=timedelta(days=1))
    cases = ['Sample Case 1', 'Sample Case 2']
    for i in [0, 1]:
        create_case(user.id, cases[i], i)
    return jsonify({"token": token}), 201  # Created

@auth_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(username=data['username']).first()
    if user and user.check_password(data['password']):
        token = create_access_token(
            identity=json.dumps({"id": user.id, "username": user.username}),
            expires_delta=timedelta(days=1))
        return jsonify({"token": token}), 200  # Login successful
    return jsonify({"error": "Invalid credentials"}), 401  # Unauthorized
