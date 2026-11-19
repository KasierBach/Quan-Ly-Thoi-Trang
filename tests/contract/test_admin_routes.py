import json
from datetime import date, datetime
from decimal import Decimal
import re
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg2
import pytest

from app.database import CaseInsensitiveRecord
from app.services.attribute_service import AttributeService
from app.services.category_service import CategoryService
from app.services.customer_service import CustomerService
from app.services.feedback_service import FeedbackService
from app.services.main_service import MainService
from app.services.order_service import OrderService
from app.services.product_service import ProductService
from app.services.report_service import ReportService


ADMIN_GETS = (
    '/admin',
    '/admin/reports',
    '/admin/reports/export',
    '/admin/products',
    '/admin/products/add',
    '/admin/products/edit/1',
    '/admin/products/manage',
    '/admin/orders',
    '/admin/orders/1',
    '/admin/customers',
    '/admin/customers/1',
    '/admin/comments',
    '/admin/contact_messages',
    '/admin/attributes',
)


def record(**values):
    return CaseInsensitiveRecord(values)


def paging(key, rows):
    return {
        key: rows,
        'total_records': len(rows),
        'total_pages': 1,
        'current_page': 1,
        'per_page': 20,
        'start_index': 1 if rows else 0,
        'end_index': len(rows),
    }


def payload_script(html, element_id):
    match = re.search(rf'<script[^>]*id="{element_id}"[^>]*>(.*?)</script>', html, re.S)
    assert match is not None
    return json.loads(match.group(1))


def mock_admin_reads(monkeypatch):
    now = datetime(2026, 1, 31, 20, 30)
    category = record(CategoryID=1, CategoryName='Category <safe>')
    product = record(
        ProductID=1,
        ProductName='Shirt',
        Description='Description',
        CategoryID=1,
        CategoryName=category.CategoryName,
        Price=Decimal('100.10'),
        OriginalPrice=Decimal('120'),
        ImageURL='images/default.jpg',
        CreatedAt=now,
        VariantCount=1,
        TotalStock=2,
        TotalSold=2,
    )
    customer = record(
        CustomerID=1,
        FullName='Customer',
        Email='person@example.test',
        PhoneNumber='0900000000',
        Address='Address',
        CreatedAt=now,
        IsAdmin=False,
    )
    order = record(
        OrderID=1,
        CustomerID=1,
        CustomerName='Customer',
        CustomerEmail=customer.Email,
        CustomerPhone=customer.PhoneNumber,
        OrderDate=now,
        TotalAmount=Decimal('200.20'),
        Status='Delivered',
        PaymentMethod='COD',
        ShippingAddress='Address',
    )
    item = record(
        ProductID=1,
        ProductName='Shirt',
        ImageURL=product.ImageURL,
        ColorName='Red',
        SizeName='M',
        UnitPrice=Decimal('100.10'),
        Quantity=2,
        Subtotal=Decimal('200.20'),
    )
    comment = record(
        CommentID=1,
        ProductID=1,
        ProductName='Shirt',
        CustomerID=1,
        CustomerName='Customer',
        Content='<img src=x onerror=alert(1)> "line"\nback\\slash </script>',
        CommentDate=now,
        AdminReply='</textarea><img src=x onerror=alert(2)>',
        ReplyDate=now,
        IsVisible=True,
    )
    contact = record(
        MessageID=1,
        Name='Name "quotes"',
        Email='person@example.test',
        Subject='</script><img onerror=alert(1)>',
        Message='<script>alert(1)</script>\nline\\slash',
        SubmitDate=now,
        Status='New',
    )
    daily = [SimpleNamespace(OrderDate=date(2026, 1, 31), DailyRevenue=Decimal('200.20'), OrderCount=1)]
    category_revenue = [
        record(CategoryID=1, CategoryName=category.CategoryName, CategoryRevenue=Decimal('200.20'), OrderCount=1)
    ]
    best = [
        record(
            ProductID=1,
            ProductName='Shirt',
            CategoryName=category.CategoryName,
            TotalSold=2,
            TotalRevenue=Decimal('200.20'),
        )
    ]
    revenue_report = {
        'start_date': '2026-01-01',
        'end_date': '2026-01-31',
        'group_by': 'day',
        'daily_revenue': daily,
        'category_revenue': category_revenue,
        'best_selling': best,
        'new_customers_range': 7,
    }
    dashboard = {
        'monthly_revenue': [record(Year=2026, Month=1, TotalRevenue=Decimal('200.20'), OrderCount=1)],
        'category_revenue': category_revenue,
        'best_selling': best,
        'current_month_revenue': Decimal('200.20'),
        'current_month_orders': 1,
        'total_sold': 2,
        'new_customers': 7,
        'history_start_date': '2026-01-01',
        'history_end_date': '2026-01-31',
    }
    patches = [
        (CategoryService, 'get_all_categories', [category]),
        (AttributeService, 'get_all_colors', []),
        (AttributeService, 'get_all_sizes', []),
        (ProductService, 'get_admin_products', paging('products', [product])),
        (ProductService, 'get_product_by_id', product),
        (ProductService, 'get_product_variants', []),
        (ProductService, 'get_featured_products', [product]),
        (ProductService, 'get_best_selling_products', [product]),
        (OrderService, 'get_orders_admin', paging('orders', [order])),
        (OrderService, 'get_order_detail', {'order': order, 'items': [item]}),
        (CustomerService, 'search_customers', paging('customers', [customer])),
        (
            CustomerService,
            'get_customer_details',
            {
                'customer': customer,
                'orders': [order],
                'comments': [comment],
                'stats': {'totalorders': 1, 'deliveredorders': 1, 'totalspent': Decimal('200.20')},
            },
        ),
        (FeedbackService, 'get_admin_comments', paging('comments', [comment])),
        (MainService, 'get_contact_messages', paging('messages', [contact])),
        (ReportService, 'get_dashboard_stats', dashboard),
        (ReportService, 'get_revenue_report', revenue_report),
        (ReportService, 'generate_csv_report', b'\xef\xbb\xbfdate,count,total\r\n'),
    ]
    for service, method, result in patches:
        monkeypatch.setattr(service, method, Mock(return_value=result))
    return SimpleNamespace(comment=comment, contact=contact, report=revenue_report, product=product, order=order)


