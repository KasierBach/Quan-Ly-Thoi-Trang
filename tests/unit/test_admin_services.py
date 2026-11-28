import csv
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO, StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from app.database import CaseInsensitiveRecord
from app.services.attribute_service import AttributeService
from app.services.customer_service import CustomerService
from app.services.feedback_service import FeedbackService
from app.services.main_service import MainService
from app.services.media_service import MediaService
from app.services.report_service import ReportService
from app.validation import ValidationError


def record(**values):
    return CaseInsensitiveRecord(values)


@pytest.mark.parametrize(
    'start,end,group',
    [
        ('bad', '2026-01-31', 'day'),
        ('2026-01-01', '2026-02-30', 'day'),
        ('2026-02-01', '2026-01-31', 'day'),
        ('2026-01-01', '9999-12-31', 'day'),
        ('2026-01-01', '2026-01-31', 'hour'),
    ],
)
def test_report_invalid_filters_never_query(fake_db, start, end, group):
    with pytest.raises(ValidationError):
        ReportService.get_revenue_report(start, end, group)
    fake_db.connection.cursor.assert_not_called()


def test_report_all_revenue_queries_delivered_and_end_day_inclusive(fake_db):
    fake_db.cursor.fetchall.side_effect = [
        [
            record(OrderDate=date(2026, 1, 31), DailyRevenue=Decimal('0.10'), OrderCount=1),
            record(OrderDate=date(2026, 1, 31), DailyRevenue=Decimal('0.20'), OrderCount=2),
        ],
        [],
        [],
    ]
    fake_db.cursor.fetchone.return_value = (4,)
    result = ReportService.get_revenue_report('2026-01-01', '2026-01-31', 'day')
    assert result['daily_revenue'][0].DailyRevenue == Decimal('0.30')
    assert result['daily_revenue'][0].OrderCount == 3
    assert result['new_customers_range'] == 4
    for call in fake_db.cursor.execute.call_args_list[:3]:
        sql, params = call.args
        assert "o.Status = 'Delivered'" in sql
        assert 'o.OrderDate >= %s AND o.OrderDate < %s' in sql
        assert params == (date(2026, 1, 1), date(2026, 2, 1))
    fake_db.connection.close.assert_called_once()


def test_report_week_uses_iso_monday_and_exact_decimal():
    rows = [
        record(OrderDate=date(2020, 12, 31), DailyRevenue=Decimal('0.10'), OrderCount=1),
        record(OrderDate=date(2021, 1, 1), DailyRevenue=Decimal('0.20'), OrderCount=1),
    ]
    result = ReportService._group_revenue(rows, 'week')
    assert len(result) == 1
    assert result[0].OrderDate == date(2020, 12, 28)
    assert result[0].DailyRevenue == Decimal('0.30')
    assert result[0].OrderCount == 2


@pytest.mark.parametrize(
    'validator,value',
    [
        (ReportService.validate_report_type, []),
        (ReportService.validate_report_type, {}),
        (ReportService.validate_group, []),
        (ReportService.validate_group, {}),
    ],
)
def test_report_filter_types_raise_validation_not_programming_error(validator, value):
    with pytest.raises(ValidationError):
        validator(value)


def test_empty_report_earliest_calendar_date_is_valid(fake_db):
    fake_db.cursor.fetchone.side_effect = [(None,), (0,)]
    fake_db.cursor.fetchall.return_value = []
    report = ReportService.get_revenue_report(None, '0001-01-01')
    assert report['daily_revenue'] == []
    assert report['start_date'] == '0001-01-01'
    assert report['end_date'] == '0001-01-01'


@pytest.mark.parametrize('value', ['=SUM(1,2)', '+1', '-cmd', '@SUM(A1)', '  =1', '\t=1', '\n=1', '\ufeff@1'])
def test_csv_formula_text_is_neutralized(value):
    assert ReportService._csv_cell(value) == "'" + value


def test_csv_one_bom_quoting_and_exact_amount(fake_db):
    fake_db.cursor.fetchall.return_value = [
        record(ProductName='=HYPERLINK("bad"),\nshirt', TotalSold=2, TotalRevenue=Decimal('123.45'))
    ]
    contents = ReportService.generate_csv_report('best_selling', '2026-01-01', '2026-01-31')
    assert contents.startswith(b'\xef\xbb\xbf')
    assert not contents[3:].startswith(b'\xef\xbb\xbf')
    rows = list(csv.reader(StringIO(contents.decode('utf-8-sig'))))
    assert rows[1] == ['\'=HYPERLINK("bad"),\nshirt', '2', '123.45']
    sql, params = fake_db.cursor.execute.call_args.args
    assert "Status = 'Delivered'" in sql
    assert params[1] == date(2026, 2, 1)


