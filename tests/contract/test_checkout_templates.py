from decimal import Decimal
from datetime import datetime

from bs4 import BeautifulSoup
from flask import render_template

from app.database import CaseInsensitiveRecord
from app.services.auth_service import AuthService
from app.services.product_service import ProductService


def test_buy_now_checkout_form_preserves_mode(auth_client, monkeypatch):
    row = {
        'variant_id': 1,
        'quantity': 2,
        'price': '199000.00',
        'stock': 10,
        'product_name': 'Áo',
        'product_id': 1,
        'color': 'Đen',
        'size': 'M',
        'image_url': 'images/default.jpg',
    }
    monkeypatch.setattr(ProductService, 'refresh_cart_items', lambda items, **_: [row])
    monkeypatch.setattr(
        AuthService,
        'get_customer_profile',
        lambda _: CaseInsensitiveRecord(
            FullName='Người nhận', PhoneNumber='0900000001', Email='user@example.test', Address='Địa chỉ'
        ),
    )
    with auth_client.session_transaction() as session:
        session['temp_cart'] = [row]
    response = auth_client.get('/checkout?buy_now=1', follow_redirects=True)
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('#checkoutForm')['action'].startswith('/checkout?buy_now=1&draft=')
    assert soup.select_one('input[name=checkout_review]')['value']
    assert soup.select_one('input[name=buy_now]')['value'] == '1'
    assert soup.select_one('input[name=phone]')['value'] == '0900000001'
    payments = soup.select('input[name=payment_method]')
    assert len(payments) == 1 and payments[0]['value'] == 'Thanh toán khi nhận hàng'
    assert soup.select_one('#discount_code') is None
    assert b'WELCOME10' not in response.data
    assert soup.select_one('input[name=shipping_method]')['value'] == 'standard'


def test_order_detail_only_shows_recorded_status_and_recipient(app):
    order = CaseInsensitiveRecord(
        OrderID=1,
        OrderDate=datetime(2026, 4, 1),
        Status='Shipped',
        TotalAmount=Decimal('398000'),
        PaymentMethod='COD',
        ShippingAddress='Địa chỉ',
        recipient_name='Tên nhận',
        recipient_phone='0900000001',
        recipient_email='recipient@example.test',
        notes='Ghi chú',
        CustomerName='Old',
        CustomerPhone='old',
        CustomerEmail='old@example.test',
    )
    item = CaseInsensitiveRecord(
        ProductName='Áo', ColorName='Đen', SizeName='M', Quantity=2, Price=Decimal('199000'), Subtotal=Decimal('398000')
    )
    with app.test_request_context('/order/1'):
        html = render_template('order_detail.html', order=order, order_details=[item])
    assert 'Tên nhận' in html and 'Đang giao' in html
    assert '398,000' in html
    assert 'SPX' not in html and 'shipping-map' not in html and 'leaflet' not in html
    assert 'nominatim' not in html and 'Shipper đang' not in html
    assert BeautifulSoup(html, 'html.parser').select_one('#cancel-order-btn') is None


def test_account_renders_order_summary_for_history_beyond_current_page(app):
    customer = CaseInsensitiveRecord(
        FullName='Test',
        Email='user@example.test',
        PhoneNumber=None,
        Address=None,
        AvatarUrl=None,
        DateOfBirth=None,
        Gender='other',
        CreatedAt=datetime(2026, 1, 1),
        DarkModeEnabled=False,
    )
    orders = [
        CaseInsensitiveRecord(
            OrderID=1, OrderDate=datetime(2026, 4, 1), Status='Pending', TotalAmount=Decimal('100000')
        ),
        CaseInsensitiveRecord(
            OrderID=2, OrderDate=datetime(2026, 4, 1), Status='Delivered', TotalAmount=Decimal('200000')
        ),
    ]
    with app.test_request_context('/my_account'):
        html = render_template(
            'my_account.html',
            customer=customer,
            orders=orders,
            total_orders=15,
            total_spent=Decimal('900000'),
            current_page=1,
            total_pages=2,
        )
    assert '900,000đ' in html and '200,000đ' not in html
    soup = BeautifulSoup(html, 'html.parser')
    assert soup.select_one('a[href="/my_account?orders_page=2#orders"]') is not None
    assert 'Diamond' not in html and 'Tháng này: +' not in html
    assert 'Đã hoàn thành</small>' not in html
    assert 'avatar-upload' in html
    assert '<form action="/logout" method="post">' in html
