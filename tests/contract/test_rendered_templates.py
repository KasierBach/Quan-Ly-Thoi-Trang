from pathlib import Path
import json
import re
import subprocess

import pytest
from bs4 import BeautifulSoup

from app import create_app
from app.database import close_db_pool


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('path', ['/login', '/register', '/forgot_password', '/reset_password/' + 'a' * 43])
def test_rendered_inline_scripts_are_valid_and_globals_do_not_collide(client, path, tmp_path):
    response = client.get(path)
    assert response.status_code == 200
    html = BeautifulSoup(response.data, 'html.parser')
    scripts = [
        script.string or script.get_text()
        for script in html.find_all('script')
        if not script.get('src') and script.get('type', '') not in {'application/json', 'text/template'}
    ]
    filename = tmp_path / 'rendered-scripts.js'
    filename.write_text('\n'.join(scripts), encoding='utf-8')
    checked = subprocess.run(
        ['node', '--check', str(filename)], capture_output=True, text=True, timeout=15, check=False
    )
    assert checked.returncode == 0, checked.stderr
    payload = html.select_one('#base-data')
    assert json.loads(payload.get_text())['searchUrl'] == '/api/search_autocomplete'
    assert not re.search(r'const\s+csrfToken\s*=', scripts[0] if scripts else '')


def test_all_jinja_templates_parse(app):
    for filename in app.jinja_env.list_templates():
        app.jinja_env.get_template(filename)


def test_local_ui_vendor_references_exist(client):
    html = BeautifulSoup(client.get('/login').data, 'html.parser')
    resources = [element.get('src') for element in html.find_all('script', src=True)]
    resources += [element.get('href') for element in html.find_all('link', rel='stylesheet')]
    for url in resources:
        if url.startswith('/static/'):
            assert (ROOT / 'app' / 'static' / url.removeprefix('/static/')).is_file(), url


def test_missing_secret_does_not_read_other_worktree_env(monkeypatch):
    monkeypatch.setenv('DISABLE_DOTENV', '1')
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    with pytest.raises(ValueError, match='SECRET_KEY'):
        create_app()


def test_app_instances_keep_caches_separate(app):
    from app.cache import app_cache

    with app.app_context():
        app_cache().set('key', 'first')
    alternate = create_app(
        {
            **{key: app.config[key] for key in app.config},
            'SECRET_KEY': 'other-test-secret-that-is-at-least-32-characters',
        }
    )
    try:
        with alternate.app_context():
            assert app_cache().get('key') is None
    finally:
        close_db_pool(alternate)
