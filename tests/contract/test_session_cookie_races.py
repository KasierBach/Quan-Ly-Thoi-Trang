from app.database import CaseInsensitiveRecord
from app.services.auth_service import AuthService


def test_credential_refresh_and_identity_reads_do_not_rewrite_cart_cookie(app, auth_client, monkeypatch):
    app.config['SESSION_REVALIDATION_ENABLED'] = True
    monkeypatch.setattr(
        AuthService,
        'get_identity_state',
        lambda _: CaseInsensitiveRecord(AuthVersion=1, FullName='Test User', Role='customer', DarkModeEnabled=False),
    )
    # The initial full-page response establishes the cookie-bound chat identity.
    response = auth_client.get('/login')
    assert response.status_code == 200
    with auth_client.session_transaction() as session:
        session['cart'] = [{'variant_id': 1, 'quantity': 3}]
        session['dark_mode'] = False
        session.permanent = True
    for path, method in [('/login', 'get'), ('/api/chat/guest-session', 'post')]:
        response = getattr(auth_client, method)(path)
        assert response.status_code == 200
        assert not any(header.startswith('session=') for header in response.headers.getlist('Set-Cookie'))
        with auth_client.session_transaction() as session:
            assert session['cart'][0]['quantity'] == 3


def test_permanent_sessions_do_not_refresh_on_every_background_request(app):
    assert app.config['SESSION_REFRESH_EACH_REQUEST'] is False
