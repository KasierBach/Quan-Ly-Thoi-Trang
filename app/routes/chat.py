from flask import Blueprint, current_app, jsonify, render_template, request, send_file
import psycopg2

from app.services.chat_service import ChatService
from app.services.conversation_service import (
    ChatAccessError,
    ConversationService,
    conversation_settings,
    get_identity,
    issue_guest_credentials,
    participant_settings,
)
from app.services.attachment_service import AttachmentService
from app.validation import ValidationError, positive_int, required_text


chat_bp = Blueprint('chat', __name__)


@chat_bp.errorhandler(ChatAccessError)
def access_error(error):
    return jsonify(success=False, error=str(error)), error.status


@chat_bp.errorhandler(ValidationError)
def validation_error(error):
    return jsonify(success=False, error=str(error)), 400


@chat_bp.errorhandler(psycopg2.Error)
def database_error(error):
    current_app.logger.exception('Chat database operation failed')
    return jsonify(success=False, error='Chat tạm thời không khả dụng'), 503


def json_payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError('Dữ liệu JSON không hợp lệ')
    return data


def require_user(admin=False):
    actor = get_identity()
    if actor.user_id is None:
        raise ChatAccessError('Cần đăng nhập', 401)
    if admin and not actor.is_admin:
        raise ChatAccessError()
    return actor


def get_access(conversation_id=None, session_id=None, *, actor=None, permission='read'):
    """Transport helper; services also enforce the same guards inside their transactions."""
    return ConversationService.get_access(conversation_id, session_id, actor=actor, permission=permission)


def publish_message(result):
    handlers = current_app.extensions.get('chat_socket_handlers')
    if handlers is not None:
        handlers.publish_message(result)


def result_response(result, status=200):
    if not result.get('success'):
        return jsonify(success=False, error=result.get('message', 'Thao tác không thành công')), 503
    return jsonify(result), status


@chat_bp.route('/messages')
def messages_page():
    return render_template('messages.html')


@chat_bp.route('/admin/messages')
def admin_messages_page():
    require_user(admin=True)
    return render_template('messages.html')


@chat_bp.route('/api/chat/guest-session', methods=['POST'])
def guest_session():
    # CSRF remains enabled. Tokens are signed and bound to the existing signed Flask cookie.
    result = jsonify(issue_guest_credentials())
    result.headers['Cache-Control'] = 'no-store'
    return result


@chat_bp.route('/admin/chat/conversations')
def admin_get_conversations():
    return jsonify(conversations=ConversationService.get_guest_conversations(actor=require_user(admin=True)))


@chat_bp.route('/api/chat/admin/send', methods=['POST'])
def admin_send_message():
    data = json_payload()
    actor = require_user(admin=True)
    result = ChatService.send_message(
        'admin',
        data.get('content'),
        data.get('session_id'),
        conversation_id=data.get('conversation_id'),
        reply_to_id=data.get('reply_to_id'),
        actor=actor,
    )
    if result.get('success'):
        publish_message(result)
    return result_response(result)


@chat_bp.route('/api/users/suggested')
def get_suggested_users():
    actor = require_user()
    return jsonify(users=ConversationService.get_suggested_users(actor.user_id, actor=actor))


@chat_bp.route('/api/users/search')
def search_users():
    actor = require_user()
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify(users=[])
    query = required_text(query, 'Tìm kiếm', 100)
    return jsonify(users=ConversationService.search_users(actor.user_id, query, actor=actor))


@chat_bp.route('/api/conversations', methods=['GET', 'POST'])
def handle_conversations():
    actor = require_user()
    if request.method == 'POST':
        data = json_payload()
        result = ConversationService.create_conversation(
            data.get('type', 'group'),
            data.get('name'),
            created_by=actor.user_id,
            participant_ids=data.get('participant_ids'),
            actor=actor,
        )
        return result_response(result, 201)
    result = ConversationService.get_user_conversations(actor.user_id, actor=actor)
    if actor.is_admin:
        result.extend(ConversationService.get_guest_conversations(actor=actor))
    return jsonify(conversations=result)


