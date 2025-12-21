from flask import Flask, jsonify
from backend.config import Config
from backend.database.session import db
from flask_jwt_extended import JWTManager
from flask_cors import CORS


def create_app(testing=False):
    app = Flask(__name__, static_folder='static', static_url_path='')
    app.config.from_object(Config)

    if testing:
        app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            JWT_SECRET_KEY="test-secret",  
        )

    # Extensions
    db.init_app(app)
    JWTManager(app)

    # Import and register blueprints after db is initialized to avoid
    # importing models before the SQLAlchemy extension is attached.
    from backend.routes.auth import auth_bp
    from backend.routes.profile import profile_bp
    from backend.routes.comments import comments_bp
    from backend.routes.cases import cases_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(comments_bp)
    app.register_blueprint(cases_bp)

    # CORS setup from Config
    origins_raw = app.config.get("CORS_ORIGINS", "*")
    origins = (
        [o.strip() for o in origins_raw.split(",") if o.strip()]
        if "," in origins_raw
        else origins_raw
    )
    supports_credentials = bool(app.config.get("CORS_SUPPORTS_CREDENTIALS", False))

    # If wildcard origins, disable credentials to satisfy browser rules
    if origins == "*" and supports_credentials:
        supports_credentials = False

    CORS(
        app,
        resources={r"/*": {"origins": origins}},
        supports_credentials=supports_credentials,
    )

    # Serve the frontend index at root
    @app.route("/")
    def frontend_index():
        return app.send_static_file("index.html")

    @app.route("/health")
    def health():
        return jsonify({"status": "healthy"})

    return app
