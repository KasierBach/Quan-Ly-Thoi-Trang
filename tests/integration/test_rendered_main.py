"""Exercise real main routes, SQL rows, rendered resources, and script scopes.

Only shared loopback/disposable database fixtures are used. Node parses rendered
scripts; it does not execute app code, fetch CDNs, or simulate a browser.
"""

from contextlib import contextmanager
from pathlib import Path
import json
import re
import shutil
import subprocess
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
from flask import template_rendered, url_for
import pytest


pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = ROOT / 'app' / 'static'
REPORT_QUERY = {'start_date': '2026-04-01', 'end_date': '2026-04-30'}
CLASSIC_TYPES = {'', 'text/javascript', 'application/javascript'}
NODE = shutil.which('node')

# endpoint/path pairs were checked against main's actual url_map and routes.
PUBLIC = [
    ('main.home', '/', {}, 'index.html'),
    ('product.products', '/products', {}, 'products.html'),
    ('product.product_detail', '/product/1', {'product_id': 1}, 'product_detail.html'),
    ('cart.view_cart', '/cart', {}, 'cart.html'),
    ('main.contact', '/contact', {}, 'contact.html'),
    ('chat.messages_page', '/messages', {}, 'messages.html'),
]
ACCOUNT = [
    ('auth.my_account', '/my_account', {}, 'my_account.html'),
    ('product.view_wishlist', '/wishlist', {}, 'wishlist.html'),
    ('cart.order_detail', '/order/1', {'order_id': 1}, 'order_detail.html'),
    ('cart.order_detail', '/order/2', {'order_id': 2}, 'order_detail.html'),
    ('cart.order_confirmation', '/order_confirmation/1', {'order_id': 1}, 'order_confirmation.html'),
    ('cart.checkout', '/checkout', {}, 'checkout.html'),
]
ADMIN = [
    ('admin.admin_dashboard', '/admin', {}, 'admin/dashboard.html'),
    ('admin.admin_products', '/admin/products', {}, 'products.html'),
    ('admin.admin_manage_products', '/admin/products/manage', {}, 'admin/manage_products.html'),
    ('admin.admin_add_product', '/admin/products/add', {}, 'admin/add_product.html'),
    ('admin.admin_edit_product', '/admin/products/edit/1', {'product_id': 1}, 'admin/edit_product.html'),
    ('admin.admin_attributes', '/admin/attributes', {}, 'admin/attributes.html'),
    ('admin.admin_orders', '/admin/orders', {}, 'admin/orders.html'),
    ('admin.admin_order_detail', '/admin/orders/1', {'order_id': 1}, 'admin/order_detail.html'),
    ('admin.admin_order_detail', '/admin/orders/2', {'order_id': 2}, 'admin/order_detail.html'),
    ('admin.admin_customers', '/admin/customers', {}, 'admin/customers.html'),
    ('admin.admin_customer_detail', '/admin/customers/1', {'customer_id': 1}, 'admin/customer_detail.html'),
    ('admin.admin_comments', '/admin/comments', {}, 'admin/comments.html'),
    ('admin.admin_contact_messages', '/admin/contact_messages', {}, 'admin/contact_messages.html'),
    ('admin.admin_reports', '/admin/reports', {}, 'admin/reports.html'),
    ('chat.admin_messages_page', '/admin/messages', {}, 'messages.html'),
]
PAGE_CASES = [(actor, *page) for actor in ('anonymous', 'customer', 'admin') for page in PUBLIC]
PAGE_CASES += [
    ('anonymous', *page)
    for page in [
        ('auth.login', '/login', {}, 'login.html'),
        ('auth.register', '/register', {}, 'register.html'),
        ('auth.forgot_password', '/forgot_password', {}, 'forgot_password.html'),
        ('auth.reset_password', '/reset_password/' + 'a' * 43, {'token': 'a' * 43}, 'reset_password.html'),
    ]
]
PAGE_CASES += [('customer', *page) for page in ACCOUNT]
PAGE_CASES += [('admin', *page) for page in ADMIN]


