from io import BytesIO
from pathlib import Path
import re

import pytest
from PIL import Image
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


def observe(page, name):
    destination = ROOT / 'artifacts' / 'e2e'
    destination.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=destination / f'{name}.png', full_page=False)
    assert not page.test_errors, page.test_errors


def login(page, email='customer@example.test'):
    page.goto('/login')
    expect(page.get_by_role('heading', name='Đăng nhập', exact=True)).to_be_visible()
    page.get_by_label('Email', exact=True).fill(email)
    page.get_by_label('Mật khẩu', exact=True).fill('TestUser123!')
    page.get_by_role('button', name=re.compile('Đăng nhập')).click()
    expect(page).to_have_url(re.compile(r'/(?:admin)?$'))


def product(page):
    page.goto('/products')
    card = page.locator('.product-card').filter(has_text='Test Cotton Shirt')
    expect(card).to_be_visible()
    card.get_by_role('link', name=re.compile('Xem')).click()
    expect(page.get_by_role('heading', name='Test Cotton Shirt', exact=True)).to_be_visible()
    page.get_by_role('button', name='Test Black', exact=True).click()
    page.get_by_role('button', name='Test M', exact=True).click()
    expect(page.get_by_role('button', name=re.compile('Thêm vào giỏ hàng'))).to_be_enabled()


def test_customer_cart_checkout_order(gui_page, db_connection):
    page = gui_page
    login(page)
    observe(page, 'customer-login')
    product(page)
    observe(page, 'selected-variant')
    page.get_by_label('Số lượng:', exact=True).fill('2')
    page.get_by_role('button', name=re.compile('Thêm vào giỏ hàng')).click()
    expect(page.locator('.flash-messages')).to_contain_text('Đã thêm sản phẩm vào giỏ hàng')
    page.locator('#navbarNav').get_by_role('link', name='Giỏ hàng', exact=True).click()
    expect(page.get_by_role('heading', name='Giỏ hàng của bạn')).to_be_visible()
    expect(page.locator('#stock-warning-1')).to_be_hidden()
    quantity = page.get_by_role('spinbutton', name='Số lượng Test Cotton Shirt')
    quantity.fill('3')
    quantity.press('Tab')
    expect(page.locator('#subtotal-1')).to_contain_text(re.compile(r'597[.,]000'))
    observe(page, 'cart-updated')
    page.get_by_role('link', name=re.compile('Tiến hành thanh toán')).click()
    page.get_by_label(re.compile('Họ và tên')).fill('Recipient Test')
    page.get_by_label(re.compile('Số điện thoại')).fill('0900000011')
    page.locator('#checkoutForm').get_by_label(re.compile('^Email')).fill('recipient@example.test')
    page.get_by_label(re.compile('Địa chỉ giao hàng')).fill('11 Synthetic Test Street')
    page.get_by_label('Ghi chú cho đơn hàng').fill('Synthetic browser order')
    observe(page, 'checkout-ready')
    page.get_by_role('button', name='Đặt hàng', exact=False).click()
    expect(page).to_have_url(re.compile(r'/order_confirmation/\d+$'))
    expect(page.get_by_text('Recipient Test', exact=False)).to_be_visible()
    observe(page, 'order-confirmed')
    with db_connection.cursor() as cursor:
        cursor.execute(
            'SELECT TotalAmount,recipient_name,recipient_email,notes FROM Orders WHERE notes=%s',
            ('Synthetic browser order',),
        )
        order = cursor.fetchone()
        assert order.TotalAmount == 597000
        assert order.recipient_name == 'Recipient Test'
        assert order.recipient_email == 'recipient@example.test'