@chat_bp.route('/api/conversations/<int:cid>')
def get_conversation_details(cid):
    conv = ConversationService.get_conversation(cid, actor=require_user())
    return jsonify(conv) if conv else (jsonify(error='Không tìm thấy'), 404)


@chat_bp.route('/api/chat/conversations/<int:cid>/pinned')
def get_pinned_messages(cid):
    return jsonify(pinned=ChatService.get_pinned_messages(cid, actor=require_user()))


@chat_bp.route('/api/conversations/<int:cid>/participants', methods=['GET', 'POST'])
def conversation_participants(cid):
    actor = require_user()
    if request.method == 'GET':
        return jsonify(participants=ConversationService.get_participants(cid, actor=actor))
    data = json_payload()
    return result_response(ConversationService.add_participant(cid, data.get('user_id'), actor=actor))


@chat_bp.route('/api/chat/send', methods=['POST'])
def handle_chat_send():
    data = json_payload()
    result = ChatService.send_message(
        'user',
        data.get('content'),
        data.get('session_id'),
        conversation_id=data.get('conversation_id'),
        message_type=data.get('message_type', 'text'),
        reply_to_id=data.get('reply_to_id'),
        actor=get_identity(),
    )
    if result.get('success'):
        publish_message(result)
    return result_response(result)


@chat_bp.route('/api/conversations/direct', methods=['POST'])
def handle_direct_chat():
    return result_response(
        ConversationService.create_direct_conversation(json_payload().get('user_id'), actor=require_user())
    )


@chat_bp.route('/api/chat/history')
def get_history():
    limit = positive_int(request.args.get('limit', 50), 'Giới hạn', 100)
    before = request.args.get('before_id')
    before = positive_int(before, 'Tin nhắn trước', 2147483647) if before is not None else None
    return jsonify(
        messages=ChatService.get_messages(
            request.args.get('session_id'),
            conversation_id=request.args.get('conversation_id'),
            limit=limit,
            before_id=before,
            actor=get_identity(),
        )
    )


@chat_bp.route('/api/chat/upload', methods=['POST'])
def upload_file():
    actor = get_identity()
    cid, sid = request.form.get('conversation_id'), request.form.get('session_id')
    get_access(cid, sid, actor=actor, permission='send')  # Authorize before writing/decoding any file.
    attachment = AttachmentService.prepare_upload(request.files.get('file'))
    committed = False
    try:
        result = ChatService.send_message(
            'user',
            attachment['file_name'],
            sid,
            conversation_id=cid,
            message_type=attachment['file_type'],
            actor=actor,
            attachment=attachment,
        )
        if not result.get('success'):
            return result_response(result)
        committed = True
        publish_message(result)
        return jsonify(
            status='success',
            success=True,
            file_url=result['attachments'][0]['file_url'],
            file_type=attachment['file_type'],
            message=result,
        )
    finally:
        if not committed:
            AttachmentService.cleanup_files([attachment['storage_name']])


@chat_bp.route('/api/chat/attachments/<int:aid>')
def download_attachment(aid):
    row = AttachmentService.get_attachment(aid, actor=get_identity())
    path = AttachmentService.storage_path(row['storage_name'])
    if not path.is_file():
        raise ChatAccessError('Tệp không tồn tại', 404)
    inline = row['file_type'] in {'image', 'audio', 'video'}
    response = send_file(
        path,
        mimetype=row['mime_type'],
        as_attachment=not inline,
        download_name=row['file_name'],
        conditional=False,
        max_age=0,
    )
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@chat_bp.route('/api/chat/messages/<int:mid>/reactions', methods=['POST', 'DELETE', 'GET'])
def manage_reactions(mid):
    actor = get_identity()
    if request.method == 'GET':
        return jsonify(reactions=ChatService.get_reactions(mid, actor=actor))
    if actor.user_id is None:
        raise ChatAccessError('Cần đăng nhập', 401)
    if request.method == 'POST':
        ok = ChatService.add_reaction(mid, actor.user_id, json_payload().get('emoji'), actor=actor)
    else:
        ok = ChatService.remove_reaction(mid, actor.user_id, request.args.get('emoji'), actor=actor)
    return (jsonify(status='success'), 200) if ok else (jsonify(error='Thao tác không thành công'), 503)


