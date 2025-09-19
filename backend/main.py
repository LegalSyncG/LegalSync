from flask import Flask, jsonify
from config import Config
from database.session import db
from routes.auth import auth_bp
from flask_jwt_extended import JWTManager
from flask_cors import CORS
import os

from routes.comments import comments_bp
from routes.cases import cases_bp
from routes.profile import profile_bp


def create_app():
    # Serve static frontend from /app/static (copied in Dockerfile)
    app = Flask(__name__, static_folder='static', static_url_path='')
    app.config.from_object(Config)

    db.init_app(app)
    jwt = JWTManager(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(comments_bp)
    app.register_blueprint(cases_bp)
    # CORS setup from Config
    origins_raw = app.config.get("CORS_ORIGINS", "*")
    origins = [o.strip() for o in origins_raw.split(",") if o.strip()] if "," in origins_raw else origins_raw
    supports_credentials = bool(app.config.get("CORS_SUPPORTS_CREDENTIALS", False))
    # If wildcard origins, disable credentials to satisfy browser rules
    if origins == "*" and supports_credentials:
        supports_credentials = False
    CORS(app, resources={r"/*": {"origins": origins}}, supports_credentials=supports_credentials)

    # Serve the frontend index at root
    @app.route('/')
    def frontend_index():
        return app.send_static_file('index.html')
    
    @app.route('/health')
    def health():
        return jsonify({"status": "healthy"})
    

    return app
