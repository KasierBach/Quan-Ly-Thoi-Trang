import csv
from datetime import date, datetime
from decimal import Decimal
from io import StringIO

import pytest

from app.services.attribute_service import AttributeService
from app.services.customer_service import CustomerService
from app.services.feedback_service import FeedbackService
from app.services.main_service import MainService
from app.services.report_service import ReportService
from app.validation import ValidationError


pytestmark = pytest.mark.integration


def admin_sign_in(client):
    with client.session_transaction() as session:
        session.update(user_id=2, role='admin', is_admin=True, user_name='Test Admin', auth_version=1)


def csv_rows(contents):
    return list(csv.reader(StringIO(contents.decode('utf-8-sig'))))


def create_delivered_order(connection, when, quantity=1):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO Orders (CustomerID, OrderDate, PaymentMethod, ShippingAddress)
            VALUES (1, %s, 'cod', 'Synthetic address') RETURNING OrderID
        """,
            (when,),
        )
        order_id = cursor.fetchone().OrderID
        cursor.execute('SELECT sp_AddOrderDetail(%s, 1, %s)', (order_id, quantity))
        for status in ('Processing', 'Shipped', 'Delivered'):
            cursor.execute('SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, status))
    connection.commit()
    return order_id


def test_real_report_excludes_pending_and_cancelled_in_all_exports(db_app):
    with db_app.app_context():
        report = ReportService.get_revenue_report('2026-04-02', '2026-04-04')
        assert sum(row.DailyRevenue for row in report['daily_revenue']) == Decimal('398000.00')
        assert sum(row.OrderCount for row in report['daily_revenue']) == 1
        assert len(report['best_selling']) == 1
        assert report['best_selling'][0].TotalSold == 2
        assert report['category_revenue'][0].CategoryRevenue == Decimal('398000.00')
        for kind, amount_column in [
            ('daily_revenue', 2),
            ('best_selling', 2),
            ('category_revenue', 2),
            ('top_customers', 3),
            ('order_details', 3),
        ]:
            rows = csv_rows(ReportService.generate_csv_report(kind, '2026-04-02', '2026-04-04'))
            assert len(rows) == 2, kind
            assert Decimal(rows[1][amount_column]) == Decimal('398000.00'), kind
        stock = csv_rows(ReportService.generate_csv_report('low_stock', '2026-04-02', '2026-04-04'))
        assert 'không lọc ngày' in stock[0][0]


def test_end_date_includes_late_orders_and_customers(db_app, db_connection):
    create_delivered_order(db_connection, datetime(2026, 4, 2, 23, 59, 59))
    create_delivered_order(db_connection, datetime(2026, 4, 3, 0, 0, 0))
    with db_connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO Customers (FullName, Email, Password, CreatedAt, IsAdmin)
            VALUES ('Late customer', 'late@example.test', 'unused-test-password', %s, FALSE)
        """,
            (datetime(2026, 4, 2, 23, 59, 59),),
        )
    db_connection.commit()
    with db_app.app_context():
        report = ReportService.get_revenue_report('2026-04-02', '2026-04-02')
        assert len(report['daily_revenue']) == 1
        assert report['daily_revenue'][0].DailyRevenue == Decimal('597000.00')
        assert report['daily_revenue'][0].OrderCount == 2
        assert report['new_customers_range'] == 1
        assert report['best_selling'][0].TotalSold == 3
        assert report['category_revenue'][0].CategoryRevenue == Decimal('597000.00')
        rows = csv_rows(ReportService.generate_csv_report('order_details', '2026-04-02', '2026-04-02'))
        assert len(rows) == 3
        assert all('02/04/2026' in row[2] for row in rows[1:])


def test_all_time_default_before_first_order_is_empty(db_app):
    with db_app.app_context():
        report = ReportService.get_revenue_report(None, '2020-01-01')
        assert report['daily_revenue'] == []
        assert report['best_selling'] == []
        assert report['category_revenue'] == []
        assert report['end_date'] == '2020-01-01'


def test_iso_week_group_and_csv_match_across_year_boundary(db_app, db_connection):
    create_delivered_order(db_connection, datetime(2020, 12, 31, 22, 0, 0))
    create_delivered_order(db_connection, datetime(2021, 1, 1, 23, 0, 0))
    with db_app.app_context():
        report = ReportService.get_revenue_report('2020-12-31', '2021-01-01', 'week')
        assert len(report['daily_revenue']) == 1
        assert report['daily_revenue'][0].OrderDate == date(2020, 12, 28)
        assert report['daily_revenue'][0].DailyRevenue == Decimal('398000.00')
        rows = csv_rows(ReportService.generate_csv_report('daily_revenue', '2020-12-31', '2021-01-01', 'week'))
        assert rows[1] == ['28/12/2020', '2', '398000.00']


def test_real_csv_neutralizes_stored_names_and_quotes(db_app, db_connection):
    with db_connection.cursor() as cursor:
        cursor.execute('UPDATE Products SET ProductName = %s WHERE ProductID = 1', ('=SUM(1,2)\nshirt',))
        cursor.execute('UPDATE Categories SET CategoryName = %s WHERE CategoryID = 1', ('  @category',))
        cursor.execute('UPDATE Customers SET FullName = %s WHERE CustomerID = 1', ('-customer',))
    db_connection.commit()
    with db_app.app_context():
        products = csv_rows(ReportService.generate_csv_report('best_selling', '2026-04-01', '2026-04-30'))
        categories = csv_rows(ReportService.generate_csv_report('category_revenue', '2026-04-01', '2026-04-30'))
        customers = csv_rows(ReportService.generate_csv_report('top_customers', '2026-04-01', '2026-04-30'))
        assert products[1][0] == "'=SUM(1,2)\nshirt"
        assert categories[1][0] == "'  @category"
        assert customers[1][0] == "'-customer"


