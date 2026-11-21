"""Complementary chat branch tests; cursor doubles test error control flow, not SQL truth."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZIP_DEFLATED, ZipFile

import psycopg2
import pytest
from werkzeug.datastructures import FileStorage

from app.database import CaseInsensitiveRecord
from app.services import attachment_storage
from app.services.attachment_service import AttachmentService
from app.services.auth_service import AuthService
from app.services.base_service import BaseService
from app.services.chat_service import ChatService
from app.services.conversation_service import ChatAccessError, ChatIdentity, ConversationService, participant_settings
from app.validation import ValidationError


@pytest.fixture(autouse=True)
def no_unplanned_database(monkeypatch):
    def refused():
        pytest.fail('Additional chat unit test attempted an unplanned database connection')

    monkeypatch.setattr(BaseService, 'get_connection', staticmethod(refused))


def actor(uid=1, *, admin=False, guest_id=None):
    return ChatIdentity(uid, is_admin=admin, name='Test Actor', auth_version=1, guest_id=guest_id)


def invoke_mutation(operation):
    actions = {
        'group_create': lambda: ConversationService.create_conversation(
            name='Group', participant_ids=[3], actor=actor()
        ),
        'direct_create': lambda: ConversationService.create_direct_conversation(2, actor=actor()),
        'participant_add': lambda: ConversationService.add_participant(3, 2, actor=actor()),
        'leave': lambda: ConversationService.leave_conversation(3, 1, actor=actor()),
        'read_alias': lambda: ChatService.mark_as_read(2, 1, actor=actor()),
        'conversation_settings': lambda: ConversationService.update_conversation_settings(
            3, {'name': 'Changed'}, actor=actor()
        ),
        'participant_settings': lambda: ConversationService.update_participant_settings(
            3, 3, {'nickname': 'Changed'}, actor=actor()
        ),
        'reaction_add': lambda: ChatService.add_reaction(3, 1, '\U0001f44d', actor=actor()),
        'reaction_remove': lambda: ChatService.remove_reaction(3, 1, '\U0001f44d', actor=actor()),
        'pin': lambda: ChatService.pin_message(2, 3, 1, actor=actor()),
        'unpin': lambda: ChatService.unpin_message(2, 3, actor=actor()),
        'last_seen': lambda: ChatService.update_last_seen(1, actor=actor()),
        'support_purge': lambda: ChatService.delete_session_messages(
            'signed-support-ticket', actor=actor(2, admin=True)
        ),
        'attachment_delete': lambda: AttachmentService.delete_attachments_by_message_id(3, actor=actor()),
    }
    return actions[operation]()


@pytest.mark.parametrize(
    'operation',
    [
        'group_create',
        'direct_create',
        'participant_add',
        'leave',
        'read_alias',
        'conversation_settings',
        'participant_settings',
        'reaction_add',
        'reaction_remove',
        'pin',
        'unpin',
        'last_seen',
        'support_purge',
        'attachment_delete',
    ],
)
def test_database_failures_roll_back_return_safe_failure_and_never_cleanup_committed_files(
    app, fake_db, monkeypatch, operation
):
    fake_db.cursor.execute.side_effect = psycopg2.OperationalError('private connection detail')
    cleanup = Mock()
    monkeypatch.setattr(attachment_storage, 'cleanup_files', cleanup)
    with app.app_context():
        result = invoke_mutation(operation)
    if isinstance(result, dict):
        assert result['success'] is False
        assert 'private connection detail' not in result['message']
    else:
        assert result is False
    fake_db.conn.rollback.assert_called_once()
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()
    cleanup.assert_not_called()


@pytest.mark.parametrize('operation', ['message_type', 'attachment_type', 'participant_role'])
def test_unhashable_discriminators_raise_validation_error_not_internal_typeerror(app, operation):
    with app.app_context(), pytest.raises(ValidationError):
        if operation == 'message_type':
            ChatService.validate_message('text', message_type=[])
        elif operation == 'attachment_type':
            ChatService.get_attachments(2, file_type=[], actor=actor())
        else:
            participant_settings({'role': {}})


def test_service_user_arguments_cannot_impersonate_before_any_database_connection(app):
    actions = [
        lambda: ChatService.get_messages(user_id=3, conversation_id=2, actor=actor()),
        lambda: ChatService.add_reaction(3, 3, '\U0001f44d', actor=actor()),
        lambda: ChatService.pin_message(2, 3, 3, actor=actor()),
        lambda: ChatService.recall_message(3, user_id=3, actor=actor()),
        lambda: ConversationService.get_direct_conversation(3, 1, actor=actor()),
        lambda: ConversationService.search_users(3, 'customer', actor=actor()),
        lambda: ConversationService.get_suggested_users(3, actor=actor()),
        lambda: ConversationService.get_suggested_users(None, actor=actor(None)),
        lambda: ConversationService.leave_conversation(2, 3, actor=actor()),
        lambda: ConversationService.mark_as_read(2, 3, actor=actor()),
        lambda: ChatService.update_last_seen(3, actor=actor()),
        lambda: ChatService.get_user_status(1, actor=actor(None)),
    ]
    with app.app_context():
        for action in actions:
            with pytest.raises(ChatAccessError):
                action()


def test_search_users_returns_public_records_with_actor_bound_search_parameters(app, fake_db):
    expected = [
        {'id': 1, 'name': "O'Connor", 'avatar': None},
        {'id': 2, 'name': 'Test Admin', 'avatar': '/static/images/default.jpg'},
    ]
    fake_db.cursor.fetchall.return_value = [CaseInsensitiveRecord(**row) for row in expected]
    with app.app_context():
        result = ConversationService.search_users(3, "  O'Connor  ", limit='2', actor=actor(3))
    assert result == expected
    assert all(type(row) is dict for row in result)
    fake_db.cursor.execute.assert_called_once()
    sql, params = fake_db.cursor.execute.call_args.args
    assert params == (3, "%O'Connor%", "%O'Connor%", 2)
    assert "O'Connor" not in sql
    assert 'CustomerID != %s AND (FullName ILIKE %s OR Email ILIKE %s)' in sql
    assert 'ORDER BY CustomerID LIMIT %s' in sql
    fake_db.cursor.fetchall.assert_called_once()
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()


def test_suggested_users_returns_public_records_with_actor_bound_exclusion(app, fake_db):
    expected = [
        {'id': 1, 'name': 'Test Customer', 'avatar': None},
        {'id': 2, 'name': 'Test Admin', 'avatar': '/static/images/default.jpg'},
    ]
    fake_db.cursor.fetchall.return_value = [CaseInsensitiveRecord(**row) for row in expected]
    with app.app_context():
        result = ConversationService.get_suggested_users(3, actor=actor(3))
    assert result == expected
    assert all(type(row) is dict for row in result)
    fake_db.cursor.execute.assert_called_once()
    sql, params = fake_db.cursor.execute.call_args.args
    assert params == (3,)
    assert 'CustomerID AS id, FullName AS name, avatar_url AS avatar' in sql
    assert 'WHERE CustomerID != %s ORDER BY CustomerID LIMIT 10' in sql
    fake_db.cursor.fetchall.assert_called_once()
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()


def test_direct_lookup_returns_pair_record_with_actor_bound_parameterized_query(app, fake_db):
    record = CaseInsensitiveRecord(id=41)
    fake_db.cursor.fetchone.return_value = record
    with app.app_context():
        result = ConversationService.get_direct_conversation(2, '3', actor=actor(2, admin=True))
    assert result is record
    assert result.id == 41
    fake_db.cursor.execute.assert_called_once()
    sql, params = fake_db.cursor.execute.call_args.args
    assert params == (2, 3)
    assert "c.type = 'private' AND p1.user_id = %s AND p2.user_id = %s" in sql
    assert '(SELECT COUNT(*) FROM Participants WHERE conversation_id = c.id) = 2' in sql
    fake_db.cursor.fetchone.assert_called_once()
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()


@pytest.mark.parametrize(
    'operation,invalid_error,denied_status',
    [
        ('search_users', ValidationError, 401),
        ('get_suggested_users', ChatAccessError, 401),
        ('get_direct_conversation', ValidationError, 403),
    ],
)
def test_discovery_rejects_invalid_foreign_and_guest_callers_before_database(
    app, monkeypatch, operation, invalid_error, denied_status
):
    connection = Mock(side_effect=AssertionError('Denied discovery caller must not connect to the database'))
    monkeypatch.setattr(BaseService, 'get_connection', staticmethod(connection))
    method = getattr(ConversationService, operation)
    extra_args = {'search_users': ('customer',), 'get_suggested_users': (), 'get_direct_conversation': (3,)}[operation]
    guest_uid = None if operation == 'get_suggested_users' else 1
    with app.app_context():
        for uid, identity in [(1, actor(2, admin=True)), (guest_uid, actor(None, guest_id='guest-discovery'))]:
            with pytest.raises(ChatAccessError) as denied:
                method(uid, *extra_args, actor=identity)
            assert denied.value.status == denied_status
        with pytest.raises(invalid_error):
            method('1 OR 1=1', *extra_args, actor=actor())
    connection.assert_not_called()


def test_group_creation_validates_omitted_and_untrusted_members_and_creator_before_database(app):
    invalid = [
        ({'actor': actor(None), 'name': 'Group'}, ChatAccessError),
        ({'actor': actor(), 'name': 'Group', 'created_by': 3}, ChatAccessError),
        ({'actor': actor(), 'name': 'Group', 'conversation_type': 'private'}, ValidationError),
        ({'actor': actor(), 'name': 'Group', 'participant_ids': 3}, ValidationError),
        ({'actor': actor(), 'name': 'Group', 'participant_ids': [3] * 51}, ValidationError),
        ({'actor': actor(), 'name': 'Group', 'participant_ids': [True]}, ValidationError),
        ({'actor': actor(), 'name': 'Group', 'avatar_url': 'https://untrusted.test/avatar'}, ValidationError),
    ]
    with app.app_context():
        for data, error_type in invalid:
            with pytest.raises(error_type):
                ConversationService.create_conversation(**data)
        with pytest.raises(ValidationError):
            ConversationService.add_participant(3, 2, role='admin', actor=actor())
        with pytest.raises(ChatAccessError):
            ConversationService.create_direct_conversation(2, actor=actor(None))


@pytest.mark.parametrize('operation', ['participant_add', 'participant_settings'])
def test_missing_participant_target_rolls_back_without_committing(app, fake_db, operation):
    fake_db.cursor.fetchone.side_effect = [
        CaseInsensitiveRecord(id=3, type='group', created_by=1, role='admin'),
        None,
    ]
    with app.app_context(), pytest.raises(ValidationError if operation == 'participant_add' else ChatAccessError):
        if operation == 'participant_add':
            ConversationService.add_participant(3, 999, actor=actor())
        else:
            ConversationService.update_participant_settings(3, 999, {'nickname': 'Absent'}, actor=actor())
    fake_db.conn.rollback.assert_called_once()
    fake_db.conn.commit.assert_not_called()
    fake_db.conn.close.assert_called_once()


def test_support_purge_rechecks_current_admin_role_before_any_write(app, fake_db, monkeypatch):
    app.config['SESSION_REVALIDATION_ENABLED'] = True
    monkeypatch.setattr(
        AuthService,
        'get_identity_state',
        lambda uid: CaseInsensitiveRecord(CustomerID=2, FullName='Demoted User', AuthVersion=1, Role='customer'),
    )
    cleanup = Mock()
    monkeypatch.setattr(attachment_storage, 'cleanup_files', cleanup)
    fake_db.cursor.fetchall.return_value = []
    with app.app_context(), pytest.raises(ChatAccessError) as denied:
        ChatService.delete_session_messages('own-ticket', actor=actor(2, admin=True, guest_id='own-ticket'))
    assert denied.value.status == 403
    fake_db.cursor.execute.assert_not_called()
    fake_db.conn.commit.assert_not_called()
    cleanup.assert_not_called()


def test_presence_uses_exact_five_minute_window_handles_future_dates_and_timezone(app, fake_db, monkeypatch):
    fixed = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed.replace(tzinfo=None)

    monkeypatch.setattr('app.services.chat_service.datetime', Clock)
    cases = [
        (fixed - timedelta(minutes=4, seconds=59), True),
        (fixed - timedelta(minutes=5), False),
        (fixed + timedelta(seconds=1), False),
        (fixed.replace(tzinfo=None) - timedelta(minutes=2), True),
        (None, False),
    ]
    with app.app_context():
        for seen, online in cases:
            fake_db.cursor.fetchone.return_value = CaseInsensitiveRecord(last_seen=seen)
            result = ChatService.get_user_status(1, actor=actor())
            assert result == {'online': online, 'last_seen': seen.isoformat() if seen is not None else None}
        fake_db.cursor.fetchone.return_value = None
        assert ChatService.get_user_status(1, actor=actor()) == {'online': False, 'last_seen': None}
    assert fake_db.conn.close.call_count == len(cases) + 1


def archive_bytes(names, *, large=False):
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, b'x' * (50 * 1024 * 1024 + 1) if large else b'entry')
    return output.getvalue()


def test_allowed_nonimage_file_formats_are_sniffed_and_written_with_canonical_metadata(app):
    ole = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'container'
    ftyp = b'\x00\x00\x00\x18ftypisom' + b'\x00' * 8
    webm = b'\x1aE\xdf\xa3' + b'webm synthetic header'
    cases = [
        ('pdf', b'%PDF-1.4\n%%EOF', 'text/html', 'file', 'application/pdf'),
        ('doc', ole, 'text/html', 'file', 'application/msword'),
        ('xls', ole, 'text/html', 'file', 'application/vnd.ms-excel'),
        ('rar', b'Rar!\x1a\x07\x00header', 'text/html', 'file', 'application/vnd.rar'),
        ('wav', b'RIFF\x00\x00\x00\x00WAVEfmt ', 'text/html', 'audio', 'audio/wav'),
        ('ogg', b'OggSheader', 'text/html', 'audio', 'audio/ogg'),
        ('mp3', b'ID3header', 'text/html', 'audio', 'audio/mpeg'),
        ('mp3', b'\xff\xfbheader', 'text/html', 'audio', 'audio/mpeg'),
        ('webm', webm, 'audio/webm;codecs=opus', 'audio', 'audio/webm'),
        ('webm', webm, 'text/html', 'video', 'video/webm'),
        ('mp4', ftyp, 'text/html', 'video', 'video/mp4'),
        ('mov', ftyp, 'text/html', 'video', 'video/quicktime'),
        ('m4a', ftyp, 'text/html', 'audio', 'audio/mp4'),
        ('zip', archive_bytes(['nested/entry.txt']), 'text/html', 'file', 'application/zip'),
        (
            'docx',
            archive_bytes(['[Content_Types].xml', 'word/document.xml']),
            'text/html',
            'file',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        ),
        (
            'xlsx',
            archive_bytes(['[Content_Types].xml', 'xl/workbook.xml']),
            'text/html',
            'file',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        ),
    ]
    with app.app_context():
        for extension, raw, declared, kind, mime in cases:
            file = FileStorage(stream=BytesIO(raw), filename=f'format.{extension}', content_type=declared)
            saved = AttachmentService.prepare_upload(file)
            assert saved['file_type'] == kind
            assert saved['mime_type'] == mime
            assert saved['storage_name'].endswith('.' + extension)
            assert AttachmentService.storage_path(saved['storage_name']).read_bytes() == raw


def test_archive_count_expansion_limits_and_truncated_container_are_rejected(app):
    unsafe = [
        b'PK\x03\x04truncated',
        archive_bytes([f'entry-{i}' for i in range(2001)]),
        archive_bytes(['expanded.txt'], large=True),
    ]
    with app.app_context():
        for raw in unsafe:
            with pytest.raises(ValidationError):
                AttachmentService.prepare_upload(FileStorage(stream=BytesIO(raw), filename='unsafe.zip'))
    assert not Path(app.config['UPLOAD_ROOT']).exists()


def test_partial_write_failure_removes_only_its_new_private_file(app, monkeypatch):
    original_open = Path.open
    created = []

    def failed_write(path, mode='r', *args, **kwargs):
        if mode == 'xb' and path.parent.name == 'chat':
            with original_open(path, mode, *args, **kwargs) as output:
                output.write(b'partial file')
            created.append(path)
            raise OSError('synthetic disk full')
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', failed_write)
    with app.app_context(), pytest.raises(OSError, match='disk full'):
        AttachmentService.prepare_upload(FileStorage(stream=BytesIO(b'private text'), filename='text.txt'))
    assert len(created) == 1 and not created[0].exists()


def test_private_storage_collision_never_deletes_preexisting_file(app, monkeypatch):
    key = 'f' * 32
    with app.app_context():
        existing = AttachmentService.storage_path(key + '.txt')
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b'previously committed private file')
        monkeypatch.setattr('app.services.attachment_service.secrets.token_hex', lambda count: key)
        with pytest.raises(FileExistsError):
            AttachmentService.prepare_upload(FileStorage(stream=BytesIO(b'new text'), filename='new.txt'))
    assert existing.is_file()
    assert existing.read_bytes() == b'previously committed private file'
