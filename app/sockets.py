"""Authorized messaging and single-peer WebRTC signaling, scoped to one Flask app."""

from functools import wraps
from threading import RLock, Timer
import re
import time
from typing import Any

from flask import Flask, current_app, request
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError as CSRFValidationError
import psycopg2

from app.calls import MeshCallRegistry
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
    def guarded(self, data=None, **kwargs):
        sid = socket_sid()
        with self.lock:
            generation = self.generations.get(sid)
        try:
            self._actor(sid)
            if not isinstance(data, dict):
                raise ValidationError('Dữ liệu sự kiện không hợp lệ')
            return method(self, data, **kwargs)
        except (ChatAccessError, ValidationError) as exc:
            status = exc.status if isinstance(exc, ChatAccessError) else 400
            result = {'success': False, 'message': str(exc), 'status': status}
            if isinstance(data, dict) and isinstance(data.get('call_id'), str):
                result['call_id'] = data['call_id'][:64]
            self._emit_to_sid('error', result, sid, generation)
            if status == 401:
                self._revoke(sid, generation)
            return result
        except psycopg2.Error:
            current_app.logger.exception('Chat socket database operation failed')
            result = {'success': False, 'message': 'Chat tạm thời không khả dụng', 'status': 503}
            self._emit_to_sid('error', result, sid, generation)
            return result

    return guarded


