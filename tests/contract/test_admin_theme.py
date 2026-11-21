"""Admin UX contracts render against mocked reads; no database or browser is used."""

from pathlib import Path
import re
import shutil
import subprocess

from bs4 import BeautifulSoup
import pytest

from tests.contract.test_admin_routes import mock_admin_reads, payload_script


ROOT = Path(__file__).resolve().parents[2]
ADMIN = ROOT / 'app' / 'templates' / 'admin'
CSS = ROOT / 'app' / 'static' / 'css' / 'admin-theme.css'
JS = ROOT / 'app' / 'static' / 'js' / 'admin-theme.js'
PAGES = (
    '/admin',
    '/admin/reports',
    '/admin/products/add',
    '/admin/products/edit/1',
    '/admin/products/manage',
    '/admin/orders',
    '/admin/orders/1',
    '/admin/customers',
    '/admin/customers/1',
    '/admin/comments',
    '/admin/contact_messages',
    '/admin/attributes',
)


@pytest.fixture
def themed_admin(admin_client, monkeypatch):
    assert not admin_client.application.config['DB_CONNECT_ENABLED']
    assert not admin_client.application.config['DB_POOL_ENABLED']
    mock_admin_reads(monkeypatch)
    return admin_client


@pytest.mark.parametrize('path', PAGES)
@pytest.mark.parametrize('dark', [False, True], ids=['light', 'dark'])
def test_admin_rendered_shell_is_shared_scoped_and_footer_free(themed_admin, path, dark):
    with themed_admin.session_transaction() as session:
        session['dark_mode'] = dark
    response = themed_admin.get(path)
    assert response.status_code == 200
    html = BeautifulSoup(response.data, 'html.parser')
    assert html.html['data-bs-theme'] == ('dark' if dark else 'light')
    assert 'admin-page' in html.body['class']
    assert not html.find('footer')
    assert not html.select('#newsletter-form, #searchForm')
    styles = [link['href'] for link in html.select('link[rel="stylesheet"]')]
    assert styles.count('/static/css/admin.css') == 1
    assert styles.count('/static/css/admin-theme.css') == 1
    assert styles.index('/static/css/admin.css') < styles.index('/static/css/admin-theme.css')
    assert html.select_one('body > .main-content .admin-layout')
    assert html.select_one('.admin-sidebar .list-group-item.active')
    assert html.select_one('#toggleTheme')
    assert html.select_one('#darkIcon') and html.select_one('#lightIcon')
    assert html.select_one('meta[name="csrf-token"]')['content']
    logout = html.select_one('form[action="/logout"]')
    assert logout['method'] == 'post'
    assert logout.select_one('input[name="csrf_token"]')['value']
    helper = html.select('script[src="/static/js/admin-theme.js"]')
    assert len(helper) == 1 and helper[0].has_attr('defer')


def test_all_admin_templates_inherit_and_preserve_extension_hooks():
    for path in ADMIN.glob('*.html'):
        source = path.read_text(encoding='utf-8')
        expected = 'base.html' if path.name == 'base.html' else 'admin/base.html'
        assert f"{{% extends '{expected}' %}}" in source, path.name
        if path.name != 'base.html':
            assert 'css/admin.css' not in source, path.name
            assert ':root' not in source, path.name
            for block in ('styles', 'scripts'):
                for contents in re.findall(rf'{{% block {block} %}}(.*?){{% endblock %}}', source, re.S):
                    assert '{{ super() }}' in contents, (path.name, block)
    legacy = (ROOT / 'app' / 'static' / 'css' / 'admin.css').read_text(encoding='utf-8')
    report = (ADMIN / 'reports.html').read_text(encoding='utf-8')
    for source in (legacy, report):
        assert 'background-clip: text' not in source
        assert 'shimmer' not in source
        assert '.page-header::before' not in source
    for name in ('dashboard.html', 'reports.html'):
        assert '<div class="main-content">' not in (ADMIN / name).read_text(encoding='utf-8')


