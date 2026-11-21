import json
from decimal import Decimal
from unittest.mock import Mock
from xml.etree import ElementTree

from bs4 import BeautifulSoup
import psycopg2
import pytest

from app.database import CaseInsensitiveRecord
from app.services.auth_service import AuthService
from app.services.base_service import BaseService
from app.services.category_service import CategoryService
from app.services.main_service import MainService
from app.services.product_service import ProductService


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('SEO contracts must not use a live database')

    monkeypatch.setattr(psycopg2, 'connect', forbidden)
    monkeypatch.setattr(BaseService, 'get_connection', staticmethod(forbidden))


@pytest.fixture
def seo_catalog(app, monkeypatch):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test'
    product = CaseInsensitiveRecord(
        ProductID=7,
        ProductName='Áo "đẹp" & </script><script>alert(1)</script>',
        Description='Mô tả thật "vải" & </script><script>alert(2)</script>',
        CategoryID=3,
        CategoryName='Áo & quần',
        Price=Decimal('1234567890123456.78'),
        OriginalPrice=Decimal('1234567890123456.78'),
        ImageURL='images/7.jpg',
        AverageRating=5,
        ReviewCount=99,
    )
    variants = [
        CaseInsensitiveRecord(VariantID=9, ColorID=1, ColorName='Đen', SizeID=1, SizeName='M', Quantity=2),
    ]
    product_read = Mock(side_effect=lambda pid: product if pid == 7 else None)
    variants_read = Mock(return_value=variants)
    search = Mock(
        return_value={
            'products': [product],
            'total_records': 25,
            'total_pages': 3,
            'current_page': 2,
            'offset': 12,
        }
    )
    monkeypatch.setattr(ProductService, 'get_product_by_id', product_read)
    monkeypatch.setattr(ProductService, 'get_product_variants', variants_read)
    monkeypatch.setattr(ProductService, 'search_products', search)
    monkeypatch.setattr(ProductService, 'get_all_colors', lambda: [])
    monkeypatch.setattr(ProductService, 'get_all_sizes', lambda: [])
    monkeypatch.setattr(ProductService, 'get_featured_products', lambda limit: [product])
    monkeypatch.setattr(ProductService, 'get_best_selling_products', lambda limit: [])
    monkeypatch.setattr(CategoryService, 'get_all_categories', lambda: [])
    return product, variants, product_read, variants_read, search


def document(response):
    return BeautifulSoup(response.data, 'html.parser')


def test_public_home_and_contact_use_configured_origin_not_host(app, client, seo_catalog):
    app.config['TRUSTED_HOSTS'] = ['localhost', 'untrusted.example.test']
    for path in ['/', '/contact']:
        response = client.get(path + '?callbacksecret=do-not-promote', base_url='https://untrusted.example.test')
        assert response.status_code == 200
        head = document(response).head
        expected = 'https://store.example.test' + path
        assert head.find('link', rel='canonical')['href'] == expected
        assert head.find('meta', property='og:url')['content'] == expected
        assert head.find('meta', attrs={'name': 'description'})['content']
        assert head.find('meta', property='og:title')['content']
        assert 'callbacksecret' not in str(head) and 'untrusted.example.test' not in str(head)
        assert response.headers['Cache-Control'] == 'no-store'
        assert head.find('meta', attrs={'name': 'csrf-token'}) is not None
        assert not document(response).find_all('script', type='application/ld+json')


def test_missing_base_omits_absolute_metadata_without_guessing_host(app, client, seo_catalog):
    app.config['PUBLIC_BASE_URL'] = None
    response = client.get('/contact')
    head = document(response).head
    assert response.status_code == 200
    assert head.find('link', rel='canonical') is None
    assert head.find('meta', property='og:url') is None
    assert head.find('meta', property='og:title') is None
    assert head.find('meta', attrs={'name': 'description'}) is not None


def test_product_id_canonical_and_safe_factual_jsonld(client, seo_catalog):
    product, _, product_read, variants_read, _ = seo_catalog
    response = client.get('/product/007?callbacksecret=private&search=secret')
    assert response.status_code == 200
    soup = document(response)
    head = soup.head
    assert head.find('link', rel='canonical')['href'] == 'https://store.example.test/product/7'
    assert head.find('meta', property='og:title')['content'] == product.ProductName + ' - Fashion Store'
    assert head.find('meta', property='og:description')['content'] == product.Description
    scripts = head.find_all('script', type='application/ld+json')
    assert len(scripts) == 1
    assert '</script>' not in scripts[0].get_text()
    data = json.loads(scripts[0].get_text())
    details, breadcrumbs = data
    assert details['name'] == product.ProductName
    assert details['offers']['price'] == '1234567890123456.78'
    assert details['offers']['priceCurrency'] == 'VND'
    assert details['offers']['availability'] == 'https://schema.org/InStock'
    assert details['image'] == 'https://store.example.test/static/images/7.jpg'
    assert {'aggregateRating', 'brand', 'sku', 'lastmod'}.isdisjoint(details)
    assert breadcrumbs['@type'] == 'BreadcrumbList'
    assert 'callbacksecret' not in str(head)
    assert soup.select_one('#product-description').get_text() == product.Description
    assert soup.select_one('#mainImage') is not None
    assert response.headers['Cache-Control'] == 'no-store'
    product_read.assert_called_once_with(7)
    variants_read.assert_called_once_with(7)


