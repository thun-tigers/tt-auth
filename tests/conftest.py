import os
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def app():
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    os.environ.setdefault('SECRET_KEY', 'test-secret')
    os.environ.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')
    os.environ.setdefault('SSO_SHARED_SECRET', 'test-sso-secret')
    os.environ.setdefault('DEFAULT_ADMIN_USERNAME', 'admin')
    os.environ.setdefault('DEFAULT_ADMIN_PASSWORD', 'test-admin-password')
    os.environ.setdefault('AUTO_CREATE_DB', 'true')
    os.environ.setdefault('CREATE_DEFAULT_USERS', 'true')
    os.environ.setdefault('CREATE_DEFAULT_SERVICES', 'true')

    from app import create_app

    app = create_app()
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_client(app, client):
    response = client.post(
        '/login',
        data={'username': 'admin', 'password': 'test-admin-password'},
    )
    assert response.status_code == 302
    return client
