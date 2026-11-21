import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app import create_app
from app.database import close_db_pool
from tests.e2e.stream_cleanup import CloseOnExhaustion


@pytest.fixture
def live_app(database_url, db_connection, tmp_path):
    config = {
        'APP_ENV': 'development',
        'TESTING': False,
        'SECRET_KEY': 'isolated-main-e2e-secret-2026-not-for-deployment',
        'DATABASE_URL': database_url,
        'SQLALCHEMY_DATABASE_URI': database_url.replace('postgresql://', 'postgresql+psycopg2://'),
        'DB_POOL_ENABLED': True,
        'DB_CONNECT_ENABLED': True,
        'SESSION_REVALIDATION_ENABLED': True,
        'WTF_CSRF_ENABLED': True,
        'SESSION_COOKIE_SECURE': False,
        'TRUSTED_HOSTS': ['localhost', '127.0.0.1'],
        'PUBLIC_BASE_URL': 'https://store.example.test',
        'MAIL_SUPPRESS_SEND': True,
        'MAIL_DEFAULT_SENDER': 'test-store@example.test',
        'MAIL_USE_SSL': False,
        'MAIL_USE_TLS': False,
        'RATELIMIT_ENABLED': False,
        'RTC_ICE_SERVERS': [],
        'PIXABAY_API_KEY': None,
        'UPLOAD_ROOT': str(tmp_path / 'uploads'),
    }
    application = create_app(config)

    # Werkzeug dev-server abort cleanup can skip closing a file wrapper. This
    # fixture-only wrapper preserves streaming and guarantees resource teardown.
    def serve(environ, start_response):
        return CloseOnExhaustion(application(environ, start_response))

    server = make_server('127.0.0.1', 0, serve, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', application
    handlers = application.extensions.get('chat_socket_handlers')
    if handlers is not None:
        handlers.close()
    server.shutdown()
    thread.join(timeout=10)
    close_db_pool(application)


@pytest.fixture(scope='session')
def browser_type_launch_args(browser_type_launch_args):
    return {
        **browser_type_launch_args,
        'args': [
            '--use-fake-device-for-media-stream',
            '--use-fake-ui-for-media-stream',
            '--auto-select-desktop-capture-source=Entire screen',
        ],
    }


@pytest.fixture
def gui_context(browser, live_app):
    base_url, _ = live_app
    context = browser.new_context(
        viewport={'width': 1280, 'height': 900}, base_url=base_url, permissions=['camera', 'microphone']
    )
    context.set_default_timeout(5000)
    # The test app's assets are local. Block unconfigured outbound calls rather than touching real services.
    context.route('https://**/*', lambda route: route.abort())
    yield context
    context.close()


@pytest.fixture
def gui_page(gui_context, request):
    page = gui_context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.test_errors = errors
    yield page
    destination = Path(__file__).resolve().parents[2] / 'artifacts' / 'e2e'
    destination.mkdir(parents=True, exist_ok=True)
    if not page.is_closed():
        page.screenshot(path=destination / f'{request.node.name.replace("[", "-").replace("]", "")}-last.png')
        (destination / f'{request.node.name.replace("[", "-").replace("]", "")}-errors.txt').write_text(
            '\n'.join(errors), encoding='utf-8'
        )
    page.close()
