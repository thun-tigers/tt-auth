"""Verifiziert, dass tt-auth das geteilte Layout aus tt-common rendert."""


def test_login_seite_nutzt_geteiltes_layout(client):
    html = client.get('/login').get_data(as_text=True)
    # Assets kommen aus tt-common
    assert '/tt-common-static/js/table_enhancements.js' in html
    assert '/tt-common-static/tt-logo.png' in html
    # zentrales Theme-Toggle-Markup
    assert 'id="themeToggle"' in html


def test_dashboard_rendert_mit_admin_nav(admin_client):
    html = admin_client.get('/').get_data(as_text=True)
    assert html  # 200 + Inhalt
    # service-spezifische Admin-Nav aus dem Block
    assert 'Benutzer' in html
    assert 'Stammdaten' in html
    assert 'Services' in html
    # geteiltes Layout aktiv
    assert '/tt-common-static/' in html