@pytest.mark.parametrize('path', ADMIN_GETS)
def test_guest_cannot_read_admin(client, path):
    response = client.get(path)
    assert response.status_code in (302, 401)


@pytest.mark.parametrize('path', ADMIN_GETS)
def test_customer_cannot_read_admin(auth_client, path):
    response = auth_client.get(path)
    assert response.status_code in (302, 403)


@pytest.mark.parametrize('path', ADMIN_GETS)
def test_admin_routes_render_existing_templates(admin_client, monkeypatch, path):
    mock_admin_reads(monkeypatch)
    response = admin_client.get(path)
    assert response.status_code == 200
    if path != '/admin/reports/export':
        assert b'<!DOCTYPE html>' in response.data
    else:
        assert response.headers['Content-Type'].startswith('text/csv')
        assert 'attachment' in response.headers['Content-Disposition']


def test_every_owned_template_parses(app):
    templates = [name for name in app.jinja_env.list_templates() if name.startswith('admin/') or name == 'contact.html']
    assert len(templates) >= 13
    for name in templates:
        app.jinja_env.get_template(name)


@pytest.mark.parametrize(
    'path,element_id,field',
    [
        ('/admin/comments', 'comments-json', 'content'),
        ('/admin/contact_messages', 'messages-json', 'message'),
    ],
)
def test_modal_payload_json_is_roundtripped_and_escaped(admin_client, monkeypatch, path, element_id, field):
    values = mock_admin_reads(monkeypatch)
    html = admin_client.get(path).get_data(as_text=True)
    value = payload_script(html, element_id)['1'][field]
    assert value == (values.comment.Content if field == 'content' else values.contact.Message)
    assert '\\u003c' in html
    assert '<script>alert(1)</script>' not in html
    assert '.textContent = ' in html
    assert '${comment.content}' not in html
    assert '${message.message' not in html


def test_reports_show_actual_counts_and_no_fake_controls(admin_client, monkeypatch):
    mock_admin_reads(monkeypatch)
    html = admin_client.get('/admin/reports').get_data(as_text=True)
    assert 'new_customers_range' not in html
    assert '<div class="stat-value">7</div>' in html
    assert 'Delivered' in html
    for fake in (
        '+12.5%',
        '+8.3%',
        '+15.7%',
        '+5.2%',
        'exportToExcel()',
        'exportToPDF()',
        'scheduleReport()',
        'id="scheduleModal"',
        'id="legacyEmailModal"',
    ):
        assert fake not in html
    assert 'Xuất CSV' in html
    assert 'chưa được tích hợp' in html
    assert 'vendor/chart/chart.umd.js' in html
    assert 'cdn.jsdelivr.net' not in html
    assert payload_script(html, 'chart-data')['dailyData'] == [200.2]


