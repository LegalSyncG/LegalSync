from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.dialects.postgresql import ENUM
from backend.database.session import db

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=False, nullable=True)
    password_hash = db.Column(db.String(512), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Files(db.Model):
    __tablename__ = 'files'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=False, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    pathname = db.Column(db.String(255), unique=False, nullable=False)
    can_edit = db.Column(db.Boolean, unique=False, nullable=False)

class Cases(db.Model):
    __tablename__ = 'cases'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(80), unique=False, nullable=False)
    audio_file = db.Column(db.Integer, db.ForeignKey('files.id'), nullable=False)
    text_file = db.Column(db.Integer, db.ForeignKey('files.id'), nullable=False)
