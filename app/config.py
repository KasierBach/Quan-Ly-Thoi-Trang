import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized not in {'true', 'false', '1', '0', 'yes', 'no'}:
        raise ValueError(f'{name} must be a boolean')
    return normalized in {'true', '1', 'yes'}


def database_urls(value):
    if not value:
        return None, None
    if value.startswith('postgres://'):
        value = value.replace('postgres://', 'postgresql://', 1)
    if value.startswith('postgresql+psycopg2://'):
        value = value.replace('postgresql+psycopg2://', 'postgresql://', 1)
    return value, value.replace('postgresql://', 'postgresql+psycopg2://', 1)


class Config:
    TESTING = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_REFRESH_EACH_REQUEST = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    MAX_FORM_MEMORY_SIZE = 1024 * 1024
    MAX_FORM_PARTS = 100
    DB_POOL_ENABLED = True
    DB_CONNECT_ENABLED = True
    DB_POOL_MIN = 1
    DB_POOL_MAX = 10
    DB_CONNECT_TIMEOUT = 5
    SESSION_REVALIDATION_ENABLED = True
    RATELIMIT_DEFAULT = '300 per minute'
    RATELIMIT_STORAGE_URI = 'memory://'
    MAIL_SUPPRESS_SEND = False
    PIXABAY_ENDPOINT = 'https://pixabay.com/api/'

    @classmethod
    def from_environment(cls):
        # Read only this worktree's optional file, never a parent's .env.
        if not env_bool('DISABLE_DOTENV', False):
            load_dotenv(Path(__file__).resolve().parents[1] / '.env')
        environment = os.environ.get('APP_ENV', os.environ.get('FLASK_ENV', 'development'))
        if environment not in {'development', 'production', 'testing'}:
            raise ValueError('APP_ENV must be development, production or testing')
        raw_url, sqlalchemy_url = database_urls(os.environ.get('DATABASE_URL'))
        return {
            'APP_ENV': environment,
            'SECRET_KEY': os.environ.get('SECRET_KEY'),
            'DATABASE_URL': raw_url,
            'SQLALCHEMY_DATABASE_URI': sqlalchemy_url,
            'SESSION_COOKIE_SECURE': environment == 'production',
            'TRUSTED_PROXY_COUNT': int(os.environ.get('TRUSTED_PROXY_COUNT', '0')),
            'TRUSTED_HOSTS': [
                host.strip()
                for host in os.environ.get('TRUSTED_HOSTS', 'localhost,127.0.0.1').split(',')
                if host.strip()
            ],
            'ALLOWED_ORIGINS': [
                origin.strip() for origin in os.environ.get('ALLOWED_ORIGINS', '').split(',') if origin.strip()
            ]
            or None,
            'RATELIMIT_STORAGE_URI': os.environ.get('RATELIMIT_STORAGE_URI', 'memory://'),
            'MAIL_SERVER': os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
            'MAIL_PORT': int(os.environ.get('MAIL_PORT', '465')),
            'MAIL_USERNAME': os.environ.get('MAIL_USERNAME'),
            'MAIL_PASSWORD': os.environ.get('MAIL_PASSWORD'),
            'MAIL_USE_TLS': env_bool('MAIL_USE_TLS', False),
            'MAIL_USE_SSL': env_bool('MAIL_USE_SSL', True),
            'MAIL_DEFAULT_SENDER': os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME'),
            'MAIL_SUPPRESS_SEND': env_bool('MAIL_SUPPRESS_SEND', False),
            'PIXABAY_API_KEY': os.environ.get('PIXABAY_API_KEY'),
            'CONTACT_EMAIL': os.environ.get('CONTACT_EMAIL'),
            'CONTACT_PHONE': os.environ.get('CONTACT_PHONE'),
            'CONTACT_ADDRESS': os.environ.get('CONTACT_ADDRESS'),
            'PUBLIC_BASE_URL': os.environ.get('PUBLIC_BASE_URL'),
        }


def validate_config(config):
    secret = config.get('SECRET_KEY')
    if not secret or len(secret) < 32:
        raise ValueError('SECRET_KEY must be an independently generated value of at least 32 characters')
    dsn = config.get('DATABASE_URL')
    if config.get('DB_CONNECT_ENABLED', True):
        if not dsn or urlsplit(dsn).scheme != 'postgresql':
            raise ValueError('DATABASE_URL must be a PostgreSQL URL')
    if config.get('MAIL_USE_TLS') and config.get('MAIL_USE_SSL'):
        raise ValueError('MAIL_USE_TLS and MAIL_USE_SSL cannot both be enabled')
    proxy_count = config.get('TRUSTED_PROXY_COUNT', 0)
    if isinstance(proxy_count, bool) or proxy_count not in {0, 1}:
        raise ValueError('TRUSTED_PROXY_COUNT must be 0 or 1')
    if config.get('APP_ENV') == 'production':
        if not config.get('SESSION_COOKIE_SECURE'):
            raise ValueError('Production requires secure session cookies')
        if not config.get('TRUSTED_HOSTS'):
            raise ValueError('Production requires an explicit TRUSTED_HOSTS allowlist')
        base_url = config.get('PUBLIC_BASE_URL')
        if not base_url or urlsplit(base_url).scheme != 'https':
            raise ValueError('Production requires an HTTPS PUBLIC_BASE_URL for reset emails')
        if config.get('RATELIMIT_ENABLED', True) and config.get('RATELIMIT_STORAGE_URI') == 'memory://':
            raise ValueError('Production requires a shared rate-limit storage URI')