def test_catalog_canonical_uses_actual_normalized_page_and_safe_query_only(client, seo_catalog):
    response = client.get('/products?category=003&page=999&per_page=24&foo=secret&callbacksecret=private')
    assert response.status_code == 200
    head = document(response).head
    expected = 'https://store.example.test/products?category=3&per_page=24&page=2'
    assert head.find('link', rel='canonical')['href'] == expected
    assert head.find('meta', property='og:url')['content'] == expected
    assert head.find('meta', attrs={'name': 'robots'})['content'] == 'index, follow'
    assert 'callbacksecret' not in str(head) and 'secret' not in str(head)
    assert 'Trang 2' in head.title.get_text()
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('query', ['search=callbacksecret', 'color=1', 'in_stock=1', 'sort=price_asc', 'min_price=0'])
def test_filtered_catalog_is_noindex_without_query_leakage(client, seo_catalog, query):
    response = client.get('/products?' + query)
    head = document(response).head
    assert response.status_code == 200
    assert head.find('meta', attrs={'name': 'robots'})['content'] == 'noindex, nofollow'
    assert 'callbacksecret' not in str(head)
    assert query not in head.find('link', rel='canonical')['href']


def test_404_has_no_canonical_or_structured_data_and_cannot_leak_secret_path(client, seo_catalog):
    response = client.get('/not-found/callbacksecret?token=private')
    head = document(response).head
    assert response.status_code == 404
    assert head.find('meta', attrs={'name': 'robots'})['content'] == 'noindex, nofollow'
    assert head.find('link', rel='canonical') is None
    assert head.find('meta', property='og:url') is None
    assert head.find('script', type='application/ld+json') is None
    assert 'callbacksecret' not in str(head) and 'token=private' not in str(head)
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('path', ['/login', '/register', '/forgot_password', '/reset_password/callbacksecret', '/cart'])
def test_private_pages_never_promote_auth_callback_urls(client, seo_catalog, monkeypatch, path):
    monkeypatch.setattr(AuthService, 'validate_reset_token', Mock(return_value=False), raising=False)
    response = client.get(path + '?next=/callbacksecret&token=private')
    assert response.status_code in {200, 302, 400}
    head = document(response).head
    if head and head.find('meta', attrs={'name': 'robots'}):
        assert head.find('meta', attrs={'name': 'robots'})['content'] == 'noindex, nofollow'
        assert head.find('link', rel='canonical') is None
        assert head.find('meta', property='og:url') is None
        assert 'callbacksecret' not in str(head)
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('path', ['/my_account', '/wishlist', '/checkout', '/order/1', '/admin'])
def test_seo_does_not_weaken_guest_route_guards(client, seo_catalog, path):
    response = client.get(path, headers={'Accept': 'application/json'})
    assert response.status_code == 401
    assert response.is_json and response.json['success'] is False
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'


def test_messages_html_is_noindex_without_changing_guest_access(client, seo_catalog):
    response = client.get('/messages?callbacksecret=private')
    assert response.status_code == 200
    head = document(response).head
    assert head.find('meta', attrs={'name': 'robots'})['content'] == 'noindex, nofollow'
    assert head.find('link', rel='canonical') is None
    assert head.find('meta', property='og:url') is None
    assert response.headers['Cache-Control'] == 'no-store'


def test_api_response_keeps_contract_and_adds_noindex(client, seo_catalog):
    response = client.get('/api/search_autocomplete?q=')
    assert response.status_code == 200
    assert response.json == {'success': True, 'products': []}
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert response.headers['Cache-Control'] == 'no-store'


def test_robots_is_database_free_even_with_authenticated_session(app, client, monkeypatch):
    app.config.update(PUBLIC_BASE_URL='https://store.example.test', SESSION_REVALIDATION_ENABLED=True)
    identity_read = Mock(side_effect=AssertionError('robots must not revalidate through the DB'))
    monkeypatch.setattr(AuthService, 'get_identity_state', identity_read)
    with client.session_transaction() as state:
        state.update(user_id=1, auth_version=1)
    response = client.get('/robots.txt?callbacksecret=private')
    assert response.status_code == 200
    assert response.content_type == 'text/plain; charset=utf-8'
    body = response.get_data(as_text=True)
    assert 'User-agent: *' in body and 'Allow: /' in body
    assert 'Disallow: /admin' in body and 'Disallow: /api/' in body and 'Disallow: /reset_password/' in body
    assert 'Sitemap: https://store.example.test/sitemap.xml' in body
    assert 'callbacksecret' not in body
    identity_read.assert_not_called()
    assert 'Set-Cookie' not in response.headers


