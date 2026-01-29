"""
Simple in-memory cache for Flask application.
Provides caching for expensive database queries without external dependencies.
"""
import time
from functools import wraps

class SimpleCache:
    def __init__(self, default_timeout=300):
        self._cache = {}
        self.default_timeout = default_timeout
    
    def get(self, key):
        if key in self._cache:
            value, expiry = self._cache[key]
            if expiry > time.time():
                return value
            else:
                del self._cache[key]
        return None
    
    def set(self, key, value, timeout=None):
        if timeout is None:
            timeout = self.default_timeout
        self._cache[key] = (value, time.time() + timeout)
    
    def delete(self, key):
        if key in self._cache:
            del self._cache[key]
    
    def clear(self):
        self._cache.clear()

# Global cache instance
cache = SimpleCache(default_timeout=300)  # 5 minutes default

def cached(timeout=300, key_prefix=''):
    """Decorator to cache function results"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Create cache key from function name and arguments
            cache_key = f"{key_prefix}{f.__name__}:{str(args)}:{str(kwargs)}"
            
            # Try to get from cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Execute function and cache result
            result = f(*args, **kwargs)
            cache.set(cache_key, result, timeout)
            return result
        return decorated_function
    return decorator

def invalidate_cache(pattern=''):
    """Invalidate cache entries matching pattern"""
    if not pattern:
        cache.clear()
    else:
        keys_to_delete = [k for k in cache._cache.keys() if pattern in k]
        for key in keys_to_delete:
            cache.delete(key)
