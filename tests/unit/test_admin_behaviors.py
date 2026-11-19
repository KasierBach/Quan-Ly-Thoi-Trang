from datetime import date, datetime
from decimal import Decimal

import pytest

from app.database import CaseInsensitiveRecord
from app.services.attribute_service import AttributeService
from app.services.base_service import BaseService
from app.services.customer_service import CustomerService
from app.services.feedback_service import FeedbackService
from app.services.main_service import MainService
from app.services.report_service import ReportService


def row(**values):
    return CaseInsensitiveRecord(values)


@pytest.mark.parametrize('method,column', [('get_all_colors', 'ColorID'), ('get_all_sizes', 'SizeID')])
def test_attribute_read_returns_actual_rows(fake_db, method, column):
    fake_db.cursor.fetchall.return_value = [row(**{column: 1})]
    assert getattr(AttributeService, method)()[0][column] == 1
    fake_db.conn.close.assert_called_once()


@pytest.mark.parametrize('method', ['add_color', 'add_size'])
def test_attribute_insert_and_duplicate(fake_db, method):
    fake_db.cursor.fetchone.return_value = None
    assert getattr(AttributeService, method)('Test')['success']
    fake_db.conn.commit.assert_called_once()
    fake_db.cursor.fetchone.return_value = row(ID=1)
    assert getattr(AttributeService, method)('Test')['status_code'] == 409


@pytest.mark.parametrize('method', ['delete_color', 'delete_size'])
def test_attribute_delete_success_and_refusal(fake_db, method):
    fake_db.cursor.fetchone.side_effect = [row(ID=1), None, row(ID=1)]
    assert getattr(AttributeService, method)(1)['success']
    fake_db.cursor.fetchone.side_effect = [row(ID=1), row(ID=1)]
    assert getattr(AttributeService, method)(1)['status_code'] == 409


@pytest.mark.parametrize(
    'method,args', [('add_color', ('Test',)), ('add_size', ('Test',)), ('delete_color', (1,)), ('delete_size', (1,))]
)
def test_attribute_failure_rolls_back(app, fake_db, method, args):
    fake_db.cursor.execute.side_effect = RuntimeError('private failure')
    with app.app_context():
        assert not getattr(AttributeService, method)(*args)['success']
    fake_db.conn.rollback.assert_called_once()


def test_customer_search_filters_pagination_and_safe_columns(fake_db):
    fake_db.cursor.fetchone.return_value = [1]
    fake_db.cursor.fetchall.return_value = [row(CustomerID=1)]
    result = CustomerService.search_customers('Test_%', 'customer', 9, 20, 'name_asc')
    assert result['current_page'] == 1
    assert result['customers'][0].CustomerID == 1
    query, params = fake_db.cursor.execute.call_args.args
    assert 'Password' not in query
    assert 'IsAdmin = FALSE' in query
    assert params[0] == '%Test\\_\\%%'


def test_customer_detail_uses_delivered_totals(fake_db):
    fake_db.cursor.fetchone.return_value = row(CustomerID=1)
    fake_db.cursor.fetchall.side_effect = [
        [row(Status='Pending', TotalAmount=100), row(Status='Delivered', TotalAmount=Decimal('200.20'))],
        [],
    ]
    result = CustomerService.get_customer_details(1)
    assert result['stats']['totalspent'] == Decimal('200.20')
    assert result['stats']['totalorders'] == 2
    assert result['stats']['deliveredorders'] == 1


def test_customer_delete_no_history_then_success(fake_db):
    fake_db.cursor.fetchone.side_effect = [row(IsAdmin=False), [False], row(CustomerID=1)]
    assert CustomerService.delete_customer(1, actor_id=2)['success']
    fake_db.conn.commit.assert_called_once()


def test_customer_delete_failure_rolls_back(app, fake_db):
    fake_db.cursor.execute.side_effect = RuntimeError('private')
    with app.app_context():
        assert not CustomerService.delete_customer(1, 2)['success']
    fake_db.conn.rollback.assert_called_once()


def test_feedback_new_review_and_update(fake_db):
    now = datetime(2026, 4, 1)
    fake_db.cursor.fetchone.side_effect = [row(FullName='Test'), row(ProductID=1), None, row(ReviewDate=now)]
    assert FeedbackService.add_review(1, 1, 4, 'Review')['success']
    fake_db.cursor.fetchone.side_effect = [row(FullName='Test'), row(ProductID=1), row(ReviewID=1), row(ReviewDate=now)]
    assert FeedbackService.add_review(1, 1, 5, 'Updated')['success']
    assert fake_db.conn.commit.call_count == 2


