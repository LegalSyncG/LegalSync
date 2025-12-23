
import pytest
from flask_jwt_extended import create_access_token
import sys 
import os  

@pytest.fixture
def app_and_user():
    from backend.main import create_app
    from backend.database.session import db
    from backend.database.models import User

    app = create_app(testing=True)

    with app.app_context():
        db.create_all()

        user = User.query.filter_by(username='testuser').first()
        if not user:
            user = User(username='testuser')
            user.set_password('testpass')
            db.session.add(user)
            db.session.commit()

        yield app, user

        db.session.remove()
        db.drop_all()


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

def test_login_missing_data(client):
    response = client.post('/auth/login', json={})
    assert response.status_code in (400, 401, 422)

def test_login_invalid_user(client):
    response = client.post('/auth/login', json={"username": "nouser", "password": "badpass"})
    assert response.status_code == 401

def test_signup_missing_data(client):
    response = client.post('/auth/signup', json={})
    assert response.status_code in (400, 422)

def test_signup_and_login(client):
    # Signup
    response = client.post('/auth/signup', json={"username": "pytestuser", "password": "pytestpass"})
    assert response.status_code in (201, 400)  # 400 if already exists
    # Login
    response = client.post('/auth/login', json={"username": "pytestuser", "password": "pytestpass"})
    assert response.status_code == 200
    assert "token" in response.json
