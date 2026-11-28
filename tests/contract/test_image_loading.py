"""Offline contracts for storefront image scheduling and existing crop reservations."""

from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

from bs4 import BeautifulSoup
from PIL import Image
import pytest
from requests.sessions import Session

from app.services.base_service import BaseService
from app.services.product_service import ProductService


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / 'app' / 'static'
JSON_TYPES = {'application/json', 'application/ld+json'}


def declarations(style):
    return {
        key.strip(): value.strip() for key, value in (part.split(':', 1) for part in style.split(';') if ':' in part)
    }


def render(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def run_node(source, *, syntax_only=False):
    command = ['node', '--check', '-'] if syntax_only else ['node', '--input-type=module', '-']
    result = subprocess.run(
        command, input=source, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=15, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def storefront(app, monkeypatch):
    assert app.config['DB_CONNECT_ENABLED'] is False
    assert app.config['DB_POOL_ENABLED'] is False
    assert app.config['SESSION_REVALIDATION_ENABLED'] is False
    database = Mock(side_effect=AssertionError('Image contracts must not connect to a database'))
    network = Mock(side_effect=AssertionError('Image contracts must not fetch HTTP media'))
    monkeypatch.setattr(BaseService, 'get_connection', staticmethod(database))
    monkeypatch.setattr('psycopg2.connect', database)
    monkeypatch.setattr(Session, 'request', network)

    sources = [(1, '1.jpg'), (2, '2.jpg'), (4, '4.jpg'), (9, '9.jpg'), (20, '20.jpg'), (999999, None)]
    products = [
        SimpleNamespace(
            ProductID=product_id,
            ProductName='Áo dài "Đỏ" <img src=x onerror=alert(1)> & Việt'
            if filename is None
            else f'Áo Việt {product_id}',
            Description='Mô tả sản phẩm thật, giữ nguyên dấu tiếng Việt.',
            CategoryID=101,
            CategoryName='Áo nam',
            Price=Decimal('100000.10'),
            OriginalPrice=Decimal('120000.20'),
            ImageURL=f'images/{filename}' if filename else None,
            TotalSold=5,
            AverageRating=4.5,
            ReviewCount=2,
        )
        for product_id, filename in sources
    ]
    categories = [
        SimpleNamespace(CategoryID=101 + index, CategoryName=name, Description='', ImageURL=f'images/{filename}')
        for index, (name, filename) in enumerate(
            [('Áo nam', 'ao-nam.jpg'), ('Quần nữ', 'quan-nu.jpg'), ('Phụ kiện', 'phu-kien.jpg')]
        )
    ]
    # The normal context processor deliberately returns [] when DB access is disabled.
    app.context_processor(lambda: {'categories': categories})
    monkeypatch.setattr(ProductService, 'get_featured_products', Mock(side_effect=lambda limit: products[:limit]))
    monkeypatch.setattr(ProductService, 'get_best_selling_products', Mock(side_effect=lambda limit: products[:limit]))
    search = Mock(
        return_value={
            'products': products,
            'total_records': len(products),
            'total_pages': 1,
            'current_page': 1,
            'offset': 0,
        }
    )
    monkeypatch.setattr(ProductService, 'search_products', search)
    monkeypatch.setattr(ProductService, 'get_all_colors', Mock(return_value=[]))
    monkeypatch.setattr(ProductService, 'get_all_sizes', Mock(return_value=[]))
    by_id = {product.ProductID: product for product in products}
    monkeypatch.setattr(ProductService, 'get_product_by_id', Mock(side_effect=by_id.get))
    monkeypatch.setattr(
        ProductService,
        'get_product_variants',
        Mock(
            side_effect=lambda product_id: [
                SimpleNamespace(
                    VariantID=product_id * 10 + 1, ColorID=1, ColorName='Đen', SizeID=1, SizeName='M', Quantity=3
                )
            ]
        ),
    )
    yield SimpleNamespace(products=products, categories=categories, search=search)
    database.assert_not_called()
    network.assert_not_called()


def test_home_hero_has_one_local_image_and_an_actual_catalog_link(client, storefront):
    page = render(client, '/')
    hero = page.select_one('.storefront-hero')
    assert len(hero.select('img')) == 1
    assert hero.select_one('a.btn')['href'] == '/products'
    assert page.select_one('[data-bs-ride=carousel]') is None

    image = hero.select_one('img')
    filename = 'ao-so-mi-nu-trang.jpg'
    assert image['src'] == f'/static/images/{filename}'
    with Image.open(STATIC / 'images' / filename) as asset:
        assert asset.getexif().get(274, 1) == 1
        assert (int(image['width']), int(image['height'])) == asset.size
    assert image['loading'] == 'eager'
    assert image['decoding'] == 'async'
    assert image['fetchpriority'] == 'high'
    assert len(page.select('img[fetchpriority="high"]')) == 1


def test_home_below_fold_cards_are_lazy_without_changing_crops(client, storefront):
    page = render(client, '/')
    categories = page.select('.category-card img')
    products = page.select('.product-card img')
    assert len(categories) == 3
    assert len(products) == 12
    for image in categories + products:
        assert image['loading'] == 'lazy'
        assert image['decoding'] == 'async'
        assert image.get('fetchpriority') != 'high'
        assert not image.has_attr('width') and not image.has_attr('height')
    for image in categories:
        assert declarations(image['style'])['height'].strip() == '280px'
        assert declarations(image['style'])['object-fit'].strip() == 'cover'
    assert all('product-img' in image['class'] and 'card-img-top' in image['class'] for image in products)


def test_catalog_keeps_first_visible_row_eager_and_defers_remaining_cards(client, storefront):
    page = render(client, '/products')
    images = page.select('#products-grid .product-card img')
    assert len(images) == 6
    assert [image['loading'] for image in images] == ['eager'] * 3 + ['lazy'] * 3
    assert [image.get('fetchpriority') for image in images] == ['high', None, None, None, None, None]
    assert [image['alt'] for image in images] == [product.ProductName for product in storefront.products]
    assert [image['src'] for image in images] == [
        '/static/images/1.jpg',
        '/static/images/2.jpg',
        '/static/images/4.jpg',
        '/static/images/9.jpg',
        '/static/images/20.jpg',
        '/static/images/default.jpg',
    ]
    assert all(image['decoding'] == 'async' and 'product-img' in image['class'] for image in images)
    assert all(not image.has_attr('width') and not image.has_attr('height') for image in images)
    storefront.search.assert_called_once()


def test_empty_catalog_does_not_invent_image_placeholders(client, storefront):
    storefront.search.return_value.update(products=[], total_records=0, total_pages=0)
    page = render(client, '/products?search=khong-co')
    assert not page.select('#products-grid img')
    assert not page.select('img[fetchpriority="high"]')
    assert 'Không tìm thấy sản phẩm' in page.get_text()


@pytest.mark.parametrize('product_id', [1, 2, 4, 9, 20, 999999])
def test_main_product_reserves_contain_box_for_mixed_local_shapes(client, storefront, product_id):
    page = render(client, f'/product/{product_id}')
    image = page.select_one('#mainImage')
    product = next(product for product in storefront.products if product.ProductID == product_id)
    assert image['alt'] == product.ProductName
    assert image['src'] == '/static/' + (product.ImageURL or 'images/default.jpg')
    with Image.open(STATIC / image['src'].removeprefix('/static/')) as asset:
        assert asset.width > 0 and asset.height > 0
        assert asset.getexif().get(274, 1) == 1
    # This is a stable CSS display box, not a claim that every source asset is square.
    assert not image.has_attr('width') and not image.has_attr('height')
    style = declarations(image['style'])
    assert style['width'].strip() == '100%'
    assert style['aspect-ratio'].strip() == '1 / 1'
    assert style['object-fit'].strip() == 'contain'
    assert style['max-height'].strip() == '100%' and style['max-width'].strip() == '100%'
    assert image['loading'] == 'eager' and image['decoding'] == 'async' and image['fetchpriority'] == 'high'
    assert len(page.select('img[fetchpriority="high"]')) == 1
    assert {'img-fluid', 'rounded'}.issubset(image['class'])


def test_image_edits_preserve_csrf_session_and_vietnamese_text(client, storefront):
    with client.session_transaction() as state:
        state.update(
            user_id=201,
            role='customer',
            user_name='Nguyễn Việt',
            auth_version=1,
            dark_mode=True,
            recently_viewed=[2, 1, 4],
            cart=[{'variant_id': 1, 'quantity': 2}],
        )
    page = render(client, '/product/1')
    config = json.loads(page.select_one('#base-data').get_text())
    assert config['isLoggedIn'] is True
    assert config['searchUrl'] == '/api/search_autocomplete'
    token = page.select_one('meta[name="csrf-token"]')['content']
    assert token and page.select_one('#productPurchaseForm [name="csrf_token"]')['value'] == token
    assert page.html['data-bs-theme'] == 'dark'
    assert page.select_one('#mainImage')['alt'] == 'Áo Việt 1'
    with client.session_transaction() as state:
        assert state['user_id'] == 201 and state['user_name'] == 'Nguyễn Việt'
        assert state['cart'] == [{'variant_id': 1, 'quantity': 2}]
        assert state['recently_viewed'] == [1, 2, 4]


def test_recent_card_markup_is_lazy_and_existing_one_shot_fallback_remains(client, storefront):
    page = render(client, '/product/1')
    assert page.select_one('#recently-viewed-container').has_attr('hidden')
    scripts = '\n'.join(script.get_text() for script in page.find_all('script') if not script.get('src'))
    markup = re.search(r'column\.innerHTML = `([^`]+)`;', scripts)
    assert markup
    image = BeautifulSoup(markup.group(1), 'html.parser').select_one('img')
    assert image['loading'] == 'lazy' and image['decoding'] == 'async'
    assert image['class'] == ['card-img-top', 'product-img']
    assert not image.has_attr('width') and not image.has_attr('height')
    assert re.search(
        r"image\.addEventListener\('error', \(\) => \{ image\.src = [\"']/static/images/default\.jpg[\"']; "
        r'\}, \{ once: true \}\);',
        scripts,
    )


def test_existing_css_reserves_card_and_autocomplete_crop_boxes():
    css = (STATIC / 'css' / 'style.css').read_text(encoding='utf-8')
    bootstrap = (STATIC / 'vendor' / 'bootstrap' / 'bootstrap.min.css').read_text(encoding='utf-8')
    assert re.search(r'\.card-img-top\{width:100%\}', bootstrap)
    card = declarations(re.search(r'\.product-img\s*\{([^}]+)\}', css).group(1))
    assert card['height'].strip() == '200px' and card['object-fit'].strip() == 'cover'
    assert re.search(r'@media\s*\(max-width:\s*768px\)\s*\{\s*\.product-img\s*\{\s*height:\s*180px;', css)
    thumbnail = declarations(re.search(r'\.search-autocomplete-img\s*\{([^}]+)\}', css).group(1))
    assert thumbnail['width'].strip() == '45px' and thumbnail['height'].strip() == '45px'
    assert thumbnail['object-fit'].strip() == 'cover'


def test_autocomplete_creates_lazy_safe_dom_thumbnails_without_http(client, storefront, monkeypatch):
    name = 'Áo dài "Đỏ" <img src=x onerror=alert(1)> & Việt'
    products = [
        {'id': 2, 'name': name, 'image': '/static/images/2.jpg', 'price': '100000.10', 'category': 'Quần nữ'},
        {'id': 4, 'name': 'Áo cao cấp', 'image': 'https://media.example.test/4.jpg', 'price': 20, 'category': 'Áo'},
        {'id': 9, 'name': 'Ảnh dự phòng', 'image': 'javascript:alert(1)', 'price': 30, 'category': ''},
        {'id': 20, 'name': 'Không có ảnh', 'image': None, 'price': 40, 'category': ''},
    ]
    monkeypatch.setattr(ProductService, 'search_autocomplete', Mock(return_value=products))
    response = client.get('/api/search_autocomplete', query_string={'q': 'Áo'})
    assert response.status_code == 200
    config = json.loads(render(client, '/products').select_one('#base-data').get_text())
    payload = json.dumps({'config': config, 'data': response.get_json()}, ensure_ascii=True)
    source = json.dumps((STATIC / 'js' / 'site.js').read_text(encoding='utf-8'), ensure_ascii=True)
    run_node(
        'import assert from "node:assert/strict";\nimport vm from "node:vm";\n'
        f'const payload = {payload};\nconst source = {source};\n' + AUTOCOMPLETE_DOM_HARNESS
    )


AUTOCOMPLETE_DOM_HARNESS = r"""
class Element {
    constructor(tagName) {
        this.tagName = tagName;
        this.children = [];
        this.style = {};
        this.dataset = {};
        this.attributes = {};
        this.listeners = {};
        const classes = new Set();
        this.classList = { add: value => classes.add(value), remove: value => classes.delete(value), contains: value => classes.has(value) };
    }
    set innerHTML(_value) { throw new Error('Autocomplete must use DOM properties, not HTML interpolation'); }
    set src(value) {
        assert.equal(this.loading, 'lazy');
        assert.equal(this.decoding, 'async');
        assert.equal(this.style.aspectRatio, '1 / 1');
        this._src = value;
    }
    get src() { return this._src; }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener(type, callback, options) { this.listeners[type] = { callback, options }; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
}
const input = new Element('input');
input.value = 'Áo';
const results = new Element('div');
const elements = {
    'base-data': { textContent: JSON.stringify(payload.config) }, searchInput: input, searchAutocomplete: results,
    darkIcon: new Element('i'), lightIcon: new Element('i')
};
const document = {
    documentElement: new Element('html'),
    getElementById: id => elements[id] || null,
    querySelector: () => ({ content: 'offline-csrf-token' }),
    querySelectorAll: () => [],
    addEventListener: () => {},
    createElement: tag => new Element(tag)
};
let pending;
let calls = 0;
vm.runInNewContext(source, {
    document, URL, URLSearchParams, AbortController, Intl, location: { origin: 'http://localhost' },
    localStorage: { getItem: () => null }, clearTimeout: () => {},
    setTimeout: (callback, delay) => { if (delay === 250) pending = callback; return 1; },
    fetch: async (url, options) => {
        calls++;
        const request = new URL(url, 'http://localhost');
        assert.equal(request.pathname, payload.config.searchUrl);
        assert.equal(request.searchParams.get('q'), input.value);
        assert.equal(options.signal.aborted, false);
        return { ok: true, json: async () => payload.data };
    }
});
input.listeners.input.callback();
await pending();
assert.equal(calls, 1);
assert.equal(results.children.length, payload.data.products.length);
assert.equal(input.attributes['aria-expanded'], 'true');
assert.equal(results.classList.contains('show'), true);
const expected = ['http://localhost/static/images/2.jpg', 'https://media.example.test/4.jpg', '/static/images/default.jpg', 'http://localhost/static/images/default.jpg'];
results.children.forEach((link, index) => {
    const [image, info] = link.children;
    assert.equal(link.href, `/product/${payload.data.products[index].id}`);
    assert.equal(image.className, 'search-autocomplete-img');
    assert.equal(image.src, expected[index]);
    assert.equal(image.alt, payload.data.products[index].name);
    assert.equal(image.style.flexShrink, '0');
    assert.equal(info.children[0].textContent, image.alt);
    assert.equal(image.children.length, 0);
    assert.equal(image.listeners.error.options.once, true);
    image.listeners.error.callback();
    assert.equal(image.src, '/static/images/default.jpg');
});
"""


@pytest.mark.parametrize('path', ['/', '/products', '/product/1'])
def test_owned_rendered_scripts_stay_valid_and_json_is_not_executed(client, storefront, path):
    page = render(client, path)
    executable = []
    for script in page.find_all('script'):
        if script.get('src'):
            continue
        mime = script.get('type', '').split(';', 1)[0].strip().lower()
        if mime in JSON_TYPES:
            json.loads(script.get_text())
        elif mime in {'', 'text/javascript', 'application/javascript'}:
            executable.append(script.get_text())
    assert executable
    run_node('\n'.join(executable), syntax_only=True)