def _session(client, actor='anonymous', cart=False):
    with client.session_transaction() as session:
        session.clear()
        if actor != 'anonymous':
            uid = 2 if actor == 'admin' else 1
            session.update(
                user_id=uid,
                user_name='Test Admin' if uid == 2 else 'Test Customer',
                role=actor,
                is_admin=actor == 'admin',
                auth_version=1,
            )
        if cart:
            # Intentionally stale client metadata: real route must refresh SQL price/name.
            session['cart'] = [
                {'variant_id': 1, 'quantity': 2, 'price': '0.01', 'product_name': 'Stale client product'}
            ]


def _uri(app, endpoint, expected=None, **values):
    with app.test_request_context('/'):
        path = url_for(endpoint, **values)
    if expected is not None:
        assert urlsplit(path).path == expected, (endpoint, path, expected)
    return path


@contextmanager
def _templates(app):
    rendered = []

    def record(sender, template, context, **_):
        rendered.append((template.name, context))

    template_rendered.connect(record, app, weak=False)
    try:
        yield rendered
    finally:
        template_rendered.disconnect(record, app)


def _get(app, client, endpoint, expected=None, query=None, **values):
    path = _uri(app, endpoint, expected, **values)
    with _templates(app) as rendered:
        response = client.get(path, query_string=query or {}, follow_redirects=False)
    assert response.status_code == 200, (
        f'{endpoint} {path} returned {response.status_code}: {response.get_data(as_text=True)[:300]}'
    )
    assert response.mimetype == 'text/html', (endpoint, response.mimetype)
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.html is not None and soup.body is not None, endpoint
    assert soup.title is not None and soup.title.get_text(strip=True), endpoint
    return soup, rendered


def _json(soup, selector):
    node = soup.select_one(selector)
    assert node is not None, f'Missing embedded data {selector}'
    return json.loads(node.get_text())


def _local_url(value, page):
    if not value or value.startswith(('#', 'data:', 'blob:', 'mailto:', 'tel:', 'javascript:')):
        return None
    parsed = urlsplit(urljoin('http://localhost' + page, value))
    if parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'localhost', '127.0.0.1'}:
        return None  # Never fetch external resources during integration tests.
    return parsed.path + (('?' + parsed.query) if parsed.query else '')


def _assets_and_links(app, client, soup, page):
    """Check actual rendered assets + local URL rules, not source Jinja strings."""
    adapter = app.url_map.bind('localhost')
    checked = {}
    for element in soup.select('[src], link[href], a[href], form[action], button[formaction]'):
        attributes = ['src'] if element.has_attr('src') else []
        attributes += [key for key in ('href', 'action', 'formaction') if element.has_attr(key)]
        for attribute in attributes:
            target = _local_url(element.get(attribute), page)
            if target is None:
                continue
            parsed = urlsplit(target)
            if parsed.path.startswith('/static/'):
                filename = unquote(parsed.path.removeprefix('/static/'))
                disk_path = (STATIC_ROOT / filename).resolve()
                assert disk_path.is_relative_to(STATIC_ROOT.resolve()) and disk_path.is_file(), (
                    f'{page}: missing local {element.name}[{attribute}] {target}'
                )
                if target not in checked:
                    asset = client.get(target)
                    try:
                        assert asset.status_code == 200, f'{page}: {target} returned {asset.status_code}'
                        content = asset.get_data()
                        assert content, f'{page}: empty static resource {target}'
                        checked[target] = content.decode('utf-8') if disk_path.suffix in {'.js', '.css'} else ''
                    finally:
                        asset.close()
            else:
                method = 'GET'
                if attribute in {'action', 'formaction'}:
                    form = element if element.name == 'form' else element.find_parent('form')
                    method = element.get('formmethod', form.get('method', 'get') if form else 'get').upper()
                # URL matching is read-only: do not follow logout/mutation actions.
                adapter.match(parsed.path, method=method)
    return checked