@chat_bp.route('/api/chat/pin', methods=['POST'])
def pin_message():
    actor = require_user()
    data = json_payload()
    cid = positive_int(data.get('conversation_id'), 'Cuộc trò chuyện', 2147483647)
    mid = positive_int(data.get('message_id'), 'Tin nhắn', 2147483647)
    ok = ChatService.pin_message(cid, mid, actor.user_id, actor=actor)
    return (jsonify(status='success'), 200) if ok else (jsonify(error='Thao tác không thành công'), 503)


@chat_bp.route('/api/chat/messages/<int:mid>/recall', methods=['POST'])
def recall_message(mid):
    ok = ChatService.recall_message(mid, actor=get_identity())
    return (jsonify(status='success'), 200) if ok else (jsonify(error='Thao tác không thành công'), 503)


@chat_bp.route('/api/conversations/<cid>/leave', methods=['POST'])
def leave_conversation(cid):
    actor = require_user()
    if not cid.isdigit():
        ok = ChatService.delete_session_messages(cid, actor=actor)
    else:
        cid = positive_int(cid, 'Cuộc trò chuyện', 2147483647)
        ok = ConversationService.leave_conversation(cid, actor.user_id, actor=actor)
        handlers = current_app.extensions.get('chat_socket_handlers')
        if ok and handlers is not None:
            handlers.evict_conversation_user(cid, actor.user_id)
    return (jsonify(status='success'), 200) if ok else (jsonify(error='Thao tác không thành công'), 503)


@chat_bp.route('/api/conversations/<cid>/read', methods=['POST'])
def mark_read(cid):
    actor = get_identity()
    access = get_access(cid, actor=actor)
    if access.conversation_id is None:
        return jsonify(status='success')  # Guest support has no participant read-receipt record.
    ok = ConversationService.mark_as_read(access.conversation_id, actor.user_id, actor=actor)
    return (jsonify(status='success'), 200) if ok else (jsonify(error='Thao tác không thành công'), 503)


@chat_bp.route('/api/conversations/<int:cid>/settings', methods=['PATCH', 'PUT'])
def update_conversation_settings(cid):
    settings = conversation_settings(json_payload())
    ok = ConversationService.update_conversation_settings(cid, settings, actor=require_user())
    return (jsonify(status='success'), 200) if ok else (jsonify(error='Thao tác không thành công'), 503)


@chat_bp.route('/api/conversations/<int:cid>/participants/me', methods=['PATCH', 'PUT'])
def update_my_participant_settings(cid):
    actor = require_user()
    settings = participant_settings(json_payload())
    if 'role' in settings:
        raise ChatAccessError('Không thể tự cấp quyền')
    ok = ConversationService.update_participant_settings(cid, actor.user_id, settings, actor=actor)
    return (jsonify(status='success'), 200) if ok else (jsonify(error='Thao tác không thành công'), 503)


@chat_bp.route('/api/conversations/<int:cid>/participants/<int:target_uid>', methods=['PATCH', 'PUT'])
def update_participant_settings_specific(cid, target_uid):
    actor = require_user()
    settings = participant_settings(json_payload())
    ok = ConversationService.update_participant_settings(cid, target_uid, settings, actor=actor)
    return (jsonify(status='success'), 200) if ok else (jsonify(error='Thao tác không thành công'), 503)


@chat_bp.route('/api/users/<int:target_uid>/status')
def get_user_status(target_uid):
    return jsonify(ChatService.get_user_status(target_uid, actor=require_user()))


@chat_bp.route('/api/conversations/<int:cid>/attachments')
def get_conversation_attachments(cid):
    return jsonify(attachments=ChatService.get_attachments(cid, request.args.get('type'), actor=require_user()))
