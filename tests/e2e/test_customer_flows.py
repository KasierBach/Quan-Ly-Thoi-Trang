"""Uncovered customer boundaries; all tested writes originate from real browser controls."""

from datetime import date
from html import unescape
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect
from werkzeug.security import check_password_hash

from app import mail
from tests.e2e.pages import ShopPages

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


def read_row(connection, sql, values=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, values)
        row = cursor.fetchone()
        assert row is not None
        return row


def count(connection, table, where='', values=()):
    suffix = f' WHERE {where}' if where else ''
    return read_row(connection, f'SELECT COUNT(*) AS total FROM {table}{suffix}', values).total


def stock(connection, variant=1):
    return read_row(connection, 'SELECT Quantity FROM ProductVariants WHERE VariantID=%s', (variant,)).Quantity


def identity(connection):
    return read_row(connection, 'SELECT Password, auth_version AS AuthVersion FROM Customers WHERE CustomerID=1')


def inventory(connection):
    with connection.cursor() as cursor:
        cursor.execute('SELECT VariantID, Quantity FROM ProductVariants ORDER BY VariantID')
        return cursor.fetchall()


def observe(page, name):
    destination = ROOT / 'artifacts' / 'e2e'
    destination.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=destination / f'customer-{name}.png', full_page=False)
    assert not page.test_errors, page.test_errors


@pytest.fixture
def second_page(browser, live_app):
    context = browser.new_context(base_url=live_app[0], viewport={'width': 1280, 'height': 900})
    context.set_default_timeout(5000)
    context.route('https://**/*', lambda route: route.abort())
    page = context.new_page()
    page.test_errors = []
    page.on('pageerror', lambda error: page.test_errors.append(str(error)))
    try:
        yield page
    finally:
        context.close()


@pytest.fixture
def suppressed_outbox(live_app):
    application = live_app[1]
    state = application.extensions.get('mail')
    assert application.config.get('MAIL_SUPPRESS_SEND') is True, 'Refuse any unsuppressed mail operation'
    assert state is not None and state.suppress is True, 'Flask-Mail must also suppress delivery'
    with mail.record_messages() as outbox:
        yield outbox


def test_guest_registration_recovers_confirmation_and_autologin_persists(gui_page, db_connection):
    page, shop = gui_page, ShopPages(gui_page)
    name, password, phone, address = (
        'Synthetic New Customer',
        'RegisteredUser123!',
        '0900000042',
        '42 Synthetic Signup Street',
    )
    shop.catalog.open()
    shop.login.register(f'  {name}  ', 'Phase3.Signup@Example.Test', password, phone, address, 'DifferentUser123!')
    expect(page).to_have_url(re.compile(r'/register$'))
    confirmation = page.locator('form[action="/register"] [name="confirm_password"]')
    assert confirmation.evaluate('(input) => input.validity.customError')
    assert count(db_connection, 'Customers') == 3
    observe(page, 'register-confirmation-rejected')
    confirmation.fill(password)
    page.locator('form[action="/register"] button[type="submit"]').click()
    expect(page).to_have_url(re.compile(r'/$'))
    expect(page.locator('.flash-messages')).to_contain_text('Đăng ký thành công!')
    customer = read_row(db_connection, 'SELECT * FROM Customers WHERE Email=%s', ('phase3.signup@example.test',))
    assert (customer.FullName, customer.PhoneNumber, customer.Address) == (name, phone, address)
    assert customer.Role == 'customer' and not customer.IsAdmin and customer.auth_version == 1
    assert check_password_hash(customer.Password, password)
    shop.account.open()  # A protected page proves the form established the real session.
    profile = page.locator('form[action="/update_profile"]')
    expect(profile.get_by_label('Email', exact=True)).to_have_value(customer.Email)
    observe(page, 'registered-autologin')
    shop.account.sign_out()
    shop.login.sign_in(customer.Email, password)
    shop.account.open()
    expect(profile.get_by_label('Họ và tên', exact=True)).to_have_value(name)
    observe(page, 'registered-login-persisted')


