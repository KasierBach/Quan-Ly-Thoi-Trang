import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.test_customer_admin import login


pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


def test_public_product_metadata_and_lazy_images(gui_page):
    page = gui_page
    page.goto('/product/1')
    expect(page.get_by_role('heading', name='Test Cotton Shirt', exact=True)).to_be_visible()
    expect(page.locator('meta[property="og:title"]')).to_have_attribute('content', re.compile('Test Cotton Shirt'))
    expect(page.locator('meta[property="og:description"]')).to_have_attribute('content', re.compile(r'\S'))
    expect(page.locator('link[rel="canonical"]')).to_have_attribute('href', re.compile(r'^https?://[^/]+/product/1$'))
    data = json.loads(page.locator('script[type="application/ld+json"]').inner_text())
    entries = data if isinstance(data, list) else [data]
    product = next(entry for entry in entries if entry.get('@type') == 'Product')
    assert product['name'] == 'Test Cotton Shirt'
    assert product['offers']['priceCurrency'] == 'VND'
    assert str(product['offers']['price']) in {'199000.00', '199000'}
    assert 'aggregateRating' not in product
    main_image = page.locator('#mainImage')
    expect(main_image).to_be_visible()
    assert main_image.get_attribute('loading') != 'lazy'
    page.goto('/products')
    images = page.locator('.product-card img')
    assert images.count() > 0
    assert all(images.nth(i).get_attribute('decoding') == 'async' for i in range(images.count()))
    page.goto('/')
    offscreen = page.locator('.product-card img')
    assert any(offscreen.nth(i).get_attribute('loading') == 'lazy' for i in range(offscreen.count()))
    assert not page.test_errors, page.test_errors


def test_skip_link_focuses_the_single_main_landmark(gui_page):
    page = gui_page
    for path in ('/products', '/messages'):
        page.goto(path)
        main = page.get_by_role('main')
        expect(main).to_have_count(1)
        skip = page.get_by_role('link', name='Đến nội dung chính', exact=True)
        page.keyboard.press('Tab')
        expect(skip).to_be_focused()
        page.keyboard.press('Enter')
        expect(main).to_be_focused()


def test_mobile_home_cta_and_catalog_put_products_above_fold(gui_page):
    page = gui_page
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto('/')
    page.locator('.storefront-hero').get_by_role('link', name='Xem sản phẩm', exact=True).click()
    expect(page).to_have_url(re.compile(r'/products$'))

    filters = page.locator('#catalogFilterPanel')
    expect(filters.locator('summary')).to_be_visible()
    assert filters.get_attribute('open') is None
    product = page.locator('.product-card').first
    expect(product).to_be_visible()
    assert product.bounding_box()['y'] < 844

    filters.locator('summary').press('Enter')
    expect(filters.locator('form')).to_be_visible()


def test_mobile_search_is_visible_outside_menu_and_shows_results(gui_page):
    page = gui_page
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto('/')
    menu = page.get_by_role('button', name='Mở menu', exact=True)
    expect(menu).to_have_attribute('aria-expanded', 'false')
    search = page.get_by_role('searchbox', name='Tìm kiếm sản phẩm')
    expect(search).to_be_visible()
    search.fill('Cotton')
    expect(page.locator('#searchAutocomplete a')).to_contain_text('Test Cotton Shirt')
    search.press('Escape')
    expect(page.locator('#searchAutocomplete')).to_be_hidden()
    search.press('Enter')
    expect(page).to_have_url(re.compile(r'/products\?search=Cotton$'))
    card = page.locator('.product-card').filter(has_text='Test Cotton Shirt')
    expect(card.locator('img')).to_have_css('object-fit', 'contain')
    expect(menu).to_have_attribute('aria-expanded', 'false')

    page.set_viewport_size({'width': 1024, 'height': 768})
    expect(menu).to_be_visible()
    expect(search).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

    page.set_viewport_size({'width': 1200, 'height': 768})
    expect(menu).to_be_hidden()
    navbar = page.locator('#navbarNav')
    expect(navbar.get_by_role('link', name='Đăng nhập')).to_be_visible()
    search_box = search.bounding_box()
    button_box = page.get_by_role('button', name='Tìm kiếm', exact=True).bounding_box()
    nav_box = navbar.bounding_box()
    assert search_box is not None and search_box['width'] >= 120
    assert button_box is not None and nav_box is not None and button_box['x'] + button_box['width'] <= nav_box['x']


