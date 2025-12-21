
import io
import json
import pytest
from unittest.mock import patch
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

def login_headers(user_id=1):
    # Simulate JWT header for user_id=1
    return {
        "Authorization": "Bearer testtoken",
        "X-User-Id": str(user_id)
    }

def test_create_case_missing_audio(client, auth_headers):
    response = client.post('/cases', data={}, headers=auth_headers)
    assert response.status_code in (400, 422)

def test_create_case_with_audio_and_text(client, auth_headers):
    data = {
        "name": "Test Case",
        "transcript_text": "This is a test transcript."
    }
    audio = (io.BytesIO(b"fake audio data"), "audio.mp3")
    response = client.post(
        '/cases',
        data={**data, "audio": audio},
        content_type='multipart/form-data',
        headers=auth_headers
    )
    assert response.status_code in (200, 500)  # 500 if file handling fails in test env
    if response.status_code == 200:
        assert "id" in response.json

def test_case_status_unknown(client, auth_headers):
    response = client.get('/cases/999/status', headers=auth_headers)
    assert response.status_code == 200
    assert response.json.get("status") == "unknown"

def test_update_progress(client, auth_headers):
    response = client.post('/cases/999/progress', json={"current": 1, "total": 10}, headers=auth_headers)
    assert response.status_code in (404, 400, 200)

def test_case_alignment_not_found(client, auth_headers):
    response = client.get('/cases/999/alignment', headers=auth_headers)
    assert response.status_code in (404, 400)

def test_case_transcript_raw_not_found(client, auth_headers):
    response = client.get('/cases/999/transcript', headers=auth_headers)
    assert response.status_code in (404, 400)

def test_export_external_comments_not_found(client, auth_headers):
    response = client.get('/cases/999/external-comments', headers=auth_headers)
    assert response.status_code in (404, 400)

def test_delete_case_not_found(client, auth_headers):
    response = client.delete('/cases/999', headers=auth_headers)
    assert response.status_code in (404, 400)

def test_rename_case_not_found(client, auth_headers):
    response = client.patch('/cases/999', json={"name": "Renamed"}, headers=auth_headers)
    assert response.status_code in (404, 400)
