"""OAuth provider protocol and transactional identity boundaries.

Only Authlib validates/exchanges provider credentials. No provider token is stored
in a customer, identity, cookie, or application log. Temporary PKCE material is
kept server-side until a one-use, session-bound callback consumes it.
"""

import hashlib
import logging
import math
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import psycopg2
from authlib.integrations.flask_client import OAuth
from flask import current_app
from psycopg2.extras import Json
from werkzeug.security import check_password_hash

from app.services.base_service import BaseService
from app.validation import email_address, positive_int, required_text


class OAuthFailure(ValueError):
    """A deliberately public-safe authentication failure."""


class OAuthUnavailable(OAuthFailure):
    pass


class OAuthAccountConflict(OAuthFailure):
    pass


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    issuer: str
    options: dict


PROVIDERS = {
    'google': Provider(
        'google',
        'Google',
        'https://accounts.google.com',
        {
            'server_metadata_url': 'https://accounts.google.com/.well-known/openid-configuration',
            'client_kwargs': {'scope': 'openid email profile', 'code_challenge_method': 'S256'},
        },
    ),
    'github': Provider(
        'github',
        'GitHub',
        'https://github.com',
        {
            'authorize_url': 'https://github.com/login/oauth/authorize',
            'access_token_url': 'https://github.com/login/oauth/access_token',
            'api_base_url': 'https://api.github.com/',
            'client_kwargs': {
                'scope': 'read:user user:email',
                'code_challenge_method': 'S256',
                'token_endpoint_auth_method': 'client_secret_post',
            },
        },
    ),
}


@dataclass(frozen=True)
class VerifiedIdentity:
    provider: str
    issuer: str
    subject: str
    email: str
    name: str

    def __post_init__(self):
        spec = PROVIDERS.get(self.provider)
        if spec is None or self.issuer != spec.issuer:
            raise OAuthFailure('Nhà cung cấp đăng nhập không hợp lệ.')
        required_text(self.subject, 'Định danh', 255)
        object.__setattr__(self, 'email', email_address(self.email))
        object.__setattr__(self, 'name', required_text(self.name, 'Họ tên', 255))


def callback_base_url(config):
    """Never derive callback destinations from Host/X-Forwarded-Host."""
    value = config.get('PUBLIC_BASE_URL')
    if not isinstance(value, str) or any(ord(char) <= 32 for char in value) or '\\' in value:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {'', '/'}
        or parsed.query
        or parsed.fragment
        or port == 0
    ):
        return None
    local_http = (
        config.get('APP_ENV') in {'development', 'testing'}
        and parsed.scheme == 'http'
        and parsed.hostname in {'localhost', '127.0.0.1', '::1'}
    )
    if parsed.scheme != 'https' and not local_http:
        return None
    return f'{parsed.scheme}://{parsed.netloc}'


class _PKCEDiagnosticFilter(logging.Filter):
    def filter(self, record):
        if record.levelno == logging.DEBUG and record.getMessage().startswith('Using code_verifier: '):
            record.msg, record.args = 'OAuth PKCE authorization prepared (verifier redacted)', ()
        return True


