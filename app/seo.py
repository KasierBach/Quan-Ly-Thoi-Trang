"""Small, factual metadata helpers; public URLs never come from the request Host."""

from decimal import Decimal, InvalidOperation
from itertools import chain
from pathlib import PurePosixPath
from urllib.parse import urlsplit
from xml.etree import ElementTree

from flask import current_app, request, url_for


STORE_NAME = 'Fashion Store'
PUBLIC_ENDPOINTS = {'main.home', 'main.contact', 'product.products', 'product.product_detail'}
CRAWLER_ENDPOINTS = {'main.robots_txt', 'main.sitemap_xml'}
PRIVATE_PATHS = (
    '/admin',
    '/api/',
    '/login',
    '/register',
    '/logout',
    '/my_account',
    '/forgot_password',
    '/reset_password/',
    '/cart',
    '/checkout',
    '/wishlist',
    '/order/',
    '/order_confirmation/',
    '/messages',
    '/chat',
    '/socket.io/',
    '/uploads/',
)
NOINDEX = 'noindex, nofollow'
MAX_SITEMAP_URLS = 50_000
MAX_SITEMAP_BYTES = 10 * 1024 * 1024


def public_base_url():
    value = current_app.config.get('PUBLIC_BASE_URL')
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    if any(ord(char) < 33 for char in value) or '\\' in value:
        return None
    try:
        parsed = urlsplit(value)
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
            or any(part in {'.', '..'} for part in parsed.path.split('/'))
            or '%' in parsed.path
        ):
            return None
        if parsed.scheme != 'https' and not (
            parsed.scheme == 'http'
            and parsed.hostname in {'localhost', '127.0.0.1', '::1'}
            and current_app.config.get('APP_ENV') != 'production'
        ):
            return None
    except ValueError:
        return None
    return value.rstrip('/')


def public_url(endpoint, **values):
    base = public_base_url()
    return base + url_for(endpoint, _external=False, **values) if base else None


def plain_text(value, limit=160):
    if not isinstance(value, str):
        return ''
    text = ' '.join(value.replace('\x00', '').split())
    return text[:limit].rstrip()


def page_metadata(title, description, canonical=None, *, noindex=False, og_type='website', image=None):
    return {
        'title': title,
        'description': plain_text(description),
        'canonical': canonical,
        'robots': NOINDEX if noindex else 'index, follow',
        'og_type': og_type,
        'image': image,
    }


def default_metadata():
    if request.method in {'GET', 'HEAD'} and request.endpoint == 'main.home':
        seo = page_metadata(
            'Fashion Store - Trang chủ',
            'Xem danh mục và thông tin sản phẩm thời trang tại Fashion Store.',
            public_url('main.home'),
        )
    elif request.method in {'GET', 'HEAD'} and request.endpoint == 'main.contact':
        seo = page_metadata(
            'Liên hệ - Fashion Store',
            'Xem thông tin liên hệ và gửi tin nhắn cho Fashion Store.',
            public_url('main.contact'),
        )
    else:
        seo = page_metadata(STORE_NAME, 'Trang thông tin của Fashion Store.', noindex=True)
    return {'seo': seo}


def metadata_response_headers(response):
    if request.endpoint == 'static':
        return response
    if response.mimetype == 'text/html':
        # Even guest HTML contains a per-session CSRF token and chat identity.
        response.headers['Cache-Control'] = 'no-store'
    if (
        response.status_code >= 400
        or request.path.startswith('/api/')
        or (request.endpoint not in PUBLIC_ENDPOINTS | CRAWLER_ENDPOINTS | {'main.health_live', 'main.health_check'})
        or request.method not in {'GET', 'HEAD'}
    ):
        response.headers['X-Robots-Tag'] = NOINDEX
    return response


def catalog_metadata(category_id, page, per_page, *, filtered=False, empty=False):
    values = {}
    if category_id is not None:
        values['category'] = category_id
    if per_page != 12:
        values['per_page'] = per_page
    if page > 1:
        values['page'] = page
    title = 'Fashion Store - Sản phẩm' + (f' - Trang {page}' if page > 1 else '')
    return page_metadata(
        title,
        'Xem danh mục, giá và thông tin sản phẩm thời trang tại Fashion Store.',
        public_url('product.products', **values),
        noindex=filtered or empty,
    )


