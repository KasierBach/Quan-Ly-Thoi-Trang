"""Chat policy/validation tests. Row doubles exercise branches, not PostgreSQL SQL semantics."""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, Mock
from zipfile import ZipFile

from flask import session
from itsdangerous.timed import TimestampSigner
from PIL import Image
import psycopg2
import pytest
from werkzeug.datastructures import FileStorage

from app.database import CaseInsensitiveRecord
from app.services import attachment_storage
from app.services.attachment_service import AttachmentService
from app.services.auth_service import AuthService
from app.services.base_service import BaseService
from app.services.chat_service import ChatService
from app.services.conversation_service import (
    ChatAccess,
    ChatAccessError,
    ChatIdentity,
    ConversationService,
    conversation_settings,
    emoji_value,
    get_identity,
    issue_guest_credentials,
    participant_settings,
    refresh_identity,
)
from app.validation import ValidationError


@pytest.fixture(autouse=True)
def forbid_unplanned_database(monkeypatch):
    def refused():
        pytest.fail('A no-DB chat unit test attempted an unplanned database connection')

    monkeypatch.setattr(BaseService, 'get_connection', staticmethod(refused))


def account(uid=1, *, admin=False, version=1):
    return ChatIdentity(uid, is_admin=admin, name=f'Cookie User {uid}', auth_version=version)


def state(uid=1, *, role='customer', version=1):
    return CaseInsensitiveRecord(
        CustomerID=uid, FullName=f'Current User {uid}', Role=role, AuthVersion=version, DarkModeEnabled=False
    )


def cursor_rows(*rows):
    cursor = MagicMock()
    cursor.fetchone.side_effect = rows
    return cursor


@pytest.fixture
def guest(app):
    with app.test_request_context():
        credentials = issue_guest_credentials()
        return get_identity(credentials['auth_token'])


def test_guest_credentials_replace_legacy_untrusted_id(app):
    with app.test_request_context('/api/chat/guest-session?session_id=attacker-chosen'):
        session['chat_guest_id'] = 'attacker-chosen'
        session['chat_guest_binding'] = 'short'
        issued = issue_guest_credentials()
        assert issued['session_id'] != 'attacker-chosen'
        assert len(issued['session_id']) == 36
        assert len(session['chat_guest_binding']) >= 32
        assert issued['expires_in'] == 3600
        assert get_identity(issued['auth_token']).guest_id == issued['session_id']
        renewed = issue_guest_credentials()
        assert renewed['session_id'] == issued['session_id']
        assert get_identity(renewed['auth_token']).guest_binding == session['chat_guest_binding']


def test_signed_guest_token_ttl_boundary_and_expiry(app, monkeypatch):
    now = [1_000_000]
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: now[0])
    app.config['CHAT_GUEST_TOKEN_TTL'] = 15
    with app.test_request_context():
        issued = issue_guest_credentials()
        now[0] += 15
        assert get_identity(issued['auth_token']).guest_id == issued['session_id']
        now[0] += 1
        with pytest.raises(ChatAccessError) as error:
            get_identity(issued['auth_token'])
        assert error.value.status == 401


@pytest.mark.parametrize('change', ['signature', 'uuid', 'binding', 'missing_cookie', 'oversized'])
def test_guest_token_requires_signature_uuid_and_browser_binding(app, change):
    with app.test_request_context():
        issued = issue_guest_credentials()
        token = issued['auth_token']
        if change == 'signature':
            parts = token.rsplit('.', 1)
            parts[1] = ('A' if parts[1][0] != 'A' else 'B') + parts[1][1:]
            token = '.'.join(parts)
        elif change == 'uuid':
            session['chat_guest_id'] = '00000000-0000-0000-0000-000000000000'
        elif change == 'binding':
            session['chat_guest_binding'] = 'another-browser-binding-with-more-than-32-characters'
        elif change == 'missing_cookie':
            session.clear()
        else:
            token = 'x' * 2049
        with pytest.raises(ChatAccessError) as error:
            get_identity(token)
        assert error.value.status == 401


@pytest.mark.parametrize('token', [None, '', 'unsigned-uuid', 123, {}])
def test_unsigned_guest_identity_is_never_accepted(app, token):
    with app.test_request_context():
        with pytest.raises(ChatAccessError) as error:
            get_identity(token)
        assert error.value.status == 401