def test_sitemap_is_bounded_public_xml_and_uses_only_one_inventory_call(app, client, monkeypatch):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test/shop&more'
    inventory = Mock(return_value=(('category', 3), ('product', 7)))
    monkeypatch.setattr(ProductService, 'get_sitemap_entries', inventory)
    response = client.get('/sitemap.xml')
    assert response.status_code == 200
    assert response.content_type == 'application/xml; charset=utf-8'
    root = ElementTree.fromstring(response.data)
    assert root.tag == '{http://www.sitemaps.org/schemas/sitemap/0.9}urlset'
    urls = [entry.text for entry in root.findall('{*}url/{*}loc')]
    assert urls == [
        'https://store.example.test/shop&more/',
        'https://store.example.test/shop&more/contact',
        'https://store.example.test/shop&more/products',
        'https://store.example.test/shop&more/products?category=3',
        'https://store.example.test/shop&more/product/7',
    ]
    assert b'&amp;more' in response.data
    assert b'lastmod' not in response.data and b'priority' not in response.data
    inventory.assert_called_once_with()
    assert 'Set-Cookie' not in response.headers


@pytest.mark.parametrize('failure', [psycopg2.OperationalError('private DSN'), ValueError('over limit')])
def test_sitemap_failure_is_503_not_false_empty_success(app, client, monkeypatch, failure):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test'
    monkeypatch.setattr(ProductService, 'get_sitemap_entries', Mock(side_effect=failure))
    response = client.get('/sitemap.xml')
    assert response.status_code == 503
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Retry-After'] == '300'
    assert b'<urlset' not in response.data and str(failure).encode() not in response.data


def test_sitemap_missing_configuration_is_503_without_db(app, client, monkeypatch):
    inventory = Mock(side_effect=AssertionError('missing base should not query'))
    monkeypatch.setattr(ProductService, 'get_sitemap_entries', inventory)
    response = client.get('/sitemap.xml')
    assert response.status_code == 503
    inventory.assert_not_called()


@pytest.mark.parametrize('query', [{'page': '1'}, {'callbacksecret': 'private'}, {'empty': ''}])
def test_sitemap_query_is_rejected_before_inventory(app, client, monkeypatch, query):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test'
    inventory = Mock(side_effect=AssertionError('unsupported sitemap query must not read inventory'))
    monkeypatch.setattr(ProductService, 'get_sitemap_entries', inventory)
    response = client.get('/sitemap.xml', query_string=query)
    assert response.status_code == 400
    assert response.content_type == 'text/plain; charset=utf-8'
    assert b'<urlset' not in response.data and b'callbacksecret' not in response.data
    assert 'Set-Cookie' not in response.headers
    inventory.assert_not_called()


def test_robots_missing_base_cannot_guess_request_host(app, client, monkeypatch):
    app.config.update(PUBLIC_BASE_URL=None, TRUSTED_HOSTS=['localhost', 'untrusted.example.test'])
    inventory = Mock(side_effect=AssertionError('robots must not read inventory'))
    monkeypatch.setattr(ProductService, 'get_sitemap_entries', inventory)
    response = client.get('/robots.txt', base_url='https://untrusted.example.test')
    assert response.status_code == 200
    assert response.content_type == 'text/plain; charset=utf-8'
    body = response.get_data(as_text=True)
    assert 'User-agent: *' in body and 'Disallow: /api/' in body
    assert 'Sitemap:' not in body and 'untrusted.example.test' not in body
    assert 'Set-Cookie' not in response.headers
    inventory.assert_not_called()


@pytest.mark.parametrize(
    'entry',
    [('private-kind', 7), ('product', True), ('category', '3'), ('product', 0), ('category', 2_147_483_648)],
    ids=['unknown-kind', 'boolean-id', 'string-id', 'zero-id', 'overflow-id'],
)
def test_sitemap_malformed_inventory_fails_closed_without_partial_xml(app, client, monkeypatch, entry):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test'
    inventory = Mock(return_value=(('product', 7), entry))
    monkeypatch.setattr(ProductService, 'get_sitemap_entries', inventory)
    response = client.get('/sitemap.xml')
    assert response.status_code == 503
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Retry-After'] == '300'
    assert response.content_type == 'text/plain; charset=utf-8'
    assert b'<urlset' not in response.data and b'private-kind' not in response.data
    assert 'Set-Cookie' not in response.headers
    inventory.assert_called_once_with()


def test_health_endpoints_preserve_existing_readiness_semantics(client, monkeypatch):
    health = Mock(return_value=False)
    monkeypatch.setattr(MainService, 'check_health', health)
    response = client.get('/health/live')
    assert response.status_code == 200 and response.json == {'status': 'live'}
    health.assert_not_called()
    response = client.get('/health/ready')
    assert response.status_code == 503
    assert response.json['status'] == 'unhealthy' and response.json['database'] == 'error'
    health.assert_called_once_with()