def test_footer_newsletter_native_validation_and_duplicate_subscription(gui_page, db_connection):
    page = gui_page
    ShopPages(page).catalog.open()
    form, field = page.locator('#newsletter-form'), page.locator('#newsletter-email')
    field.fill('not-an-email')
    form.locator('button[type="submit"]').click()
    assert field.evaluate('(input) => input.validity.typeMismatch')
    expect(page.locator('#newsletter-status')).to_have_text('')
    assert count(db_connection, 'NewsletterSubscribers') == 1
    field.fill('Phase3.News@Example.Test')
    form.locator('button[type="submit"]').click()
    expect(page.locator('#newsletter-status')).to_have_text('Đã lưu đăng ký nhận tin')
    expect(field).to_have_value('')
    subscriber = read_row(
        db_connection, 'SELECT Email, IsActive FROM NewsletterSubscribers WHERE Email=%s', ('phase3.news@example.test',)
    )
    assert subscriber.Email == 'phase3.news@example.test' and subscriber.IsActive
    field.fill('phase3.news@example.test')
    form.locator('button[type="submit"]').click()
    expect(page.locator('#newsletter-status')).to_have_text('Email đã đăng ký')
    assert count(db_connection, 'NewsletterSubscribers', 'Email=%s', ('phase3.news@example.test',)) == 1
    observe(page, 'newsletter-duplicate-recovered')


def test_contact_server_validation_preserves_fields_then_saves_real_submission(gui_page, db_connection):
    page = gui_page
    name, email, subject = 'Synthetic Phase3 Contact', 'phase3.contact@example.test', 'Synthetic contact recovery'
    message = 'Xin tư vấn chất liệu áo thử nghiệm.\nKhông gửi email thật.'
    ShopPages(page).catalog.open()
    page.locator('footer a[href="/contact"]').click()
    form = page.locator('form[action="/contact"]')
    form.get_by_label(re.compile(r'^Họ và tên')).fill(name)
    form.get_by_label(re.compile(r'^Email')).fill(email)
    form.get_by_label('Tiêu đề', exact=True).fill(subject)
    form.get_by_label(re.compile(r'^Nội dung')).fill('   ')
    with page.expect_response(
        lambda response: urlsplit(response.url).path == '/contact' and response.request.method == 'POST'
    ) as rejected:
        form.locator('button[type="submit"]').click()
    assert rejected.value.status == 400
    expect(page.get_by_role('alert')).to_have_text('Nội dung không hợp lệ')
    expect(form.get_by_label('Tiêu đề', exact=True)).to_have_value(subject)
    expect(form.get_by_label(re.compile(r'^Email'))).to_have_value(email)
    assert count(db_connection, 'ContactMessages', 'Email=%s', (email,)) == 0
    observe(page, 'contact-validation')
    form.get_by_label(re.compile(r'^Nội dung')).fill(message)
    form.locator('button[type="submit"]').click()
    expect(page.locator('.flash-messages')).to_contain_text('Đã lưu tin nhắn liên hệ. Cảm ơn bạn!')
    contact = read_row(db_connection, 'SELECT * FROM ContactMessages WHERE Email=%s', (email,))
    assert (contact.Name, contact.Subject, contact.Message.replace('\r\n', '\n'), contact.Status) == (
        name,
        subject,
        message,
        'New',
    )
    assert count(db_connection, 'ContactMessages') == 2
    observe(page, 'contact-saved')


def test_profile_and_address_updates_survive_reload_and_prefill_checkout(gui_page, db_connection):
    page, shop = gui_page, ShopPages(gui_page)
    name, phone, gender, dob = 'Synthetic Updated Customer', '0900000021', 'female', '1994-06-12'
    address = '42 Synthetic Lane\nTest District'
    shop.login.sign_in()
    shop.account.open()
    profile = page.locator('form[action="/update_profile"]')
    expect(profile.get_by_label('Email', exact=True)).to_have_attribute('readonly', '')
    shop.account.update_profile(name, phone, gender, dob)
    expect(page.locator('.flash-messages')).to_contain_text('Cập nhật thông tin thành công!')
    customer = read_row(db_connection, 'SELECT * FROM Customers WHERE CustomerID=1')
    assert (customer.FullName, customer.PhoneNumber, customer.Gender, customer.DateOfBirth) == (
        name,
        phone,
        gender,
        date.fromisoformat(dob),
    )
    assert customer.Email == 'customer@example.test' and customer.auth_version == 1
    shop.account.update_address(address)
    expect(page.locator('.flash-messages')).to_contain_text('Cập nhật địa chỉ thành công!')
    assert (
        read_row(db_connection, 'SELECT Address FROM Customers WHERE CustomerID=1').Address.replace('\r\n', '\n')
        == address
    )
    page.reload()
    shop.account.tab('Thông tin cá nhân')
    expect(profile.get_by_label('Họ và tên', exact=True)).to_have_value(name)
    expect(profile.locator('[name="gender"]')).to_have_value(gender)
    expect(profile.locator('[name="dob"]')).to_have_value(dob)
    shop.account.tab('Địa chỉ')
    expect(page.get_by_label('Địa chỉ giao hàng mặc định', exact=True)).to_have_value(address)
    assert (
        read_row(db_connection, 'SELECT FullName FROM Customers WHERE CustomerID=3').FullName == 'Test Other Customer'
    )
    observe(page, 'account-updated')
    shop.product.open()
    shop.product.select_variant()
    shop.product.add_to_cart()
    shop.cart.open()
    checkout = shop.cart.checkout()
    for label, value in [
        ('^Họ và tên', name),
        ('^Số điện thoại', phone),
        ('^Email', customer.Email),
        ('^Địa chỉ giao hàng', address),
    ]:
        expect(checkout.get_by_label(re.compile(label))).to_have_value(value)
    observe(page, 'profile-checkout-defaults')