@pytest.mark.parametrize('transport', ['header', 'query', 'socket_auth'])
def test_guest_token_transports_are_bound_to_same_signed_cookie(app, transport):
    with app.test_request_context():
        issued = issue_guest_credentials()
        cookie_state = dict(session)
    token = issued['auth_token']
    headers = {'X-Chat-Token': token} if transport == 'header' else {}
    query = {'auth_token': token} if transport == 'query' else {}
    with app.test_request_context('/api/chat/history', headers=headers, query_string=query):
        session.update(cookie_state)
        actor = get_identity(token if transport == 'socket_auth' else None)
        assert actor.user_id is None
        assert actor.guest_id == issued['session_id']
        assert actor.is_admin is False


@pytest.mark.parametrize('current_role,cookie_admin', [('customer', True), ('admin', False)])
def test_current_database_role_and_name_override_cookie_claims(app, monkeypatch, current_role, cookie_admin):
    app.config['SESSION_REVALIDATION_ENABLED'] = True
    current = state(role=current_role)
    lookup = Mock(return_value=current)
    monkeypatch.setattr(AuthService, 'get_identity_state', lookup)
    with app.test_request_context():
        session.update(user_id=1, user_name='Spoofed Name', is_admin=cookie_admin, role='admin', auth_version=1)
        actor = get_identity()
        assert actor.user_id == 1
        assert actor.is_admin is (current_role == 'admin')
        assert actor.name == 'Current User 1'
    lookup.assert_called_once_with(1)


@pytest.mark.parametrize('current', [None, state(version=2)])
def test_revoked_or_missing_user_is_denied_on_identity_refresh(app, monkeypatch, current):
    app.config['SESSION_REVALIDATION_ENABLED'] = True
    monkeypatch.setattr(AuthService, 'get_identity_state', lambda uid: current)
    with app.app_context(), pytest.raises(ChatAccessError) as error:
        refresh_identity(account())
    assert error.value.status == 401


@pytest.mark.parametrize(
    'kind,role,creator,site_admin,permission,status',
    [
        ('private', None, 3, False, 'read', 403),
        ('private', None, 3, True, 'read', 403),
        ('private', None, 3, True, 'send', 403),
        ('group', None, 3, True, 'read', 403),
        ('group', None, 3, True, 'manage', 403),
        ('support', None, 3, False, 'read', 403),
        ('support', None, 3, True, 'read', None),
        ('support', None, 3, True, 'send', None),
        ('support', None, 3, True, 'manage', None),
        ('support', None, 3, True, 'pin', None),
        ('support', None, 3, True, 'read_receipt', 403),
        ('support', None, 3, True, 'call', 403),
        ('private', 'member', 3, False, 'read', None),
        ('private', 'member', 3, False, 'send', None),
        ('private', 'member', 3, False, 'read_receipt', None),
        ('private', 'member', 3, False, 'call', None),
        ('private', 'member', 3, False, 'manage', 403),
        ('private', 'member', 3, True, 'pin', 403),
        ('private', 'member', 1, False, 'pin', None),
        ('private', 'admin', 3, False, 'manage', None),
        ('group', 'admin', 3, False, 'pin', None),
        ('group', 'admin', 3, False, 'call', 409),
        ('support', 'admin', 3, True, 'call', 409),
    ],
)
def test_conversation_acl_is_membership_scoped_not_site_admin_scoped(
    app, kind, role, creator, site_admin, permission, status
):
    cursor = cursor_rows(CaseInsensitiveRecord(id=2, type=kind, created_by=creator, role=role))
    with app.app_context():
        if status is not None:
            with pytest.raises(ChatAccessError) as error:
                ConversationService.get_access(2, actor=account(admin=site_admin), permission=permission, cursor=cursor)
            assert error.value.status == status
        else:
            access = ConversationService.get_access(
                '2', actor=account(admin=site_admin), permission=permission, cursor=cursor
            )
            assert access.room == 'conv_2'
            assert access.conversation_type == kind
            assert access.role == role
            assert access.session_id is None


def test_missing_conversation_is_denied_without_exposing_existence(app):
    with app.app_context(), pytest.raises(ChatAccessError) as error:
        ConversationService.get_access(999, actor=account(admin=True), cursor=cursor_rows(None))
    assert error.value.status == 403


def test_guest_cannot_access_numeric_conversation_even_with_valid_token(app, guest):
    cursor = cursor_rows()
    with app.app_context(), pytest.raises(ChatAccessError) as error:
        ConversationService.get_access(2, actor=guest, cursor=cursor)
    assert error.value.status == 401
    cursor.execute.assert_not_called()