class ChatSocketHandlers:
    def __init__(self, socketio, app: Flask):
        self.socketio = socketio
        self.clients = {}
        self.joined = {}
        self.generations = {}
        self.room_intents = {}
        self.calls = {}
        self.lock = RLock()
        self.clock = time.monotonic
        self.app = app
        self.closed = False
        self.mesh_calls = MeshCallRegistry(self)

    def close(self):
        with self.lock:
            self.closed = True
            self.mesh_calls.close()
            for call in self.calls.values():
                timer = call.get('timer')
                if timer is not None:
                    timer.cancel()
            self.calls.clear()
            for sid in list(self.clients):
                self._remove_client(sid)
            self.joined.clear()
            self.generations.clear()
            self.room_intents.clear()

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
            'group_call_start': self.handle_group_call_start,
            'group_call_join': self.handle_group_call_join,
            'group_call_leave': self.handle_group_call_leave,
            'group_call_signal': self.handle_group_call_signal,
        }
        for event, handler in events.items():
            self.socketio.on(event)(handler)

    def _connected(self, sid, *, connecting=False):
        manager = self.socketio.server.manager
        return manager.is_connected(sid, '/') or (connecting and manager.is_pre_connected(sid, '/'))

    def _live(self, sid, generation, *, connecting=False):
        return (
            not self.closed
            and generation is not None
            and self.generations.get(sid) is generation
            and sid in self.clients
            and self._connected(sid, connecting=connecting)
        )

    def _actor(self, sid=None):
        sid = sid or socket_sid()
        with self.lock:
            generation = self.generations.get(sid)
            if not self._live(sid, generation):
                self._remove_client(sid, generation)
                raise ChatAccessError('Cần kết nối chat được xác thực', 401)
            actor = self.clients[sid]
        actor = refresh_identity(actor)  # Slow auth I/O must not resurrect a disconnected SID.
        with self.lock:
            if not self._live(sid, generation):
                self._remove_client(sid, generation)
                raise ChatAccessError('Cần kết nối chat được xác thực', 401)
            self.clients[sid] = actor
        return actor

    @staticmethod
    def _delivery_room(conversation_id, user_id, auth_version):
        cid = positive_int(conversation_id, 'Cuộc trò chuyện', 2147483647)
        uid = positive_int(user_id, 'Tài khoản', 2147483647)
        version = positive_int(auth_version, 'Phiên tài khoản', 2147483647)
        return f'conv_{cid}_user_{uid}_v{version}'

    def _emit_to_sid(self, event, payload, sid, generation):
        with self.lock:
            if not self._live(sid, generation):
                return False
            self.socketio.emit(event, payload, to=sid, namespace='/')
            return True

    def _emit_current(self, event, payload):
        sid = socket_sid()
        with self.lock:
            return self._emit_to_sid(event, payload, sid, self.generations.get(sid))

    def _room_error_is_disconnect(self, exc, sid, *, connecting=False):
        # These are the two missing-connection paths in the pinned Socket.IO manager.
        # An unrelated ValueError/KeyError is a bug, even if a disconnect also happened.
        missing_connection = (
            isinstance(exc, ValueError) and str(exc) == 'sid is not connected to requested namespace'
        ) or (isinstance(exc, KeyError) and exc.args in ((sid,), ('/',), (None,)))
        return missing_connection and not self._connected(sid, connecting=connecting)

    def _enter_room(self, room, *, sid=None, generation=None, intent=None, connecting=False):
        sid = sid or socket_sid()
        with self.lock:
            generation = generation or self.generations.get(sid)
            if not self._live(sid, generation, connecting=connecting):
                self._remove_client(sid, generation)
                raise ChatAccessError('Cần kết nối chat được xác thực', 401)
            if intent is not None and self.room_intents[sid].get(room) is not intent:
                raise ChatAccessError('Yêu cầu vào phòng đã được thay thế', 409)
            try:
                self.socketio.server.enter_room(sid, room, namespace='/')
            except (ValueError, KeyError) as exc:
                if not self._room_error_is_disconnect(exc, sid, connecting=connecting):
                    raise
                self._remove_client(sid, generation)
                raise ChatAccessError('Kết nối chat đã đóng', 401) from exc
            if not self._live(sid, generation, connecting=connecting):
                self._remove_client(sid, generation)
                raise ChatAccessError('Kết nối chat đã đóng', 401)
            if room not in self.socketio.server.rooms(sid, namespace='/'):
                raise ChatAccessError('Không thể vào phòng chat', 503)
            self.joined[sid].add(room)
            return True

    def _leave_room(self, sid, room):
        with self.lock:
            try:
                self.socketio.server.leave_room(sid, room, namespace='/')
            except (ValueError, KeyError) as exc:
                if not self._room_error_is_disconnect(exc, sid):
                    raise
                self._remove_client(sid)
                return False
            if room in self.socketio.server.rooms(sid, namespace='/'):
                raise ChatAccessError('Không thể rời phòng chat', 503)
            rooms = self.joined.get(sid)
            if rooms is not None:
                rooms.discard(room)
            return self._connected(sid)

    def handle_connect(self, auth=None):
        sid = socket_sid()
        auth = auth if isinstance(auth, dict) else {}
        generation = None
        accepted = False
        try:
            if current_app.config.get('WTF_CSRF_ENABLED', True):
                validate_csrf(auth.get('csrf_token'))
            actor = get_identity(auth.get('auth_token'))
            access = ConversationService.get_access(session_id=actor.guest_id, actor=actor) if actor.guest_id else None
            with self.lock:
                if self.closed or not self._connected(sid, connecting=True):
                    return False
                generation = object()
                self.clients[sid] = actor
                self.joined[sid] = set()
                self.generations[sid] = generation
                self.room_intents[sid] = {}
                if access is not None:
                    self._enter_room(access.room, sid=sid, generation=generation, connecting=True)
            if actor.user_id is not None:
                ChatService.update_last_seen(actor.user_id, actor=actor)
            with self.lock:
                accepted = self._live(sid, generation, connecting=True)
                return accepted
        except (ChatAccessError, ValidationError, CSRFValidationError):
            return False
        except psycopg2.Error:
            current_app.logger.exception('Chat socket connection authentication failed')
            return False
        finally:
            if not accepted and generation is not None:
                self._remove_client(sid, generation)

    def _revoke(self, sid, generation=None):
        with self.lock:
            if generation is not None and self.generations.get(sid) is not generation:
                return
            self._remove_client(sid, generation)
            self.socketio.server.disconnect(sid, namespace='/')

    def revoke_user(self, user_id):
        with self.lock:
            for sid, actor in list(self.clients.items()):
                if actor.user_id == user_id:
                    self._revoke(sid, self.generations.get(sid))

    def _remove_client(self, sid, generation=None, *, disconnecting=False):
        with self.lock:
            if generation is not None and self.generations.get(sid) is not generation:
                return
            current_generation = self.generations.get(sid)
            self.mesh_calls.on_disconnect(sid, current_generation)
            self.clients.pop(sid, None)
            self.generations.pop(sid, None)
            self.room_intents.pop(sid, None)
            rooms = self.joined.pop(sid, set())
            if not disconnecting:
                for room in rooms:
                    self._leave_room(sid, room)
            for call_id, call in list(self.calls.items()):
                if sid in call['sids']:
                    self._finish_call(call_id, 'call_ended', sid, reason='disconnected')

    def handle_disconnect(self, reason=None):
        self._remove_client(socket_sid(), disconnecting=True)

    def evict_conversation_user(self, cid, uid):
        room = f'conv_{cid}'
        with self.lock:
            self.mesh_calls.evict(cid, uid)
            for sid, actor in list(self.clients.items()):
                if actor.user_id == uid:
                    self.room_intents[sid][room] = object()  # Supersede an in-flight join/ACL check.
                    self._leave_delivery_room(cid, sid)
                    self._leave_room(sid, room)
                    for call_id, call in list(self.calls.items()):
                        if call['conversation_id'] == cid and sid in call['sids']:
                            self._finish_call(call_id, 'call_ended', sid, reason='left_conversation')

    def _enter_delivery_room(self, access, *, sid=None, generation=None, connecting=False, intent=None):
        if access.conversation_id is None or access.actor.user_id is None:
            return None
        sid = sid or socket_sid()
        room = self._delivery_room(access.conversation_id, access.actor.user_id, access.actor.auth_version)
        with self.lock:
            if intent is not None and self.room_intents.get(sid, {}).get(access.room) is not intent:
                raise ChatAccessError('Yêu cầu vào phòng đã được thay thế', 409)
            if access.room not in self.joined.get(sid, set()):
                raise ChatAccessError('Phòng nội dung đã đóng', 409)
            self._enter_room(room, sid=sid, generation=generation, connecting=connecting)
        return room

    def _leave_delivery_room(self, conversation_id, sid):
        with self.lock:
            actor = self.clients.get(sid)
        if conversation_id is None or actor is None or actor.user_id is None:
            return
        room = self._delivery_room(conversation_id, actor.user_id, actor.auth_version)
        self._leave_room(sid, room)

    def _access(self, data, permission='read'):
        sid = socket_sid()
        with self.lock:
            generation = self.generations.get(sid)
        access = ConversationService.get_access(
            data.get('conversation_id'), data.get('session_id'), actor=self._actor(sid), permission=permission
        )
        with self.lock:
            if not self._live(sid, generation):
                self._remove_client(sid, generation)
                raise ChatAccessError('Kết nối chat đã đóng', 401)
        return access

    def _block_delivery(self, access, sid, generation, blocked_rooms):
        with self.lock:
            if self.generations.get(sid) is not generation:
                return
            actor = self.clients.get(sid)
            if access.conversation_id is not None and actor is not None and actor.user_id is not None:
                blocked_rooms.add(self._delivery_room(access.conversation_id, actor.user_id, actor.auth_version))

    def _broadcast(self, event, payload, access, exclude_sid=None, *, participants_only=False, queued_room=False):
        # Snapshot only routing candidates. Refresh outside the lock, then recheck the
        # same connection AND room intent under the lock immediately before enqueueing.
        room = access.room
        blocked_rooms = set()
        with self.lock:
            recipients = [
                (sid, self.generations.get(sid), self.room_intents.get(sid, {}).get(room))
                for sid, actor in self.clients.items()
                if sid != exclude_sid
                and (
                    (participants_only and actor.user_id is not None)
                    or (
                        not participants_only
                        and (room in self.joined.get(sid, set()) or (access.conversation_id is None and actor.is_admin))
                    )
                )
            ]
        for sid, generation, intent in recipients:
            try:
                with self.lock:
                    if not self._live(sid, generation):
                        continue
                actor = self._actor(sid)
                recipient_access = ConversationService.get_access(
                    access.conversation_id,
                    access.session_id,
                    actor=actor,
                    permission='read_receipt' if participants_only else 'read',
                )
            except ChatAccessError as exc:
                with self.lock:
                    if self.generations.get(sid) is not generation:
                        continue
                    if queued_room:
                        self._block_delivery(access, sid, generation, blocked_rooms)
                    try:
                        if exc.status == 401:
                            self._revoke(sid, generation)
                        elif not participants_only and self.room_intents.get(sid, {}).get(room) is intent:
                            self.room_intents[sid][room] = object()
                            self._leave_delivery_room(access.conversation_id, sid)
                            self._leave_room(sid, room)
                    except Exception:
                        if not queued_room:
                            raise
                        current_app.logger.exception('Chat recipient cleanup failed; delivery remains blocked')
                continue
            except psycopg2.Error:
                current_app.logger.exception('Chat recipient authorization failed')
                if queued_room:
                    self._block_delivery(access, sid, generation, blocked_rooms)
                continue
            with self.lock:
                if not self._live(sid, generation) or recipient_access.room != room:
                    continue
                if self.room_intents.get(sid, {}).get(room) is not intent:
                    continue
                if participants_only:
                    # A support admin with read access but no Participants row is NOT
                    # eligible for numeric sidebar invalidations.
                    if recipient_access.actor.user_id is None or not recipient_access.role:
                        continue
                elif room not in self.joined.get(sid, set()) and not (
                    access.conversation_id is None and recipient_access.actor.is_admin
                ):
                    continue
                self.clients[sid] = recipient_access.actor
                if not queued_room:
                    self._emit_to_sid(event, payload, sid, generation)
        if queued_room:
            if access.conversation_id is None or participants_only:
                raise RuntimeError('Queued room publication requires a numeric content scope')
            try:
                targets = ConversationService.get_publication_targets(access.conversation_id)
            except psycopg2.Error:
                current_app.logger.exception('Chat publication target query failed after mutation commit')
                return
            rooms = [
                self._delivery_room(access.conversation_id, item['user_id'], item['auth_version']) for item in targets
            ]
            rooms = [destination for destination in rooms if destination not in blocked_rooms]
            if rooms:
                self.socketio.emit(event, payload, to=rooms, namespace='/')

    def _publish_committed(self, event, payload, access, **options):
        try:
            self._broadcast(event, payload, access, **options)
        except Exception:
            current_app.logger.exception('Committed chat mutation could not be published (%s)', event)

    def publish_conversation_updated(self, access):
        """Post-commit numeric invalidation; no message, sender or participant data."""
        if access.conversation_id is not None:
            cid = positive_int(access.conversation_id, 'Cuộc trò chuyện', 2147483647)
            self._publish_committed('conversation_updated', {'conversation_id': cid}, access, participants_only=True)

    def publish_message(self, result):
        if not result.get('success'):
            return
        from app.services.conversation_service import ChatAccess, ChatIdentity

        access = ChatAccess(
            ChatIdentity(result.get('user_id')), result.get('conversation_id'), result.get('session_id')
        )
        payload = {key: value for key, value in result.items() if key not in {'success', 'message'}}
        self._publish_committed('new_message', payload, access, queued_room=access.conversation_id is not None)
        self.publish_conversation_updated(access)

    def publish_recall(self, message_id, access):
        """Call after recall succeeds, with the message's authorized pre-delete scope."""
        self._publish_committed(
            'message_recalled',
            {'message_id': message_id, 'conversation_id': access.conversation_id, 'session_id': access.session_id},
            access,
        )
        self.publish_conversation_updated(access)

    def publish_read_receipt(self, access):
        """Call only after a participant read receipt was committed successfully."""
        if access.conversation_id is None:
            return
        self._publish_committed(
            'messages_read', {'conversation_id': access.conversation_id, 'user_id': access.actor.user_id}, access
        )
        self.publish_conversation_updated(access)

    def _room_intent(self, data):
        if not isinstance(data, dict):
            return None, None
        cid, session_id = data.get('conversation_id'), data.get('session_id')
        with self.lock:
            sid = socket_sid()
            actor = self.clients.get(sid)
            generation = self.generations.get(sid)
            if actor is None or not self._live(sid, generation):
                return None, None
            if cid not in (None, '') and re.fullmatch(r'[0-9]+', str(cid)):
                room = f'conv_{int(cid)}'
            else:
                room = f'support_{cid or session_id or actor.guest_id}'
            intent = object()
            self.room_intents[sid][room] = intent
        return generation, intent

    def handle_join_conversation(self, data=None):
        # Record both joins and leaves before slow authentication; newest intent wins.
        generation, intent = self._room_intent(data)
        return self._join_conversation(data, generation=generation, intent=intent)

    @guarded_event
    def _join_conversation(self, data, *, generation=None, intent=None):
        access = self._access(data)
        sid = socket_sid()
        with self.lock:
            self._enter_room(access.room, sid=sid, generation=generation, intent=intent)
            try:
                self._enter_delivery_room(access, sid=sid, generation=generation, intent=intent)
                if intent is not None and self.room_intents.get(sid, {}).get(access.room) is not intent:
                    raise ChatAccessError('Yêu cầu vào phòng đã được thay thế', 409)
            except Exception:
                if self.generations.get(sid) is generation and (
                    intent is None or self.room_intents.get(sid, {}).get(access.room) is intent
                ):
                    self._leave_delivery_room(access.conversation_id, sid)
                    self._leave_room(sid, access.room)
                raise
        return {'success': True, 'conversation_id': access.conversation_id, 'session_id': access.session_id}

    def handle_leave_conversation(self, data=None):
        generation, intent = self._room_intent(data)
        return self._leave_conversation(data, generation=generation, intent=intent)

    @guarded_event
    def _leave_conversation(self, data, *, generation=None, intent=None):
        access = self._access(data)
        sid = socket_sid()
        with self.lock:
            if not self._live(sid, generation):
                raise ChatAccessError('Kết nối chat đã đóng', 401)
            if self.room_intents.get(sid, {}).get(access.room) is not intent:
                raise ChatAccessError('Yêu cầu rời phòng đã được thay thế', 409)
            self._leave_delivery_room(access.conversation_id, sid)
            if not self._leave_room(sid, access.room):
                self._remove_client(sid, generation)
                raise ChatAccessError('Kết nối chat đã đóng', 401)
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
            self._emit_current('error', {'success': False, 'message': result.get('message'), 'status': 503})
            return result
        self.publish_message(result)
        try:
            self._emit_current('message_sent', {'success': True, 'id': result['id']})
        except Exception:
            current_app.logger.exception('Committed chat message acknowledgement notice could not be delivered')
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
        self.publish_recall(mid, access)
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
        self.publish_read_receipt(access)
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
        self._emit_current(
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
                if not self._call_live(call):
                    raise ChatAccessError('Kết nối cuộc gọi đã đóng', 409)
            except ChatAccessError as exc:
                self._finish_call(call_id, 'call_ended', None, reason='access_revoked')
                if exc.status == 401:
                    self._revoke(sid)
                if sid == socket_sid():
                    raise
                raise ChatAccessError('Người tham gia đã mất quyền truy cập', 409) from exc
        return call_id, call

    def _call_live(self, call):
        return self.calls.get(call['id']) is call and all(
            self._live(sid, generation) for sid, generation in zip(call['sids'], call['generations'], strict=True)
        )

    def _signal(self, event, payload, call):
        with self.lock:
            actor = self._actor()
            if not self._call_live(call):
                self._finish_call(call['id'], 'call_ended', None, reason='disconnected')
                raise ChatAccessError('Kết nối cuộc gọi đã đóng', 409)
            peer_sid = next(sid for sid in call['sids'] if sid != socket_sid())
            payload = {
                **payload,
                'conversation_id': call['conversation_id'],
                'call_id': call['id'],
                'sender_id': actor.user_id,
                'user_id': actor.user_id,
                'sender_name': actor.name,
            }
            self._emit_to_sid(event, payload, peer_sid, self.generations[peer_sid])

    def _finish_call(self, call_id, event, sender_sid, reason=None):
        with self.lock:
            call = self.calls.pop(call_id, None)
            if call is None:
                return
            timer = call.get('timer')
            if timer is not None:
                timer.cancel()
            payload = {'call_id': call_id, 'conversation_id': call['conversation_id'], 'reason': reason}
            for sid, generation in zip(call['sids'], call['generations'], strict=True):
                if sid != sender_sid:
                    self._emit_to_sid(event, payload, sid, generation)

    @guarded_event
    def handle_call_user(self, data):
        caller_sid = socket_sid()
        with self.lock:
            caller_generation = self.generations.get(caller_sid)
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
            if (
                access.actor.user_id in occupied
                or peer_uid in occupied
                or self.mesh_calls.busy(access.actor.user_id)
                or self.mesh_calls.busy(peer_uid)
            ):
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
            peer_generation = self.generations.get(peer_sid)
            if not self._live(caller_sid, caller_generation) or not self._live(peer_sid, peer_generation):
                raise ChatAccessError('Kết nối cuộc gọi đã đóng', 409)
            call = {
                'id': call_id,
                'conversation_id': access.conversation_id,
                'sids': (caller_sid, peer_sid),
                'generations': (caller_generation, peer_generation),
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

    def _mesh_context(self):
        sid = socket_sid()
        with self.lock:
            generation = self.generations.get(sid)
        return self._actor(sid), sid, generation

    @guarded_event
    def handle_group_call_start(self, data):
        actor, sid, generation = self._mesh_context()
        return self.mesh_calls.start(actor, sid, generation, data)

    @guarded_event
    def handle_group_call_join(self, data):
        actor, sid, generation = self._mesh_context()
        return self.mesh_calls.join(actor, sid, generation, data)

    @guarded_event
    def handle_group_call_leave(self, data):
        actor, sid, generation = self._mesh_context()
        return self.mesh_calls.leave(actor, sid, generation, data)

    @guarded_event
    def handle_group_call_signal(self, data):
        actor, sid, generation = self._mesh_context()
        return self.mesh_calls.signal(actor, sid, generation, data)

    @guarded_event
    def handle_stream_status(self, data):
        if self.mesh_calls.contains(data.get('call_id')):
            actor, sid, generation = self._mesh_context()
            return self.mesh_calls.stream_status(actor, sid, generation, data)
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
        if self.mesh_calls.contains(data.get('call_id')):
            actor, sid, generation = self._mesh_context()
            return self.mesh_calls.call_chat_message(actor, sid, generation, data)
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
        if self.mesh_calls.contains(data.get('call_id')):
            actor, sid, generation = self._mesh_context()
            return self.mesh_calls.media_status(actor, sid, generation, data)
        if data.get('type') not in {'mic', 'cam'} or not isinstance(data.get('enabled'), bool):
            raise ValidationError('Trạng thái phương tiện không hợp lệ')
        revision = data.get('revision')
        if revision is not None and (type(revision) is not int or not 1 <= revision <= 2147483647):
            raise ValidationError('Thứ tự trạng thái phương tiện không hợp lệ')
        with self.lock:
            _, call = self._lookup_call(data, active=True)
            payload = {'type': data['type'], 'enabled': data['enabled']}
            if revision is not None:
                payload['revision'] = revision
            self._signal('media_status', payload, call)
        return {'success': True}


def register_socket_events(socketio, app: Flask):
    handlers = ChatSocketHandlers(socketio, app)
    app.extensions['chat_socket_handlers'] = handlers
    handlers.register_all()
    return handlers
