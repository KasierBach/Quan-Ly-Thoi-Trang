import threading
import time
from collections import OrderedDict
from functools import wraps

from flask import current_app, has_app_context


class SimpleCache:
    def __init__(self, default_timeout=300, max_entries=256):
        self._cache = OrderedDict()
        self.default_timeout = default_timeout
        self.max_entries = max_entries
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                return None
            value, expiry = item
            if expiry <= time.monotonic():
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return value

    def set(self, key, value, timeout=None):
        timeout = self.default_timeout if timeout is None else timeout
        with self._lock:
            self._cache[key] = (value, time.monotonic() + timeout)
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)

    def delete(self, key):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def invalidate(self, pattern):
        with self._lock:
            for key in list(self._cache):
                if pattern in key:
                    del self._cache[key]


cache = SimpleCache()


def app_cache():
    if has_app_context():
        return current_app.extensions.setdefault('query_cache', SimpleCache())
    return cache


def cached(timeout=300, key_prefix=''):
    def decorator(func):
        @wraps(func)
        def decorated(*args, **kwargs):
            store = app_cache()
            key = f'{key_prefix}{func.__module__}.{func.__name__}:{args!r}:{sorted(kwargs.items())!r}'
            result = store.get(key)
            if result is not None:
                return result
            result = func(*args, **kwargs)
            store.set(key, result, timeout)
            return result

        return decorated

    return decorator


def invalidate_cache(pattern=''):
    store = app_cache()
    if pattern:
        store.invalidate(pattern)
    else:
        store.clear()
