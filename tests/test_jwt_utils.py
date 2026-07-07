from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest


@pytest.fixture()
def admin_user(app):
    from app.models import User

    with app.app_context():
        yield User.query.filter_by(username='admin').first()


def test_jwt_roundtrip(app, admin_user):
    from app.jwt_utils import generate_jwt, validate_jwt

    with app.app_context():
        token = generate_jwt(admin_user)
        payload = validate_jwt(token)

    assert payload is not None
    assert payload['username'] == 'admin'
    assert payload['role'] == 'admin'
    assert payload['sub'] == str(admin_user.id)


def test_abgelaufenes_jwt_wird_abgelehnt(app):
    from app.jwt_utils import validate_jwt

    with app.app_context():
        now = datetime.now(timezone.utc)
        token = pyjwt.encode(
            {'sub': '1', 'iat': now - timedelta(hours=2), 'exp': now - timedelta(hours=1)},
            app.config['SECRET_KEY'],
            algorithm='HS256',
        )
        assert validate_jwt(token) is None


def test_manipuliertes_jwt_wird_abgelehnt(app, admin_user):
    from app.jwt_utils import generate_jwt, validate_jwt

    with app.app_context():
        token = generate_jwt(admin_user)
        header, payload, signature = token.split('.')
        tampered = f'{header}.{payload}.{"A" * len(signature)}'
        assert validate_jwt(tampered) is None


def test_jwt_mit_fremdem_secret_wird_abgelehnt(app):
    from app.jwt_utils import validate_jwt

    with app.app_context():
        now = datetime.now(timezone.utc)
        token = pyjwt.encode(
            {'sub': '1', 'role': 'admin', 'iat': now, 'exp': now + timedelta(hours=1)},
            'angreifer-secret',
            algorithm='HS256',
        )
        assert validate_jwt(token) is None


def test_sso_token_roundtrip(app, admin_user):
    from app.jwt_utils import generate_sso_token, validate_sso_token

    with app.app_context():
        token = generate_sso_token(admin_user, audience='tt-members')
        payload = validate_sso_token(token, audience='tt-members')

    assert payload is not None
    assert payload['username'] == 'admin'
    assert payload['aud'] == 'tt-members'
    assert payload['account_status'] == 'active'


def test_sso_token_enthaelt_eindeutige_jti(app, admin_user):
    from app.jwt_utils import generate_sso_token, validate_sso_token

    with app.app_context():
        first = validate_sso_token(generate_sso_token(admin_user, audience='tt-members'), audience='tt-members')
        second = validate_sso_token(generate_sso_token(admin_user, audience='tt-members'), audience='tt-members')

    assert first['jti']
    assert second['jti']
    assert first['jti'] != second['jti']


def test_sso_token_mit_falscher_audience_wird_abgelehnt(app, admin_user):
    from app.jwt_utils import generate_sso_token, validate_sso_token

    with app.app_context():
        token = generate_sso_token(admin_user, audience='tt-members')
        assert validate_sso_token(token, audience='tt-agenda') is None


def test_sso_token_ist_kurzlebig(app, admin_user):
    from app.jwt_utils import generate_sso_token, validate_sso_token

    with app.app_context():
        expiry = app.config['SSO_TOKEN_EXPIRY_SECONDS']
        token = generate_sso_token(admin_user, audience='tt-members')
        payload = validate_sso_token(token, audience='tt-members')

    assert payload['exp'] - payload['iat'] == expiry


def test_admin_erhaelt_wildcard_permissions(app, admin_user):
    from app.jwt_utils import generate_sso_token, validate_sso_token

    with app.app_context():
        token = generate_sso_token(admin_user, audience='tt-members')
        payload = validate_sso_token(token, audience='tt-members')

    assert payload['permissions'] == ['*']