def test_guest_buy_now_survives_login_and_preserves_normal_cart(gui_page, db_connection):
    page = gui_page
    product(page)
    page.get_by_role('button', name=re.compile('Thêm vào giỏ hàng')).click()
    page.get_by_role('button', name='Test Black', exact=True).click()
    page.get_by_role('button', name='Test M', exact=True).click()
    page.get_by_label('Số lượng:', exact=True).fill('2')
    page.get_by_role('button', name=re.compile('Mua ngay')).click()
    expect(page).to_have_url(re.compile(r'/login\?next='))
    page.get_by_label('Email', exact=True).fill('customer@example.test')
    page.get_by_label('Mật khẩu', exact=True).fill('TestUser123!')
    page.get_by_role('button', name=re.compile('Đăng nhập')).click()
    expect(page).to_have_url(re.compile(r'/checkout\?buy_now=1&draft=.+$'))
    page.get_by_label(re.compile('Số điện thoại')).fill('0900000011')
    page.get_by_label('Ghi chú cho đơn hàng').fill('Synthetic buy now')
    page.get_by_role('button', name='Đặt hàng', exact=False).click()
    expect(page).to_have_url(re.compile(r'/order_confirmation/\d+$'))
    observe(page, 'buy-now-confirmed')
    page.get_by_role('link', name='Giỏ hàng', exact=True).click()
    expect(page.get_by_role('spinbutton', name='Số lượng Test Cotton Shirt')).to_have_value('1')
    observe(page, 'normal-cart-retained')
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT TotalAmount FROM Orders WHERE notes=%s', ('Synthetic buy now',))
        assert cursor.fetchone().TotalAmount == 398000


def test_wishlist_persists_and_can_be_removed(gui_page, db_connection):
    page = gui_page
    login(page)
    product(page)
    page.get_by_role('button', name=re.compile('Thêm vào yêu thích')).click()
    expect(page.locator('#addToWishlistBtn')).to_have_attribute('aria-pressed', 'true')
    page.get_by_role('link', name='Danh sách yêu thích', exact=True).click()
    expect(page.get_by_role('heading', name='Test Cotton Shirt', exact=True)).to_be_visible()
    observe(page, 'wishlist-saved')
    row = page.locator('.card').filter(has=page.get_by_role('heading', name='Test Cotton Shirt', exact=True))
    page.once('dialog', lambda dialog: dialog.accept())
    row.get_by_role('button', name=re.compile('Xóa')).click()
    expect(page.get_by_role('heading', name='Test Cotton Shirt', exact=True)).to_have_count(0)
    observe(page, 'wishlist-removed')
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM Wishlist WHERE CustomerID=1 AND ProductID=1')
        assert cursor.fetchone().total == 0


def test_admin_order_transition_and_csv(gui_page, db_connection):
    page = gui_page
    login(page, 'admin@example.test')
    expect(page.get_by_role('heading', name=re.compile('Dashboard|Tổng quan'))).to_be_visible()
    observe(page, 'admin-dashboard')
    page.set_viewport_size({'width': 390, 'height': 844})
    menu = page.get_by_role('button', name='Danh mục quản trị', exact=True)
    expect(menu).to_be_in_viewport()
    expect(page.get_by_role('navigation', name='Danh mục quản trị')).to_be_hidden()
    menu.click()
    drawer = page.get_by_role('dialog', name='Danh mục quản trị')
    expect(drawer.get_by_role('link', name='Tổng quan')).to_have_attribute('aria-current', 'page')
    expect(drawer).to_be_focused()
    observe(page, 'mobile-admin-menu')
    page.keyboard.press('Escape')
    expect(drawer).to_be_hidden()
    expect(menu).to_be_focused()
    page.set_viewport_size({'width': 1280, 'height': 900})
    page.goto('/admin/orders/2')
    expect(page.get_by_role('heading', name=re.compile('Chi tiết đơn hàng'))).to_be_visible()
    page.get_by_role('combobox', name='Cập nhật trạng thái:', exact=True).select_option('Processing')
    page.get_by_role('button', name=re.compile('Cập nhật')).click()
    expect(page.get_by_role('combobox', name='Cập nhật trạng thái:', exact=True)).to_have_value('Processing')
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT Status FROM Orders WHERE OrderID=2')
        assert cursor.fetchone().Status == 'Processing'
    history = page.get_by_role('region', name='Lịch sử trạng thái')
    expect(history).to_contain_text('Test Admin')
    expect(history.locator('time')).to_have_count(2)
    observe(page, 'admin-order-processing')
    page.goto('/admin/reports?start_date=2026-04-01&end_date=2026-04-30')
    observe(page, 'admin-report')
    with page.expect_download() as download:
        page.locator('form[action="/admin/reports/export"]').get_by_role('button', name=re.compile('Xuất CSV')).click()
    assert download.value.suggested_filename.endswith('.csv')


