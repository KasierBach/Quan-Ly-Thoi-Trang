import re

from playwright.sync_api import Page, expect


class CartPage:
    def __init__(self, page: Page):
        self.page = page

    def open(self):
        self.page.get_by_role('link', name='Giỏ hàng', exact=True).click()
        expect(self.page.get_by_role('heading', name='Giỏ hàng của bạn', exact=True)).to_be_visible()

    def quantity(self, name='Test Cotton Shirt'):
        return self.page.get_by_role('spinbutton', name=f'Số lượng {name}', exact=True)

    def remove(self, name, confirm=True):
        self.page.once('dialog', lambda dialog: dialog.accept() if confirm else dialog.dismiss())
        self.page.get_by_role('button', name=f'Xóa {name}', exact=True).click()
        if confirm:
            expect(self.quantity(name)).to_have_count(0)

    def checkout(self):
        self.page.get_by_role('link', name=re.compile('Tiến hành thanh toán')).click()
        form = self.page.locator('#checkoutForm')
        expect(form).to_be_visible()
        return form