def test_theme_rules_are_admin_scoped_and_cover_operational_states():
    source = CSS.read_text(encoding='utf-8')
    assert len(source.splitlines()) <= 250
    assert ':root' not in source
    assert not re.search(r'\.(?:chat|message|conversation)[\w-]*', source)
    # Every CSS rule selector (including rules inside media queries) retains admin scope.
    stripped = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    for selector in re.findall(r'(?:^|[{}])\s*([^{}]+)\{', stripped):
        if not selector.strip().startswith('@'):
            assert '.admin-page' in selector, selector
    for token in ('--admin-surface', '--admin-text', '--admin-muted', '--admin-border', '--admin-hover'):
        assert source.count(token + ':') >= 2
    for selector in (
        '.form-section',
        '.search-section',
        '.table',
        '.text-dark',
        '.bg-white',
        '.bg-light',
        '.form-control::placeholder',
        ':focus-visible',
        '.btn-icon',
        '.admin-sidebar',
    ):
        assert selector in source
    assert 'min-height: 44px' in source and 'min-width: 44px' in source
    assert 'height: auto' in source and 'overflow: visible' in source
    assert 'flex: 0 0 17rem' in source and 'flex-direction: column' in source
    assert 'white-space: nowrap' in source


def luminance(hex_color):
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


def test_both_token_palettes_have_readable_body_placeholder_and_semantic_text():
    source = CSS.read_text(encoding='utf-8')
    palettes = re.findall(r'(?:^|\n)(?:\[data-bs-theme="dark"\] )?\.admin-page \{(.*?)\n\}', source, re.S)
    assert len(palettes) == 2
    for block in palettes:
        tokens = dict(re.findall(r'--admin-([\w-]+):\s*(#[0-9a-f]{6})', block))
        for foreground in ('text', 'muted', 'primary', 'success', 'warning', 'info', 'danger'):
            for background in ('bg', 'surface', 'subtle'):
                levels = sorted((luminance(tokens[foreground]), luminance(tokens[background])))
                assert (levels[1] + 0.05) / (levels[0] + 0.05) >= 4.5, (foreground, background, tokens)