def _check_javascript(source, label, module=False):
    assert NODE is not None, 'Node.js is required for rendered script syntax checks'
    check = subprocess.run(
        [NODE, '--check', '--input-type=' + ('module' if module else 'commonjs')],
        input=source,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=20,
        check=False,
    )
    assert check.returncode == 0, f'{label}: rendered JavaScript does not parse\n{check.stderr}'


def _scripts(app, client, soup, page, assets):
    classic = []
    modules = []
    for index, element in enumerate(soup.find_all('script')):
        kind = element.get('type', '').lower().strip()
        if kind not in CLASSIC_TYPES | {'module'}:
            if kind in {'application/json', 'application/ld+json'} or element.get('id') == 'chart-data':
                json.loads(element.get_text())
            continue
        source = element.get_text()
        label = f'{page} inline script {index}'
        if element.get('src'):
            target = _local_url(element['src'], page)
            if target is None:
                continue
            source = assets.get(target)
            assert source is not None, f'Unchecked script resource {target}'
            label = target
        if kind == 'module':
            modules.append((label, source))
        else:
            # NO IIFE/block wrapping: all classic script globals share one scope.
            classic.append(f'\n/* rendered source: {label} */\n{source}\n;\n')
    _check_javascript('\n'.join(classic), page + ' combined classic scripts')
    seen = set()
    while modules:
        label, source = modules.pop()
        if label in seen:
            continue
        seen.add(label)
        _check_javascript(source, page + ' module ' + label, module=True)
        # Static ES-module dependencies must exist too; never import/execute them.
        for match in re.finditer(r'\b(?:from\s*|import\s*)[\'"]([^\'"]+)[\'"]', source):
            dependency = _local_url(match.group(1), label if label.startswith('/') else page)
            if dependency and urlsplit(dependency).path.startswith('/static/'):
                path = (STATIC_ROOT / unquote(urlsplit(dependency).path.removeprefix('/static/'))).resolve()
                assert path.is_relative_to(STATIC_ROOT.resolve()) and path.is_file(), (
                    f'{label}: missing module import {dependency}'
                )
                modules.append((dependency, path.read_text(encoding='utf-8')))


@pytest.mark.parametrize(
    'actor,endpoint,path,values,template', PAGE_CASES, ids=[actor + ':' + path for actor, _, path, _, _ in PAGE_CASES]
)
def test_seeded_main_routes_render_with_valid_resources_and_shared_script_scope(
    db_app, db_client, actor, endpoint, path, values, template
):
    _session(db_client, actor, cart=endpoint in {'cart.view_cart', 'cart.checkout'})
    query = REPORT_QUERY if endpoint == 'admin.admin_reports' else None
    soup, rendered = _get(db_app, db_client, endpoint, path, query=query, **values)
    assert any(name == template for name, _ in rendered), (path, [name for name, _ in rendered])
    config = _json(soup, '#base-data')
    assert config['isLoggedIn'] is (actor != 'anonymous')
    assert config['searchUrl'] == _uri(db_app, 'product.search_autocomplete')
    if endpoint in {
        'main.home',
        'product.products',
        'product.product_detail',
        'cart.view_cart',
        'cart.checkout',
        'cart.order_detail',
        'cart.order_confirmation',
    }:
        product_name = (
            'Test Summer Dress'
            if endpoint == 'cart.order_detail' and values.get('order_id') == 2
            else 'Test Cotton Shirt'
        )
        assert product_name in soup.get_text(), f'{path}: seeded SQL product missing'
    if endpoint == 'auth.my_account':
        assert 'customer@example.test' in str(soup)
    if endpoint == 'admin.admin_customer_detail':
        assert 'customer@example.test' in soup.get_text()
    if endpoint == 'cart.view_cart':
        assert soup.select_one('#price-1').get_text(strip=True) == '199,000 đ'
        assert soup.select_one('#subtotal-1').get_text(strip=True) == '398,000 đ'
    if endpoint == 'cart.checkout':
        assert soup.select_one('#checkoutForm')['action'] == '/checkout'
        assert soup.select_one('input[name=email]')['value'] == 'customer@example.test'
        assert 'Stale client product' not in soup.get_text()
    assets = _assets_and_links(db_app, db_client, soup, path)
    _scripts(db_app, db_client, soup, path, assets)