class ProviderRegistry:
    """Fixed provider allowlist; registering clients does not contact providers."""

    def __init__(self, app):
        logger = logging.getLogger('authlib.integrations.base_client.sync_app')
        if not any(isinstance(item, _PKCEDiagnosticFilter) for item in logger.filters):
            logger.addFilter(_PKCEDiagnosticFilter())
        self.oauth = OAuth(app)
        self.clients = {}
        self.config = app.config
        for name, spec in PROVIDERS.items():
            prefix = f'OAUTH_{name.upper()}'
            client_id = app.config.get(f'{prefix}_CLIENT_ID')
            client_secret = app.config.get(f'{prefix}_CLIENT_SECRET')
            if not self._configured(client_id, client_secret):
                continue
            options = {**spec.options, 'client_kwargs': dict(spec.options['client_kwargs'])}
            options['client_kwargs']['default_timeout'] = app.config['OAUTH_HTTP_TIMEOUT']
            self.clients[name] = self.oauth.register(name, client_id=client_id, client_secret=client_secret, **options)

    def _configured(self, client_id, client_secret):
        return bool(
            self.config.get('OAUTH_ENABLED', True)
            and isinstance(client_id, str)
            and client_id.strip()
            and isinstance(client_secret, str)
            and client_secret.strip()
            and callback_base_url(self.config)
        )

    def available(self, name):
        return name in self.clients and bool(callback_base_url(self.config))

    def client(self, name):
        if not self.available(name):
            raise OAuthUnavailable('Đăng nhập bằng nhà cung cấp này chưa được cấu hình.')
        return self.clients[name]

    def choices(self):
        return [
            dict(name=spec.name, label=spec.label, enabled=self.available(spec.name)) for spec in PROVIDERS.values()
        ]

    def callback_url(self, name):
        self.client(name)
        return f'{callback_base_url(self.config)}/oauth/{name}/callback'

    def authorize(self, name, flow, *, next_page=None):
        client = self.client(name)
        options = {'state': flow['state']}
        if name == 'google':
            options['nonce'] = flow['nonce']
            options['prompt'] = 'select_account'
        if flow['intent'] == 'reauth':
            options['max_age'] = 0
        result = client.create_authorization_url(self.callback_url(name), **options)
        if result.get('state') != flow['state'] or not result.get('code_verifier'):
            raise OAuthFailure('Không thể khởi tạo phiên đăng nhập an toàn.')
        # Authlib's temporary data normally lives in a readable signed cookie.
        # Keep callback data and the optional return path in the server ledger.
        data = {'redirect_uri': self.callback_url(name), 'code_verifier': result['code_verifier']}
        if name == 'google':
            data['nonce'] = flow['nonce']
        if next_page is not None:
            data['next_page'] = next_page
        OAuthService.issue_ticket(flow['state'], flow['binding'], 'authorization', data)
        return result['url']

    def exchange(self, name, flow, data):
        client = self.client(name)
        client.save_authorize_data(state=flow['state'], **data)
        try:
            if name == 'google':
                return self._google_identity(client, flow)
            return self._github_identity(client)
        finally:
            # Also clear Authlib data on provider denial, malformed JWT or I/O failure.
            from flask import session

            client.framework.clear_state_data(session, flow['state'])
            client.token = None

    def _google_identity(self, client, flow):
        claims = {'iss': {'essential': True, 'value': PROVIDERS['google'].issuer}}
        if flow['intent'] == 'reauth':
            claims['auth_time'] = {'essential': True}
        token = client.authorize_access_token(
            claims_options=claims, leeway=30, timeout=self.config['OAUTH_HTTP_TIMEOUT'], allow_redirects=False
        )
        info = token.get('userinfo')
        if not isinstance(info, dict) or info.get('email_verified') is not True:
            raise OAuthFailure('Nhà cung cấp chưa xác minh địa chỉ email của bạn.')
        if flow['intent'] == 'reauth':
            auth_time = info.get('auth_time')
            now = time.time()
            if (
                isinstance(auth_time, bool)
                or not isinstance(auth_time, (int, float))
                or not math.isfinite(auth_time)
                or auth_time < flow['issued_at'] - 30
                or auth_time > now + 30
                or now - auth_time > self.config['OAUTH_REAUTH_TTL']
            ):
                raise OAuthFailure('Cần xác thực lại với Google hoặc dùng mật khẩu hiện tại.')
        email = email_address(info.get('email'))
        return VerifiedIdentity(
            'google',
            required_text(info.get('iss'), 'Nhà cung cấp', 255),
            required_text(info.get('sub'), 'Định danh', 255),
            email,
            self._display_name(info.get('name'), email),
        )

    def _github_identity(self, client):
        token = client.authorize_access_token(timeout=self.config['OAUTH_HTTP_TIMEOUT'], allow_redirects=False)
        profile = self._github_json(client, 'user', token)
        emails = self._github_json(client, 'user/emails', token)
        if not isinstance(profile, dict) or not isinstance(emails, list):
            raise OAuthFailure('Không thể xác minh tài khoản GitHub.')
        subject = positive_int(profile.get('id'), 'Định danh')
        verified = [entry for entry in emails if isinstance(entry, dict) and entry.get('verified') is True]
        if not verified:
            raise OAuthFailure('GitHub chưa xác minh địa chỉ email của bạn.')
        primary = next((entry for entry in verified if entry.get('primary') is True), verified[0])
        email = email_address(primary.get('email'))
        return VerifiedIdentity(
            'github',
            PROVIDERS['github'].issuer,
            str(subject),
            email,
            self._display_name(profile.get('name') or profile.get('login'), email),
        )

    def _github_json(self, client, path, token):
        response = client.get(
            path,
            token=token,
            timeout=self.config['OAUTH_HTTP_TIMEOUT'],
            allow_redirects=False,
            headers={'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'},
        )
        if response.status_code != 200:
            raise OAuthFailure('Không thể xác minh tài khoản GitHub.')
        return response.json()

    @staticmethod
    def _display_name(value, email):
        if not isinstance(value, str) or not value.strip() or len(value) > 255 or '\x00' in value:
            return email.split('@', 1)[0]
        return value.strip()


