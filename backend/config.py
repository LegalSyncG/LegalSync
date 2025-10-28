import os


class Config:
    # Secrets: require env in production; allow dev fallbacks
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-secret-change-me"
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or "dev-only-jwt-secret-change-me"

    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///legalsync.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Uploads
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "./uploads")
    # Allow overriding max upload size via env (bytes or MB). Defaults to 50MB.
    MAX_CONTENT_LENGTH = (
        int(os.getenv("MAX_CONTENT_LENGTH_BYTES") or 0)
        or int(os.getenv("MAX_CONTENT_LENGTH") or 0)  # bytes, if set
        or int(os.getenv("MAX_CONTENT_LENGTH_MB") or 50) * 1024 * 1024
    )

    # CORS
    # Comma-separated origins in env, e.g. "http://localhost:8080,http://127.0.0.1:8080"
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
    # If using "*", browsers will ignore credentials; keep False unless whitelisting origins
    CORS_SUPPORTS_CREDENTIALS = os.getenv("CORS_SUPPORTS_CREDENTIALS", "false").lower() in {"1", "true", "yes"}
    CORS_HEADERS = "Content-Type"
