import re

from playwright.sync_api import Page, expect


class AccountPage:
    def __init__(self, page: Page):
        self.page = page

    def open(self):
        self.page.locator('footer a[href="/my_account"]').click()
        expect(self.page.get_by_role('heading', name='Tài khoản của tôi', exact=True)).to_be_visible()

    def tab(self, label):
        tabs = {
            'Thông tin cá nhân': 'profile',
            'Đơn hàng của tôi': 'orders',
            'Địa chỉ': 'address',
            'Đổi mật khẩu': 'password',
            'Giao diện': 'appearance',
        }
        # Bootstrap assigns role=tab to these anchors after the page initializes.
        tab = self.page.locator(f'.list-group a[href="#{tabs[label]}"]')
        expect(tab).to_have_attribute('role', 'tab')
        tab.click()
        expect(self.page.locator(f'.tab-content > #{tabs[label]}')).to_have_class(re.compile('active'))

    def update_profile(self, name, phone, gender, dob):
        self.tab('Thông tin cá nhân')
        form = self.page.locator('form[action="/update_profile"]')
        form.get_by_label('Họ và tên', exact=True).fill(name)
        form.get_by_label('Số điện thoại', exact=True).fill(phone)
        # These two existing controls have no associated label; select their literal form names.
        form.locator('select[name="gender"]').select_option(gender)
        form.locator('input[name="dob"]').fill(dob)
        form.locator('button[type="submit"]').click()

    def update_address(self, address):
        self.tab('Địa chỉ')
        form = self.page.locator('form[action="/update_address"]')
        form.get_by_label('Địa chỉ giao hàng mặc định', exact=True).fill(address)
        form.locator('button[type="submit"]').click()

    def change_password(self, current, new):
        self.tab('Đổi mật khẩu')
        form = self.page.locator('#passwordForm')
        form.get_by_label('Mật khẩu hiện tại', exact=True).fill(current)
        form.get_by_label('Mật khẩu mới', exact=True).fill(new)
        form.get_by_label('Xác nhận mật khẩu mới', exact=True).fill(new)
        form.locator('button[type="submit"]').click()

    def set_dark_mode(self, enabled):
        self.tab('Giao diện')
        self.page.get_by_label('Chế độ tối', exact=True).set_checked(enabled)

    def sign_out(self):
        self.page.locator('.list-group form[action="/logout"] button[type="submit"]').click()
        expect(self.page).to_have_url(re.compile(r'/$'))