@pytest.mark.parametrize(
    'path,amount',
    [
        ('/admin/reports', '200.2'),
        ('/admin/customers/1', '200.2'),
        ('/admin/products/manage', '100.1'),
        ('/admin', '200.2'),
        ('/admin/orders', '200.2'),
        ('/admin/orders/1', '200.2'),
    ],
)
def test_currency_render_does_not_hide_fractional_money(admin_client, monkeypatch, path, amount):
    mock_admin_reads(monkeypatch)
    html = admin_client.get(path).get_data(as_text=True)
    assert amount in re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.S)


def test_edit_template_modal_is_rendered_and_config_exists(admin_client, monkeypatch):
    mock_admin_reads(monkeypatch)
    html = admin_client.get('/admin/products/edit/1').get_data(as_text=True)
    assert 'id="pixabayModal"' in html
    assert 'const productConfig = JSON.parse' in html
    assert payload_script(html, 'product-config') == {'productId': 1}
    assert '${hit.tags}' not in html
    assert 'image.alt = hit.tags' in html


@pytest.mark.parametrize('path', ['/admin/api/save_pixabay_image', '/admin/api/send_report_email'])
@pytest.mark.parametrize('body', ['null', '[]', '"text"', '{malformed'])
def test_json_endpoints_reject_nonobjects(admin_client, path, body):
    response = admin_client.post(path, data=body, content_type='application/json')
    assert response.status_code == 400
    assert response.json['success'] is False


def test_external_email_and_image_disabled_during_testing(admin_client, monkeypatch):
    mail = Mock(side_effect=AssertionError('mail prohibited'))
    outbound = Mock(side_effect=AssertionError('network prohibited'))
    monkeypatch.setattr('app.routes.admin.reports.send_email', mail)
    monkeypatch.setattr('app.services.media_service.requests.get', outbound)
    email = admin_client.post(
        '/admin/api/send_report_email',
        json={
            'email': 'one@example.test',
            'start_date': '2026-01-01',
            'end_date': '2026-01-31',
            'report_type': 'daily_revenue',
        },
    )
    assert email.status_code == 503
    search = admin_client.get('/admin/api/search_pixabay?q=shirt')
    assert search.status_code == 503
    assert not search.json['success']
    mail.assert_not_called()
    outbound.assert_not_called()


@pytest.mark.parametrize(
    'path,form',
    [
        ('/admin/reply_comment', {'comment_id': 1, 'reply': ' '}),
        ('/admin/toggle_comment_visibility', {'comment_id': 1, 'visible': 2}),
        ('/admin/update_message_status', {'message_id': 1, 'status': 'unknown'}),
    ],
)
def test_invalid_admin_mutations_no_sql(admin_client, fake_db, path, form):
    response = admin_client.post(path, data=form)
    assert response.status_code == 400
    assert response.json['success'] is False
    fake_db.cursor.execute.assert_not_called()


def test_contact_validates_and_preserves_user_input(client, fake_db):
    response = client.post('/contact', data={'name': '<b>name</b>', 'email': 'invalid', 'message': 'message'})
    assert response.status_code == 400
    assert b'&lt;b&gt;name&lt;/b&gt;' in response.data
    fake_db.cursor.execute.assert_not_called()


def test_newsletter_invalid_email_has_400_no_db(client, fake_db):
    response = client.post('/subscribe_newsletter', data={'email': 'one@example.test\r\nBcc: victim'})
    assert response.status_code == 400
    assert response.json['success'] is False
    fake_db.cursor.execute.assert_not_called()


def test_home_and_contact_keep_main_ui_without_fake_integrations(client, monkeypatch):
    mock_admin_reads(monkeypatch)
    assert client.get('/').status_code == 200
    html = client.get('/contact').get_data(as_text=True)
    assert 'Gửi tin nhắn cho chúng tôi' in html
    assert 'chưa được cấu hình' in html
    assert '<iframe' not in html
    assert '69 Đường Gì Đó' not in html


