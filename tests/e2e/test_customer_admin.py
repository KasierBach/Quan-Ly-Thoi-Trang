from pathlib import Path
import re

import pytest
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
    page.get_by_role('link', name='Giỏ hàng', exact=True).click()
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
    page.goto('/admin/orders/2')
    expect(page.get_by_role('heading', name=re.compile('Chi tiết đơn hàng'))).to_be_visible()
    page.get_by_label(re.compile('trạng thái', re.IGNORECASE)).select_option('Processing')
    page.get_by_role('button', name=re.compile('Cập nhật')).click()
    expect(page.get_by_label(re.compile('trạng thái', re.IGNORECASE))).to_have_value('Processing')
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT Status FROM Orders WHERE OrderID=2')
        assert cursor.fetchone().Status == 'Processing'
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