@pytest.mark.parametrize('permission', ['read', 'send'])
def test_guest_support_access_is_exactly_own_signed_scope(app, guest, permission):
    with app.app_context():
        own = ConversationService.get_access(session_id=guest.guest_id, actor=guest, permission=permission)
        assert own.room == f'support_{guest.guest_id}'
        assert own.conversation_id is None
        with pytest.raises(ChatAccessError) as error:
            ConversationService.get_access(
                session_id='00000000-0000-0000-0000-000000000000', actor=guest, permission=permission
            )
        assert error.value.status == 403


@pytest.mark.parametrize('permission', ['manage', 'pin', 'read_receipt', 'call'])
def test_guest_support_has_no_management_receipts_or_calls(app, guest, permission):
    with app.app_context(), pytest.raises(ChatAccessError) as error:
        ConversationService.get_access(session_id=guest.guest_id, actor=guest, permission=permission)
    assert error.value.status == 403


@pytest.mark.parametrize('content', [None, '', ' \r\n ', {}, 'x' * 4001])
def test_text_validation_rejects_empty_nontext_or_oversized_content(content):
    with pytest.raises(ValidationError):
        ChatService.validate_message(content)


@pytest.mark.parametrize(
    'url',
    [
        'http://media.giphy.com/media/abc123/giphy.gif',
        'https://media.giphy.com.evil.test/media/abc123/giphy.gif',
        'https://user:pass@media.giphy.com/media/abc123/giphy.gif',
        'https://media.giphy.com/media/abc123/giphy.gif?tracking=1',
        'https://media.giphy.com/media/abc123/giphy.gif#fragment',
        'https://cdnjs.cloudflare.com/ajax/libs/twemoji/99/72x72/1f44d.png',
        'javascript:alert(1)',
        '/static/uploads/arbitrary.png',
    ],
)
def test_stickers_are_exact_allowlisted_https_assets(url):
    with pytest.raises(ValidationError):
        ChatService.validate_message(url, 'sticker')


@pytest.mark.parametrize(
    'url',
    [
        'https://media.giphy.com/media/abc123/giphy.gif',
        'https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/1f44d.png',
    ],
)
def test_allowlisted_sticker_and_normal_text_are_accepted(url):
    assert ChatService.validate_message(url, 'sticker') == url
    assert ChatService.validate_message('  hello  ') == 'hello'


@pytest.mark.parametrize('kind', ['image', 'audio', 'video', 'file', 'html', 'system'])
def test_clients_cannot_forge_media_messages_without_private_upload(kind):
    with pytest.raises(ValidationError):
        ChatService.validate_message('https://evil.test/file', kind)


@pytest.mark.parametrize('value', ['text', '<img>', ':)', '\U0001f44d<script>', '1', None])
def test_reaction_must_be_emoji_not_html_or_text(value):
    with pytest.raises(ValidationError):
        emoji_value(value)


@pytest.mark.parametrize('value', ['\U0001f44d', '\u2764\ufe0f', '\U0001f469\u200d\U0001f4bb'])
def test_emoji_sequences_are_accepted(value):
    assert emoji_value(value) == value


@pytest.mark.parametrize(
    'value',
    [
        {},
        [],
        {'created_by': 2},
        {'theme_color': 'red'},
        {'theme_color': '#12345'},
        {'avatar_url': 'https://evil.test/avatar.jpg'},
        {'default_emoji': '<script>'},
    ],
)
def test_conversation_settings_are_validated_and_whitelisted(value):
    with pytest.raises(ValidationError):
        conversation_settings(value)


@pytest.mark.parametrize(
    'value',
    [
        {},
        {'user_id': 2},
        {'is_muted': 'false'},
        {'is_muted': 1},
        {'role': 'owner'},
        {'role': 'superadmin'},
    ],
)
def test_participant_settings_reject_mass_assignment_and_nonboolean_mute(value):
    with pytest.raises(ValidationError):
        participant_settings(value)


def test_valid_settings_preserve_literal_false_and_normalize_nickname():
    assert participant_settings({'is_muted': False, 'nickname': ''}) == {'is_muted': False, 'nickname': None}
    assert conversation_settings({'name': '  New name  ', 'theme_color': '#12aBcD'}) == {
        'name': 'New name',
        'theme_color': '#12aBcD',
    }


