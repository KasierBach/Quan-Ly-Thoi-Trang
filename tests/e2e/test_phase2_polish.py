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