def test_password_change_rejects_wrong_current_and_revalidates_other_context_without_losing_carts(
    gui_page, second_page, db_connection
):
    page, current, other = gui_page, ShopPages(gui_page), ShopPages(second_page)
    before = identity(db_connection)
    for shop, quantity in [(current, 2), (other, 3)]:
        shop.login.sign_in()
        shop.product.open()
        shop.product.select_variant(quantity=quantity)
        shop.product.add_to_cart()
        shop.cart.open()
        expect(shop.cart.quantity()).to_have_value(str(quantity))
        shop.account.open()
    current.account.change_password('WrongUser123!', 'ChangedUser456!')
    expect(page.locator('.flash-messages')).to_contain_text('Mật khẩu hiện tại không đúng')
    assert identity(db_connection) == before
    other.account.open()
    current.account.change_password('TestUser123!', 'ChangedUser456!')
    expect(page.locator('.flash-messages')).to_contain_text('Đổi mật khẩu thành công!')
    changed = identity(db_connection)
    assert changed.AuthVersion == before.AuthVersion + 1
    assert check_password_hash(changed.Password, 'ChangedUser456!')
    current.cart.open()
    expect(current.cart.quantity()).to_have_value('2')
    observe(page, 'password-current-cart-kept')
    second_page.locator('footer a[href="/my_account"]').click()
    expect(second_page).to_have_url(re.compile(r'/login\?next='))
    assert parse_qs(urlsplit(second_page.url).query)['next'] == ['/my_account']
    other.cart.open()
    expect(other.cart.quantity()).to_have_value('3')
    other.login.open()
    other.login.submit('customer@example.test', 'TestUser123!')
    expect(second_page.locator('.flash-messages')).to_contain_text('Email hoặc mật khẩu không đúng')
    other.login.submit('customer@example.test', 'ChangedUser456!')
    expect(second_page).to_have_url(re.compile(r'/$'))
    other.account.open()
    other.cart.open()
    expect(other.cart.quantity()).to_have_value('3')
    observe(second_page, 'password-other-context-recovered')


