# backend/app.py
from backend.main import create_app
from backend.database.session import db
from flask_migrate import Migrate

app = create_app()
migrate = Migrate(app, db)