def test_unknown_csv_type_does_not_emit_fake_empty_export(fake_db):
    with pytest.raises(ValidationError):
        ReportService.generate_csv_report('xlsx', '2026-01-01', '2026-01-31')
    fake_db.connection.cursor.assert_not_called()


@pytest.mark.parametrize(
    'name,email,subject,message',
    [
        (' ', 'one@example.test', None, 'message'),
        ('name', 'x@y.z trailing', None, 'message'),
        ('name', 'x@y.z\r\nBcc: bad', None, 'message'),
        ('name', 'one@example.test', None, ' '),
        ('name', 'one@example.test', 'x' * 201, 'message'),
        ('name', 'one@example.test', None, 'x' * 5001),
    ],
)
def test_contact_validation_before_db(fake_db, name, email, subject, message):
    with pytest.raises(ValidationError):
        MainService.add_contact_message(name, email, subject, message)
    fake_db.connection.cursor.assert_not_called()


def test_newsletter_normalizes_and_atomic_duplicate_is_success(fake_db):
    fake_db.cursor.fetchone.return_value = None
    result = MainService.subscribe_newsletter('  ONE@Example.TEST  ')
    assert result['success'] is True
    assert result['message'] == 'Email đã đăng ký'
    sql, params = fake_db.cursor.execute.call_args.args
    assert 'ON CONFLICT DO NOTHING' in sql
    assert params == ('one@example.test',)
    assert fake_db.cursor.execute.call_count == 1
    fake_db.connection.commit.assert_called_once()


def test_health_handles_connection_failure(app, monkeypatch):
    monkeypatch.setattr(MainService, 'get_connection', Mock(side_effect=RuntimeError('secret database URL')))
    with app.app_context():
        assert MainService.check_health() is False


@pytest.mark.parametrize(
    'method,args',
    [
        (FeedbackService.add_review, (1, 2, True, 'review')),
        (FeedbackService.add_review, (1, 2, 6, 'review')),
        (FeedbackService.add_review, (1, 2, 1, ' ')),
        (FeedbackService.add_comment, (1, -2, 'comment')),
        (FeedbackService.add_comment, (1, 2, ' ')),
        (FeedbackService.admin_reply_comment, (0, 'reply')),
        (FeedbackService.toggle_comment_visibility, (1, 'false')),
        (FeedbackService.toggle_comment_visibility, (1, 2)),
        (FeedbackService.get_admin_comments, ('unknown', 1, 20)),
        (FeedbackService.get_admin_comments, ('', 1, 0)),
    ],
)
def test_feedback_bad_values_no_db(fake_db, method, args):
    with pytest.raises(ValidationError):
        method(*args)
    fake_db.connection.cursor.assert_not_called()


def test_review_missing_product_rolls_back_without_write(fake_db):
    fake_db.cursor.fetchone.side_effect = [record(FullName='Customer'), None]
    result = FeedbackService.add_review(1, 999, 5, 'review')
    assert result['status_code'] == 404
    assert not any(
        'INSERT' in call.args[0] or 'UPDATE Reviews' in call.args[0] for call in fake_db.cursor.execute.call_args_list
    )
    fake_db.connection.rollback.assert_called_once()
    fake_db.connection.commit.assert_not_called()


def test_comment_moderation_updates_comments_not_reviews(fake_db):
    fake_db.cursor.fetchone.return_value = record(CommentID=1, ReplyDate=datetime(2026, 1, 1, 12))
    result = FeedbackService.admin_reply_comment(1, ' reply ')
    assert result['reply'] == 'reply'
    sql, params = fake_db.cursor.execute.call_args.args
    assert 'UPDATE ProductComments' in sql
    assert 'Reviews' not in sql
    assert params == ('reply', 1)


def test_missing_contact_status_update_is_not_success(fake_db):
    fake_db.cursor.fetchone.return_value = None
    result = MainService.update_contact_message_status(999, 'Answered')
    assert result['success'] is False
    assert result['status_code'] == 404
    fake_db.connection.commit.assert_not_called()


def test_customer_self_and_admin_deletion_rejected(fake_db):
    assert CustomerService.delete_customer(2, actor_id=2)['status_code'] == 409
    fake_db.connection.cursor.assert_not_called()
    fake_db.cursor.fetchone.return_value = record(CustomerID=2, IsAdmin=True)
    assert CustomerService.delete_customer(2, actor_id=1)['status_code'] == 409
    fake_db.connection.commit.assert_not_called()


def test_customer_history_is_conservative_no_cascade(fake_db):
    fake_db.cursor.fetchone.side_effect = [record(CustomerID=3, IsAdmin=False), (True,)]
    assert CustomerService.delete_customer(3, actor_id=2)['status_code'] == 409
    sql = fake_db.cursor.execute.call_args.args[0]
    for table in (
        'Orders',
        'Reviews',
        'ProductComments',
        'Messages',
        'Participants',
        'Conversations',
        'Reactions',
        'PinnedMessages',
    ):
        assert table in sql
    assert not any('DELETE' in call.args[0] for call in fake_db.cursor.execute.call_args_list)


