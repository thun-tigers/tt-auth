def test_login_seite_laedt(client):
    response = client.get('/login')
    assert response.status_code == 200


def test_login_mit_gueltigen_daten_setzt_jwt_cookie(client):
    response = client.post(
        '/login',
        data={'username': 'admin', 'password': 'test-admin-password'},
    )
    assert response.status_code == 302
    set_cookie = response.headers.get('Set-Cookie', '')
    assert 'tt_jwt=' in set_cookie
    assert 'HttpOnly' in set_cookie


def test_login_mit_falschem_passwort_setzt_kein_cookie(client):
    response = client.post(
        '/login',
        data={'username': 'admin', 'password': 'falsch'},
    )
    assert response.status_code == 200
    assert 'tt_jwt=' not in response.headers.get('Set-Cookie', '')


def test_login_mit_unbekanntem_benutzer(client):
    response = client.post(
        '/login',
        data={'username': 'gibtsnicht', 'password': 'egal'},
    )
    assert response.status_code == 200
    assert 'tt_jwt=' not in response.headers.get('Set-Cookie', '')


def test_gesperrter_benutzer_kann_sich_nicht_anmelden(app, client):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(username='gesperrt', role='user', is_active=True, account_status='suspended')
        user.set_password('geheim123')
        db.session.add(user)
        db.session.commit()

    response = client.post(
        '/login',
        data={'username': 'gesperrt', 'password': 'geheim123'},
    )
    assert response.status_code == 200
    assert 'tt_jwt=' not in response.headers.get('Set-Cookie', '')


def test_logout_loescht_jwt_cookie(admin_client):
    response = admin_client.get('/logout')
    assert response.status_code == 302
    set_cookie = response.headers.get('Set-Cookie', '')
    assert 'tt_jwt=;' in set_cookie


def test_unsichere_next_url_wird_verworfen(client):
    response = client.post(
        '/login?next=https://boese-seite.example/phishing',
        data={'username': 'admin', 'password': 'test-admin-password'},
    )
    assert response.status_code == 302
    assert 'boese-seite' not in response.headers.get('Location', '')
