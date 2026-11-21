import re

from playwright.sync_api import Page, expect


class CatalogPage:
    def __init__(self, page: Page):
        self.page = page

    def open(self):
        self.page.goto('/products')
        expect(self.page.get_by_role('heading', name='Tất cả sản phẩm', exact=True)).to_be_visible()

    def card(self, name):
        return self.page.locator('#products-grid .product-card').filter(
            has=self.page.get_by_role('heading', name=name, exact=True)
        )

    def open_product(self, name):
        self.card(name).get_by_role('link', name=re.compile('Xem')).click()
        expect(self.page.get_by_role('heading', name=name, exact=True)).to_be_visible()

    def search(self, query):
        self.page.get_by_role('searchbox', name='Tìm kiếm sản phẩm', exact=True).fill(query)

    def suggestion(self, name):
        return self.page.locator('#searchAutocomplete').get_by_role('link', name=re.compile(re.escape(name)))
