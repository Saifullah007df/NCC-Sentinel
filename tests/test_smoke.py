import os, tempfile
from pathlib import Path
from fastapi.testclient import TestClient

def test_health_and_login_page():
    import app
    with TestClient(app.app) as client:
        assert client.get('/health').json()['status']=='ok'
        assert client.get('/login').status_code==200
        assert 'Welcome back' in client.get('/login').text

def test_cadet_cannot_access_admin():
    import app
    with TestClient(app.app) as client:
        assert client.get('/admin').status_code==401
        assert client.get('/cadet').status_code==401
