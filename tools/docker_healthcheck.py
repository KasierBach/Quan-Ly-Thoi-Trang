"""Probe Gunicorn directly while honoring the service's trusted public host."""

from contextlib import closing
from http.client import HTTPConnection, HTTPException
import os
from urllib.parse import urlsplit


def is_ready():
    host = urlsplit(os.environ.get('PUBLIC_BASE_URL', '')).netloc.rsplit('@', 1)[-1]
    headers = {'Host': host} if host else {}
    try:
        with closing(HTTPConnection('127.0.0.1', 4000, timeout=3)) as connection:
            connection.request('GET', '/health/ready', headers=headers)
            return connection.getresponse().status == 200
    except (OSError, HTTPException):
        return False


if __name__ == '__main__':
    raise SystemExit(0 if is_ready() else 1)
