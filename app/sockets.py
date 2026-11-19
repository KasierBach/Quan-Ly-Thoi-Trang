"""Authorized messaging and single-peer WebRTC signaling, scoped to one Flask app."""

from functools import wraps
from threading import RLock, Timer
import re
import time
from typing import Any

from flask import Flask, current_app, request
from flask_socketio import emit, join_room, leave_room
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError as CSRFValidationError
import psycopg2

from app.services.chat_service import ChatService
from app.services.conversation_service import (
    ChatAccessError,
    ConversationService,
    conversation_settings,
    get_identity,
    participant_settings,
    refresh_identity,
)
from app.validation import ValidationError, positive_int, required_text


def socket_sid():
    sid = getattr(request, 'sid', None)
    if not isinstance(sid, str) or not sid:
        raise ChatAccessError('Cần kết nối Socket.IO', 401)
    return sid


def guarded_event(method):
    @wraps(method)
    def guarded(self, data=None):
        try:
            self._actor()
            if not isinstance(data, dict):
                raise ValidationError('Dữ liệu sự kiện không hợp lệ')
            return method(self, data)
        except (ChatAccessError, ValidationError) as exc:
            status = exc.status if isinstance(exc, ChatAccessError) else 400
            result = {'success': False, 'message': str(exc), 'status': status}
            if isinstance(data, dict) and isinstance(data.get('call_id'), str):
                result['call_id'] = data['call_id'][:64]
            emit('error', result)
            if status == 401:
                self._revoke(socket_sid())
            return result
        except psycopg2.Error:
            current_app.logger.exception('Chat socket database operation failed')
            result = {'success': False, 'message': 'Chat tạm thời không khả dụng', 'status': 503}
            emit('error', result)
            return result

    return guarded


