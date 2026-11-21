from playwright.sync_api import Page, expect

from .catalog import CatalogPage


class ProductPage:
    def __init__(self, page: Page):
        self.page = page

    def open(self, name='Test Cotton Shirt'):
        catalog = CatalogPage(self.page)
        catalog.open()
        catalog.open_product(name)

    def select_variant(self, color='Test Black', size='Test M', quantity=1):
        form = self.page.locator('#productPurchaseForm')
        form.get_by_role('button', name=color, exact=True).click()
        form.get_by_role('button', name=size, exact=True).click()
        expect(form.get_by_label('Số lượng:', exact=True)).to_be_enabled()
        form.get_by_label('Số lượng:', exact=True).fill(str(quantity))

    def add_to_cart(self):
        self.page.locator('#addToCartBtn').click()
        expect(self.page.locator('.flash-messages')).to_contain_text('Đã thêm sản phẩm vào giỏ hàng')

    def review(self, text, rating=4):
        self.page.locator('#reviews-tab').click()
        self.page.locator('#openReviewModalBtn').click()
        modal = self.page.locator('#reviewModal')
        modal.get_by_role('button', name=f'{rating} sao', exact=True).click()
        modal.get_by_label('Nhận xét của bạn', exact=True).fill(text)
        self.page.once('dialog', lambda dialog: dialog.accept())
        modal.locator('#submit-review').click()
        expect(modal).to_be_hidden()
        expect(self.page.locator('#reviews-container')).to_contain_text(text)

    def comment(self, text):
        self.page.locator('#comments-tab').click()
        self.page.locator('#openCommentModalBtn').click()
        modal = self.page.locator('#commentModal')
        modal.get_by_label('Nội dung bình luận', exact=True).fill(text)
        self.page.once('dialog', lambda dialog: dialog.accept())
        modal.locator('#submit-comment').click()
        expect(modal).to_be_hidden()
        expect(self.page.locator('#comments-container')).to_contain_text(text)