@pytest.mark.parametrize(
    'path',
    ['/admin/customers', '/admin/comments', '/admin/contact_messages', '/admin/products/manage', '/admin/orders'],
)
def test_malformed_paging_is_bounded(admin_client, monkeypatch, path):
    mock_admin_reads(monkeypatch)
    response = admin_client.get(path + '?page=-99&per_page=999999999999999999')
    assert response.status_code == 200
    service = {
        '/admin/customers': CustomerService.search_customers,
        '/admin/comments': FeedbackService.get_admin_comments,
        '/admin/contact_messages': MainService.get_contact_messages,
        '/admin/products/manage': ProductService.get_admin_products,
        '/admin/orders': OrderService.get_orders_admin,
    }[path]
    args = service.call_args.args
    if path == '/admin/customers':
        assert args[2:4] == (1, 20)
    elif path == '/admin/products/manage':
        assert args[:2] == (1, 20)
    else:
        assert args[1:3] == (1, 15 if path == '/admin/comments' else 20)


def test_product_invalid_variant_id_redirects_safely(admin_client, monkeypatch):
    mutation = Mock()
    monkeypatch.setattr(ProductService, 'add_variant', mutation)
    response = admin_client.post(
        '/admin/products/add_variant', data={'product_id': 'bad'}, headers={'Referer': 'https://evil.example/'}
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin/products/manage')
    mutation.assert_not_called()


def test_product_zero_quantity_and_money_supported(admin_client, monkeypatch):
    mutation = Mock(return_value={'success': True})
    monkeypatch.setattr(ProductService, 'add_variant', mutation)
    response = admin_client.post(
        '/admin/products/add_variant', data={'product_id': 1, 'color_id': 1, 'size_id': 1, 'quantity': 0}
    )
    assert response.status_code == 302
    mutation.assert_called_once_with(1, 1, 1, 0)
    add = Mock(return_value={'success': True, 'product_id': 1})
    monkeypatch.setattr(ProductService, 'add_product', add)
    response = admin_client.post(
        '/admin/products/add', data={'product_name': ' Free ', 'price': '0.00', 'category_id': 1, 'original_price': '0'}
    )
    assert response.status_code == 302
    assert add.call_args.args[0] == 'Free'
    assert add.call_args.args[2] == Decimal('0.00')


def test_missing_comment_returns_404_not_fake_success(admin_client, fake_db):
    fake_db.cursor.fetchone.return_value = None
    response = admin_client.post('/admin/reply_comment', data={'comment_id': 999, 'reply': 'Reply'})
    assert response.status_code == 404
    assert not response.json['success']


def test_contact_reply_ignores_form_recipient_and_failed_send_keeps_status(admin_client, monkeypatch):
    mock_admin_reads(monkeypatch)
    monkeypatch.setattr(MainService, 'get_contact_message', Mock(return_value=record(Email='stored@example.test')))
    status = Mock(return_value={'success': True})
    monkeypatch.setattr(MainService, 'update_contact_message_status', status)
    mail = Mock(return_value=False)
    monkeypatch.setattr('app.routes.admin.feedback.send_email', mail)
    app = admin_client.application
    app.testing = False
    app.config.update(
        MAIL_SUPPRESS_SEND=False, MAIL_SERVER='unused.example.test', MAIL_DEFAULT_SENDER='shop@example.test'
    )
    response = admin_client.post(
        '/admin/reply_contact_message',
        data={'message_id': 1, 'email': 'attacker@example.test', 'reply': '<script>bad</script>'},
    )
    assert response.status_code == 502
    assert mail.call_args.args[0] == 'stored@example.test'
    assert '&lt;script&gt;' in mail.call_args.args[2]
    status.assert_not_called()


def test_delivered_order_has_no_status_mutation_form(admin_client, monkeypatch):
    mock_admin_reads(monkeypatch)
    html = admin_client.get('/admin/orders/1').get_data(as_text=True)
    assert 'name="status"' not in html
    assert 'không thể thay đổi' in html


def test_health_live_never_uses_database(client, fake_db):
    response = client.get('/health/live')
    assert response.status_code == 200
    assert response.json == {'status': 'live'}
    fake_db.connection.cursor.assert_not_called()


@pytest.mark.parametrize('path', ['/health', '/health/ready'])
def test_health_readiness_reports_503(client, monkeypatch, path):
    monkeypatch.setattr(MainService, 'check_health', Mock(return_value=False))
    response = client.get(path)
    assert response.status_code == 503
    assert response.json['database'] == 'error'


def test_safe_error_hides_database_detail(admin_client, monkeypatch):
    monkeypatch.setattr(
        CustomerService, 'delete_customer', Mock(side_effect=psycopg2.OperationalError('secret-db-password'))
    )
    response = admin_client.post('/admin/customers/delete/1', headers={'X-Requested-With': 'XMLHttpRequest'})
    assert response.status_code == 503
    assert not response.json['success']
    assert 'secret-db-password' not in response.get_data(as_text=True)