class ChatSocketHandlers:
    def __init__(self, socketio, app: Flask):
        self.socketio = socketio
        self.clients = {}
        self.joined = {}
        self.calls = {}
        self.lock = RLock()
        self.clock = time.monotonic
        self.app = app
        self.closed = False

    def close(self):
        with self.lock:
            self.closed = True
            for call in self.calls.values():
                timer = call.get('timer')
                if timer is not None:
                    timer.cancel()
            self.calls.clear()
            self.clients.clear()
            self.joined.clear()

    def _ring_timeout(self, call_id):
        with self.app.app_context(), self.lock:
            if self.closed:
                return
            call = self.calls.get(call_id)
            if call is not None and call['phase'] == 'ringing':
                self._finish_call(call_id, 'call_ended', None, reason='timeout')

    def register_all(self):
        self.socketio.on('connect')(self.handle_connect)
        self.socketio.on('disconnect')(self.handle_disconnect)
        events = {
            'join_conversation': self.handle_join_conversation,
            'leave_conversation': self.handle_leave_conversation,
            'send_message': self.handle_message,
            'admin_reply': self.handle_admin_reply,
            'typing': self.handle_typing,
            'stop_typing': self.handle_stop_typing,
            'admin_typing': self.handle_admin_typing,
            'admin_stop_typing': self.handle_admin_stop_typing,
            'add_reaction': self.handle_add_reaction,
            'remove_reaction': self.handle_remove_reaction,
            'recall_message': self.handle_recall_message,
            'pin_message': self.handle_pin_message,
            'unpin_message': self.handle_unpin_message,
            'mark_read': self.handle_mark_read,
            'update_conversation_settings': self.handle_update_conversation_settings,
            'update_participant_settings': self.handle_update_participant_settings,
            'call_user': self.handle_call_user,
            'answer_call': self.handle_answer_call,
            'reject_call': self.handle_reject_call,
            'end_call': self.handle_end_call,
            'ice_candidate': self.handle_ice_candidate,
            'call_resume': self.handle_call_resume,
            'stream_status': self.handle_stream_status,
            'request_stream': self.handle_request_stream,
            'call_chat_message': self.handle_call_chat_message,
            'media_status': self.handle_media_status,
        }
        for event, handler in events.items():
            self.socketio.on(event)(handler)

    def _actor(self, sid=None):
        sid = sid or socket_sid()
        with self.lock:
            actor = self.clients.get(sid)
        if actor is None:
            raise ChatAccessError('Cần kết nối chat được xác thực', 401)
        actor = refresh_identity(actor)  # Recheck auth_version/role or signed guest expiry on EVERY event.
        with self.lock:
            self.clients[sid] = actor
        return actor

    def handle_connect(self, auth=None):
        auth = auth if isinstance(auth, dict) else {}
        try:
            if current_app.config.get('WTF_CSRF_ENABLED', True):
                validate_csrf(auth.get('csrf_token'))
            actor = get_identity(auth.get('auth_token'))
        except (ChatAccessError, ValidationError, CSRFValidationError):
            return False
        except psycopg2.Error:
            current_app.logger.exception('Chat socket connection authentication failed')
            return False
        with self.lock:
            self.clients[socket_sid()] = actor
            self.joined[socket_sid()] = set()
        if actor.guest_id:
            access = ConversationService.get_access(session_id=actor.guest_id, actor=actor)
            join_room(access.room)
            self.joined[socket_sid()].add(access.room)
        if actor.user_id is not None:
            ChatService.update_last_seen(actor.user_id, actor=actor)
        return True

    def _revoke(self, sid):
        self._remove_client(sid)
        self.socketio.server.disconnect(sid, namespace='/')

    def revoke_user(self, user_id):
        with self.lock:
            sids = [sid for sid, actor in self.clients.items() if actor.user_id == user_id]
        for sid in sids:
            self._revoke(sid)

    def _remove_client(self, sid):
        with self.lock:
            self.clients.pop(sid, None)
            self.joined.pop(sid, None)
            for call_id, call in list(self.calls.items()):
                if sid in call['sids']:
                    self._finish_call(call_id, 'call_ended', sid, reason='disconnected')

    def handle_disconnect(self, reason=None):
        self._remove_client(socket_sid())

    def evict_conversation_user(self, cid, uid):
        with self.lock:
            for sid, actor in list(self.clients.items()):
                if actor.user_id == uid:
                    self.joined.get(sid, set()).discard(f'conv_{cid}')
                    self.socketio.server.leave_room(sid, f'conv_{cid}', namespace='/')
                    for call_id, call in list(self.calls.items()):
                        if call['conversation_id'] == cid and sid in call['sids']:
                            self._finish_call(call_id, 'call_ended', sid, reason='left_conversation')

    def _access(self, data, permission='read'):
        return ConversationService.get_access(
            data.get('conversation_id'), data.get('session_id'), actor=self._actor(), permission=permission
        )

    def _broadcast(self, event, payload, access, exclude_sid=None):
        # Routing uses the persisted message scope, never the caller's room/recipient fields.
        # Recipient ACLs are refreshed as well, so departed participants/stale admins cannot listen forever.
        with self.lock:
            recipients = list(self.clients.items())
        for sid, actor in recipients:
            if sid == exclude_sid:
                continue
            if access.room not in self.joined.get(sid, set()) and not (
                access.conversation_id is None and actor.is_admin
            ):
                continue
            try:
                actor = refresh_identity(actor)
                recipient_access = ConversationService.get_access(
                    access.conversation_id, access.session_id, actor=actor
                )
            except ChatAccessError as exc:
                if exc.status == 401:
                    self._revoke(sid)
                else:
                    self.joined.get(sid, set()).discard(access.room)
                    self.socketio.server.leave_room(sid, access.room, namespace='/')
                continue
            except psycopg2.Error:
                current_app.logger.exception('Chat recipient authorization failed')
                continue
            if recipient_access.room == access.room:
                self.socketio.emit(event, payload, to=sid)

    def publish_message(self, result):
        if not result.get('success'):
            return
        # Use a validated access for routing. Authorizing receivers remains mandatory in _broadcast.
        from app.services.conversation_service import ChatAccess, ChatIdentity

        access = ChatAccess(
            ChatIdentity(result.get('user_id')), result.get('conversation_id'), result.get('session_id')
        )
        payload = {key: value for key, value in result.items() if key not in {'success', 'message'}}
        self._broadcast('new_message', payload, access)

    @guarded_event
    def handle_join_conversation(self, data):
        access = self._access(data)
        join_room(access.room)
        self.joined[socket_sid()].add(access.room)
        return {'success': True, 'conversation_id': access.conversation_id, 'session_id': access.session_id}

    @guarded_event
    def handle_leave_conversation(self, data):
        access = self._access(data)
        leave_room(access.room)
        self.joined[socket_sid()].discard(access.room)
        return {'success': True}

    @guarded_event
    def handle_message(self, data):
        actor = self._actor()
        result = ChatService.send_message(
            'user',
            data.get('content'),
            data.get('session_id'),
            conversation_id=data.get('conversation_id'),
            message_type=data.get('message_type', 'text'),
            reply_to_id=data.get('reply_to_id'),
            actor=actor,
        )
        if not result.get('success'):
            emit('error', {'success': False, 'message': result.get('message'), 'status': 503})
            return result
        self.publish_message(result)
        emit('message_sent', {'success': True, 'id': result['id']})
        return result

    @guarded_event
    def handle_admin_reply(self, data):
        if not self._actor().is_admin:
            raise ChatAccessError()
        return self.handle_message(data)

    def _typing(self, data, stopped=False):
        access = self._access(data)
        payload = {
            'conversation_id': access.conversation_id,
            'session_id': access.session_id,
            'user_id': access.actor.user_id,
            'user_name': access.actor.name,
            'is_admin': access.actor.is_admin,
        }
        self._broadcast('stop_typing' if stopped else 'typing', payload, access, exclude_sid=socket_sid())
        return {'success': True}

    @guarded_event
    def handle_typing(self, data):
        return self._typing(data)

    @guarded_event
    def handle_stop_typing(self, data):
        return self._typing(data, stopped=True)

    @guarded_event
    def handle_admin_typing(self, data):
        if not self._actor().is_admin:
            raise ChatAccessError()
        return self._typing(data)

    @guarded_event
    def handle_admin_stop_typing(self, data):
        if not self._actor().is_admin:
            raise ChatAccessError()
        return self._typing(data, stopped=True)

    def _reaction(self, data, remove=False):
        actor = self._actor()
        mid = positive_int(data.get('message_id'), 'Tin nhắn', 2147483647)
        access = ChatService.get_message_access(
            mid, actor=actor, permission='reaction', conversation_id=data.get('conversation_id')
        )
        operation = ChatService.remove_reaction if remove else ChatService.add_reaction
        if not operation(mid, actor.user_id, data.get('emoji'), actor=actor):
            raise ChatAccessError('Không thể cập nhật cảm xúc', 503)
        payload = {
            'message_id': mid,
            'emoji': data.get('emoji'),
            'user_id': actor.user_id,
            'action': 'remove' if remove else 'add',
            'conversation_id': access.conversation_id,
            'session_id': access.session_id,
        }
        self._broadcast('reaction_update', payload, access)
        return {'success': True}

    @guarded_event
    def handle_add_reaction(self, data):
        return self._reaction(data)

    @guarded_event
    def handle_remove_reaction(self, data):
        return self._reaction(data, remove=True)

    @guarded_event
    def handle_recall_message(self, data):
        actor = self._actor()
        mid = positive_int(data.get('message_id'), 'Tin nhắn', 2147483647)
        access = ChatService.get_message_access(
            mid, actor=actor, permission='recall', conversation_id=data.get('conversation_id')
        )
        if not ChatService.recall_message(mid, actor=actor):
            raise ChatAccessError('Không thể thu hồi', 503)
        self._broadcast(
            'message_recalled',
            {'message_id': mid, 'conversation_id': access.conversation_id, 'session_id': access.session_id},
            access,
        )
        return {'success': True}

    def _pin(self, data, remove=False):
        actor = self._actor()
        cid = positive_int(data.get('conversation_id'), 'Cuộc trò chuyện', 2147483647)
        mid = positive_int(data.get('message_id'), 'Tin nhắn', 2147483647)
        access = ChatService.get_message_access(mid, actor=actor, permission='pin', conversation_id=cid)
        ok = (
            ChatService.unpin_message(cid, mid, actor=actor)
            if remove
            else ChatService.pin_message(cid, mid, actor.user_id, actor=actor)
        )
        if not ok:
            raise ChatAccessError('Không thể ghim tin nhắn', 503)
        self._broadcast(
            'message_unpinned' if remove else 'message_pinned', {'message_id': mid, 'conversation_id': cid}, access
        )
        return {'success': True}

    @guarded_event
    def handle_pin_message(self, data):
        return self._pin(data)

    @guarded_event
    def handle_unpin_message(self, data):
        return self._pin(data, remove=True)

    @guarded_event
    def handle_mark_read(self, data):
        access = self._access(data, 'read_receipt')
        if not ConversationService.mark_as_read(access.conversation_id, access.actor.user_id, actor=access.actor):
            raise ChatAccessError('Không thể cập nhật đã đọc', 503)
        self._broadcast(
            'messages_read', {'conversation_id': access.conversation_id, 'user_id': access.actor.user_id}, access
        )
        return {'success': True}

    @guarded_event
    def handle_update_conversation_settings(self, data):
        access = self._access(data, 'manage')
        settings = conversation_settings(data.get('settings'))
        if not ConversationService.update_conversation_settings(access.conversation_id, settings, actor=access.actor):
            raise ChatAccessError('Không thể cập nhật thiết lập', 503)
        self._broadcast(
            'conversation_settings_updated', {'conversation_id': access.conversation_id, 'settings': settings}, access
        )
        return {'success': True}

    @guarded_event
    def handle_update_participant_settings(self, data):
        actor = self._actor()
        settings = participant_settings(data.get('settings'))
        uid = positive_int(data.get('user_id', actor.user_id), 'Thành viên', 2147483647)
        access = self._access(data, 'manage' if uid != actor.user_id or 'role' in settings else 'read_receipt')
        if uid == actor.user_id and 'role' in settings:
            raise ChatAccessError('Không thể tự cấp quyền')
        if not ConversationService.update_participant_settings(access.conversation_id, uid, settings, actor=actor):
            raise ChatAccessError('Không thể cập nhật thành viên', 503)
        # Personal mute settings are not broadcast to other participants.
        public = {key: value for key, value in settings.items() if key != 'is_muted'}
        if public:
            self._broadcast(
                'participant_settings_updated',
                {'conversation_id': access.conversation_id, 'user_id': uid, 'settings': public},
                access,
            )
        emit(
            'participant_settings_updated',
            {'conversation_id': access.conversation_id, 'user_id': uid, 'settings': settings},
        )
        return {'success': True}

    def _description(self, value, kind):
        if not isinstance(value, dict) or value.get('type') != kind:
            raise ValidationError('Mô tả cuộc gọi không hợp lệ')
        sdp = value.get('sdp')
        if not isinstance(sdp, str) or not sdp.strip() or len(sdp) > 65536 or '\x00' in sdp:
            raise ValidationError('SDP không hợp lệ')
        # SDP is wire-format data: its terminating CRLF must not be stripped.
        return {'type': kind, 'sdp': sdp}

    def _call_id(self, data):
        call_id = data.get('call_id')
        if not isinstance(call_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', call_id):
            raise ValidationError('Mã cuộc gọi không hợp lệ')
        return call_id

    def _expire_calls(self):
        for call_id, call in list(self.calls.items()):
            if call['phase'] == 'ringing' and self.clock() - call['created'] > 30:
                self._finish_call(call_id, 'call_ended', None, reason='timeout')

    def _lookup_call(self, data, active=False):
        call_id = self._call_id(data)
        self._expire_calls()
        call = self.calls.get(call_id)
        cid = positive_int(data.get('conversation_id'), 'Cuộc trò chuyện', 2147483647)
        if call is None or socket_sid() not in call['sids'] or call['conversation_id'] != cid:
            raise ChatAccessError('Cuộc gọi không tồn tại trên kết nối này', 409)
        if active and call['phase'] != 'active':
            raise ChatAccessError('Cuộc gọi chưa được chấp nhận', 409)
        for sid in call['sids']:
            try:
                ConversationService.get_access(cid, actor=self._actor(sid), permission='call')
            except ChatAccessError as exc:
                self._finish_call(call_id, 'call_ended', None, reason='access_revoked')
                if exc.status == 401:
                    self._revoke(sid)
                if sid == socket_sid():
                    raise
                raise ChatAccessError('Người tham gia đã mất quyền truy cập', 409) from exc
        return call_id, call

    def _signal(self, event, payload, call):
        peer_sid = next(sid for sid in call['sids'] if sid != socket_sid())
        actor = self._actor()
        payload = {
            **payload,
            'conversation_id': call['conversation_id'],
            'call_id': call['id'],
            'sender_id': actor.user_id,
            'user_id': actor.user_id,
            'sender_name': actor.name,
        }
        self.socketio.emit(event, payload, to=peer_sid)

    def _finish_call(self, call_id, event, sender_sid, reason=None):
        call = self.calls.pop(call_id, None)
        if call is None:
            return
        timer = call.get('timer')
        if timer is not None:
            timer.cancel()
        payload = {'call_id': call_id, 'conversation_id': call['conversation_id'], 'reason': reason}
        for sid in call['sids']:
            if sid != sender_sid and sid in self.clients:
                self.socketio.emit(event, payload, to=sid)

    @guarded_event
    def handle_call_user(self, data):
        access = self._access(data, 'call')
        call_id = self._call_id(data)
        offer = self._description(data.get('offer'), 'offer')
        video = data.get('isVideo', True)
        if not isinstance(video, bool):
            raise ValidationError('Loại cuộc gọi không hợp lệ')
        with self.lock:
            self._expire_calls()
            if data.get('isResume') is True:
                _, call = self._lookup_call(data, active=True)
                if call['awaiting_answer'] is not None:
                    raise ChatAccessError('Đang đàm phán cuộc gọi', 409)
                call['awaiting_answer'] = next(sid for sid in call['sids'] if sid != socket_sid())
                self._signal('incoming_call', {'offer': offer, 'isVideo': video, 'isResume': True}, call)
                return {'success': True, 'call_id': call_id}
            if call_id in self.calls:
                call = self.calls[call_id]
                if call['sids'][0] == socket_sid() and call['conversation_id'] == access.conversation_id:
                    return {'success': True, 'call_id': call_id}  # Retry is idempotent, not a second ring.
                raise ChatAccessError('Mã cuộc gọi đã được sử dụng', 409)
            participants = ConversationService.get_participants(access.conversation_id, actor=access.actor)
            ids = {row['id'] for row in participants}
            if len(ids) != 2 or access.actor.user_id not in ids:
                raise ChatAccessError('Chỉ hỗ trợ cuộc gọi một-một', 409)
            peer_uid = next(uid for uid in ids if uid != access.actor.user_id)
            if (
                data.get('target_user_id') is not None
                and positive_int(data['target_user_id'], 'Người nhận') != peer_uid
            ):
                raise ChatAccessError()
            occupied = {uid for call in self.calls.values() for uid in call['user_ids']}
            if access.actor.user_id in occupied or peer_uid in occupied:
                raise ChatAccessError('Một người tham gia đang bận', 409)
            peer_sid = None
            for sid, actor in list(self.clients.items()):
                if actor.user_id == peer_uid:
                    try:
                        ConversationService.get_access(
                            access.conversation_id, actor=self._actor(sid), permission='call'
                        )
                    except ChatAccessError:
                        continue
                    peer_sid = sid
                    break
            if peer_sid is None:
                raise ChatAccessError('Người nhận chưa kết nối', 409)
            call = {
                'id': call_id,
                'conversation_id': access.conversation_id,
                'sids': (socket_sid(), peer_sid),
                'user_ids': (access.actor.user_id, peer_uid),
                'phase': 'ringing',
                'created': self.clock(),
                'awaiting_answer': peer_sid,
            }
            self.calls[call_id] = call
            timer = Timer(current_app.config.get('CHAT_RING_TIMEOUT', 30), self._ring_timeout, args=(call_id,))
            timer.daemon = True
            call['timer'] = timer
            timer.start()
            self._signal('incoming_call', {'offer': offer, 'isVideo': video, 'isResume': False}, call)
        return {'success': True, 'call_id': call_id}

    @guarded_event
    def handle_answer_call(self, data):
        answer = self._description(data.get('answer'), 'answer')
        with self.lock:
            call_id, call = self._lookup_call(data)
            if call['awaiting_answer'] != socket_sid():
                raise ChatAccessError('Không chờ câu trả lời từ kết nối này', 409)
            call['phase'] = 'active'
            timer = call.get('timer')
            if timer is not None:
                timer.cancel()
            call['awaiting_answer'] = None
            self._signal('call_answered', {'answer': answer}, call)
        return {'success': True, 'call_id': call_id}

    @guarded_event
    def handle_reject_call(self, data):
        with self.lock:
            call_id, call = self._lookup_call(data)
            if call['phase'] != 'ringing' or socket_sid() != call['sids'][1]:
                raise ChatAccessError('Không thể từ chối cuộc gọi này', 409)
            self._finish_call(call_id, 'call_rejected', socket_sid(), reason='declined')
        return {'success': True}

    @guarded_event
    def handle_end_call(self, data):
        with self.lock:
            call_id, _ = self._lookup_call(data)
            self._finish_call(call_id, 'call_ended', socket_sid(), reason='ended')
        return {'success': True}

    @guarded_event
    def handle_ice_candidate(self, data):
        candidate = data.get('candidate')
        if not isinstance(candidate, dict):
            raise ValidationError('ICE không hợp lệ')
        cleaned: dict[str, Any] = {'candidate': required_text(candidate.get('candidate'), 'ICE', 2048)}
        if candidate.get('sdpMid') is not None:
            cleaned['sdpMid'] = required_text(candidate['sdpMid'], 'ICE mid', 100)
        if candidate.get('sdpMLineIndex') is not None:
            index = candidate['sdpMLineIndex']
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 100:
                raise ValidationError('ICE index không hợp lệ')
            cleaned['sdpMLineIndex'] = index
        with self.lock:
            _, call = self._lookup_call(data)
            self._signal('remote_ice_candidate', {'candidate': cleaned}, call)
        return {'success': True}

    @guarded_event
    def handle_call_resume(self, data):
        with self.lock:
            _, call = self._lookup_call(data, active=True)
            self._signal('call_resume', {}, call)
        return {'success': True}

    @guarded_event
    def handle_stream_status(self, data):
        if not isinstance(data.get('is_streaming'), bool):
            raise ValidationError('Trạng thái chia sẻ không hợp lệ')
        with self.lock:
            _, call = self._lookup_call(data, active=True)
            self._signal('stream_status', {'is_streaming': data['is_streaming']}, call)
        return {'success': True}

    @guarded_event
    def handle_request_stream(self, data):
        raise ChatAccessError(
            'Livestream và xem nhóm chưa được hỗ trợ; chia sẻ màn hình chỉ trong cuộc gọi một-một', 409
        )

    @guarded_event
    def handle_call_chat_message(self, data):
        text = required_text(data.get('text'), 'Tin nhắn cuộc gọi', 1000)
        with self.lock:
            _, call = self._lookup_call(data, active=True)
            self._signal(
                'call_chat_message',
                {
                    'text': text,
                    'timestamp': data.get('timestamp') if isinstance(data.get('timestamp'), (int, float)) else None,
                },
                call,
            )
        return {'success': True}

    @guarded_event
    def handle_media_status(self, data):
        if data.get('type') not in {'mic', 'cam'} or not isinstance(data.get('enabled'), bool):
            raise ValidationError('Trạng thái phương tiện không hợp lệ')
        with self.lock:
            _, call = self._lookup_call(data, active=True)
            self._signal('media_status', {'type': data['type'], 'enabled': data['enabled']}, call)
        return {'success': True}


def register_socket_events(socketio, app: Flask):
    handlers = ChatSocketHandlers(socketio, app)
    app.extensions['chat_socket_handlers'] = handlers
    handlers.register_all()
    return handlers