def test_all_main_jinja_templates_compile_against_real_app_environment(db_app):
    failures = []
    for name in db_app.jinja_env.list_templates():
        try:
            db_app.jinja_env.get_template(name)
        except Exception as error:
            failures.append(f'{name}: {type(error).__name__}: {error}')
    assert not failures, '\n'.join(failures)


@pytest.mark.parametrize('actor,expected_json', [('anonymous', 401), ('customer', 403)])
def test_main_admin_and_account_html_json_auth_guards(db_app, db_client, actor, expected_json):
    _session(db_client, actor)
    for endpoint, path, values, _ in ADMIN:
        target = _uri(db_app, endpoint, path, **values)
        response = db_client.get(target, headers={'Accept': 'application/json'})
        assert response.status_code == expected_json, (actor, target, response.status_code)
        assert response.is_json
        response = db_client.get(target)
        if endpoint == 'chat.admin_messages_page':
            assert response.status_code == expected_json
        else:
            assert response.status_code == 302, (actor, target, response.status_code)
            location = urlsplit(response.headers['Location'])
            assert location.path == ('/login' if actor == 'anonymous' else '/')
            if actor == 'anonymous':
                assert parse_qs(location.query)['next'] == [target]
    if actor == 'anonymous':
        for endpoint, path, values, _ in ACCOUNT:
            target = _uri(db_app, endpoint, path, **values)
            assert db_client.get(target, headers={'Accept': 'application/json'}).status_code == 401
            response = db_client.get(target)
            assert response.status_code == 302 and urlsplit(response.headers['Location']).path == '/login'


def test_empty_account_catalog_and_admin_filters_render_without_fake_rows(db_app, db_client):
    _session(db_client, 'admin')  # seeded admin has no personal orders/wishlist
    for endpoint, expected in [('auth.my_account', '/my_account'), ('product.view_wishlist', '/wishlist')]:
        soup, rendered = _get(db_app, db_client, endpoint, expected)
        context = rendered[-1][1]
        rows = context['orders'] if endpoint == 'auth.my_account' else context['wishlist_items']
        assert not rows
        assert 'Test Other Customer' not in soup.get_text()
    queries = [
        ('product.products', '/products', {'search': 'synthetic-no-such-product'}, 'products'),
        ('admin.admin_customers', '/admin/customers', {'search': 'synthetic-no-such-customer'}, 'customers'),
        ('admin.admin_orders', '/admin/orders', {'status': 'Processing'}, 'orders'),
        ('admin.admin_comments', '/admin/comments', {'filter': 'no_reply'}, 'comments'),
        ('admin.admin_contact_messages', '/admin/contact_messages', {'status': 'Answered'}, 'messages'),
    ]
    for endpoint, path, query, key in queries:
        soup, rendered = _get(db_app, db_client, endpoint, path, query=query)
        assert not rendered[-1][1][key], (path, key)
        assets = _assets_and_links(db_app, db_client, soup, path)
        _scripts(db_app, db_client, soup, path, assets)


def test_empty_cart_and_checkout_redirect_to_real_cart_page(db_app, db_client):
    _session(db_client, 'customer')
    soup, rendered = _get(db_app, db_client, 'cart.view_cart', '/cart')
    assert rendered[-1][1]['cart'] == []
    assert rendered[-1][1]['total'] == 0
    assert soup.select_one('#cart-item-1') is None
    response = db_client.get(_uri(db_app, 'cart.checkout', '/checkout'))
    assert response.status_code == 302
    assert urlsplit(response.headers['Location']).path == '/cart'
    assert db_client.get('/checkout', headers={'Accept': 'application/json'}).status_code == 400


