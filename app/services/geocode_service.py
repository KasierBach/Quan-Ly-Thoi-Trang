"""Opt-in, address-only geocoding; never a live courier/tracking service.

Public Nominatim forbids personal/confidential data. Network access additionally
requires an informed operator opt-in for public addresses only. Local fixtures
can populate the positive cache without enabling any network access.
"""

import hashlib
import math
import re
import threading
import time
import unicodedata
from urllib.parse import urlsplit

import requests
from flask import current_app

from app.cache import SimpleCache


class GeocodeError(Exception):
    def __init__(self, message, status_code=503, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class GeocodeService:
    NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
    CACHE_TTL_SECONDS = 12 * 60 * 60
    CACHE_MAX_ENTRIES = 256
    REQUEST_TIMEOUT = (3, 5)
    _provider_lock = threading.Lock()
    _next_request_at = 0.0

    @staticmethod
    def _safe_header(value, max_length):
        return (
            isinstance(value, str)
            and 0 < len(value) <= max_length
            and value == value.strip()
            and all(32 <= ord(char) < 127 for char in value)
        )

    @classmethod
    def is_configured(cls):
        config = current_app.config
        agent = config.get('GEOCODE_USER_AGENT')
        contact = config.get('GEOCODE_CONTACT')
        if config.get('GEOCODE_ENABLED') is not True:
            return False
        if (
            not isinstance(agent, str)
            or not cls._safe_header(agent, 160)
            or not re.fullmatch(r'[A-Za-z][\w.-]*/[0-9][\w.-]*', agent)
        ):
            return False
        if agent.split('/', 1)[0].casefold() in {'python-requests', 'requests', 'curl', 'mozilla', 'node', 'urllib'}:
            return False
        if not isinstance(contact, str) or not cls._safe_header(contact, 254):
            return False
        if re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', contact):
            host = contact.rsplit('@', 1)[1].casefold()
        else:
            try:
                parsed = urlsplit(contact)
                if (
                    parsed.scheme != 'https'
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                    or parsed.port not in (None, 443)
                ):
                    return False
                host = parsed.hostname.casefold()
            except ValueError:
                return False
        if not current_app.testing and (
            '.' not in host
            or host.endswith(('.test', '.invalid', '.localhost'))
            or host in {'example.com', 'example.org', 'example.net', 'localhost'}
            or host.endswith(('.example.com', '.example.org', '.example.net'))
        ):
            return False
        return True

    @classmethod
    def network_enabled(cls):
        return (
            cls.is_configured()
            and current_app.config.get('GEOCODE_NETWORK_ENABLED') is True
            and current_app.config.get('GEOCODE_ALLOW_PUBLIC_ADDRESS_QUERIES') is True
        )

    @staticmethod
    def normalize_address(address):
        if not isinstance(address, str) or not address.strip() or len(address) > 500:
            raise GeocodeError('Địa chỉ đã lưu chưa đủ thông tin để xác định vị trí.', 422)
        normalized = ' '.join(unicodedata.normalize('NFC', address).split()).casefold()
        if not normalized or len(normalized) > 500 or any(unicodedata.category(c).startswith('C') for c in normalized):
            raise GeocodeError('Địa chỉ đã lưu chưa đủ thông tin để xác định vị trí.', 422)
        return normalized

    @classmethod
    def cache_key(cls, address):
        # Never retain/log plaintext addresses as cache keys.
        digest = hashlib.sha256(cls.normalize_address(address).encode('utf-8')).hexdigest()
        return f'shipping-geocode:{digest}'

    @classmethod
    def cache(cls):
        return current_app.extensions.setdefault(
            'shipping_geocode_cache',
            SimpleCache(default_timeout=cls.CACHE_TTL_SECONDS, max_entries=cls.CACHE_MAX_ENTRIES),
        )

    @staticmethod
    def _validated_point(value):
        if not isinstance(value, dict):
            return None
        point = {}
        for field, bound in (('lat', 90), ('lon', 180)):
            coordinate = value.get(field)
            if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
                return None
            try:
                coordinate = float(coordinate)
            except (ValueError, OverflowError):
                return None
            if not math.isfinite(coordinate) or not -bound <= coordinate <= bound:
                return None
            point[field] = coordinate
        return point

    @classmethod
    def _provider_point(cls, value):
        if not isinstance(value, dict):
            return None
        point = {}
        for field in ('lat', 'lon'):
            coordinate = value.get(field)
            if isinstance(coordinate, str):
                if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', coordinate):
                    return None
                try:
                    coordinate = float(coordinate)
                except (ValueError, OverflowError):
                    return None
            point[field] = coordinate
        return cls._validated_point(point)

    @staticmethod
    def _retry_after(response, default=60):
        value = response.headers.get('Retry-After', '')
        if isinstance(value, str) and re.fullmatch(r'[0-9]{1,4}', value):
            return max(1, min(int(value), 3600))
        return default

    @classmethod
    def geocode(cls, address):
        if not cls.is_configured():
            raise GeocodeError('Bản đồ địa chỉ chưa được bật hoặc chưa được cấu hình đầy đủ.')
        normalized = cls.normalize_address(address)
        key = cls.cache_key(normalized)
        store = cls.cache()
        cached = store.get(key)
        point = cls._validated_point(cached)
        if point is not None:
            return point
        if cached is not None:
            store.delete(key)  # Cache reads receive the same bounds/type checks as HTTP results.
        if not cls.network_enabled():
            raise GeocodeError('Chưa có vị trí đã lưu cho địa chỉ này. Dịch vụ tra cứu bên ngoài đang tắt.')
        if not cls._provider_lock.acquire(blocking=False):
            raise GeocodeError('Dịch vụ bản đồ đang bận. Vui lòng thử lại sau.', 429, 1)
        try:
            now = time.monotonic()
            if now < cls._next_request_at:
                retry_after = max(1, math.ceil(cls._next_request_at - now))
                raise GeocodeError('Dịch vụ bản đồ đang bận. Vui lòng thử lại sau.', 429, retry_after)
            # One in-flight request per process; reject rather than queue/retry unfairly.
            cls._next_request_at = now + 1.0
            point = cls._request_point(normalized)
            store.set(key, dict(point), timeout=cls.CACHE_TTL_SECONDS)
            return point
        finally:
            cls._provider_lock.release()

    @classmethod
    def _request_point(cls, normalized):
        response = None
        try:
            response = requests.get(
                cls.NOMINATIM_URL,
                params={'q': normalized, 'format': 'jsonv2', 'limit': 1, 'addressdetails': 0},
                headers={
                    'User-Agent': f'{current_app.config["GEOCODE_USER_AGENT"]} ({current_app.config["GEOCODE_CONTACT"]})',
                    'Accept': 'application/json',
                    'Accept-Language': 'vi,en;q=0.8',
                },
                timeout=cls.REQUEST_TIMEOUT,
                allow_redirects=False,
                verify=True,
            )
            if response.status_code == 429:
                retry_after = cls._retry_after(response)
                cls._next_request_at = max(cls._next_request_at, time.monotonic() + retry_after)
                raise GeocodeError('Dịch vụ bản đồ đang giới hạn lượt xem. Vui lòng thử lại sau.', 429, retry_after)
            if response.status_code != 200:
                raise GeocodeError('Dịch vụ bản đồ tạm thời không khả dụng. Vui lòng thử lại sau.')
            payload = response.json()
            if payload == []:
                raise GeocodeError('Chưa tìm thấy vị trí phù hợp với địa chỉ đã lưu.', 404)
            if not isinstance(payload, list) or len(payload) != 1:
                raise GeocodeError('Dịch vụ bản đồ chưa trả về vị trí hợp lệ. Vui lòng thử lại sau.')
            point = cls._provider_point(payload[0])
            if point is None:
                raise GeocodeError('Dịch vụ bản đồ chưa trả về vị trí hợp lệ. Vui lòng thử lại sau.')
            # Discard provider display_name, links, metadata and raw URL fields.
            return point
        except requests.Timeout:
            raise GeocodeError('Dịch vụ bản đồ phản hồi quá chậm. Vui lòng thử lại sau.') from None
        except (requests.RequestException, ValueError):
            # Exception strings can contain q=address; never log/return them.
            raise GeocodeError('Dịch vụ bản đồ tạm thời không khả dụng. Vui lòng thử lại sau.') from None
        finally:
            if response is not None:
                response.close()
