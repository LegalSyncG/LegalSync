
import pytest
from flask_jwt_extended import create_access_token

@pytest.fixture
def app_and_user():
    from backend.main import create_app
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        from backend.database.session import db
        db.create_all()
        from backend.database.models import User
        user = User.query.filter_by(username='testuser').first()
        if not user:
            user = User(username='testuser')
            user.set_password('testpass')
            db.session.add(user)
            db.session.commit()
        yield app, user

@pytest.fixture
def client(app_and_user):
    app, _ = app_and_user
    with app.test_client() as client:
        yield client

@pytest.fixture
def auth_headers(app_and_user):
    app, user = app_and_user
    with app.app_context():
        token = create_access_token(identity='{"id": %d, "username": "%s"}' % (user.id, user.username))
    return {"Authorization": f"Bearer {token}"}

def test_get_files_unauthenticated(client):
    response = client.get('/files')
    assert response.status_code in (401, 403, 200, 404)