def test_real_missing_and_foreign_order_routes_return_404_not_other_customer_data(db_app, db_client):
    _session(db_client, 'customer')
    paths = [
        _uri(db_app, 'product.product_detail', product_id=2147483647),
        _uri(db_app, 'cart.order_detail', order_id=2147483647),
        _uri(db_app, 'cart.order_detail', order_id=3),
        _uri(db_app, 'cart.order_confirmation', order_id=3),
    ]
    for path in paths:
        response = db_client.get(path)
        assert response.status_code == 404, (path, response.status_code)
        assert 'Test Other Customer' not in response.get_data(as_text=True)
        soup = BeautifulSoup(response.data, 'html.parser')
        assert soup.title is not None
        assets = _assets_and_links(db_app, db_client, soup, path)
        _scripts(db_app, db_client, soup, path, assets)
    _session(db_client, 'admin')
    for endpoint, values in [
        ('admin.admin_customer_detail', {'customer_id': 2147483647}),
        ('admin.admin_order_detail', {'order_id': 2147483647}),
        ('admin.admin_edit_product', {'product_id': 2147483647}),
    ]:
        path = _uri(db_app, endpoint, **values)
        assert db_client.get(path).status_code == 404, path


@pytest.mark.parametrize('group', ['day', 'week', 'month', 'year'])
def test_rendered_april_report_uses_delivered_rows_and_consistent_chart_payload(db_app, db_client, group):
    _session(db_client, 'admin')
    soup, rendered = _get(
        db_app, db_client, 'admin.admin_reports', '/admin/reports', query={**REPORT_QUERY, 'group_by': group}
    )
    context = rendered[-1][1]
    assert context['total_revenue'] == 398000
    assert context['total_category_revenue'] == 398000
    assert context['total_orders'] == 1
    assert _json(soup, '#report-config') == {
        'startDate': '2026-04-01',
        'endDate': '2026-04-30',
        'groupBy': group,
        'emailUrl': _uri(db_app, 'admin.admin_send_report_email'),
    }
    chart = _json(soup, '#chart-data')
    assert len(chart['dailyLabels']) == len(chart['dailyData']) == 1
    assert chart['dailyData'] == [398000.0]
    assert chart['categoryLabels'] == ['Test Tops']
    assert chart['categoryData'] == [398000.0]
    assert soup.select_one('.stat-card.revenue .stat-value').get_text(strip=True) == '398,000 đ'
    assets = _assets_and_links(db_app, db_client, soup, '/admin/reports')
    _scripts(db_app, db_client, soup, '/admin/reports', assets)


def test_empty_report_chart_payload_has_no_seeded_revenue(db_app, db_client):
    _session(db_client, 'admin')
    soup, rendered = _get(
        db_app,
        db_client,
        'admin.admin_reports',
        '/admin/reports',
        query={'start_date': '2026-03-01', 'end_date': '2026-03-31'},
    )
    context = rendered[-1][1]
    assert context['total_revenue'] == context['total_orders'] == 0
    assert _json(soup, '#chart-data') == {
        'dailyLabels': [],
        'dailyData': [],
        'categoryLabels': [],
        'categoryData': [],
    }
    assets = _assets_and_links(db_app, db_client, soup, '/admin/reports')
    _scripts(db_app, db_client, soup, '/admin/reports', assets)


@pytest.mark.parametrize(
    'state,options',
    [
        ('Pending', {'Pending', 'Processing', 'Cancelled'}),
        ('Processing', {'Processing', 'Shipped', 'Cancelled'}),
        ('Shipped', {'Shipped', 'Delivered'}),
        ('Delivered', set()),
        ('Cancelled', set()),
    ],
)
def test_actual_order_status_controls_match_database_lifecycle(db_app, db_client, db_connection, state, options):
    # Real seeded Pending order 2 belongs to customer 1. Use its SQL functions.
    with db_connection.cursor() as cursor:
        for next_state in {
            'Pending': [],
            'Processing': ['Processing'],
            'Shipped': ['Processing', 'Shipped'],
            'Delivered': ['Processing', 'Shipped', 'Delivered'],
            'Cancelled': ['Cancelled'],
        }[state]:
            cursor.execute('SELECT sp_UpdateOrderStatus(2, %s)', (next_state,))
    db_connection.commit()
    _session(db_client, 'customer')
    soup, rendered = _get(db_app, db_client, 'cart.order_detail', '/order/2', order_id=2)
    assert rendered[-1][1]['order'].Status == state
    assert (soup.select_one('#cancel-order-btn') is not None) is (state == 'Pending')
    assert rendered[-1][1]['order_details'][0].Price == rendered[-1][1]['order_details'][0].UnitPrice == 399000
    _session(db_client, 'admin')
    soup, rendered = _get(db_app, db_client, 'admin.admin_order_detail', '/admin/orders/2', order_id=2)
    actual_options = {option['value'] for option in soup.select('select[name=status] option')}
    assert actual_options == options
    assert rendered[-1][1]['order'].Status == state


