import re

from playwright.sync_api import Page, expect


class LoginPage:
    def __init__(self, page: Page):
        self.page = page

    def open(self):
        self.page.goto('/login')
        expect(self.page.get_by_role('heading', name='Đăng nhập', exact=True)).to_be_visible()

    def submit(self, email, password):
        form = self.page.locator('form[action="/login"]')
        form.get_by_label('Email', exact=True).fill(email)
        form.get_by_label('Mật khẩu', exact=True).fill(password)
        form.locator('button[type="submit"]').click()

    def sign_in(self, email='customer@example.test', password='TestUser123!'):
        self.open()
        self.submit(email, password)
        expect(self.page).to_have_url(re.compile(r'/(?:admin)?$'))

    def register(self, name, email, password, phone, address, confirmation=None):
        self.page.locator('footer a[href="/register"]').click()
        form = self.page.locator('form[action="/register"]')
        form.get_by_label(re.compile(r'^Họ và tên')).fill(name)
        form.get_by_label(re.compile(r'^Email')).fill(email)
        form.get_by_label(re.compile(r'^Mật khẩu')).fill(password)
        form.get_by_label(re.compile(r'^Xác nhận mật khẩu')).fill(confirmation or password)
        form.get_by_label('Số điện thoại', exact=True).fill(phone)
        form.get_by_label('Địa chỉ', exact=True).fill(address)
        form.locator('button[type="submit"]').click()
