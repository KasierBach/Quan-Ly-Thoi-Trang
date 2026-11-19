from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.config import database_urls, env_bool, validate_config
from app.database import CaseInsensitiveRecord, PooledConnection
from app.validation import (
    ValidationError,
    date_value,
    email_address,
    local_redirect,
    money,
    password_value,
    positive_int,
    required_text,
)


@pytest.mark.parametrize('value', [None, '', '0', '-1', '1.0', '1e3', 0, -1, True, False, {}, []])
def test_positive_int_rejects_invalid_values(value):
    with pytest.raises(ValidationError):
        positive_int(value, 'Số lượng', 20)


@pytest.mark.parametrize('value', [1, '1', '001', 20])
def test_positive_int_accepts_bounded_values(value):
    assert positive_int(value, 'Số lượng', 20) == int(value)


def test_positive_int_enforces_bound():
    with pytest.raises(ValidationError):
        positive_int(21, 'Số lượng', 20)


@pytest.mark.parametrize('value', [None, '', ' ', '\x00name', 'a' * 11, 1])
def test_required_text(value):
    with pytest.raises(ValidationError):
        required_text(value, 'Tên', 10)
    assert required_text(' abc ', 'Tên', 10) == 'abc'


@pytest.mark.parametrize('value', ['', 'a', 'a@b', 'a @b.c', 'a@b c.d', None])
def test_email_rejects_invalid(value):
    with pytest.raises(ValidationError):
        email_address(value)


def test_email_normalization():
    assert email_address(' User@Example.TEST ') == 'user@example.test'


@pytest.mark.parametrize('value', ['nan', 'Infinity', '-1', '0.001', True, {}, None, '1e20'])
def test_money_rejects_non_finite_negative_or_imprecise(value):
    with pytest.raises(ValidationError):
        money(value, 'Giá')


def test_money_keeps_exact_decimal():
    assert money('0.10', 'Giá') + money('0.20', 'Giá') == Decimal('0.30')


@pytest.mark.parametrize('value', ['', '2025-02-30', None, 'bad'])
def test_date_validation(value):
    with pytest.raises(ValidationError):
        date_value(value, 'Ngày')
    assert date_value('2025-01-01', 'Ngày').year == 2025


@pytest.mark.parametrize('value', ['', 'abc123', 'A' * 8, 'a' * 8, '1' * 8, 'a' * 129, None])
def test_password_validation(value):
    with pytest.raises(ValidationError):
        password_value(value)
    assert password_value('ValidPass123!') == 'ValidPass123!'


@pytest.mark.parametrize(
    'value', [None, 'https://evil.test', '//evil.test', '/\\evil.test', '/\nLocation:x', 'javascript:alert(1)', 'path']
)
def test_redirect_blocks_external_or_malformed(value):
    assert local_redirect(value) is None


def test_redirect_preserves_local_query():
    assert local_redirect('/checkout?buy_now=1') == '/checkout?buy_now=1'


def test_urls_use_raw_driver_and_orm_driver():
    raw, orm = database_urls('postgres://user:pass@localhost/db')
    assert raw == 'postgresql://user:pass@localhost/db'
    assert orm == 'postgresql+psycopg2://user:pass@localhost/db'
    assert database_urls(orm) == (raw, orm)
    assert database_urls(None) == (None, None)


def test_boolean_environment(monkeypatch):
    monkeypatch.delenv('TEST_BOOL', raising=False)
    assert env_bool('TEST_BOOL', True)
    monkeypatch.setenv('TEST_BOOL', 'false')
    assert not env_bool('TEST_BOOL', True)
    monkeypatch.setenv('TEST_BOOL', 'nonsense')
    with pytest.raises(ValueError):
        env_bool('TEST_BOOL')


def test_config_fails_closed():
    with pytest.raises(ValueError, match='SECRET_KEY'):
        validate_config({'SECRET_KEY': 'fashion_store_secret_key'})
    with pytest.raises(ValueError, match='DATABASE_URL'):
        validate_config({'SECRET_KEY': 'x' * 32})


def test_record_supports_case_and_indices():
    record = CaseInsensitiveRecord(ProductID=1, Name='Áo')
    assert record.productid == record['PRODUCTID'] == record[0] == 1
    assert record.get('missing', 4) == 4
    record.Other = 2
    assert record['other'] == 2
    with pytest.raises(AttributeError):
        _ = record.Missing


def test_pooled_close_rolls_back_and_only_returns_once():
    pool, conn = MagicMock(), MagicMock()
    conn.closed = False
    conn.get_transaction_status.return_value = 2
    wrapped = PooledConnection(pool, conn)
    wrapped.close()
    wrapped.close()
    conn.rollback.assert_called_once()
    pool.putconn.assert_called_once_with(conn, close=False)


def test_closed_pool_connection_discarded():
    pool, conn = MagicMock(), MagicMock()
    conn.closed = True
    with PooledConnection(pool, conn):
        pass
    pool.putconn.assert_called_once_with(conn, close=True)
    conn.rollback.assert_not_called()