def test_invalid_render_route_filters_return_400_instead_of_sql_or_template_error(db_app, db_client):
    _session(db_client, 'admin', cart=True)
    invalid = [
        ('/products', {'category': 'bad'}),
        ('/products', {'category': '-1'}),
        ('/products', {'color': '0'}),
        ('/products', {'size': '1.5'}),
        ('/products', {'min_price': 'NaN'}),
        ('/products', {'min_price': '3', 'max_price': '2'}),
        ('/products', {'in_stock': 'true'}),
        ('/checkout', {'buy_now': 'bad'}),
        ('/admin/products', {'sort_by': 'bad'}),
        ('/admin/customers', {'role': 'bad'}),
        ('/admin/orders', {'status': 'bad'}),
        ('/admin/comments', {'filter': 'bad'}),
        ('/admin/contact_messages', {'status': 'bad'}),
        ('/admin/reports', {'start_date': '2026-02-30'}),
        ('/admin/reports', {'start_date': '2026-05-01', 'end_date': '2026-04-30'}),
        ('/admin/reports', {**REPORT_QUERY, 'group_by': 'bad'}),
    ]
    for path, query in invalid:
        response = db_client.get(path, query_string=query)
        assert response.status_code == 400, (path, query, response.status_code, response.get_data(as_text=True)[:200])


def test_message_page_script_handles_real_database_display_name_with_apostrophe(db_app, db_client, db_connection):
    with db_connection.cursor() as cursor:
        cursor.execute('UPDATE Customers SET FullName = %s WHERE CustomerID = 1', ("Synthetic O'Reilly",))
    db_connection.commit()
    _session(db_client, 'customer')
    soup, _ = _get(db_app, db_client, 'chat.messages_page', '/messages')
    inline = '\n'.join(script.get_text() for script in soup.find_all('script') if not script.get('src'))
    assert 'O&#39;Reilly' not in inline and 'O&#x27;Reilly' not in inline, (
        'Display names must use JavaScript/JSON serialization, not literal HTML entities inside scripts'
    )
    assets = _assets_and_links(db_app, db_client, soup, '/messages')
    _scripts(db_app, db_client, soup, '/messages', assets)


def test_product_page_review_comment_consumers_receive_real_seeded_api_contract(db_app, db_client):
    _session(db_client, 'customer')
    soup, _ = _get(db_app, db_client, 'product.product_detail', '/product/1', product_id=1)
    variants = _json(soup, '#variants-data')
    assert variants['1_1'] == {'variant_id': 1, 'quantity': 98}
    reviews = db_client.get(_uri(db_app, 'product.get_product_reviews'), query_string={'product_id': 1})
    assert reviews.status_code == 200
    review_data = reviews.get_json()
    assert review_data['success'] is True
    assert review_data['total_reviews'] == 1 and review_data['average_rating'] == 5
    assert review_data['reviews'][0]['customer_name'] == 'Test Customer'
    assert review_data['reviews'][0]['comment'] == 'Synthetic integration review'
    comments = db_client.get(_uri(db_app, 'product.get_product_comments'), query_string={'product_id': 1})
    assert comments.status_code == 200
    comment_data = comments.get_json()
    assert comment_data['success'] is True
    assert comment_data['comments'][0]['reply'] == 'Synthetic admin reply'
    assert comment_data['comments'][0]['content'] == 'Synthetic integration comment'
