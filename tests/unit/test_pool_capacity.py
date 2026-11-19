from unittest.mock import MagicMock

import psycopg2
from psycopg2.pool import PoolError
import pytest

from app.database import acquire_connection


def test_pool_wait_reuses_capacity_without_unbounded_new_connection(monkeypatch):
    pool = MagicMock()
    connection = object()
    pool.getconn.side_effect = [PoolError('exhausted'), connection]
    sleep = MagicMock()
    monkeypatch.setattr('app.database.time.sleep', sleep)
    assert acquire_connection(pool, 2) is connection
    assert pool.getconn.call_count == 2
    sleep.assert_called_once()


def test_pool_wait_has_bounded_timeout(monkeypatch):
    pool = MagicMock()
    pool.getconn.side_effect = PoolError('exhausted')
    monkeypatch.setattr('app.database.time.monotonic', MagicMock(side_effect=[0, 3]))
    with pytest.raises(psycopg2.OperationalError, match='capacity'):
        acquire_connection(pool, 2)
    assert pool.getconn.call_count == 1
