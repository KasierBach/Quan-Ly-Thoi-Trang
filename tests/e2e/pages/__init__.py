"""Small, real-form page helpers shared by storefront E2E tests."""

from playwright.sync_api import Page

from .account import AccountPage
from .cart import CartPage
from .catalog import CatalogPage
from .login import LoginPage
from .product import ProductPage

__all__ = ['ShopPages', 'LoginPage', 'CatalogPage', 'ProductPage', 'CartPage', 'AccountPage']


class ShopPages:
    def __init__(self, page: Page):
        self.login = LoginPage(page)
        self.catalog = CatalogPage(page)
        self.product = ProductPage(page)
        self.cart = CartPage(page)
        self.account = AccountPage(page)
