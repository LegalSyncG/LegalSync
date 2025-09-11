from main import create_app
from database.session import db

app = create_app()

with app.app_context():
    db.create_all()