def _stored_image_url(product):
    image = getattr(product, 'ImageURL', None)
    if not isinstance(image, str) or not image or len(image) > 2048:
        return None
    if '\\' in image or any(ord(char) < 33 or ord(char) == 127 for char in image):
        return None
    try:
        parsed = urlsplit(image)
        if parsed.query or parsed.fragment or parsed.username is not None or parsed.password is not None:
            return None
        if parsed.scheme:
            return image if parsed.scheme == 'https' and parsed.hostname and parsed.port != 0 else None
        if parsed.netloc or image.startswith('/') or any(part in {'.', '..'} for part in image.split('/')):
            return None
    except ValueError:
        return None
    if '%' in image or PurePosixPath(image).parts[:2] == ('uploads', 'chat'):
        return None
    return public_url('static', filename=image)


def _exact_price(value):
    # Do not turn an imprecise float into an apparently exact database price.
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        return None
    try:
        price = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not price.is_finite() or price < 0 or price > Decimal('9999999999999999.99'):
        return None
    return format(price, 'f')


def product_metadata(product, variants):
    product_id = getattr(product, 'ProductID', None)
    name = plain_text(getattr(product, 'ProductName', None), 255)
    canonical = (
        public_url('product.product_detail', product_id=product_id)
        if type(product_id) is int and 0 < product_id <= 2_147_483_647 and name
        else None
    )
    description = plain_text(getattr(product, 'Description', None))
    seo = page_metadata(
        f'{name} - {STORE_NAME}' if name else STORE_NAME,
        description or f'Xem thông tin sản phẩm {name} tại Fashion Store.',
        canonical,
        og_type='product',
        image=_stored_image_url(product) if canonical else None,
        noindex=canonical is None,
    )
    if not canonical:
        return seo, []
    data: dict[str, object] = {'@context': 'https://schema.org', '@type': 'Product', 'name': name, 'url': canonical}
    if description:
        data['description'] = description
    if seo['image']:
        data['image'] = seo['image']
    quantities = [getattr(variant, 'Quantity', None) for variant in variants]
    price = _exact_price(getattr(product, 'Price', None))
    if price is not None and quantities and all(type(qty) is int and qty >= 0 for qty in quantities):
        data['offers'] = {
            '@type': 'Offer',
            'url': canonical,
            'price': price,
            'priceCurrency': 'VND',
            'availability': 'https://schema.org/'
            + ('InStock' if any(type(qty) is int and qty > 0 for qty in quantities) else 'OutOfStock'),
        }
    breadcrumbs = [{'@type': 'ListItem', 'position': 1, 'name': 'Trang chủ', 'item': public_url('main.home')}]
    category_id = getattr(product, 'CategoryID', None)
    category_name = plain_text(getattr(product, 'CategoryName', None), 100)
    if type(category_id) is int and 0 < category_id <= 2_147_483_647 and category_name:
        breadcrumbs.append(
            {
                '@type': 'ListItem',
                'position': 2,
                'name': category_name,
                'item': public_url('product.products', category=category_id),
            }
        )
    breadcrumbs.append({'@type': 'ListItem', 'position': len(breadcrumbs) + 1, 'name': name, 'item': canonical})
    return seo, [data, {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': breadcrumbs}]


def sitemap_document(base, entries):
    """Bound URL count and serialized bytes; do not silently truncate the catalog."""
    parts = [b'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    size = len(parts[0]) + len(b'</urlset>')
    paths = [url_for('main.home'), url_for('main.contact')]

    def inventory_paths():
        for index, (kind, entity_id) in enumerate(entries):
            if index == 0:
                yield url_for('product.products')
            if type(entity_id) is not int or not 0 < entity_id <= 2_147_483_647:
                raise ValueError('Invalid public sitemap ID')
            if kind == 'product':
                yield url_for('product.product_detail', product_id=entity_id)
            elif kind == 'category':
                yield url_for('product.products', category=entity_id)
            else:
                raise ValueError('Invalid public sitemap entry')

    for count, path in enumerate(chain(paths, inventory_paths()), start=1):
        if count > MAX_SITEMAP_URLS:
            raise ValueError('Public sitemap exceeds its URL limit')
        element = ElementTree.Element('url')
        ElementTree.SubElement(element, 'loc').text = base + path
        chunk = ElementTree.tostring(element, encoding='utf-8')
        size += len(chunk)
        if size > MAX_SITEMAP_BYTES:
            raise ValueError('Public sitemap exceeds its byte limit')
        parts.append(chunk)
    parts.append(b'</urlset>')
    return b''.join(parts)