def test_customer_spending_only_delivered_and_canonical_total(fake_db):
    fake_db.cursor.fetchone.return_value = record(CustomerID=1)
    fake_db.cursor.fetchall.side_effect = [
        [
            record(Status='Delivered', TotalAmount=Decimal('0.10')),
            record(Status='Delivered', TotalAmount=Decimal('0.20')),
            record(Status='Cancelled', TotalAmount=Decimal('900.00')),
        ],
        [],
    ]
    result = CustomerService.get_customer_details(1)
    assert result['stats'] == {'totalorders': 3, 'deliveredorders': 2, 'totalspent': Decimal('0.30')}
    assert 'AS TotalAmount' not in fake_db.cursor.execute.call_args_list[1].args[0]


@pytest.mark.parametrize(
    'method,args',
    [
        (AttributeService.add_color, (' ',)),
        (AttributeService.add_size, ('x' * 51,)),
        (AttributeService.delete_color, (0,)),
        (CustomerService.search_customers, ('', 'all', 1, 0)),
        (CustomerService.search_customers, ('', 'staff', 1, 20)),
    ],
)
def test_admin_service_validation_bounds(fake_db, method, args):
    with pytest.raises(ValidationError):
        method(*args)
    fake_db.connection.cursor.assert_not_called()


def test_attribute_in_use_is_not_deleted(fake_db):
    fake_db.cursor.fetchone.side_effect = [record(ColorID=1), (1,)]
    result = AttributeService.delete_color(1)
    assert result['status_code'] == 409
    assert not any('DELETE' in call.args[0] for call in fake_db.cursor.execute.call_args_list)


def test_pixabay_disabled_in_tests_even_with_key(app, fake_db, monkeypatch):
    outbound = Mock(side_effect=AssertionError('outbound prohibited'))
    monkeypatch.setattr('app.services.media_service.requests.get', outbound)
    app.config['PIXABAY_API_KEY'] = 'test-secret'
    with app.app_context():
        assert MediaService.search_pixabay('shirts')['status_code'] == 503
        assert MediaService.save_pixabay_image('https://cdn.pixabay.com/photo.jpg', 1)['status_code'] == 503
    outbound.assert_not_called()
    fake_db.connection.cursor.assert_not_called()


@pytest.mark.parametrize(
    'url,product',
    [
        ('http://cdn.pixabay.com/photo.jpg', 1),
        ('https://127.0.0.1/image.jpg', 1),
        ('https://cdn.pixabay.com.evil.test/a.jpg', 1),
        ('https://user:pass@cdn.pixabay.com/a.jpg', 1),
        ('https://cdn.pixabay.com:444/a.jpg', 1),
        ('file:///private', 1),
        ('https://cdn.pixabay.com/a.jpg', '../outside'),
    ],
)
def test_pixabay_unsafe_input_never_outbound(app, fake_db, monkeypatch, url, product):
    outbound = Mock()
    monkeypatch.setattr('app.services.media_service.requests.get', outbound)
    with app.app_context(), pytest.raises(ValidationError):
        MediaService.save_pixabay_image(url, product)
    outbound.assert_not_called()
    fake_db.connection.cursor.assert_not_called()


def test_pixabay_download_reencodes_and_never_overwrites(app, fake_db, tmp_path, monkeypatch):
    source = BytesIO()
    Image.new('RGB', (2, 2), 'red').save(source, 'PNG')
    response = SimpleNamespace(
        status_code=200,
        headers={'Content-Type': 'image/png'},
        iter_content=lambda chunk_size: [source.getvalue()],
        close=Mock(),
    )
    outbound = Mock(return_value=response)
    monkeypatch.setattr('app.services.media_service.requests.get', outbound)
    monkeypatch.setattr(app, 'static_folder', str(tmp_path))
    app.testing = False
    app.config['PIXABAY_API_KEY'] = 'test-key-not-sent'
    original = tmp_path / 'images' / '1.jpg'
    original.parent.mkdir()
    original.write_bytes(b'original')
    fake_db.cursor.fetchone.return_value = record(ProductID=1)
    with app.app_context():
        result = MediaService.save_pixabay_image('https://cdn.pixabay.com/photo.jpg', 1)
    assert result['success'] is True
    assert original.read_bytes() == b'original'
    product_directory = tmp_path / 'uploads' / 'products'
    with Image.open(product_directory / result['path'].removeprefix('images/')) as saved:
        assert saved.format == 'JPEG'
    assert outbound.call_args.kwargs['allow_redirects'] is False
    assert outbound.call_args.kwargs['stream'] is True
    response.close.assert_called_once()
    assert not list(product_directory.glob('.pixabay-*'))