@pytest.mark.parametrize('path', PAGES)
def test_rendered_admin_inline_scripts_still_parse(themed_admin, path, tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the offline JavaScript syntax contract')
    html = BeautifulSoup(themed_admin.get(path).data, 'html.parser')
    scripts = [
        script.get_text()
        for script in html.find_all('script')
        if not script.get('src')
        and script.get('type', '') not in {'application/json', 'application/ld+json', 'text/template'}
    ]
    rendered = tmp_path / 'admin-rendered.js'
    rendered.write_text('\n'.join(scripts), encoding='utf-8')
    checked = subprocess.run([node, '--check', str(rendered)], capture_output=True, text=True, timeout=15, check=False)
    assert checked.returncode == 0, checked.stderr


def test_charts_and_actions_keep_their_data_and_auth_hooks(themed_admin):
    dashboard = themed_admin.get('/admin').get_data(as_text=True)
    assert payload_script(dashboard, 'revenue-data')[0]['TotalRevenue'] == 200.2
    assert payload_script(dashboard, 'category-data')[0]['TotalRevenue'] == 200.2
    report = themed_admin.get('/admin/reports').get_data(as_text=True)
    assert payload_script(report, 'chart-data')['dailyData'] == [200.2]
    assert 'form.requestSubmit()' in report
    assert "'X-CSRFToken': csrfToken" in report
    assert 'generateLabels: function (chart)' in report
    assert 'backgroundColor: chartColors' in report
    helper = JS.read_text(encoding='utf-8')
    assert 'ChartAPI.getChart(canvas)' in helper
    assert 'MutationObserver' in helper and "['data-bs-theme']" in helper
    assert "chart.update('none')" in helper
    assert 'fetch(' not in helper and 'new Chart' not in helper
    assert 'Chart.defaults' not in helper and 'chart.data =' not in helper
    assert '.datasets' not in helper


def test_chart_helper_updates_existing_instances_without_data_or_callback_changes():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the offline chart-helper runtime contract')
    harness = r"""
        const fs = require('node:fs');
        const vm = require('node:vm');
        const assert = require('node:assert/strict');
        const code = fs.readFileSync(process.argv[1], 'utf8');
        const data = { labels: ['A'], datasets: [{ data: [200.2], backgroundColor: ['#ff6b6b'] }] };
        const callback = value => `${value} VND`;
        const labels = () => [{ text: 'A (100%)', fillStyle: '#ff6b6b', hidden: false, index: 0 }];
        const charts = [
            { data, options: { scales: { y: { ticks: { callback }, grid: { display: false } } },
                plugins: { legend: { labels: { generateLabels: labels } }, tooltip: { callbacks: { label: callback } } } } },
            { data, options: { scales: {}, plugins: { legend: false, tooltip: false } } }
        ];
        const canvases = [{}, {}, {}];
        let theme = 'light';
        let observer;
        let observeOptions;
        let domReady;
        let loaded;
        let frame;
        let updates = 0;
        for (const chart of charts) chart.update = mode => { assert.equal(mode, 'none'); updates++; };
        const palettes = {
            light: { '--admin-text': '#202b3d', '--admin-muted': '#536176', '--admin-surface': '#ffffff', '--admin-border': '#cbd3df' },
            dark: { '--admin-text': '#edf2fa', '--admin-muted': '#b5c1d4', '--admin-surface': '#202a3a', '--admin-border': '#4c5c73' }
        };
        const document = {
            body: { classList: { contains: name => name === 'admin-page' } }, documentElement: {}, readyState: 'loading',
            querySelectorAll: selector => { assert.equal(selector, '.admin-page > .main-content canvas'); return canvases; },
            addEventListener: (name, fn) => { assert.equal(name, 'DOMContentLoaded'); domReady = fn; }
        };
        const context = {
            document, window: { Chart: { getChart: canvas => charts[canvases.indexOf(canvas)] },
                addEventListener: (name, fn) => { assert.equal(name, 'load'); loaded = fn; } },
            getComputedStyle: () => ({ getPropertyValue: name => palettes[theme][name] || '' }),
            requestAnimationFrame: fn => { frame = fn; },
            MutationObserver: class { constructor(fn) { observer = fn; }
                observe(root, options) { assert.equal(root, document.documentElement); observeOptions = options; } }
        };
        vm.runInNewContext(code, context);
        assert.equal(observeOptions.attributes, true);
        assert.equal(observeOptions.attributeFilter.join(','), 'data-bs-theme');
        assert.equal(updates, 0);
        domReady(); frame();
        assert.equal(charts[0].options.plugins.legend.labels.color, '#202b3d');
        const wrapped = charts[0].options.plugins.legend.labels.generateLabels;
        assert.equal(wrapped()[0].fontColor, '#202b3d');
        assert.equal(wrapped()[0].text, 'A (100%)');
        theme = 'dark'; observer(); observer(); frame();
        const options = charts[0].options;
        assert.equal(options.plugins.legend.labels.color, '#edf2fa');
        assert.equal(options.plugins.legend.labels.generateLabels, wrapped);
        assert.equal(wrapped()[0].fontColor, '#edf2fa');
        assert.equal(wrapped()[0].fillStyle, '#ff6b6b');
        assert.equal(options.plugins.tooltip.backgroundColor, '#202a3a');
        assert.equal(options.plugins.tooltip.bodyColor, '#edf2fa');
        assert.equal(options.plugins.tooltip.borderColor, '#4c5c73');
        assert.equal(options.scales.y.ticks.color, '#b5c1d4');
        assert.equal(options.scales.y.grid.color, '#4c5c73');
        assert.equal(options.scales.y.grid.display, false);
        assert.equal(options.scales.y.ticks.callback, callback);
        assert.equal(options.plugins.tooltip.callbacks.label, callback);
        assert.equal(charts[0].data, data);
        assert.equal(charts[1].options.plugins.legend, false);
        assert.equal(charts[1].options.plugins.tooltip, false);
        assert.equal(JSON.stringify(data), '{"labels":["A"],"datasets":[{"data":[200.2],"backgroundColor":["#ff6b6b"]}]}');
        loaded(); frame();
        assert.equal(updates, 6);
        context.window.Chart = undefined;
        observer(); frame();
        document.body.classList.contains = () => false;
        vm.runInNewContext(code, context);
    """
    checked = subprocess.run([node, '-e', harness, str(JS)], capture_output=True, text=True, timeout=15, check=False)
    assert checked.returncode == 0, checked.stderr