def test_admin_inventory_history_shows_adjustment_and_restock(gui_page, db_connection):
    page = gui_page
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT Quantity FROM ProductVariants WHERE VariantID = 1')
        initial = cursor.fetchone().Quantity

    login(page, 'admin@example.test')
    page.goto('/admin/products/edit/1')
    history = page.get_by_role('region', name='Lịch sử điều chỉnh tồn kho')
    expect(history).to_contain_text('Chưa có điều chỉnh tồn kho')

    adjustment = page.locator('form[action="/admin/products/1/variants/1/stock"]')
    adjustment.locator('#stock-delta-1').fill('-2')
    adjustment.locator('#stock-reason-1').fill('Hàng hỏng')
    adjustment.get_by_role('button', name='Điều chỉnh', exact=True).click()
    expect(history.get_by_role('row').nth(1).get_by_role('cell').nth(3)).to_have_text(str(initial))
    expect(history.get_by_role('row').nth(1).get_by_role('cell').nth(4)).to_have_text(str(initial - 2))

    restock = page.locator('form[action="/admin/products/add_variant"]')
    restock.get_by_label('Màu sắc').select_option('1')
    restock.get_by_label('Kích thước').select_option('1')
    restock.get_by_label('Số lượng').fill('5')
    restock.get_by_label('Lý do điều chỉnh').fill('Nhập lô mới')
    restock.get_by_role('button', name='Thêm biến thể').click()
    rows = history.get_by_role('row')
    expect(rows).to_have_count(3)
    restock_row = rows.nth(1)
    expect(restock_row).to_contain_text('Test Black · Test M #1')
    expect(restock_row).to_contain_text('Test Admin #2')
    expect(restock_row.get_by_role('cell').nth(3)).to_have_text(str(initial - 2))
    expect(restock_row.get_by_role('cell').nth(4)).to_have_text(str(initial + 3))
    expect(restock_row.get_by_role('cell').nth(5)).to_have_text('Nhập lô mới')
    expect(rows.nth(2).get_by_role('cell').nth(5)).to_have_text('Hàng hỏng')
    page.get_by_role('link', name='Xem lịch sử điều chỉnh').click()
    expect(page).to_have_url(re.compile(r'#inventory-history$'))
    expect(history.get_by_role('heading')).to_be_in_viewport()
    assert not page.test_errors, page.test_errors


def test_real_404_has_recovery_link_and_noindex(gui_page):
    page = gui_page
    response = page.goto('/not-a-real-product-page')
    assert response.status == 404
    expect(page.locator('meta[name="robots"]')).to_have_attribute('content', re.compile('noindex'))
    link = page.get_by_role('link', name=re.compile('Trang chủ|trang chủ|cửa hàng|sản phẩm')).first
    expect(link).to_be_visible()
    link.click()
    expect(page).not_to_have_url(re.compile('not-a-real'))
    assert not page.test_errors, page.test_errors


def test_admin_dark_mode_applies_to_charts_and_form_surfaces(gui_page):
    page = gui_page
    login(page, 'admin@example.test')
    expect(page.locator('body')).to_have_class(re.compile('admin-page'))
    assert page.locator('footer').count() == 0
    page.wait_for_function('() => !!window.Chart?.getChart(document.getElementById("revenueChart"))')
    if page.locator('html').get_attribute('data-bs-theme') != 'dark':
        with page.expect_response(re.compile('/toggle_dark_mode$')) as response:
            page.locator('#toggleTheme').click()
        assert response.value.ok
    expect(page.locator('html')).to_have_attribute('data-bs-theme', 'dark')
    page.wait_for_function("""() => {
        const chart = Chart.getChart(document.getElementById('revenueChart'));
        return chart?.options.plugins.legend.labels.color === getComputedStyle(document.body).getPropertyValue('--admin-text').trim();
    }""")
    destination = ROOT / 'artifacts' / 'e2e' / 'phase2'
    destination.mkdir(parents=True, exist_ok=True)
    page.wait_for_function("""() => {
        const node = document.querySelector('.admin-navbar .nav-link');
        return getComputedStyle(node).color === 'rgb(237, 242, 250)';
    }""")
    state = page.evaluate("""() => {
        const ids = ['revenueChart','categoryChart'];
        const computed = id => {
            const node = document.getElementById(id);
            const canvas = getComputedStyle(node);
            const parent = getComputedStyle(node.parentElement);
            const chart = Chart.getChart(node);
            return {background:canvas.backgroundColor, parent:parent.backgroundColor,
                opacity:parent.opacity, legend:chart.options.plugins.legend.labels.color,
                globalAlpha:node.getContext('2d').globalAlpha};
        };
        return {charts:ids.map(computed), navbar:[...document.querySelectorAll('.admin-navbar .nav-link')].map(node => ({color:getComputedStyle(node).color,opacity:getComputedStyle(node).opacity}))};
    }""")
    (destination / 'admin-dark-state.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
    page.screenshot(path=destination / 'admin-dashboard-dark.png')
    page.goto('/admin/products/edit/1')
    section = page.locator('.form-section').first
    expect(section).to_be_visible()
    color = section.evaluate('el => getComputedStyle(el).backgroundColor')
    assert color not in {'rgb(255, 255, 255)', 'rgba(0, 0, 0, 0)'}
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    page.screenshot(path=destination / 'admin-product-form-dark.png')
    assert not page.test_errors, page.test_errors