def message_row(*, uid=3, cid=2, sid='user_3', deleted=False, sender='user'):
    return CaseInsensitiveRecord(
        id=9, conversation_id=cid, session_id=sid, user_id=uid, sender_type=sender, is_deleted=deleted
    )


@pytest.mark.parametrize('row', [None, message_row(deleted=True)])
def test_nonexistent_or_recalled_message_is_not_readable(app, row):
    with app.app_context(), pytest.raises(ChatAccessError) as error:
        ChatService.get_message_access(9, actor=account(), cursor=cursor_rows(row))
    assert error.value.status == 404


@pytest.mark.parametrize(
    'uid,owner,kind,role,admin,status',
    [
        (3, 3, 'private', 'member', False, None),
        (1, 3, 'private', 'owner', False, 403),
        (2, 1, 'support', 'admin', True, 403),
        (2, 2, 'support', 'admin', True, None),
    ],
)
def test_only_sender_can_recall_not_conversation_owner_or_site_admin(app, uid, owner, kind, role, admin, status):
    cursor = cursor_rows(message_row(uid=owner), CaseInsensitiveRecord(id=2, type=kind, created_by=1, role=role))
    with app.app_context():
        if status:
            with pytest.raises(ChatAccessError) as error:
                ChatService.get_message_access(9, actor=account(uid, admin=admin), permission='recall', cursor=cursor)
            assert error.value.status == status
        else:
            assert (
                ChatService.get_message_access(
                    9, actor=account(uid, admin=admin), permission='recall', cursor=cursor
                ).conversation_id
                == 2
            )


def test_pin_cannot_name_a_message_from_another_scope(app):
    cursor = cursor_rows(message_row(), CaseInsensitiveRecord(id=2, type='private', created_by=1, role='owner'))
    with app.app_context(), pytest.raises(ChatAccessError) as error:
        ChatService.get_message_access(9, actor=account(), permission='pin', conversation_id=1, cursor=cursor)
    assert error.value.status == 403


def test_guest_can_recall_own_message_but_not_admin_reply_or_add_reaction(app, guest):
    with app.app_context():
        row = message_row(uid=None, cid=None, sid=guest.guest_id)
        assert (
            ChatService.get_message_access(9, actor=guest, permission='recall', cursor=cursor_rows(row)).session_id
            == guest.guest_id
        )
        for permission, sender in [('recall', 'admin'), ('reaction', 'user')]:
            with pytest.raises(ChatAccessError) as error:
                ChatService.get_message_access(
                    9,
                    actor=guest,
                    permission=permission,
                    cursor=cursor_rows(message_row(uid=None, cid=None, sid=guest.guest_id, sender=sender)),
                )
            assert error.value.status == (401 if permission == 'reaction' else 403)


def test_send_ignores_untrusted_sender_type_and_uses_authoritative_actor(app, fake_db):
    fake_db.cursor.fetchone.side_effect = [
        CaseInsensitiveRecord(id=2, type='private', created_by=1, role='owner'),
        CaseInsensitiveRecord(id=10, created_at=datetime(2026, 11, 17, 12, 0)),
    ]
    with app.app_context():
        result = ChatService.send_message('admin', '  hello  ', conversation_id=2, actor=account())
    assert result['success'] is True
    assert result['content'] == 'hello'
    assert result['sender_type'] == 'user'
    assert result['sender_id'] == result['user_id'] == 1
    assert result['sender_name'] == 'Cookie User 1'
    assert result['conversation_id'] == 2
    assert result['session_id'] is None
    fake_db.conn.commit.assert_called_once()
    fake_db.conn.close.assert_called_once()


def test_send_revalidates_role_inside_service_boundary(app, fake_db, monkeypatch):
    app.config['SESSION_REVALIDATION_ENABLED'] = True
    monkeypatch.setattr(AuthService, 'get_identity_state', lambda uid, **kwargs: state(role='customer'))
    fake_db.cursor.fetchone.side_effect = [
        CaseInsensitiveRecord(id=2, type='private', created_by=1, role='owner'),
        CaseInsensitiveRecord(id=10, created_at=datetime(2026, 11, 17)),
    ]
    with app.app_context():
        result = ChatService.send_message('admin', 'hello', conversation_id=2, actor=account(admin=True))
    assert result['sender_type'] == 'user'
    assert result['sender_name'] == 'Current User 1'


def test_send_cannot_impersonate_another_user_before_database(app):
    with app.app_context(), pytest.raises(ChatAccessError) as error:
        ChatService.send_message('user', 'hello', user_id=2, conversation_id=2, actor=account())
    assert error.value.status == 403