def test_real_newsletter_duplicates_are_idempotent(db_app, db_connection):
    with db_app.app_context():
        assert MainService.subscribe_newsletter('  Subscriber@Example.TEST  ')['success'] is True
        assert MainService.subscribe_newsletter('SUBSCRIBER@example.test')['success'] is True
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM NewsletterSubscribers WHERE LOWER(Email) = 'subscriber@example.test'")
        assert cursor.fetchone()[0] == 1


def test_real_contact_stored_validation_and_missing_status(db_app, db_connection):
    with db_app.app_context():
        assert (
            MainService.add_contact_message('  Name  ', 'CONTACT2@EXAMPLE.TEST', '', '  Message  ')['success'] is True
        )
        assert MainService.update_contact_message_status(99999, 'Answered')['status_code'] == 404
        with pytest.raises(ValidationError):
            MainService.update_contact_message_status(1, 'bad-status')
        result = MainService.get_contact_messages('New', page=999, per_page=10)
        assert result['current_page'] == 1
        assert result['total_records'] == 2
    with db_connection.cursor() as cursor:
        cursor.execute(
            "SELECT Name, Email, Subject, Message FROM ContactMessages WHERE Email = 'contact2@example.test'"
        )
        row = cursor.fetchone()
        assert row.Name == 'Name'
        assert row.Subject is None
        assert row.Message == 'Message'


def test_real_comment_moderation_never_changes_reviews(db_app, db_connection):
    with db_app.app_context():
        result = FeedbackService.admin_reply_comment(1, '  New reply  ')
        assert result['success'] is True
        assert FeedbackService.toggle_comment_visibility(1, '0')['success'] is True
        assert FeedbackService.get_product_comments(1)['comments'] == []
        assert FeedbackService.admin_reply_comment(99999, 'Reply')['status_code'] == 404
        assert FeedbackService.add_review(1, 1, 4, 'Updated review')['success'] is True
        assert FeedbackService.add_comment(1, 99999, 'Missing product')['status_code'] == 404
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT Rating, Comment FROM Reviews WHERE CustomerID = 1 AND ProductID = 1')
        row = cursor.fetchone()
        assert row.Rating == 4
        assert row.Comment == 'Updated review'
        cursor.execute('SELECT AdminReply, IsVisible FROM ProductComments WHERE CommentID = 1')
        row = cursor.fetchone()
        assert row.AdminReply == 'New reply'
        assert row.IsVisible is False
        cursor.execute('SELECT COUNT(*) FROM Reviews WHERE CustomerID = 1 AND ProductID = 1')
        assert cursor.fetchone()[0] == 1


def test_real_customer_deletion_and_realized_spending_guards(db_app):
    with db_app.app_context():
        details = CustomerService.get_customer_details(1)
        assert details['stats']['totalorders'] == 2
        assert details['stats']['totalspent'] == Decimal('398000.00')
        assert CustomerService.delete_customer(1, actor_id=2)['status_code'] == 409
        assert CustomerService.delete_customer(2, actor_id=2)['status_code'] == 409
        assert CustomerService.delete_customer(2, actor_id=1)['status_code'] == 409
        assert CustomerService.delete_customer(99999, actor_id=2)['status_code'] == 404
        assert CustomerService.get_customer_details(1) is not None


def test_real_customer_without_history_can_be_deleted(db_app, db_connection):
    with db_connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO Customers (FullName, Email, Password, IsAdmin)
            VALUES ('Disposable', 'disposable@example.test', 'test-unused', FALSE) RETURNING CustomerID
        """)
        customer_id = cursor.fetchone().CustomerID
    db_connection.commit()
    with db_app.app_context():
        assert CustomerService.delete_customer(customer_id, actor_id=2)['success'] is True
        assert CustomerService.get_customer_details(customer_id) is None


def test_real_attributes_protect_referenced_and_duplicate_values(db_app):
    with db_app.app_context():
        assert AttributeService.delete_color(1)['status_code'] == 409
        assert AttributeService.delete_size(1)['status_code'] == 409
        assert AttributeService.delete_color(99999)['status_code'] == 404
        assert AttributeService.add_color(' test black ')['status_code'] == 409
        assert AttributeService.add_size(' test m ')['status_code'] == 409
        assert AttributeService.add_color('New color')['success'] is True


def test_real_all_admin_views_and_main_contact_render(db_client):
    admin_sign_in(db_client)
    for path in (
        '/admin',
        '/admin/reports?start_date=2026-04-01&end_date=2026-04-30',
        '/admin/reports/export?start_date=2026-04-01&end_date=2026-04-30',
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
        '/contact',
    ):
        response = db_client.get(path)
        assert response.status_code == 200, (path, response.status_code, response.get_data(as_text=True)[:300])


def test_real_route_filters_and_missing_entities(db_client):
    admin_sign_in(db_client)
    for path in (
        '/admin/reports?start_date=2026-04-30&end_date=2026-04-01',
        '/admin/reports?start_date=not-a-date',
        '/admin/reports?group_by=invalid',
        '/admin/customers?role=invalid',
        '/admin/comments?filter=invalid',
        '/admin/orders?status=Completed',
    ):
        assert db_client.get(path).status_code == 400, path
    for path in ('/admin/customers/99999', '/admin/orders/99999', '/admin/products/edit/99999'):
        assert db_client.get(path).status_code == 404, path
    response = db_client.post('/admin/customers/delete/1', headers={'X-Requested-With': 'XMLHttpRequest'})
    assert response.status_code == 409
    assert response.json['success'] is False
