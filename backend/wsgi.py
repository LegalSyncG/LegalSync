import os
from backend.main import create_app
from backend.database.session import db
from flask_migrate import Migrate
from backend.logger import logger

app = create_app()

ENV = os.getenv("FLASK_ENV", "development")  
USE_MIGRATIONS = os.getenv("USE_MIGRATIONS", "true").lower() in {"1", "true", "yes"}

migrate = Migrate(app, db)

with app.app_context():
    if ENV == "development":
        db_url = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if db_url.startswith("sqlite:///"):
            db_file = db_url.replace("sqlite:///", "")
            if not os.path.exists(db_file):
                logger.info(f"SQLite DB not found, creating: {db_file}")
                db.create_all()
        else:
            db.create_all()
    else:
        if USE_MIGRATIONS:
            from flask_migrate import upgrade
            logger.info("Running migrations...")
            upgrade()
        else:
            db.create_all()