def test_denied_reply_rolls_back_and_never_commits_a_message(app, fake_db):
    fake_db.cursor.fetchone.side_effect = [
        CaseInsensitiveRecord(id=2, type='private', created_by=1, role='owner'),
        None,
    ]
    with app.app_context(), pytest.raises(ChatAccessError) as error:
        ChatService.send_message('user', 'hello', conversation_id=2, reply_to_id=1, actor=account())
    assert error.value.status == 403
    fake_db.conn.rollback.assert_called_once()
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()


def test_attachment_storage_facade_preserves_public_arguments(app, monkeypatch):
    inserted = CaseInsensitiveRecord(id=17)
    monkeypatch.setattr(attachment_storage, 'storage_path', lambda name: ('path', name))
    monkeypatch.setattr(
        attachment_storage,
        'insert_attachment',
        lambda cursor, mid, attachment: ('insert', cursor, mid, attachment),
    )
    monkeypatch.setattr(attachment_storage, 'delete_records', lambda cursor, mid: ('delete', cursor, mid))
    monkeypatch.setattr(attachment_storage, 'cleanup_files', lambda names: ('cleanup', names))

    assert AttachmentService.storage_path('a' * 32 + '.txt') == ('path', 'a' * 32 + '.txt')
    assert AttachmentService.insert_attachment(inserted, 4, {'storage_name': 'x'}) == (
        'insert',
        inserted,
        4,
        {'storage_name': 'x'},
    )
    assert AttachmentService.delete_records(inserted, 4) == ('delete', inserted, 4)
    assert AttachmentService.cleanup_files(['x']) == ('cleanup', ['x'])


@pytest.mark.parametrize('operation', ['recall', 'delete_attachments'])
@pytest.mark.parametrize('commit_failure', [False, True])
def test_attachment_cleanup_runs_only_after_committed_deletion(app, fake_db, monkeypatch, operation, commit_failure):
    order = []
    monkeypatch.setattr(ChatService, 'get_message_access', lambda *args, **kwargs: ChatAccess(account(), 2))
    if operation == 'recall':
        monkeypatch.setattr(attachment_storage, 'delete_records', lambda cursor, mid: ['a' * 32 + '.txt'])
    else:
        monkeypatch.setattr(AttachmentService, 'delete_records', lambda cursor, mid: ['a' * 32 + '.txt'])
    cleanup = Mock(side_effect=lambda names: order.append('cleanup'))
    if operation == 'recall':
        monkeypatch.setattr(attachment_storage, 'cleanup_files', cleanup)
    else:
        monkeypatch.setattr(AttachmentService, 'cleanup_files', cleanup)
    fake_db.cursor.fetchone.return_value = CaseInsensitiveRecord(
        id=9,
        conversation_id=2,
        session_id='user_1',
        user_id=1,
        sender_type='user',
        is_deleted=False,
        type='private',
        created_by=1,
        role='owner',
    )

    def commit():
        order.append('commit')
        if commit_failure:
            raise psycopg2.OperationalError('synthetic commit failure')

    fake_db.conn.commit.side_effect = commit
    with app.app_context():
        result = (
            ChatService.recall_message(9, actor=account())
            if operation == 'recall'
            else AttachmentService.delete_attachments_by_message_id(9, actor=account())
        )
    if commit_failure:
        assert result is False
        cleanup.assert_not_called()
        fake_db.conn.rollback.assert_called_once()
        assert order == ['commit']
    else:
        assert result is True
        cleanup.assert_called_once_with(['a' * 32 + '.txt'])
        assert order == ['commit', 'cleanup']
    fake_db.conn.close.assert_called_once()


def upload(raw, filename, mime='application/octet-stream'):
    return FileStorage(stream=BytesIO(raw), filename=filename, content_type=mime)


@pytest.mark.parametrize(
    'raw,filename',
    [
        (b'', 'empty.txt'),
        (b'<script>alert(1)</script>', 'fake.png'),
        (b'MZ executable', 'fake.pdf'),
        (b'\xff\xfe', 'bad.txt'),
        (b'a\x00b', 'nul.txt'),
        (b'a\x01b', 'control.txt'),
        (b'hello', 'payload.svg'),
        (b'hello', 'payload.html'),
        (b'hello', 'payload.exe'),
        (b'hello', 'no-extension'),
    ],
)
def test_invalid_upload_content_is_rejected_without_creating_files(app, raw, filename):
    with app.app_context(), pytest.raises(ValidationError):
        AttachmentService.prepare_upload(upload(raw, filename))
    assert not Path(app.config['UPLOAD_ROOT']).exists()