USER_FIELDS = """c.CustomerID, c.FullName, c.DarkModeEnabled, c.auth_version AS AuthVersion,
                 CASE WHEN c.IsAdmin THEN 'admin' ELSE COALESCE(c.Role, 'customer') END AS Role"""


class OAuthService(BaseService):
    """Identity associations and one-use tickets, under PostgreSQL transactions."""

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    @staticmethod
    def new_ticket():
        return secrets.token_urlsafe(32)

    @staticmethod
    def issue_ticket(token, binding, purpose, data, ttl=None):
        ttl = ttl or current_app.config['OAUTH_STATE_TTL']
        conn = OAuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM OAuthStates WHERE expires_at <= CURRENT_TIMESTAMP')
                cursor.execute(
                    """INSERT INTO OAuthStates (state_digest, binding_digest, purpose, auth_data, expires_at)
                       VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'))""",
                    (OAuthService.digest(token), OAuthService.digest(binding), purpose, Json(data), ttl),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def consume_ticket(token, binding, purpose):
        conn = OAuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """DELETE FROM OAuthStates WHERE state_digest = %s AND binding_digest = %s
                       AND purpose = %s AND expires_at > CURRENT_TIMESTAMP RETURNING auth_data AS AuthData""",
                    (OAuthService.digest(token), OAuthService.digest(binding), purpose),
                )
                record = cursor.fetchone()
            conn.commit()
            if record is None:
                raise OAuthFailure('Phiên xác thực không hợp lệ hoặc đã hết hạn. Vui lòng thử lại.')
            return record.AuthData
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _find_identity(cursor, identity):
        cursor.execute(
            f"""SELECT {USER_FIELDS} FROM Customers c JOIN OAuthIdentities i ON i.customer_id = c.CustomerID
                WHERE i.provider = %s AND i.issuer = %s AND i.subject = %s""",
            (identity.provider, identity.issuer, identity.subject),
        )
        return cursor.fetchone()

    @staticmethod
    def _locked_user(cursor, user_id, auth_version):
        cursor.execute(
            f'SELECT {USER_FIELDS}, c.Password FROM Customers c WHERE c.CustomerID = %s FOR UPDATE',
            (positive_int(user_id, 'Tài khoản'),),
        )
        user = cursor.fetchone()
        if user is None or user.AuthVersion != auth_version:
            raise OAuthFailure('Phiên đăng nhập đã thay đổi. Vui lòng đăng nhập lại.')
        return user

    @staticmethod
    def _insert_identity(cursor, user_id, identity):
        cursor.execute(
            """INSERT INTO OAuthIdentities (customer_id, provider, issuer, subject, email, email_verified)
               VALUES (%s, %s, %s, %s, %s, TRUE)""",
            (user_id, identity.provider, identity.issuer, identity.subject, identity.email),
        )

    @staticmethod
    def login_or_register(identity):
        conn = OAuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                user = OAuthService._find_identity(cursor, identity)
                if user is not None:
                    return user
                cursor.execute('SELECT CustomerID FROM Customers WHERE LOWER(Email) = %s', (identity.email,))
                if cursor.fetchone() is not None:
                    raise OAuthAccountConflict(
                        'Email đã có tài khoản. Hãy đăng nhập bằng mật khẩu rồi liên kết nhà cung cấp.'
                    )
                cursor.execute(
                    f"""INSERT INTO Customers AS c (FullName, Email, Password, IsAdmin, Role)
                        VALUES (%s, %s, NULL, FALSE, 'customer') RETURNING {USER_FIELDS}""",
                    (identity.name, identity.email),
                )
                user = cursor.fetchone()
                OAuthService._insert_identity(cursor, user.CustomerID, identity)
            conn.commit()
            return user
        except psycopg2.IntegrityError:
            # A racing subject insert can only log into the exact same identity.
            # A racing email insert is NOT authority to associate that account.
            conn.rollback()
            with conn.cursor() as cursor:
                winner = OAuthService._find_identity(cursor, identity)
            if winner is not None:
                return winner
            raise OAuthAccountConflict(
                'Email đã có tài khoản. Hãy đăng nhập bằng mật khẩu rồi liên kết nhà cung cấp.'
            ) from None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def reauthenticate_password(user_id, auth_version, password):
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            return False
        conn = OAuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                user = OAuthService._locked_user(cursor, user_id, auth_version)
                if not isinstance(user.Password, str) or not user.Password:
                    return False
                return check_password_hash(user.Password, password)
        finally:
            conn.rollback()
            conn.close()

    @staticmethod
    def reauthenticate_identity(identity, user_id, auth_version):
        conn = OAuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                OAuthService._locked_user(cursor, user_id, auth_version)
                owner = OAuthService._find_identity(cursor, identity)
                if owner is None or owner.CustomerID != user_id:
                    raise OAuthFailure('Cần xác thực bằng Google đã liên kết với tài khoản hiện tại.')
        finally:
            conn.rollback()
            conn.close()

    @staticmethod
    def link_identity(identity, user_id, auth_version):
        conn = OAuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                OAuthService._locked_user(cursor, user_id, auth_version)
                owner = OAuthService._find_identity(cursor, identity)
                if owner is not None:
                    raise OAuthAccountConflict(
                        'Nhà cung cấp đã được liên kết. Không thể chuyển liên kết giữa tài khoản.'
                    )
                OAuthService._insert_identity(cursor, user_id, identity)
                version = OAuthService._bump_version(cursor, user_id)
            conn.commit()
            return version
        except psycopg2.IntegrityError:
            conn.rollback()
            raise OAuthAccountConflict('Nhà cung cấp đã được liên kết với một tài khoản.') from None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def unlink_identity(provider, user_id, auth_version):
        if provider not in PROVIDERS:
            raise OAuthFailure('Nhà cung cấp không hợp lệ.')
        conn = OAuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                user = OAuthService._locked_user(cursor, user_id, auth_version)
                cursor.execute('SELECT provider FROM OAuthIdentities WHERE customer_id = %s', (user_id,))
                identities = cursor.fetchall()
                if not any(item.provider == provider for item in identities):
                    raise OAuthFailure('Nhà cung cấp chưa được liên kết với tài khoản này.')
                if not user.Password and len(identities) <= 1:
                    raise OAuthFailure('Không thể gỡ cách đăng nhập cuối cùng. Hãy thiết lập mật khẩu trước.')
                cursor.execute(
                    'DELETE FROM OAuthIdentities WHERE customer_id = %s AND provider = %s', (user_id, provider)
                )
                version = OAuthService._bump_version(cursor, user_id)
            conn.commit()
            return version
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _bump_version(cursor, user_id):
        cursor.execute(
            """UPDATE Customers SET auth_version = auth_version + 1 WHERE CustomerID = %s
                          RETURNING auth_version AS AuthVersion""",
            (user_id,),
        )
        return cursor.fetchone().AuthVersion

    @staticmethod
    def list_identities(user_id):
        conn = OAuthService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT provider, email FROM OAuthIdentities WHERE customer_id = %s ORDER BY provider',
                    (positive_int(user_id, 'Tài khoản'),),
                )
                return cursor.fetchall()
        finally:
            conn.close()