def test_mobile_catalog_has_no_horizontal_document_overflow(gui_page):
    page = gui_page
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto('/products')
    expect(page.get_by_role('heading', name=re.compile('Sản phẩm|Tất cả'))).to_be_visible()
    page.get_by_role('button', name='Mở menu', exact=True).click()
    expect(page.locator('#navbarNav').get_by_role('link', name=re.compile('Đăng nhập'))).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1')
    observe(page, 'mobile-catalog')


def test_admin_product_gallery_size_guide_and_threshold_are_visible(gui_page):
    page = gui_page
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, 'admin@example.test')
    page.goto('/admin/products/edit/1')
    gallery = page.locator('#product-gallery-admin')
    with BytesIO() as image:
        Image.new('RGB', (64, 48), '#27696a').save(image, 'PNG')
        gallery.get_by_label('Ảnh bổ sung').set_input_files(
            {'name': 'synthetic-back.png', 'mimeType': 'image/png', 'buffer': image.getvalue()}
        )
    gallery.get_by_label('Tên góc ảnh').fill('Mặt sau')
    gallery.get_by_role('button', name='Thêm ảnh', exact=True).click()
    expect(gallery.get_by_role('img', name='Mặt sau')).to_be_visible()

    guide = page.locator('#category-size-guide')
    guide.get_by_label('Size', exact=True).select_option('1')
    guide.get_by_label('Vòng ngực (cm)').fill('98')
    guide.get_by_label('Vòng eo (cm)').fill('82')
    guide.get_by_role('button', name='Lưu số đo').click()
    expect(guide.get_by_role('cell', name='98', exact=True)).to_be_visible()
    guide.get_by_label('Size', exact=True).select_option('1')
    expect(guide.get_by_label('Vòng ngực (cm)')).to_have_value('98')

    variant = page.locator('#variant-1')
    variant.get_by_label(re.compile('Ngưỡng tồn thấp')).fill('99')
    variant.get_by_role('button', name='Lưu ngưỡng').click()
    expect(variant.get_by_label(re.compile('Ngưỡng tồn thấp'))).to_have_value('99')
    page.goto('/admin/reports#low-stock')
    expect(page.locator('#low-stock').get_by_role('link', name='Test Cotton Shirt')).to_have_attribute(
        'href', '/admin/products/edit/1#variant-1'
    )

    page.goto('/product/1')
    page.get_by_text('Bảng số đo (cm)', exact=True).click()
    expect(page.get_by_role('cell', name='98', exact=True)).to_be_visible()
    observe(page, 'mobile-product-size-guide')
    page.evaluate('window.scrollTo(0, 0)')
    back = page.get_by_role('link', name='Mặt sau', exact=True)
    back.focus()
    page.keyboard.press('Enter')
    expect(back).to_have_attribute('aria-current', 'true')
    expect(back).to_be_focused()
    expect(back).to_be_in_viewport()
    expect(page.locator('#mainImage')).to_have_attribute('alt', 'Test Cotton Shirt – Mặt sau')
    page.wait_for_function(
        "document.querySelector('#mainImage').complete && document.querySelector('#mainImage').naturalWidth === 64"
    )
    assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
    observe(page, 'mobile-product-gallery')

    page.goto('/product/2')
    expect(page.get_by_text('Bảng số đo (cm)', exact=True)).to_have_count(0)