def test_cart_remove_confirmation_updates_totals_and_persists_empty_cart(gui_page, db_connection):
    page, shop = gui_page, ShopPages(gui_page)
    before = inventory(db_connection)
    for name, color, size, quantity in [
        ('Test Cotton Shirt', 'Test Black', 'Test M', 2),
        ('Test Summer Dress', 'Test White', 'Test L', 1),
    ]:
        shop.product.open(name)
        shop.product.select_variant(color, size, quantity)
        shop.product.add_to_cart()
    shop.cart.open()
    expect(page.locator('#total')).to_contain_text(re.compile(r'797[.,]000'))
    shop.cart.remove('Test Cotton Shirt', confirm=False)
    expect(shop.cart.quantity()).to_have_value('2')
    expect(page.locator('#cart-item-count')).to_have_text('2')
    observe(page, 'cart-remove-dismissed')
    shop.cart.remove('Test Cotton Shirt')
    expect(page.locator('#cart-item-count')).to_have_text('1')
    expect(page.locator('#total')).to_contain_text(re.compile(r'399[.,]000'))
    page.reload()
    expect(shop.cart.quantity()).to_have_count(0)
    expect(shop.cart.quantity('Test Summer Dress')).to_have_value('1')
    shop.cart.remove('Test Summer Dress')
    expect(page.get_by_role('heading', name='Giỏ hàng của bạn đang trống', exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_role('heading', name='Giỏ hàng của bạn đang trống', exact=True)).to_be_visible()
    assert inventory(db_connection) == before
    assert count(db_connection, 'Orders') == 3
    observe(page, 'cart-removed-empty')


def test_cancel_pending_order_restores_stock_once_and_delivered_has_no_cancel(gui_page, db_connection):
    page, shop = gui_page, ShopPages(gui_page)
    before = read_row(
        db_connection,
        'SELECT o.Status, pv.Quantity AS Stock, od.Quantity AS Reserved FROM Orders o '
        'JOIN OrderDetails od ON od.OrderID=o.OrderID JOIN ProductVariants pv ON pv.VariantID=od.VariantID '
        'WHERE o.OrderID=2',
    )
    assert before.Status == 'Pending'
    shop.login.sign_in()
    shop.account.open()
    shop.account.tab('Đơn hàng của tôi')
    row = page.locator('#orders tbody tr').filter(has=page.get_by_role('cell', name='#2', exact=True))
    row.locator('a[href="/order/2"]').click()
    expect(page.locator('#order-status')).to_have_text('Chờ xử lý')
    page.once('dialog', lambda dialog: dialog.dismiss())
    page.locator('#cancel-order-btn').click()
    expect(page.locator('#order-status')).to_have_text('Chờ xử lý')
    assert stock(db_connection, 2) == before.Stock
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#cancel-order-btn').click()
    expect(page.locator('#order-status')).to_have_text('Đã hủy')
    expect(page.locator('#cancel-order-btn')).to_have_count(0)
    assert read_row(db_connection, 'SELECT Status FROM Orders WHERE OrderID=2').Status == 'Cancelled'
    assert stock(db_connection, 2) == before.Stock + before.Reserved
    observe(page, 'pending-cancelled')
    page.reload()
    assert stock(db_connection, 2) == before.Stock + before.Reserved
    page.get_by_role('link', name='Đơn hàng của tôi', exact=True).click()
    expect(row).to_contain_text('Đã hủy')
    delivered = page.locator('#orders tbody tr').filter(has=page.get_by_role('cell', name='#1', exact=True))
    delivered.locator('a[href="/order/1"]').click()
    expect(page.locator('#order-status')).to_have_text('Đã giao')
    expect(page.locator('#cancel-order-btn')).to_have_count(0)
    observe(page, 'delivered-not-cancellable')


def test_review_upsert_and_comment_persist_script_looking_text_literally(gui_page, db_connection):
    page, shop = gui_page, ShopPages(gui_page)
    shop.login.sign_in()
    shop.product.open()
    review = 'Vải mềm <script>alert("review")</script> & "giữ nguyên"'
    comment = 'Xin tư vấn <img src=x onerror=alert("comment")> & size M?'
    shop.product.review(review, rating=4)
    expect(page.locator('#review-count')).to_have_text('1')  # Updates the existing customer review, not a duplicate.
    expect(page.locator('#reviews-container script')).to_have_count(0)
    saved = read_row(db_connection, 'SELECT Rating, Comment FROM Reviews WHERE CustomerID=1 AND ProductID=1')
    assert saved.Rating == 4 and saved.Comment == review
    assert count(db_connection, 'Reviews', 'CustomerID=1 AND ProductID=1') == 1
    observe(page, 'review-literal')
    shop.product.comment(comment)
    expect(page.locator('#comment-count')).to_have_text('2')
    expect(page.locator('#comments-container img, #comments-container script')).to_have_count(0)
    saved = read_row(
        db_connection,
        'SELECT CustomerID, ProductID, Content, IsVisible FROM ProductComments WHERE Content=%s',
        (comment,),
    )
    assert (saved.CustomerID, saved.ProductID, saved.Content, saved.IsVisible) == (1, 1, comment, True)
    page.reload()
    page.locator('#reviews-tab').click()
    expect(page.locator('#reviews-container')).to_contain_text(review)
    expect(page.locator('#reviews-container script')).to_have_count(0)
    page.locator('#comments-tab').click()
    expect(page.locator('#comments-container')).to_contain_text(comment)
    expect(page.locator('#comments-container img, #comments-container script')).to_have_count(0)
    observe(page, 'feedback-reloaded-literal')


def test_search_autocomplete_escape_empty_recovery_and_keyboard_navigation(gui_page):
    page, shop = gui_page, ShopPages(gui_page)
    shop.catalog.open()
    search = page.get_by_role('searchbox', name='Tìm kiếm sản phẩm', exact=True)
    shop.catalog.search('Cotton')
    expect(shop.catalog.suggestion('Test Cotton Shirt')).to_be_visible()
    expect(search).to_have_attribute('aria-expanded', 'true')
    search.press('Escape')
    expect(search).to_have_attribute('aria-expanded', 'false')
    expect(shop.catalog.suggestion('Test Cotton Shirt')).to_be_hidden()
    shop.catalog.search('Phase3MissingItem')
    expect(page.locator('#searchAutocomplete')).to_have_text('Không tìm thấy sản phẩm')
    expect(page.locator('#searchAutocomplete a')).to_have_count(0)
    observe(page, 'search-no-results')
    shop.catalog.search('Summer')
    suggestion = shop.catalog.suggestion('Test Summer Dress')
    expect(suggestion).to_be_visible()
    search.press('ArrowDown')
    expect(suggestion).to_be_focused()
    suggestion.press('Enter')
    expect(page).to_have_url(re.compile(r'/product/2$'))
    expect(page.get_by_role('heading', name='Test Summer Dress', exact=True)).to_be_visible()
    observe(page, 'autocomplete-navigated')
    shop.catalog.search('Cotton')
    search.press('Enter')
    expect(page).to_have_url(re.compile(r'/products\?search=Cotton$'))
    expect(shop.catalog.card('Test Cotton Shirt')).to_be_visible()
    expect(shop.catalog.card('Test Summer Dress')).to_have_count(0)
    observe(page, 'search-form-results')


def test_account_dark_preference_persists_in_database_and_fresh_context(gui_page, second_page, db_connection):
    page, current, other = gui_page, ShopPages(gui_page), ShopPages(second_page)
    assert not read_row(db_connection, 'SELECT DarkModeEnabled FROM Customers WHERE CustomerID=1').DarkModeEnabled
    current.login.sign_in()
    current.account.open()
    current.account.set_dark_mode(True)
    expect(page.locator('html')).to_have_attribute('data-bs-theme', 'dark')
    assert read_row(db_connection, 'SELECT DarkModeEnabled FROM Customers WHERE CustomerID=1').DarkModeEnabled
    page.reload()
    current.account.tab('Giao diện')
    expect(page.get_by_label('Chế độ tối', exact=True)).to_be_checked()
    other.login.sign_in()
    other.account.open()
    other.account.tab('Giao diện')
    expect(second_page.get_by_label('Chế độ tối', exact=True)).to_be_checked()
    expect(second_page.locator('html')).to_have_attribute('data-bs-theme', 'dark')
    observe(second_page, 'dark-fresh-context')
    other.account.set_dark_mode(False)
    expect(second_page.locator('html')).to_have_attribute('data-bs-theme', 'light')
    assert not read_row(db_connection, 'SELECT DarkModeEnabled FROM Customers WHERE CustomerID=1').DarkModeEnabled
    page.reload()
    current.account.tab('Giao diện')
    expect(page.get_by_label('Chế độ tối', exact=True)).not_to_be_checked()
    expect(page.locator('html')).to_have_attribute('data-bs-theme', 'light')
    observe(page, 'dark-preference-restored')


def test_checkout_invalid_phone_preserves_cart_and_fields_then_recovers(gui_page, db_connection):
    page, shop = gui_page, ShopPages(gui_page)
    name, email, address = 'Synthetic Phone Recovery', 'phase3.checkout@example.test', '80 Synthetic Recovery Road'
    before = stock(db_connection)
    shop.login.sign_in()
    shop.product.open()
    shop.product.select_variant(quantity=2)
    shop.product.add_to_cart()
    shop.cart.open()
    form = shop.cart.checkout()
    for label, value in [
        ('^Họ và tên', name),
        ('^Số điện thoại', '123abc'),
        ('^Email', email),
        ('^Địa chỉ giao hàng', address),
    ]:
        form.get_by_label(re.compile(label)).fill(value)
    form.get_by_label('Ghi chú cho đơn hàng', exact=True).fill('Phase3 checkout phone recovery')
    with page.expect_response(
        lambda response: urlsplit(response.url).path == '/checkout' and response.request.method == 'POST'
    ) as rejected:
        form.locator('button[type="submit"]').click()
    assert rejected.value.status == 400
    expect(page.locator('.flash-messages')).to_contain_text('Số điện thoại cần từ 8 đến 15 chữ số')
    expect(form.get_by_label(re.compile(r'^Số điện thoại'))).to_have_value('123abc')
    expect(form.get_by_label('Ghi chú cho đơn hàng', exact=True)).to_have_value('Phase3 checkout phone recovery')
    expect(form.locator('button[type="submit"]')).to_be_enabled()
    assert count(db_connection, 'Orders') == 3
    assert stock(db_connection) == before
    observe(page, 'checkout-phone-rejected')
    form.get_by_label(re.compile(r'^Số điện thoại')).fill('0900000061')
    form.locator('button[type="submit"]').click()
    expect(page).to_have_url(re.compile(r'/order_confirmation/\d+$'))
    order = read_row(db_connection, 'SELECT * FROM Orders WHERE notes=%s', ('Phase3 checkout phone recovery',))
    assert order.CustomerID == 1 and order.Status == 'Pending' and order.TotalAmount == 398000
    assert (order.recipient_name, order.recipient_phone, order.recipient_email, order.ShippingAddress) == (
        name,
        '0900000061',
        email,
        address,
    )
    assert count(db_connection, 'Orders') == 4
    assert stock(db_connection) == before - 2
    observe(page, 'checkout-phone-recovered')
    shop.cart.open()
    expect(page.get_by_role('heading', name='Giỏ hàng của bạn đang trống', exact=True)).to_be_visible()


def test_password_reset_uses_actual_suppressed_mail_link_and_cannot_reuse_token(
    gui_page, suppressed_outbox, db_connection
):
    page, shop = gui_page, ShopPages(gui_page)
    shop.login.open()
    page.get_by_role('link', name='Quên mật khẩu?', exact=True).click()
    form = page.locator('form[action="/forgot_password"]')
    form.get_by_label('Email', exact=True).fill('customer@example.test')
    form.locator('button[type="submit"]').click()
    expect(page.get_by_role('heading', name='Email đã được gửi!', exact=True)).to_be_visible()
    assert len(suppressed_outbox) == 1
    message = suppressed_outbox[0]
    assert message.recipients == ['customer@example.test'] and message.subject == 'Đặt lại mật khẩu'
    match = re.search(r'href="([^"]+)"', message.html or '')
    assert match is not None, 'Use only the actual token link emitted to the suppressed mail outbox'
    link = urlsplit(unescape(match.group(1)))
    assert link.scheme == 'https' and link.hostname == 'store.example.test'
    assert re.fullmatch(r'/reset_password/[A-Za-z0-9_-]{20,128}', link.path)
    page.goto(link.path)  # Map the captured canonical mail link to this fixture's loopback origin.
    form = page.locator('#resetPasswordForm')
    form.get_by_label('Mật khẩu mới', exact=True).fill('RecoveredUser456!')
    form.get_by_label('Xác nhận mật khẩu mới', exact=True).fill('RecoveredUser456!')
    form.locator('button[type="submit"]').click()
    expect(page.get_by_role('heading', name='Mật khẩu đã được đặt lại!', exact=True)).to_be_visible()
    customer = identity(db_connection)
    assert customer.AuthVersion == 2 and check_password_hash(customer.Password, 'RecoveredUser456!')
    assert count(db_connection, 'PasswordResetTokens', 'CustomerID=1 AND IsUsed=FALSE') == 0
    observe(page, 'reset-from-suppressed-mail')
    page.goto(link.path)
    form.get_by_label('Mật khẩu mới', exact=True).fill('ReuseDenied789!')
    form.get_by_label('Xác nhận mật khẩu mới', exact=True).fill('ReuseDenied789!')
    form.locator('button[type="submit"]').click()
    expect(page.locator('.flash-messages')).to_contain_text('Token không hợp lệ hoặc đã hết hạn')
    assert identity(db_connection) == customer
    observe(page, 'reset-token-reuse-rejected')
    shop.login.open()
    shop.login.submit('customer@example.test', 'TestUser123!')
    expect(page.locator('.flash-messages')).to_contain_text('Email hoặc mật khẩu không đúng')
    shop.login.submit('customer@example.test', 'RecoveredUser456!')
    expect(page).to_have_url(re.compile(r'/$'))
    shop.account.open()
    observe(page, 'reset-login-recovered')
