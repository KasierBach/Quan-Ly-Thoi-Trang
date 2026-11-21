"""Process-local, SID-bound group calls. Socket.IO ACK adapters live in sockets.py."""

from contextlib import nullcontext
from dataclasses import dataclass, field
import hashlib
import math
import re
import secrets
from threading import Timer

from app.services.conversation_service import ChatAccessError, ConversationService
from app.validation import ValidationError, positive_int, required_text


@dataclass
class CallMember:
    user_id: int
    sid: str
    generation: object
    name: str
    conversation_role: str
    status: str = 'invited'
    admission_rank: int = 0
    invite_id: str | None = None
    deadline: float | None = None
    timer: object | None = None
    accepted_invite_id: str | None = None
    media_revision: int = 0
    mic_enabled: bool = False
    cam_enabled: bool = False
    is_sharing: bool = False
    media_revisions: dict[str, int] = field(default_factory=dict)


@dataclass
class PeerPair:
    pair_id: str
    peer_revision: int
    offerer_user_id: int
    user_ids: tuple[int, int]
    offered: bool = False
    awaiting_answer: bool = False
    offer_digest: str | None = None
    ice_keys: dict = field(default_factory=dict)


@dataclass
class CallRoom:
    call_id: str
    conversation_id: int
    owner_id: int
    is_video: bool
    request_id: str | None
    invite_user_ids: tuple[int, ...]
    status: str = 'waiting'
    revision: int = 1
    next_rank: int = 1
    next_peer_revision: int = 1
    members: dict[int, CallMember] = field(default_factory=dict)
    pairs: dict[str, PeerPair] = field(default_factory=dict)


