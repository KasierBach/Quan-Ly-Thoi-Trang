from decimal import Decimal
from types import SimpleNamespace
from xml.etree import ElementTree

import psycopg2
import pytest

from app.database import CaseInsensitiveRecord
import app.seo as seo
from app.services.product_service import ProductService


@pytest.fixture(autouse=True)
def no_live_database(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('SEO unit tests must not connect to a database')

    monkeypatch.setattr(psycopg2, 'connect', forbidden)


@pytest.mark.parametrize(
    'base',
    [
        None,
        '',
        'https://',
        'https://user:secret@store.example.test',
        'https://store.example.test/?callbacksecret=secret',
        'https://store.example.test/#secret',
        'https://store.example.test:bad',
        'https://store.example.test:0',
        'https://store.example.test/../private',
        'https://store.example.test/%2e%2e',
        'https://store.example.test\\private',
        'https://store.example.test/\nsecret',
        'http://store.example.test',
        '//store.example.test',
    ],
)
def test_invalid_or_missing_base_never_falls_back_to_host(app, base):
    app.config['PUBLIC_BASE_URL'] = base
    with app.test_request_context('/', base_url='https://untrusted.example.test'):
        assert seo.public_base_url() is None
        assert seo.public_url('main.home') is None


@pytest.mark.parametrize(
    'base,expected',
    [
        ('https://store.example.test/', 'https://store.example.test'),
        ('https://store.example.test/shop/', 'https://store.example.test/shop'),
        ('http://localhost:5000/', 'http://localhost:5000'),
        ('http://127.0.0.1:5000', 'http://127.0.0.1:5000'),
        ('http://[::1]:5000', 'http://[::1]:5000'),
    ],
)
def test_trusted_base_supports_https_and_development_loopback(app, base, expected):
    app.config['PUBLIC_BASE_URL'] = base
    with app.test_request_context('/'):
        assert seo.public_base_url() == expected
        assert seo.public_url('main.contact') == expected + '/contact'
    app.config['APP_ENV'] = 'production'
    if base.startswith('http:'):
        with app.app_context():
            assert seo.public_base_url() is None


def product(**overrides):
    values = dict(
        ProductID=7,
        ProductName='Áo "đẹp" </script>',
        Description='Mô tả thật & <b>vải</b>\n dòng hai',
        CategoryID=3,
        CategoryName='Áo & quần',
        Price=Decimal('1234567890123456.78'),
        ImageURL='images/7.jpg',
        AvailableStock=999,
        AverageRating=5,
        ReviewCount=100,
        Brand='Unverified',
        SKU='Unverified',
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_product_jsonld_uses_decimal_and_real_variant_stock_only(app):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test'
    with app.test_request_context('/product/7?callbacksecret=secret'):
        metadata, data = seo.product_metadata(product(), [SimpleNamespace(Quantity=0), SimpleNamespace(Quantity=2)])
    assert metadata['canonical'] == 'https://store.example.test/product/7'
    assert metadata['image'] == 'https://store.example.test/static/images/7.jpg'
    details, breadcrumb = data
    assert details['offers'] == {
        '@type': 'Offer',
        'url': 'https://store.example.test/product/7',
        'price': '1234567890123456.78',
        'priceCurrency': 'VND',
        'availability': 'https://schema.org/InStock',
    }
    assert {'aggregateRating', 'brand', 'sku', 'lastmod', 'sales'}.isdisjoint(details)
    assert [entry['position'] for entry in breadcrumb['itemListElement']] == [1, 2, 3]
    assert breadcrumb['itemListElement'][1]['item'] == 'https://store.example.test/products?category=3'
    assert 'callbacksecret' not in str(data)


def test_zero_variants_stock_is_out_of_stock_not_product_aggregate(app):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test'
    with app.test_request_context('/'):
        _, data = seo.product_metadata(product(), [SimpleNamespace(Quantity=0)])
    assert data[0]['offers']['availability'] == 'https://schema.org/OutOfStock'


@pytest.mark.parametrize('quantities', [[], [None], [-1], [True], ['2'], [0, None]])
def test_unproven_variant_stock_omits_offer(app, quantities):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test'
    with app.test_request_context('/'):
        _, data = seo.product_metadata(product(), [SimpleNamespace(Quantity=qty) for qty in quantities])
    assert 'offers' not in data[0]


@pytest.mark.parametrize('price', [None, 0.1, True, 'NaN', 'Infinity', '-1', 'not-money'])
def test_invalid_or_imprecise_price_omits_offer(app, price):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test'
    with app.test_request_context('/'):
        _, data = seo.product_metadata(product(Price=price), [SimpleNamespace(Quantity=2)])
    assert 'offers' not in data[0]


@pytest.mark.parametrize(
    'image',
    [
        None,
        '//evil.test/image.jpg',
        'javascript:alert(1)',
        '../image.jpg',
        'uploads/chat/private.jpg',
        'https://images.example.test/image.jpg?callbacksecret=secret',
        'http://images.example.test/image.jpg',
    ],
)
def test_unproven_or_private_images_are_not_promoted_to_metadata(app, image):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test'
    with app.test_request_context('/'):
        metadata, data = seo.product_metadata(product(ImageURL=image), [SimpleNamespace(Quantity=2)])
    assert metadata['image'] is None
    assert 'image' not in data[0]


@pytest.mark.parametrize(
    'image',
    [
        pytest.param('https://images.example.test/\nimage.jpg', id='newline-control'),
        pytest.param('images/\t7.jpg', id='tab-control'),
        pytest.param('https://images.example.test/\x00image.jpg', id='null-control'),
        pytest.param('https://images.example.test/\x7fimage.jpg', id='del-control'),
        pytest.param('https://images.example.test:bad/image.jpg', id='nonnumeric-port'),
        pytest.param('https://images.example.test:0/image.jpg', id='zero-port'),
        pytest.param('https://images.example.test:65536/image.jpg', id='out-of-range-port'),
    ],
)
def test_image_urls_with_controls_or_invalid_ports_are_omitted(app, image):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test'
    with app.test_request_context('/product/7'):
        metadata, data = seo.product_metadata(product(ImageURL=image), [SimpleNamespace(Quantity=2)])
    assert metadata['canonical'] == 'https://store.example.test/product/7'
    assert metadata['image'] is None
    assert 'image' not in data[0]
    assert data[0]['offers']['availability'] == 'https://schema.org/InStock'


def test_missing_base_omits_product_and_breadcrumb_structured_data(app):
    with app.test_request_context('/', base_url='https://untrusted.example.test'):
        metadata, data = seo.product_metadata(product(), [SimpleNamespace(Quantity=2)])
    assert metadata['canonical'] is None
    assert data == []


def test_catalog_metadata_uses_normalized_paging_and_only_selected_public_keys(app):
    app.config['PUBLIC_BASE_URL'] = 'https://store.example.test'
    with app.test_request_context('/products?search=callbacksecret&foo=secret&page=999'):
        metadata = seo.catalog_metadata(3, 2, 24, filtered=True)
    assert metadata['canonical'] == 'https://store.example.test/products?category=3&per_page=24&page=2'
    assert metadata['robots'] == seo.NOINDEX
    assert 'callbacksecret' not in str(metadata)


def test_sitemap_escapes_xml_and_enforces_url_and_byte_caps(app, monkeypatch):
    with app.test_request_context('/'):
        body = seo.sitemap_document('https://store.example.test/shop&more', [('category', 3), ('product', 7)])
        root = ElementTree.fromstring(body)
        urls = [entry.text for entry in root.findall('{*}url/{*}loc')]
        assert urls == [
            'https://store.example.test/shop&more/',
            'https://store.example.test/shop&more/contact',
            'https://store.example.test/shop&more/products',
            'https://store.example.test/shop&more/products?category=3',
            'https://store.example.test/shop&more/product/7',
        ]
        assert b'&amp;more' in body
        assert b'lastmod' not in body
        monkeypatch.setattr(seo, 'MAX_SITEMAP_URLS', 4)
        with pytest.raises(ValueError, match='URL limit'):
            seo.sitemap_document('https://store.example.test', [('product', 7), ('product', 8)])
        monkeypatch.setattr(seo, 'MAX_SITEMAP_BYTES', 100)
        with pytest.raises(ValueError, match='byte limit'):
            seo.sitemap_document('https://store.example.test', [])


def test_sitemap_inventory_one_bounded_id_query_cached_and_invalidated(app, fake_db):
    fake_db.cursor.fetchall.return_value = [
        CaseInsensitiveRecord(Kind='category', EntityID=3),
        CaseInsensitiveRecord(Kind='product', EntityID=7),
    ]
    with app.app_context():
        assert ProductService.get_sitemap_entries() == (('category', 3), ('product', 7))
        assert ProductService.get_sitemap_entries() == (('category', 3), ('product', 7))
        fake_db.cursor.execute.assert_called_once()
        query, args = fake_db.cursor.execute.call_args.args
        assert args == (49_998,)
        assert 'UNION ALL' in query and 'JOIN Categories' in query and 'LIMIT %s' in query
        assert not any(field in query for field in ['Description', 'ImageURL', 'Price', 'Rating'])
        ProductService.invalidate_catalog()
        ProductService.get_sitemap_entries()
        assert fake_db.cursor.execute.call_count == 2
    assert fake_db.connection.close.call_count == 2


def test_sitemap_inventory_db_failures_are_not_cached(app, fake_db):
    fake_db.cursor.execute.side_effect = [psycopg2.OperationalError('private dsn'), None]
    fake_db.cursor.fetchall.return_value = []
    with app.app_context():
        with pytest.raises(psycopg2.OperationalError):
            ProductService.get_sitemap_entries()
        assert ProductService.get_sitemap_entries() == ()
    assert fake_db.cursor.execute.call_count == 2
    assert fake_db.connection.close.call_count == 2


def test_sitemap_inventory_overflow_is_not_a_partial_success(app, fake_db):
    fake_db.cursor.fetchall.return_value = [CaseInsensitiveRecord(Kind='product', EntityID=1)] * 49_998
    with app.app_context(), pytest.raises(ValueError, match='URL limit'):
        ProductService.get_sitemap_entries()
    fake_db.connection.close.assert_called_once()