def test_missing_upload_and_configured_byte_limit_are_enforced(app):
    app.config['CHAT_UPLOAD_MAX_BYTES'] = 4
    with app.app_context():
        for file in [None, upload(b'hello', 'too-large.txt')]:
            with pytest.raises(ValidationError):
                AttachmentService.prepare_upload(file)
    assert not Path(app.config['UPLOAD_ROOT']).exists()


def test_upload_basename_and_sniffed_mime_are_not_trusted_from_client(app):
    with app.app_context():
        saved = AttachmentService.prepare_upload(upload(b'plain text', '../../unsafe\\name.txt', 'text/html'))
        path = AttachmentService.storage_path(saved['storage_name'])
        assert saved['file_name'] == 'name.txt'
        assert saved['mime_type'] == 'text/plain'
        assert saved['file_type'] == 'file'
        assert saved['file_url'] == ''
        assert saved['file_size'] == 10
        assert path.parent == Path(app.config['UPLOAD_ROOT']).resolve() / 'chat'
        assert path.read_bytes() == b'plain text'


def test_image_upload_is_decoded_and_reencoded_not_saved_verbatim(app):
    original = BytesIO()
    Image.new('RGB', (3, 2), (40, 80, 120)).save(original, 'PNG')
    raw = original.getvalue() + b'<script>not an image payload</script>'
    with app.app_context():
        saved = AttachmentService.prepare_upload(upload(raw, 'picture.png', 'application/javascript'))
        cleaned = AttachmentService.storage_path(saved['storage_name']).read_bytes()
    assert saved['file_name'] == 'picture.jpg'
    assert saved['mime_type'] == 'image/jpeg'
    assert saved['file_type'] == 'image'
    assert cleaned.startswith(b'\xff\xd8')
    assert b'<script>' not in cleaned
    with Image.open(BytesIO(cleaned)) as image:
        assert image.size == (3, 2)


def zip_bytes(names):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for name in names:
            archive.writestr(name, 'synthetic test entry')
    return output.getvalue()


@pytest.mark.parametrize(
    'names,extension',
    [
        (['../outside.txt'], 'zip'),
        (['/absolute.txt'], 'zip'),
        (['dir\\..\\outside.txt'], 'zip'),
        (['\\absolute.txt'], 'zip'),
        (['[Content_Types].xml'], 'docx'),
        (['word/document.xml'], 'xlsx'),
    ],
)
def test_archive_traversal_and_forged_office_files_are_rejected(app, names, extension):
    with app.app_context(), pytest.raises(ValidationError):
        AttachmentService.prepare_upload(upload(zip_bytes(names), f'unsafe.{extension}'))
    assert not Path(app.config['UPLOAD_ROOT']).exists()


@pytest.mark.parametrize(
    'storage_name',
    [
        '../outside.txt',
        '..\\outside.txt',
        '/tmp/outside.txt',
        'C:\\outside.txt',
        'a' * 32 + '/../outside.txt',
        'A' * 32 + '.txt',
        'a' * 31 + '.txt',
        'a' * 32 + '.html<script>',
        None,
    ],
)
def test_private_storage_rejects_path_traversal_and_noncanonical_keys(app, storage_name):
    with app.app_context(), pytest.raises(ValidationError):
        AttachmentService.storage_path(storage_name)


def test_storage_refuses_symlinked_directory_or_file(app, monkeypatch):
    root = Path(app.config['UPLOAD_ROOT']).resolve()
    key = 'a' * 32 + '.txt'
    for forbidden in [root / 'chat', root / 'chat' / key]:
        monkeypatch.setattr(Path, 'is_symlink', lambda path, target=forbidden: path == target)
        with app.app_context(), pytest.raises(ValidationError):
            AttachmentService.storage_path(key)


def test_cleanup_cannot_delete_paths_outside_private_chat_storage(app, tmp_path):
    outside = tmp_path / 'outside.txt'
    outside.write_bytes(b'keep me')
    with app.app_context():
        key = 'a' * 32 + '.txt'
        private = AttachmentService.storage_path(key)
        private.parent.mkdir(parents=True)
        private.write_bytes(b'delete me')
        AttachmentService.cleanup_files(['../outside.txt', key, None])
    assert outside.read_bytes() == b'keep me'
    assert not private.exists()