def test_feedback_reads_reviews_and_breakdown(fake_db):
    fake_db.cursor.fetchone.side_effect = [row(ProductID=1), row(AverageRating=Decimal('4.5'), TotalReviews=2)]
    fake_db.cursor.fetchall.side_effect = [
        [row(ReviewID=1, Rating=5, Comment='Test', ReviewDate=datetime(2026, 4, 1), CustomerName='Test')],
        [row(Rating=5, Count=1), row(Rating=4, Count=1)],
    ]
    result = FeedbackService.get_product_reviews(1)
    assert result['success'] and result['average_rating'] == 4.5
    assert result['rating_breakdown'][5] == 1
    assert result['reviews'][0]['customer_name'] == 'Test'


def test_feedback_comment_new_and_read(fake_db):
    now = datetime(2026, 4, 1)
    fake_db.cursor.fetchone.side_effect = [row(FullName='Test'), row(ProductID=1), row(CommentDate=now)]
    assert FeedbackService.add_comment(1, 1, 'Comment')['success']
    fake_db.cursor.fetchone.side_effect = [row(ProductID=1)]
    fake_db.cursor.fetchall.side_effect = [
        [row(CommentID=1, Content='Test', CommentDate=now, AdminReply='Reply', ReplyDate=now, CustomerName='Test')]
    ]
    result = FeedbackService.get_product_comments(1)
    assert result['success'] and result['comments'][0]['content'] == 'Test'


@pytest.mark.parametrize(
    'method,args',
    [
        ('add_review', (1, 1, 5, 'Test')),
        ('add_comment', (1, 1, 'Test')),
        ('get_product_reviews', (1,)),
        ('get_product_comments', (1,)),
    ],
)
def test_feedback_failure_is_safe(app, fake_db, method, args):
    fake_db.cursor.execute.side_effect = RuntimeError('private')
    with app.app_context():
        result = getattr(FeedbackService, method)(*args)
    assert not result['success'] and 'private' not in result['message']
    fake_db.conn.close.assert_called_once()


def test_main_contact_list_filters_and_paginates(fake_db):
    fake_db.cursor.fetchone.return_value = [1]
    fake_db.cursor.fetchall.return_value = [row(MessageID=1)]
    result = MainService.get_contact_messages('New', 20, 20)
    assert result['current_page'] == 1 and result['messages'][0].MessageID == 1
    assert fake_db.cursor.execute.call_args.args[1] == ['New', 20, 0]


def test_main_contact_insert_update_read_and_health(fake_db):
    assert MainService.add_contact_message('Test', 'test@example.test', 'Subject', 'Test message')['success']
    fake_db.cursor.fetchone.return_value = row(MessageID=1)
    assert MainService.update_contact_message_status(1, 'Answered')['success']
    assert MainService.get_contact_message(1).MessageID == 1
    fake_db.cursor.fetchone.return_value = [1]
    assert MainService.check_health()
    fake_db.cursor.execute.side_effect = RuntimeError('failure')
    assert not MainService.check_health()


@pytest.mark.parametrize(
    'method,args',
    [
        ('add_contact_message', ('Test', 'test@example.test', 'Subject', 'Test message')),
        ('update_contact_message_status', (1, 'New')),
        ('subscribe_newsletter', ('test@example.test',)),
    ],
)
def test_main_write_failure_rolls_back(app, fake_db, method, args):
    fake_db.cursor.execute.side_effect = RuntimeError('private')
    with app.app_context():
        assert not getattr(MainService, method)(*args)['success']
    fake_db.conn.rollback.assert_called_once()


def test_base_success_preserves_contract():
    assert BaseService.success([1])['data'] == [1]
    assert BaseService.success({'value': 1})['value'] == 1


def test_report_dashboard_query_outputs(fake_db):
    today = date.today()
    fake_db.cursor.fetchone.side_effect = [[today.replace(day=1)], [3], [2]]
    fake_db.cursor.fetchall.side_effect = [[row(OrderDate=today, DailyRevenue=Decimal('100.10'), OrderCount=1)], [], []]
    result = ReportService.get_dashboard_stats()
    assert result['current_month_revenue'] == Decimal('100.10')
    assert result['current_month_orders'] == 1 and result['new_customers'] == 2


@pytest.mark.parametrize('report_type', ['top_customers', 'order_details', 'low_stock'])
def test_all_csv_queries_format_real_fields(fake_db, report_type):
    fake_db.cursor.fetchall.return_value = []
    fake_db.cursor.fetchone.return_value = [date(2026, 4, 1)]
    data = ReportService.generate_csv_report(report_type, '2026-04-01', '2026-04-30')
    assert isinstance(data, (bytes, str))
    query = fake_db.cursor.execute.call_args.args[0]
    if report_type != 'low_stock':
        assert "Status = 'Delivered'" in query
