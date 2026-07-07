from urllib.parse import parse_qs, urlparse

import jwt as pyjwt


def _service_id(app, name):
    from app.models import Service

    with app.app_context():
        return Service.query.filter_by(name=name).first().id


def test_launch_leitet_mit_sso_token_weiter(app, admin_client):
    service_id = _service_id(app, 'members')
    response = admin_client.get(f'/launch/{service_id}')
    assert response.status_code == 302

    location = urlparse(response.headers['Location'])
    assert location.path == '/auth/sso'

    token = parse_qs(location.query)['token'][0]
    payload = pyjwt.decode(
        token,
        'test-sso-secret',
        algorithms=['HS256'],
        audience='tt-members',
    )
    assert payload['username'] == 'admin'
    assert payload['jti']
    assert payload['service_role'] == 'admin'


def test_launch_ohne_login_wird_abgewiesen(app, client):
    service_id = _service_id(app, 'members')
    response = client.get(f'/launch/{service_id}')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_launch_unbekannter_service(admin_client):
    response = admin_client.get('/launch/99999')
    assert response.status_code == 302
    location = response.headers['Location']
    assert 'token=' not in location