class MeshCallRegistry:
    """One authoritative process per call; a message queue does not share this store.

    gateway supplies lock, clients, generations, calls (the private-call registry),
    clock, _actor(sid), _live(sid, generation), and _emit_to_sid(...).
    Public mutations take (actor, sid, generation, data); actor is always refreshed
    from that SID. No request globals, event decorators, or imports from sockets.py.
    """

    MAX_PARTICIPANTS = 4
    MAX_REVISION = 2147483647
    TOKEN_PATTERN = r'[A-Za-z0-9_-]{16,64}'

    def __init__(self, gateway, *, clock=None, timer_factory=Timer, invite_timeout=30, authorize=None):
        if isinstance(invite_timeout, bool) or not isinstance(invite_timeout, (int, float)):
            raise ValueError('invite_timeout must be a positive finite number')
        if not math.isfinite(invite_timeout) or invite_timeout <= 0:
            raise ValueError('invite_timeout must be a positive finite number')
        self.gateway = gateway
        self.lock = gateway.lock
        self.clock = clock or gateway.clock
        self.timer_factory = timer_factory
        self.invite_timeout = invite_timeout
        self.authorize = authorize or ConversationService.get_access
        self.calls: dict[str, CallRoom] = {}
        self.by_conversation: dict[int, str] = {}
        self.by_user: dict[int, str] = {}
        self.terminal_calls: dict[str, None] = {}
        self.closed = False

    @classmethod
    def _token(cls, value, label):
        if not isinstance(value, str) or not re.fullmatch(cls.TOKEN_PATTERN, value):
            raise ValidationError(f'{label} không hợp lệ')
        return value

    def _scope(self, data):
        if not isinstance(data, dict):
            raise ValidationError('Dữ liệu cuộc gọi không hợp lệ')
        return self._token(data.get('call_id'), 'Mã cuộc gọi'), positive_int(
            data.get('conversation_id'), 'Cuộc trò chuyện', self.MAX_REVISION
        )

    def _connection(self, actor, sid, generation):
        if self.closed or not self.gateway._live(sid, generation):
            raise ChatAccessError('Kết nối cuộc gọi đã đóng', 401)
        current = self.gateway._actor(sid)
        if current.user_id is None or current.user_id != getattr(actor, 'user_id', None):
            raise ChatAccessError('Cần kết nối tài khoản được xác thực', 401)
        if not self.gateway._live(sid, generation):
            raise ChatAccessError('Kết nối cuộc gọi đã đóng', 401)
        return current

    def _access(self, conversation_id, actor, sid, generation):
        current = self._connection(actor, sid, generation)
        access = self.authorize(conversation_id, actor=current, permission='group_call')
        if (
            access.conversation_id != conversation_id
            or access.conversation_type != 'group'
            or not access.role
            or access.actor.user_id != current.user_id
        ):
            raise ChatAccessError('Cuộc gọi nhóm chỉ dành cho thành viên đã đăng nhập')
        if self.closed or not self.gateway._live(sid, generation):
            raise ChatAccessError('Kết nối cuộc gọi đã đóng', 401)
        if self.gateway.clients[sid].user_id != current.user_id:
            raise ChatAccessError('Kết nối tài khoản đã được thay thế', 401)
        return access

    @staticmethod
    def _name(actor):
        return str(actor.name or 'Người dùng').replace('\x00', '')[:200]

    def contains(self, call_id):
        with self.lock:
            return not self.closed and call_id in self.calls

    def busy(self, user_id):
        with self.lock:
            self._expire_due()
            return user_id in self.by_user or any(
                user_id in call.get('user_ids', ()) for call in self.gateway.calls.values()
            )

    def _selected_peer(self, conversation_id, user_id):
        for sid, candidate in sorted(list(self.gateway.clients.items())):
            if candidate.user_id != user_id:
                continue
            generation = self.gateway.generations.get(sid)
            try:
                access = self._access(conversation_id, candidate, sid, generation)
            except ChatAccessError:
                continue
            if access.role is None:
                continue
            return CallMember(user_id, sid, generation, self._name(access.actor), access.role)
        raise ChatAccessError('Một người được mời chưa kết nối hoặc không có quyền', 409)

    def start(self, actor, sid, generation, data):
        call_id, cid = self._scope(data)
        invites = data.get('invite_user_ids')
        if not isinstance(invites, list) or not 1 <= len(invites) <= self.MAX_PARTICIPANTS - 1:
            raise ValidationError('Cần mời từ một đến ba thành viên')
        invite_ids = tuple(positive_int(uid, 'Thành viên', self.MAX_REVISION) for uid in invites)
        if len(set(invite_ids)) != len(invite_ids) or getattr(actor, 'user_id', None) in invite_ids:
            raise ValidationError('Danh sách mời không được trùng hoặc chứa người gọi')
        video = data.get('isVideo', True)
        if not isinstance(video, bool):
            raise ValidationError('Loại cuộc gọi không hợp lệ')
        request_id = data.get('request_id')
        if request_id is not None:
            self._token(request_id, 'Mã yêu cầu')
        with self.lock:
            self._expire_due()
            access = self._access(cid, actor, sid, generation)
            existing = self.calls.get(call_id)
            if existing is not None:
                _, member = self._lookup(actor, sid, generation, data)
                if (
                    member.status != 'joined'
                    or existing.owner_id != access.actor.user_id
                    or existing.request_id != request_id
                    or existing.invite_user_ids != invite_ids
                    or existing.is_video != video
                ):
                    raise ChatAccessError('Mã cuộc gọi đã được sử dụng', 409)
                return self._ack(existing, sid)
            if call_id in self.terminal_calls or call_id in self.gateway.calls or cid in self.by_conversation:
                raise ChatAccessError('Cuộc gọi đã kết thúc hoặc phòng đang có cuộc gọi', 409)
            owner_id = access.actor.user_id
            owner_role = access.role
            if owner_id is None or owner_role is None:
                raise ChatAccessError('Cần kết nối tài khoản được xác thực', 401)
            if any(self.busy(uid) for uid in (owner_id, *invite_ids)):
                raise ChatAccessError('Một người tham gia đang bận', 409)
            owner = CallMember(owner_id, sid, generation, self._name(access.actor), owner_role, status='joined')
            invited = [self._selected_peer(cid, uid) for uid in invite_ids]
            # Slow peer authorization must never commit a stale caller or selected tab.
            for member in [owner, *invited]:
                refreshed = self._access(cid, self.gateway.clients.get(member.sid), member.sid, member.generation)
                if refreshed.role is None:
                    raise ChatAccessError('Cuộc gọi nhóm chỉ dành cho thành viên đã đăng nhập')
                member.name = self._name(refreshed.actor)
                member.conversation_role = refreshed.role
            if any(self.busy(member.user_id) for member in [owner, *invited]):
                raise ChatAccessError('Một người tham gia đang bận', 409)
            room = CallRoom(call_id, cid, owner.user_id, video, request_id, invite_ids)
            room.members[owner.user_id] = owner
            for member in invited:
                member.invite_id = secrets.token_hex(16)
                member.deadline = self.clock() + self.invite_timeout
                room.members[member.user_id] = member
            self.calls[call_id] = room
            self.by_conversation[cid] = call_id
            for member in room.members.values():
                self.by_user[member.user_id] = call_id
            try:
                for member in invited:
                    self._schedule(room, member)
                    if not self.gateway._emit_to_sid(
                        'group_call_invited',
                        {
                            'call_id': call_id,
                            'conversation_id': cid,
                            'invite_id': member.invite_id,
                            'isVideo': video,
                            'sender_id': owner.user_id,
                            'sender_name': owner.name,
                        },
                        member.sid,
                        member.generation,
                    ):
                        self._drop(room, member, 'disconnected')
                self._publish(room)
            except Exception:
                self._end(room, 'start_failed')
                raise
            if self.calls.get(call_id) is not room:
                raise ChatAccessError('Không còn người nhận kết nối', 409)
            return self._ack(room, sid)

    def _lookup(self, actor, sid, generation, data, *, joined=False, refresh_room=True):
        call_id, cid = self._scope(data)
        current = self._connection(actor, sid, generation)
        self._expire_due()
        room = self.calls.get(call_id)
        member = room.members.get(current.user_id) if room is not None else None
        if room is None or room.conversation_id != cid or member is None:
            raise ChatAccessError('Cuộc gọi không tồn tại trên kết nối này', 409)
        if member.sid != sid or member.generation is not generation:
            raise ChatAccessError('Cuộc gọi thuộc kết nối khác của tài khoản', 409)
        if refresh_room:
            self._refresh(room)
        else:
            try:
                self._access(cid, current, sid, generation)
            except ChatAccessError:
                self._drop(room, member, 'access_revoked')
                self._publish(room)
                raise
        if self.calls.get(call_id) is not room or room.members.get(current.user_id) is not member:
            raise ChatAccessError('Thành viên không còn trong cuộc gọi', 409)
        if joined and (room.status != 'active' or member.status != 'joined'):
            raise ChatAccessError('Cuộc gọi chưa được chấp nhận', 409)
        return room, member

    def join(self, actor, sid, generation, data):
        invite_id = self._token(data.get('invite_id') if isinstance(data, dict) else None, 'Mã lời mời')
        with self.lock:
            room, member = self._lookup(actor, sid, generation, data)
            expected = member.invite_id if member.status == 'invited' else member.accepted_invite_id
            if expected is None or not secrets.compare_digest(invite_id, expected):
                raise ChatAccessError('Lời mời không thuộc kết nối này', 409)
            if member.status == 'joined':
                return self._ack(room, sid)
            incumbents = sorted(
                (person for person in room.members.values() if person.status == 'joined'),
                key=lambda person: person.admission_rank,
            )
            self._cancel_timer(member)
            member.accepted_invite_id, member.invite_id = member.invite_id, None
            member.deadline = None
            member.status = 'joined'
            member.admission_rank = room.next_rank
            room.next_rank += 1
            for incumbent in incumbents:
                pair = PeerPair(
                    secrets.token_hex(16),
                    room.next_peer_revision,
                    incumbent.user_id,
                    (incumbent.user_id, member.user_id),
                )
                room.next_peer_revision += 1
                room.pairs[pair.pair_id] = pair
            room.status = 'active'
            room.revision += 1
            self._publish(room)
            if self.calls.get(room.call_id) is not room or room.members.get(member.user_id) is not member:
                raise ChatAccessError('Kết nối cuộc gọi đã đóng', 409)
            return self._ack(room, sid)

    def leave(self, actor, sid, generation, data):
        with self.lock:
            room, member = self._lookup(actor, sid, generation, data)
            self._drop(room, member, 'left')
            self._publish(room)
            return {'success': True, 'call_id': room.call_id, 'conversation_id': room.conversation_id}

    @staticmethod
    def _description(payload, kind):
        if not isinstance(payload, dict) or payload.get('type') != kind:
            raise ValidationError('Mô tả cuộc gọi không hợp lệ')
        sdp = payload.get('sdp')
        if not isinstance(sdp, str) or not sdp.strip() or len(sdp) > 65536 or '\x00' in sdp:
            raise ValidationError('SDP không hợp lệ')
        description: dict[str, str] = {'type': kind, 'sdp': sdp}
        return description  # Preserve the terminating CRLF byte-for-byte.

    @staticmethod
    def _candidate(payload):
        if not isinstance(payload, dict):
            raise ValidationError('ICE không hợp lệ')
        cleaned: dict[str, str | int] = {'candidate': required_text(payload.get('candidate'), 'ICE', 2048)}
        if payload.get('sdpMid') is not None:
            cleaned['sdpMid'] = required_text(payload['sdpMid'], 'ICE mid', 100)
        if payload.get('sdpMLineIndex') is not None:
            index = payload['sdpMLineIndex']
            if type(index) is not int or not 0 <= index <= 100:
                raise ValidationError('ICE index không hợp lệ')
            cleaned['sdpMLineIndex'] = index
        return cleaned

    def signal(self, actor, sid, generation, data):
        self._scope(data)
        kind = data.get('type')
        if not isinstance(kind, str) or kind not in {'offer', 'answer', 'ice'}:
            raise ValidationError('Tín hiệu cuộc gọi không hợp lệ')
        payload = (
            self._candidate(data.get('payload')) if kind == 'ice' else self._description(data.get('payload'), kind)
        )
        target_id = positive_int(data.get('target_user_id'), 'Người nhận', self.MAX_REVISION)
        pair_id = self._token(data.get('pair_id'), 'Mã cặp kết nối')
        revision = data.get('peer_revision')
        if type(revision) is not int or not 1 <= revision <= self.MAX_REVISION:
            raise ValidationError('Thứ tự kết nối không hợp lệ')
        with self.lock:
            room, sender = self._lookup(actor, sid, generation, data, joined=True, refresh_room=False)
            pair = room.pairs.get(pair_id)
            target = room.members.get(target_id)
            if (
                pair is None
                or target is None
                or target.status != 'joined'
                or sender.user_id == target_id
                or set(pair.user_ids) != {sender.user_id, target_id}
            ):
                raise ChatAccessError('Người nhận không thuộc cặp kết nối này', 409)
            # Receiver authorization can remove its pair; recheck the exact objects afterwards.
            try:
                self._access(room.conversation_id, self.gateway.clients.get(target.sid), target.sid, target.generation)
            except ChatAccessError as exc:
                self._drop(room, target, 'access_revoked')
                self._publish(room)
                raise ChatAccessError('Người nhận đã rời cuộc gọi', 409) from exc
            if not self._pair_live(room, pair, sender, target):
                raise ChatAccessError('Cặp kết nối đã đóng', 409)
            if kind == 'offer':
                if sender.user_id != pair.offerer_user_id:
                    raise ChatAccessError('Chỉ người được chỉ định mới được tạo offer', 409)
                sdp = payload.get('sdp')
                if not isinstance(sdp, str):
                    raise ValidationError('SDP không hợp lệ')
                digest = hashlib.sha256(sdp.encode()).hexdigest()
                if revision == pair.peer_revision and pair.offered:
                    if pair.awaiting_answer and digest == pair.offer_digest:
                        return {'success': True, 'call_id': room.call_id, 'peer_revision': revision}
                    raise ChatAccessError('Thứ tự offer đã được sử dụng', 409)
                if revision == pair.peer_revision + 1 and pair.offered and not pair.awaiting_answer:
                    pair.peer_revision = revision
                    room.next_peer_revision = max(room.next_peer_revision, revision + 1)
                    pair.ice_keys.clear()
                    room.revision += 1
                    self._publish(room)
                elif revision != pair.peer_revision:
                    raise ChatAccessError('Offer không khớp thứ tự kết nối', 409)
                if not self._pair_live(room, pair, sender, target):
                    raise ChatAccessError('Cặp kết nối đã đóng', 409)
                pair.offered, pair.awaiting_answer, pair.offer_digest = True, True, digest
            elif revision != pair.peer_revision:
                raise ChatAccessError('Tín hiệu không khớp thứ tự kết nối', 409)
            elif kind == 'answer':
                if sender.user_id == pair.offerer_user_id or not pair.awaiting_answer:
                    raise ChatAccessError('Không chờ câu trả lời từ kết nối này', 409)
                pair.awaiting_answer = False
            else:
                keys = pair.ice_keys.setdefault(sender.user_id, set())
                key = repr(sorted(payload.items()))
                if key in keys:
                    return {'success': True, 'call_id': room.call_id, 'peer_revision': revision}
                if len(keys) >= 128:
                    raise ValidationError('Quá nhiều ICE cho cặp kết nối')
                keys.add(key)
            envelope = {
                'call_id': room.call_id,
                'conversation_id': room.conversation_id,
                'sender_id': sender.user_id,
                'target_user_id': target.user_id,
                'pair_id': pair.pair_id,
                'peer_revision': pair.peer_revision,
                'type': kind,
                'payload': payload,
            }
            if not self.gateway._emit_to_sid('group_call_signal', envelope, target.sid, target.generation):
                self._drop(room, target, 'disconnected')
                self._publish(room)
                raise ChatAccessError('Người nhận đã mất kết nối', 409)
            return {'success': True, 'call_id': room.call_id, 'peer_revision': pair.peer_revision}

    def _pair_live(self, room, pair, sender, target):
        return (
            self.calls.get(room.call_id) is room
            and room.pairs.get(pair.pair_id) is pair
            and all(
                room.members.get(member.user_id) is member
                and member.status == 'joined'
                and self.gateway._live(member.sid, member.generation)
                for member in (sender, target)
            )
        )

    def media_status(self, actor, sid, generation, data):
        self._scope(data)
        kind, enabled, revision = data.get('type'), data.get('enabled'), data.get('revision')
        if not isinstance(kind, str) or kind not in {'mic', 'cam'} or not isinstance(enabled, bool):
            raise ValidationError('Trạng thái phương tiện không hợp lệ')
        if type(revision) is not int or not 1 <= revision <= self.MAX_REVISION:
            raise ValidationError('Thứ tự phương tiện không hợp lệ')
        with self.lock:
            room, member = self._lookup(actor, sid, generation, data)
            if member.status != 'joined':
                raise ChatAccessError('Cuộc gọi chưa được chấp nhận', 409)
            if revision <= member.media_revisions.get(kind, 0):
                return {'success': True, 'call_id': room.call_id}
            member.media_revisions[kind] = revision
            member.media_revision = max(member.media_revision, revision)
            setattr(member, 'mic_enabled' if kind == 'mic' else 'cam_enabled', enabled)
            room.revision += 1
            self._relay(room, member, 'media_status', {'type': kind, 'enabled': enabled, 'revision': revision})
            return {'success': True, 'call_id': room.call_id}

    def stream_status(self, actor, sid, generation, data):
        self._scope(data)
        sharing = data.get('is_streaming')
        if not isinstance(sharing, bool):
            raise ValidationError('Trạng thái chia sẻ không hợp lệ')
        revision = data.get('revision')
        if revision is not None and (type(revision) is not int or not 1 <= revision <= self.MAX_REVISION):
            raise ValidationError('Thứ tự chia sẻ không hợp lệ')
        with self.lock:
            room, member = self._lookup(actor, sid, generation, data)
            if member.status != 'joined':
                raise ChatAccessError('Cuộc gọi chưa được chấp nhận', 409)
            previous = member.media_revisions.get('stream')
            if revision is None and previous is not None:
                return {'success': True, 'call_id': room.call_id}
            if revision is not None and revision <= (previous or 0):
                return {'success': True, 'call_id': room.call_id}
            if revision is not None:
                member.media_revisions['stream'] = revision
            member.is_sharing = sharing
            room.revision += 1
            payload: dict[str, bool | int] = {'is_streaming': sharing}
            if revision is not None:
                payload['revision'] = revision
            self._relay(room, member, 'stream_status', payload)
            return {'success': True, 'call_id': room.call_id}

    def call_chat_message(self, actor, sid, generation, data):
        self._scope(data)
        text = required_text(data.get('text'), 'Tin nhắn cuộc gọi', 1000)
        timestamp = data.get('timestamp')
        if timestamp is not None and (
            type(timestamp) not in {int, float} or not math.isfinite(timestamp) or not 0 <= timestamp <= 2**53 - 1
        ):
            raise ValidationError('Thời gian tin nhắn không hợp lệ')
        with self.lock:
            room, member = self._lookup(actor, sid, generation, data, joined=True)
            self._relay(room, member, 'call_chat_message', {'text': text, 'timestamp': timestamp})
            return {'success': True, 'call_id': room.call_id}

    def relay(self, actor, sid, generation, data, event, payload):
        handlers = {
            'media_status': self.media_status,
            'stream_status': self.stream_status,
            'call_chat_message': self.call_chat_message,
        }
        if (
            not isinstance(event, str)
            or event not in handlers
            or not isinstance(data, dict)
            or not isinstance(payload, dict)
        ):
            raise ValidationError('Tín hiệu phương tiện không hợp lệ')
        return handlers[event](actor, sid, generation, {**payload, **data})

    def _relay(self, room, sender, event, payload):
        for recipient in list(room.members.values()):
            if recipient is sender or recipient.status != 'joined':
                continue
            try:
                self._access(
                    room.conversation_id, self.gateway.clients.get(recipient.sid), recipient.sid, recipient.generation
                )
            except ChatAccessError:
                self._drop(room, recipient, 'access_revoked')
                continue
            if self.calls.get(room.call_id) is not room or room.members.get(sender.user_id) is not sender:
                raise ChatAccessError('Cuộc gọi đã kết thúc', 409)
            if room.members.get(recipient.user_id) is not recipient or recipient.status != 'joined':
                continue
            if not self.gateway._live(sender.sid, sender.generation):
                self._drop(room, sender, 'disconnected')
                self._publish(room)
                raise ChatAccessError('Người gửi đã mất kết nối', 409)
            envelope = {
                **payload,
                'call_id': room.call_id,
                'conversation_id': room.conversation_id,
                'sender_id': sender.user_id,
                'user_id': sender.user_id,
                'sender_name': sender.name,
            }
            if not self.gateway._emit_to_sid(event, envelope, recipient.sid, recipient.generation):
                self._drop(room, recipient, 'disconnected')
        if self.calls.get(room.call_id) is not room:
            raise ChatAccessError('Cuộc gọi đã kết thúc', 409)
        self._publish(room)

    def _snapshot(self, room, viewer_sid=None, reason=None):
        participants = []
        for member in room.members.values():
            public = {
                'user_id': member.user_id,
                'name': member.name,
                'status': member.status,
                'role': 'owner' if member.user_id == room.owner_id else 'member',
                'media_revision': member.media_revision,
                'media_revisions': {kind: member.media_revisions.get(kind, 0) for kind in ('mic', 'cam')},
                'stream_revision': member.media_revisions.get('stream', 0),
                'mic_enabled': member.mic_enabled,
                'cam_enabled': member.cam_enabled,
                'is_sharing': member.is_sharing,
            }
            if member.status == 'invited' and member.sid == viewer_sid:
                public['invite_id'] = member.invite_id
            participants.append(public)
        snapshot = {
            'call_id': room.call_id,
            'conversation_id': room.conversation_id,
            'revision': room.revision,
            'isVideo': room.is_video,
            'status': room.status,
            'participants': participants,
            'pairs': [
                {
                    'pair_id': pair.pair_id,
                    'peer_revision': pair.peer_revision,
                    'offerer_user_id': pair.offerer_user_id,
                    'user_ids': list(pair.user_ids),
                }
                for pair in room.pairs.values()
            ],
        }
        if reason is not None:
            snapshot['reason'] = reason
        return snapshot

    def _ack(self, room, sid):
        return {'success': True, **self._snapshot(room, sid)}

    def _refresh(self, room):
        for member in list(room.members.values()):
            if self.calls.get(room.call_id) is not room:
                return
            try:
                access = self._access(
                    room.conversation_id, self.gateway.clients.get(member.sid), member.sid, member.generation
                )
            except ChatAccessError:
                self._drop(room, member, 'access_revoked')
                continue
            member.name = self._name(access.actor)
            member.conversation_role = access.role

    def _publish(self, room):
        if self.calls.get(room.call_id) is not room:
            return
        self._refresh(room)
        for member in list(room.members.values()):
            if self.calls.get(room.call_id) is not room:
                return
            # A previous recipient's refresh may have removed this selected SID.
            if room.members.get(member.user_id) is not member:
                continue
            try:
                self._access(room.conversation_id, self.gateway.clients.get(member.sid), member.sid, member.generation)
            except ChatAccessError:
                self._drop(room, member, 'access_revoked')
                self._publish(room)
                return
            if self.calls.get(room.call_id) is not room or room.members.get(member.user_id) is not member:
                return
            if not self.gateway._emit_to_sid(
                'group_call_state', self._snapshot(room, member.sid), member.sid, member.generation
            ):
                self._drop(room, member, 'disconnected')
                self._publish(room)
                return

    def _cancel_timer(self, member):
        if member.timer is not None:
            member.timer.cancel()
            member.timer = None

    def _schedule(self, room, member):
        timer = self.timer_factory(
            max(0, member.deadline - self.clock()), self._invite_timeout, args=(room, member, member.invite_id)
        )
        timer.daemon = True
        member.timer = timer
        timer.start()

    def _invite_timeout(self, room, member, invite_id):
        app = getattr(self.gateway, 'app', None)
        with app.app_context() if app is not None else nullcontext():
            with self.lock:
                if (
                    self.closed
                    or self.calls.get(room.call_id) is not room
                    or room.members.get(member.user_id) is not member
                    or member.status != 'invited'
                    or member.invite_id != invite_id
                ):
                    return
                if self.clock() < member.deadline:
                    self._schedule(room, member)
                    return
                self._drop(room, member, 'timeout')
                self._publish(room)

    def _expire_due(self):
        for room in list(self.calls.values()):
            expired = [
                member
                for member in room.members.values()
                if member.status == 'invited' and member.deadline is not None and self.clock() >= member.deadline
            ]
            for member in expired:
                self._drop(room, member, 'timeout')
            if expired:
                self._publish(room)

    def _drop(self, room, member, reason):
        if self.calls.get(room.call_id) is not room or room.members.get(member.user_id) is not member:
            return
        self._cancel_timer(member)
        room.members.pop(member.user_id)
        if self.by_user.get(member.user_id) == room.call_id:
            self.by_user.pop(member.user_id)
        room.pairs = {pair_id: pair for pair_id, pair in room.pairs.items() if member.user_id not in pair.user_ids}
        room.revision += 1
        joined = sorted(
            (person for person in room.members.values() if person.status == 'joined'),
            key=lambda person: person.admission_rank,
        )
        if not joined or (room.status == 'active' and len(joined) < 2) or len(room.members) < 2:
            self._end(room, reason)
        elif member.user_id == room.owner_id:
            room.owner_id = joined[0].user_id
        self.gateway._emit_to_sid(
            'group_call_state',
            {
                'call_id': room.call_id,
                'conversation_id': room.conversation_id,
                'revision': room.revision,
                'isVideo': room.is_video,
                'status': 'ended',
                'participants': [],
                'pairs': [],
                'reason': reason,
            },
            member.sid,
            member.generation,
        )

    def _end(self, room, reason, *, publish=True):
        if self.calls.get(room.call_id) is not room:
            return
        self.calls.pop(room.call_id)
        self.by_conversation.pop(room.conversation_id, None)
        self.terminal_calls[room.call_id] = None
        if len(self.terminal_calls) > 256:
            self.terminal_calls.pop(next(iter(self.terminal_calls)))
        recipients = list(room.members.values())
        for member in recipients:
            self._cancel_timer(member)
            if self.by_user.get(member.user_id) == room.call_id:
                self.by_user.pop(member.user_id)
        room.members.clear()
        room.pairs.clear()
        room.status = 'ended'
        room.revision += 1
        if publish:
            for member in recipients:
                self.gateway._emit_to_sid(
                    'group_call_state', self._snapshot(room, reason=reason), member.sid, member.generation
                )

    def on_disconnect(self, sid, generation=None):
        with self.lock:
            for room in list(self.calls.values()):
                for member in list(room.members.values()):
                    if member.sid == sid and (generation is None or member.generation is generation):
                        self._drop(room, member, 'disconnected')
                        self._publish(room)

    def evict(self, conversation_id, user_id):
        with self.lock:
            call_id = self.by_conversation.get(conversation_id)
            room = self.calls.get(call_id) if call_id is not None else None
            member = room.members.get(user_id) if room is not None else None
            if member is not None:
                self._drop(room, member, 'access_revoked')
                self._publish(room)

    def close(self):
        with self.lock:
            self.closed = True
            for room in list(self.calls.values()):
                self._end(room, 'closed', publish=False)
            self.by_user.clear()
            self.by_conversation.clear()
