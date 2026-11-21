"""Offline mesh contracts: no Flask application, real database, browser, or network."""

from copy import deepcopy
import math
from threading import RLock
from types import SimpleNamespace

import pytest

from app.calls import MeshCallRegistry
from app.services.conversation_service import ChatAccess, ChatAccessError, ChatIdentity
from app.validation import ValidationError


CALL_ID = 'mesh_0123456789abcdef'
OTHER_CALL = 'mesh_abcdef0123456789'
SDP = 'v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n'


class FakeTimer:
    def __init__(self, seconds, callback, args=()):
        self.seconds, self.callback, self.args = seconds, callback, args
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.callback(*self.args)


class FakeGateway:
    def __init__(self):
        self.lock = RLock()
        self.clients = {}
        self.generations = {}
        self.calls = {}
        self.now = 100.0
        self.clock = lambda: self.now
        self.events = []
        self.timers = []
        self.roles = {1: {uid: 'admin' if uid == 1 else 'member' for uid in range(1, 7)}}
        self.auth_hook = None
        self.access_hook = None
        self.registry = None
        for uid in range(1, 7):
            self.connect(uid)

    def connect(self, uid, sid=None, *, name=None, admin=False):
        sid = sid or f'user-{uid}'
        self.clients[sid] = ChatIdentity(uid, is_admin=admin, name=name or f'User {uid}')
        self.generations[sid] = object()
        return sid

    def _live(self, sid, generation):
        return sid in self.clients and generation is not None and self.generations.get(sid) is generation

    def _actor(self, sid):
        if self.auth_hook is not None:
            self.auth_hook(sid)
        if sid not in self.clients:
            raise ChatAccessError('Disconnected', 401)
        return self.clients[sid]

    def _emit_to_sid(self, event, payload, sid, generation):
        if not self._live(sid, generation):
            return False
        self.events.append((event, deepcopy(payload), sid))
        return True

    def authorize(self, cid, *, actor, permission):
        assert permission == 'group_call'
        if self.access_hook is not None:
            self.access_hook(cid, actor)
        role = self.roles.get(cid, {}).get(actor.user_id)
        if actor.user_id is None or role is None:
            raise ChatAccessError('Not a member')
        return ChatAccess(actor, cid, conversation_type='group', role=role, created_by=1)

    def timer_factory(self, seconds, callback, args=()):
        timer = FakeTimer(seconds, callback, args)
        self.timers.append(timer)
        return timer

    def invoke(self, method, uid, data=None, *, sid=None, actor=None, generation=None):
        sid = sid or f'user-{uid}'
        return getattr(self.registry, method)(
            actor or self.clients[sid],
            sid,
            generation if generation is not None else self.generations[sid],
            data or {'call_id': CALL_ID, 'conversation_id': 1},
        )

    def start(self, invites=None, *, uid=1, call_id=CALL_ID, cid=1, **extra):
        return self.invoke(
            'start',
            uid,
            {
                'call_id': call_id,
                'conversation_id': cid,
                'invite_user_ids': invites or [2, 3],
                'isVideo': True,
                **extra,
            },
        )

    def join(self, uid, *, sid=None, call_id=CALL_ID, invite_id=None):
        room = self.registry.calls[call_id]
        member = room.members[uid]
        return self.invoke(
            'join',
            uid,
            {
                'call_id': call_id,
                'conversation_id': room.conversation_id,
                'invite_id': invite_id or member.invite_id or member.accepted_invite_id,
            },
            sid=sid,
        )

    def signal(self, sender, target, *, kind='offer', revision=None, payload=None, pair_id=None):
        room = self.registry.calls[CALL_ID]
        pair = next(pair for pair in room.pairs.values() if set(pair.user_ids) == {sender, target})
        return self.invoke(
            'signal',
            sender,
            {
                'call_id': CALL_ID,
                'conversation_id': 1,
                'pair_id': pair_id or pair.pair_id,
                'target_user_id': target,
                'peer_revision': revision if revision is not None else pair.peer_revision,
                'type': kind,
                'payload': payload if payload is not None else {'type': kind, 'sdp': SDP},
            },
        )

    def only(self, event):
        return [(payload, sid) for name, payload, sid in self.events if name == event]


@pytest.fixture
def mesh():
    gateway = FakeGateway()
    gateway.registry = MeshCallRegistry(
        gateway, timer_factory=gateway.timer_factory, authorize=gateway.authorize, invite_timeout=30
    )
    yield gateway
    gateway.registry.close()


def trio(mesh):
    mesh.start()
    mesh.join(2)
    mesh.join(3)
    return mesh.registry.calls[CALL_ID]


@pytest.mark.parametrize('timeout', [True, '30', 0, -1, math.inf, math.nan])
def test_registry_rejects_invalid_invite_timeout_without_state(mesh, timeout):
    with pytest.raises(ValueError, match='invite_timeout'):
        MeshCallRegistry(mesh, timer_factory=mesh.timer_factory, authorize=mesh.authorize, invite_timeout=timeout)


def test_scope_connection_and_access_fail_closed_on_malformed_or_replaced_identity(mesh):
    with pytest.raises(ValidationError):
        mesh.registry._scope([])
    generation = mesh.generations['user-1']
    with pytest.raises(ChatAccessError):
        mesh.registry._connection(ChatIdentity(None), 'user-1', generation)

    stale = mesh.clients['user-1']
    original_actor = mesh._actor

    def replace_after_refresh(sid):
        current = original_actor(sid)
        mesh.clients[sid] = ChatIdentity(6, name='Replacement')
        return current

    mesh.auth_hook = None
    mesh._actor = replace_after_refresh
    with pytest.raises(ChatAccessError, match='thay thế'):
        mesh.registry._access(1, stale, 'user-1', generation)


def test_access_rejects_malformed_authorization_result(mesh):
    generation = mesh.generations['user-1']
    actor = mesh.clients['user-1']
    for access in (
        ChatAccess(actor, 2, conversation_type='group', role='admin'),
        ChatAccess(actor, 1, conversation_type='private', role='admin'),
        ChatAccess(actor, 1, conversation_type='group', role=None),
        ChatAccess(ChatIdentity(2), 1, conversation_type='group', role='member'),
    ):
        registry = MeshCallRegistry(
            mesh, timer_factory=mesh.timer_factory, authorize=lambda *_args, value=access, **_kwargs: value
        )
        with pytest.raises(ChatAccessError):
            registry._access(1, actor, 'user-1', generation)


def test_selected_peer_skips_authorized_connection_without_role(mesh):
    original = mesh.registry.authorize

    def authorize(cid, *, actor, permission):
        access = original(cid, actor=actor, permission=permission)
        return ChatAccess(access.actor, access.conversation_id, conversation_type='group', role=None)

    mesh.registry.authorize = authorize
    with pytest.raises(ChatAccessError, match='chưa kết nối'):
        mesh.registry._selected_peer(1, 2)


def test_start_rolls_back_room_when_invitation_publish_raises(mesh):
    def failed_emit(*_args, **_kwargs):
        raise RuntimeError('synthetic publish failure')

    mesh._emit_to_sid = failed_emit
    with pytest.raises(RuntimeError, match='synthetic publish failure'):
        mesh.start()
    assert not mesh.registry.calls and not mesh.registry.by_user and not mesh.registry.by_conversation


def test_start_fails_when_every_invitee_disconnects_before_publish(mesh):
    mesh._emit_to_sid = lambda *_args, **_kwargs: False
    with pytest.raises(ChatAccessError, match='Không còn người nhận'):
        mesh.start()
    assert not mesh.registry.calls and not mesh.registry.by_user


def test_join_rechecks_room_after_publish_side_effect(mesh):
    mesh.start()
    original = mesh.registry._publish

    def end_during_publish(room):
        original(room)
        mesh.registry._end(room, 'synthetic')

    mesh.registry._publish = end_during_publish
    with pytest.raises(ChatAccessError, match='đã đóng'):
        mesh.join(2)


def test_signal_failed_target_emit_drops_target_and_preserves_other_pair(mesh):
    room = trio(mesh)
    mesh.events.clear()
    original = mesh._emit_to_sid

    def fail_target(event, payload, sid, generation):
        if event == 'group_call_signal' and sid == 'user-2':
            return False
        return original(event, payload, sid, generation)

    mesh._emit_to_sid = fail_target
    with pytest.raises(ChatAccessError, match='mất kết nối'):
        mesh.signal(1, 2)
    assert set(room.members) == {1, 3}


def test_media_and_stream_reject_invited_member_and_stale_revisions(mesh):
    mesh.start()
    scope = {'call_id': CALL_ID, 'conversation_id': 1}
    with pytest.raises(ChatAccessError, match='chưa được chấp nhận'):
        mesh.invoke('media_status', 2, {**scope, 'type': 'mic', 'enabled': True, 'revision': 1})
    with pytest.raises(ChatAccessError, match='chưa được chấp nhận'):
        mesh.invoke('stream_status', 2, {**scope, 'is_streaming': True, 'revision': 1})

    mesh.invoke('media_status', 1, {**scope, 'type': 'mic', 'enabled': True, 'revision': 2})
    assert mesh.invoke('media_status', 1, {**scope, 'type': 'mic', 'enabled': False, 'revision': 1})['success']
    mesh.invoke('stream_status', 1, {**scope, 'is_streaming': True, 'revision': 2})
    assert mesh.invoke('stream_status', 1, {**scope, 'is_streaming': False, 'revision': 1})['success']
    member = mesh.registry.calls[CALL_ID].members[1]
    assert member.mic_enabled and member.is_sharing


def test_relay_validates_dispatch_and_detects_room_removed_mid_delivery(mesh):
    trio(mesh)
    with pytest.raises(ValidationError):
        mesh.registry.relay(mesh.clients['user-1'], 'user-1', mesh.generations['user-1'], {}, 'unknown', {})

    room = mesh.registry.calls[CALL_ID]

    def close_on_access(cid, actor):
        if actor.user_id == 2:
            mesh.registry._end(room, 'synthetic')

    mesh.access_hook = close_on_access
    with pytest.raises(ChatAccessError, match='không còn'):
        mesh.invoke('call_chat_message', 1, {'call_id': CALL_ID, 'conversation_id': 1, 'text': 'stop'})


def test_snapshot_reason_ack_and_timer_reschedule_boundaries(mesh):
    mesh.start()
    room = mesh.registry.calls[CALL_ID]
    snapshot = mesh.registry._snapshot(room, reason='synthetic')
    assert snapshot['reason'] == 'synthetic'
    assert mesh.registry._ack(room, 'user-2')['participants'][1]['invite_id'] == room.members[2].invite_id

    member = room.members[2]
    timer = member.timer
    member.deadline = mesh.now + 60
    timer.fire()
    assert member.timer is not timer and member.timer.started


def test_invite_timeout_uses_null_context_without_flask_app(mesh):
    mesh.start()
    room = mesh.registry.calls[CALL_ID]
    member = room.members[2]
    mesh.app = None
    mesh.now = member.deadline + 1
    member.timer.fire()
    assert 2 not in room.members


def test_drop_noops_for_retired_member_and_transfers_owner(mesh):
    room = trio(mesh)
    retired = SimpleNamespace(user_id=99)
    revision = room.revision
    mesh.registry._drop(room, retired, 'synthetic')
    assert room.revision == revision
    mesh.registry._drop(room, room.members[1], 'left')
    assert room.owner_id == 2


def test_end_prunes_terminal_history_to_bound(mesh):
    room = trio(mesh)
    mesh.registry.terminal_calls = {f'old_{index:016d}': None for index in range(256)}
    mesh.registry._end(room, 'synthetic')
    assert len(mesh.registry.terminal_calls) == 256
    assert CALL_ID in mesh.registry.terminal_calls


def test_start_binds_unique_users_selected_sids_and_private_busy_reservations(mesh):
    mesh.connect(2, 'z-other-tab')
    result = mesh.start([2, 3, 4])
    assert result['status'] == 'waiting'
    assert len(result['participants']) == 4
    assert result['pairs'] == []
    assert mesh.registry.by_conversation == {1: CALL_ID}
    assert mesh.registry.by_user == {uid: CALL_ID for uid in (1, 2, 3, 4)}
    assert [sid for _, sid in mesh.only('group_call_invited')] == ['user-2', 'user-3', 'user-4']
    assert all(timer.started and timer.daemon for timer in mesh.timers)
    assert not any(sid == 'z-other-tab' for _, _, sid in mesh.events)
    assert mesh.registry.busy(1) and mesh.registry.busy(4) and not mesh.registry.busy(5)


@pytest.mark.parametrize('invites', [[2, 3, 4, 5], [2, 2], [1, 2], [True], ['bad']])
def test_bad_invitation_list_cannot_reserve_or_emit(mesh, invites):
    with pytest.raises(ValidationError):
        mesh.start(invites)
    assert not mesh.registry.calls and not mesh.events


@pytest.mark.parametrize(
    'field,value',
    [
        ('call_id', 'short'),
        ('call_id', 'x' * 65),
        ('conversation_id', True),
        ('isVideo', 1),
        ('request_id', 'x'),
    ],
)
def test_start_validation_is_strict_and_has_no_side_effects(mesh, field, value):
    data = {'call_id': CALL_ID, 'conversation_id': 1, 'invite_user_ids': [2], 'isVideo': True, field: value}
    with pytest.raises(ValidationError):
        mesh.invoke('start', 1, data)
    assert not mesh.registry.calls and not mesh.events


def test_idempotent_start_does_not_fork_ring_or_replace_selected_tab(mesh):
    first = mesh.start(request_id='request_0123456789')
    timers, rings = len(mesh.timers), len(mesh.only('group_call_invited'))
    second = mesh.start(request_id='request_0123456789')
    assert first == second
    assert len(mesh.timers) == timers and len(mesh.only('group_call_invited')) == rings
    mesh.connect(1, 'other-owner-tab')
    with pytest.raises(ChatAccessError):
        mesh.invoke(
            'start',
            1,
            {
                'call_id': CALL_ID,
                'conversation_id': 1,
                'invite_user_ids': [2, 3],
                'request_id': 'request_0123456789',
                'isVideo': True,
            },
            sid='other-owner-tab',
        )
    with pytest.raises(ChatAccessError):
        mesh.start([4], uid=5, call_id=OTHER_CALL)
    with pytest.raises(ChatAccessError):
        mesh.start([2], request_id='request_0123456789')
    assert len(mesh.registry.calls) == 1


@pytest.mark.parametrize('busy_uid', [1, 2])
def test_private_call_reservations_block_mesh_start(mesh, busy_uid):
    mesh.calls['private_0123456789'] = {'user_ids': (busy_uid, 6)}
    with pytest.raises(ChatAccessError, match='bận'):
        mesh.start()
    assert not mesh.registry.calls and not mesh.events


def test_mesh_busy_is_global_across_group_conversations(mesh):
    mesh.start()
    mesh.roles[2] = {uid: 'member' for uid in range(1, 7)}
    with pytest.raises(ChatAccessError, match='bận'):
        mesh.start([2], uid=4, call_id=OTHER_CALL, cid=2)
    assert len(mesh.registry.calls) == 1


@pytest.mark.parametrize('missing_uid', [1, 2])
def test_authenticated_membership_is_required_for_every_invitation(mesh, missing_uid):
    mesh.roles[1].pop(missing_uid)
    mesh.connect(missing_uid, admin=True)
    with pytest.raises(ChatAccessError):
        mesh.start()
    assert not mesh.registry.calls and not mesh.events


def test_guest_forged_actor_and_stale_generation_cannot_start(mesh):
    mesh.connect(None, 'guest')
    with pytest.raises(ChatAccessError):
        mesh.invoke(
            'start',
            None,
            {
                'call_id': CALL_ID,
                'conversation_id': 1,
                'invite_user_ids': [2],
            },
            sid='guest',
        )
    with pytest.raises(ChatAccessError):
        mesh.invoke(
            'start',
            1,
            {
                'call_id': CALL_ID,
                'conversation_id': 1,
                'invite_user_ids': [3],
            },
            actor=mesh.clients['user-2'],
        )
    with pytest.raises(ChatAccessError):
        mesh.invoke(
            'start',
            1,
            {
                'call_id': CALL_ID,
                'conversation_id': 1,
                'invite_user_ids': [2],
            },
            generation=object(),
        )
    assert not mesh.events


def test_join_requires_selected_sid_and_exact_invitation_and_is_idempotent(mesh):
    mesh.start()
    mesh.connect(2, 'other-tab')
    invitation = mesh.registry.calls[CALL_ID].members[2].invite_id
    for sid, token in [('other-tab', invitation), ('user-2', 'forged_0123456789')]:
        with pytest.raises(ChatAccessError):
            mesh.join(2, sid=sid, invite_id=token)
    assert mesh.registry.calls[CALL_ID].members[2].status == 'invited'
    answer = mesh.join(2)
    assert answer['status'] == 'active' and len(answer['pairs']) == 1
    assert mesh.timers[0].cancelled
    again = mesh.join(2, invite_id=invitation)
    assert again == answer and len(mesh.registry.calls[CALL_ID].pairs) == 1


def test_four_admissions_build_six_pairs_with_incumbents_as_offerers(mesh):
    mesh.start([2, 3, 4])
    mesh.join(3)
    mesh.join(2)
    result = mesh.join(4)
    room = mesh.registry.calls[CALL_ID]
    assert len(room.pairs) == 6
    ranks = {member.user_id: member.admission_rank for member in room.members.values()}
    for pair in room.pairs.values():
        assert pair.offerer_user_id == min(pair.user_ids, key=ranks.get)
    assert len({pair.peer_revision for pair in room.pairs.values()}) == 6
    assert result['status'] == 'active'
    assert {person['role'] for person in result['participants']} == {'owner', 'member'}
    assert not any(person.get('invite_id') for person in result['participants'])


def test_snapshot_names_are_canonical_text_and_invitation_tokens_are_recipient_only(mesh):
    mesh.connect(2, name='<img src=x onerror=alert(1)>')
    result = mesh.start()
    assert next(person for person in result['participants'] if person['user_id'] == 2)['name'].startswith('<img')
    assert all(
        'invite_id' not in person and 'sid' not in person and 'generation' not in person
        for person in result['participants']
    )
    for state, sid in mesh.only('group_call_state'):
        for person in state['participants']:
            if 'invite_id' in person:
                assert sid == f'user-{person["user_id"]}'


def test_offer_answer_ice_are_canonical_exact_pair_only_and_sdp_crlf_is_preserved(mesh):
    trio(mesh)
    mesh.events.clear()
    mesh.signal(1, 2, payload={'type': 'offer', 'sdp': SDP, 'sender_id': 6})
    mesh.signal(2, 1, kind='answer')
    mesh.signal(
        1, 2, kind='ice', payload={'candidate': 'candidate:local', 'sdpMid': '0', 'sdpMLineIndex': 0, 'user_id': 6}
    )
    signals = mesh.only('group_call_signal')
    assert [sid for _, sid in signals] == ['user-2', 'user-1', 'user-2']
    assert signals[0][0]['sender_id'] == 1 and signals[0][0]['payload'] == {'type': 'offer', 'sdp': SDP}
    assert signals[0][0]['payload']['sdp'].endswith('\r\n')
    assert signals[-1][0]['payload'] == {'candidate': 'candidate:local', 'sdpMid': '0', 'sdpMLineIndex': 0}
    assert not any(sid in {'user-3', 'user-4'} for _, sid in signals)


def test_signal_rejects_invited_other_tab_wrong_pair_scope_and_wrong_offer_role(mesh):
    mesh.start()
    mesh.join(2)
    mesh.connect(2, 'other-tab')
    room = mesh.registry.calls[CALL_ID]
    pair = next(iter(room.pairs.values()))
    base = {
        'call_id': CALL_ID,
        'conversation_id': 1,
        'pair_id': pair.pair_id,
        'peer_revision': pair.peer_revision,
        'target_user_id': 1,
        'type': 'offer',
        'payload': {'type': 'offer', 'sdp': SDP},
    }
    for uid, sid, changes in [
        (2, 'other-tab', {}),
        (3, 'user-3', {}),
        (4, 'user-4', {}),
        (2, 'user-2', {}),
        (1, 'user-1', {'target_user_id': 3}),
        (1, 'user-1', {'target_user_id': 2, 'conversation_id': 2}),
        (1, 'user-1', {'target_user_id': 2, 'pair_id': 'missing_0123456789'}),
    ]:
        with pytest.raises(ChatAccessError):
            mesh.invoke('signal', uid, {**base, **changes}, sid=sid)
    assert not mesh.only('group_call_signal')


@pytest.mark.parametrize(
    'kind,payload',
    [
        ('offer', {'type': 'offer', 'sdp': 'x' * 65537}),
        ('offer', {'type': 'offer', 'sdp': 'v=0\x00\r\n'}),
        ('offer', {'type': 'answer', 'sdp': SDP}),
        ('ice', {'candidate': 'x' * 2049}),
        ('ice', {'candidate': 'candidate:a', 'sdpMLineIndex': True}),
        ('ice', {'candidate': 'candidate:a', 'sdpMLineIndex': 101}),
        ('ice', 'bad'),
    ],
)
def test_malformed_signals_are_rejected_without_relay(mesh, kind, payload):
    trio(mesh)
    with pytest.raises(ValidationError):
        mesh.signal(1, 2, kind=kind, payload=payload)
    assert not mesh.only('group_call_signal')


@pytest.mark.parametrize('boundary', ['identity', 'membership'])
def test_start_disconnect_during_authorization_cannot_reserve_users(mesh, boundary):
    if boundary == 'identity':
        original = mesh._actor

        def disconnect_after_identity(sid):
            actor = original(sid)
            mesh.clients.pop(sid)
            mesh.generations.pop(sid)
            return actor

        mesh._actor = disconnect_after_identity
    else:

        def disconnect_after_membership(cid, actor):
            mesh.clients.pop('user-1', None)
            mesh.generations.pop('user-1', None)

        mesh.access_hook = disconnect_after_membership

    with pytest.raises(ChatAccessError) as failure:
        mesh.start()

    assert failure.value.status == 401
    assert not mesh.registry.calls and not mesh.registry.by_user and not mesh.registry.by_conversation
    assert not mesh.events and not mesh.timers


def test_private_call_winning_during_peer_refresh_aborts_mesh_start(mesh):
    private_call = {'user_ids': (2, 6)}

    def reserve_private_peer(cid, actor):
        if actor.user_id == 2:
            mesh.calls['private_0123456789'] = private_call

    mesh.access_hook = reserve_private_peer
    with pytest.raises(ChatAccessError, match='bận'):
        mesh.start()

    assert mesh.calls['private_0123456789'] is private_call
    assert not mesh.registry.calls and not mesh.registry.by_user
    assert not mesh.events and not mesh.timers


def test_target_revoked_during_signal_authorization_keeps_remaining_mesh_pair(mesh):
    room = trio(mesh)
    mesh.events.clear()

    def revoke_on_directed_check(cid, actor):
        if actor.user_id == 2:
            mesh.roles[cid].pop(2, None)

    mesh.access_hook = revoke_on_directed_check
    with pytest.raises(ChatAccessError, match='Người nhận đã rời') as failure:
        mesh.signal(1, 2)

    assert failure.value.status == 409
    assert set(room.members) == {1, 3}
    assert [set(pair.user_ids) for pair in room.pairs.values()] == [{1, 3}]
    assert not mesh.only('group_call_signal')


def test_ice_revalidates_exact_pair_without_unrelated_member_queries(mesh):
    trio(mesh)
    authorized = []
    mesh.access_hook = lambda cid, actor: authorized.append(actor.user_id)

    assert mesh.signal(1, 2, kind='ice', payload={'candidate': 'candidate:bounded-pair'})['success']

    assert authorized == [1, 2]
    assert mesh.only('group_call_signal')[-1][1] == 'user-2'


def test_conflicting_offer_retry_cannot_replace_pending_or_completed_description(mesh):
    room = trio(mesh)
    pair = next(pair for pair in room.pairs.values() if set(pair.user_ids) == {1, 2})
    mesh.signal(1, 2)
    digest = pair.offer_digest
    events = len(mesh.only('group_call_signal'))

    with pytest.raises(ChatAccessError, match='offer đã được sử dụng'):
        mesh.signal(1, 2, payload={'type': 'offer', 'sdp': SDP + 'a=sendrecv\r\n'})

    assert pair.offer_digest == digest and pair.awaiting_answer
    assert len(mesh.only('group_call_signal')) == events
    mesh.signal(2, 1, kind='answer')
    with pytest.raises(ChatAccessError, match='offer đã được sử dụng'):
        mesh.signal(1, 2)
    assert pair.offer_digest == digest and not pair.awaiting_answer


def test_recipient_revoked_during_chat_relay_gets_no_content_while_other_peer_continues(mesh):
    room = trio(mesh)
    mesh.events.clear()
    target_checks = 0

    def revoke_on_relay_check(cid, actor):
        nonlocal target_checks
        if actor.user_id == 2:
            target_checks += 1
            if target_checks == 2:
                mesh.roles[cid].pop(2)

    mesh.access_hook = revoke_on_relay_check
    result = mesh.invoke(
        'call_chat_message', 1, {'call_id': CALL_ID, 'conversation_id': 1, 'text': 'Current peers only'}
    )

    assert result['success']
    assert [sid for _, sid in mesh.only('call_chat_message')] == ['user-3']
    assert set(room.members) == {1, 3}


def test_sender_disconnect_during_chat_recipient_refresh_stops_all_content(mesh):
    room = trio(mesh)
    mesh.events.clear()
    target_checks = 0

    def disconnect_on_relay_check(cid, actor):
        nonlocal target_checks
        if actor.user_id == 2:
            target_checks += 1
            if target_checks == 2:
                mesh.clients.pop('user-1')
                mesh.generations.pop('user-1')

    mesh.access_hook = disconnect_on_relay_check
    with pytest.raises(ChatAccessError, match='Người gửi đã mất kết nối'):
        mesh.invoke('call_chat_message', 1, {'call_id': CALL_ID, 'conversation_id': 1, 'text': 'Never delivered'})

    assert not mesh.only('call_chat_message')
    assert set(room.members) == {2, 3}
    assert not mesh.registry.busy(1)


def test_failed_last_peer_chat_delivery_ends_room_without_success_ack(mesh):
    mesh.start([2])
    mesh.join(2)
    mesh.events.clear()
    original = mesh._emit_to_sid

    def fail_chat_delivery(event, payload, sid, generation):
        if event == 'call_chat_message':
            return False
        return original(event, payload, sid, generation)

    mesh._emit_to_sid = fail_chat_delivery
    with pytest.raises(ChatAccessError, match='Cuộc gọi đã kết thúc'):
        mesh.invoke('call_chat_message', 1, {'call_id': CALL_ID, 'conversation_id': 1, 'text': 'No recipient'})

    assert not mesh.only('call_chat_message')
    assert not mesh.registry.calls and not mesh.registry.by_user and not mesh.registry.by_conversation


def test_expired_invites_release_busy_reservations_even_before_timer_dispatch(mesh):
    mesh.start()
    mesh.now += 31

    assert not mesh.registry.busy(2)
    assert not mesh.registry.busy(3)
    assert not mesh.registry.calls and not mesh.registry.by_user and not mesh.registry.by_conversation
    assert all(timer.cancelled for timer in mesh.timers)


def test_negotiation_revisions_answers_and_retries_are_pair_local(mesh):
    room = trio(mesh)
    pair = next(pair for pair in room.pairs.values() if set(pair.user_ids) == {1, 2})
    revision = pair.peer_revision
    other_revisions = {key: other.peer_revision for key, other in room.pairs.items() if other is not pair}
    with pytest.raises(ChatAccessError):
        mesh.signal(2, 1, kind='answer')
    mesh.signal(1, 2)
    count = len(mesh.only('group_call_signal'))
    mesh.signal(1, 2)
    assert len(mesh.only('group_call_signal')) == count
    with pytest.raises(ChatAccessError):
        mesh.signal(1, 2, revision=revision + 1)
    mesh.signal(2, 1, kind='answer')
    with pytest.raises(ChatAccessError):
        mesh.signal(2, 1, kind='answer')
    mesh.signal(1, 2, revision=revision + 1)
    assert pair.peer_revision == revision + 1 and pair.awaiting_answer
    with pytest.raises(ChatAccessError):
        mesh.signal(2, 1, kind='answer', revision=revision)
    with pytest.raises(ChatAccessError):
        mesh.signal(1, 2, kind='ice', revision=revision, payload={'candidate': 'candidate:old'})
    assert {key: other.peer_revision for key, other in room.pairs.items() if other is not pair} == other_revisions


def test_ice_duplicates_and_queue_size_are_bounded_per_sender_pair_revision(mesh):
    trio(mesh)
    mesh.signal(1, 2, kind='ice', payload={'candidate': 'candidate:first'})
    mesh.signal(1, 2, kind='ice', payload={'candidate': 'candidate:first'})
    assert len(mesh.only('group_call_signal')) == 1
    for index in range(127):
        mesh.signal(1, 2, kind='ice', payload={'candidate': f'candidate:{index}'})
    with pytest.raises(ValidationError):
        mesh.signal(1, 2, kind='ice', payload={'candidate': 'candidate:overflow'})
    mesh.signal(1, 3, kind='ice', payload={'candidate': 'candidate:other-pair'})
    assert len(mesh.only('group_call_signal')) == 129


@pytest.mark.parametrize(
    'method,payload,event',
    [
        ('media_status', {'type': 'mic', 'enabled': True, 'revision': 1}, 'media_status'),
        ('stream_status', {'is_streaming': True, 'revision': 1}, 'stream_status'),
    ],
)
def test_status_update_publishes_one_snapshot_per_current_member(mesh, method, payload, event):
    trio(mesh)
    mesh.events.clear()

    assert mesh.invoke(method, 1, {'call_id': CALL_ID, 'conversation_id': 1, **payload})['success']

    assert len(mesh.only(event)) == 2
    assert [sid for _, sid in mesh.only('group_call_state')] == ['user-1', 'user-2', 'user-3']


def test_media_revisions_are_per_participant_and_type_and_invitees_get_no_content(mesh):
    mesh.start([2, 3, 4])
    mesh.join(2)
    mesh.join(3)
    mesh.events.clear()
    scope = {'call_id': CALL_ID, 'conversation_id': 1}
    mesh.invoke('media_status', 1, {**scope, 'type': 'mic', 'enabled': True, 'revision': 2})
    mesh.invoke('media_status', 1, {**scope, 'type': 'cam', 'enabled': True, 'revision': 2})
    mesh.invoke('media_status', 1, {**scope, 'type': 'mic', 'enabled': False, 'revision': 1})
    mesh.invoke('stream_status', 1, {**scope, 'is_streaming': True, 'revision': 3})
    mesh.invoke('stream_status', 1, {**scope, 'is_streaming': False, 'revision': 2})
    mesh.invoke('call_chat_message', 1, {**scope, 'text': '<b>plain</b>', 'timestamp': 123.0})
    member = mesh.registry.calls[CALL_ID].members[1]
    assert member.mic_enabled and member.cam_enabled and member.is_sharing and member.media_revision == 2
    content = [
        (event, sid) for event, _, sid in mesh.events if event in {'media_status', 'stream_status', 'call_chat_message'}
    ]
    assert {sid for _, sid in content} == {'user-2', 'user-3'}
    assert len(mesh.only('media_status')) == 4 and len(mesh.only('stream_status')) == 2
    assert mesh.only('call_chat_message')[0][0]['text'] == '<b>plain</b>'
    late = mesh.join(4)
    owner = next(person for person in late['participants'] if person['user_id'] == 1)
    assert owner['mic_enabled'] and owner['cam_enabled'] and owner['is_sharing']


@pytest.mark.parametrize(
    'method,extra',
    [
        ('media_status', {'type': 'mic', 'enabled': True, 'revision': True}),
        ('media_status', {'type': 'cam', 'enabled': 1, 'revision': 1}),
        ('stream_status', {'is_streaming': 'yes'}),
        ('call_chat_message', {'text': 'x' * 1001}),
        ('call_chat_message', {'text': 'test', 'timestamp': float('nan')}),
    ],
)
def test_media_and_chat_payload_validation_never_relays(mesh, method, extra):
    trio(mesh)
    mesh.events.clear()
    with pytest.raises(ValidationError):
        mesh.invoke(method, 1, {'call_id': CALL_ID, 'conversation_id': 1, **extra})
    assert not mesh.events


def test_leave_retains_remaining_pair_and_local_call_until_last_peer_leaves(mesh):
    room = trio(mesh)
    surviving = next(pair for pair in room.pairs.values() if set(pair.user_ids) == {2, 3})
    mesh.invoke('leave', 1)
    assert mesh.registry.calls[CALL_ID] is room and room.status == 'active'
    assert room.owner_id == 2 and set(room.members) == {2, 3}
    assert room.pairs == {surviving.pair_id: surviving}
    assert not mesh.registry.busy(1) and mesh.registry.busy(2)
    assert mesh.only('group_call_state')[-1][0]['participants']
    mesh.invoke('leave', 2)
    assert not mesh.registry.calls and not mesh.registry.by_user and not mesh.registry.by_conversation
    assert mesh.only('group_call_state')[-1][0]['status'] == 'ended'


def test_disconnect_and_membership_revocation_drop_only_affected_member(mesh):
    room = trio(mesh)
    generation = room.members[3].generation
    mesh.registry.on_disconnect('user-3', object())
    assert 3 in room.members
    mesh.clients.pop('user-3')
    mesh.generations.pop('user-3')
    mesh.registry.on_disconnect('user-3', generation)
    assert mesh.registry.calls[CALL_ID] is room and set(room.members) == {1, 2}
    mesh.roles[1].pop(2)
    mesh.registry.evict(1, 2)
    assert not mesh.registry.calls and not mesh.registry.by_user


def test_invitee_decline_and_timeout_are_independent_and_cannot_end_active_pair(mesh):
    mesh.start([2, 3, 4])
    mesh.join(2)
    room = mesh.registry.calls[CALL_ID]
    mesh.invoke('leave', 3)
    assert room.status == 'active' and set(room.members) == {1, 2, 4}
    assert mesh.timers[1].cancelled
    mesh.now += 30
    mesh.timers[2].fire()
    assert mesh.registry.calls[CALL_ID] is room and set(room.members) == {1, 2}
    assert mesh.timers[2].cancelled and not mesh.registry.busy(4)


def test_waiting_room_retains_other_invitation_but_ends_when_none_remain(mesh):
    mesh.start()
    mesh.invoke('leave', 2)
    room = mesh.registry.calls[CALL_ID]
    assert room.status == 'waiting' and set(room.members) == {1, 3}
    mesh.now += 30
    mesh.timers[1].fire()
    assert not mesh.registry.calls and not mesh.registry.by_user
    assert mesh.only('group_call_state')[-1][0]['status'] == 'ended'


def test_late_timer_and_join_cannot_revive_closed_or_recalled_room(mesh):
    mesh.start()
    room = mesh.registry.calls[CALL_ID]
    invite_id = room.members[2].invite_id
    timer = mesh.timers[0]
    mesh.invoke('leave', 1)
    events = len(mesh.events)
    mesh.now += 40
    timer.fire()
    assert len(mesh.events) == events
    with pytest.raises(ChatAccessError):
        mesh.invoke('join', 2, {'call_id': CALL_ID, 'conversation_id': 1, 'invite_id': invite_id})
    with pytest.raises(ChatAccessError):
        mesh.start()
    assert not mesh.registry.calls


def test_close_cancels_all_timeouts_and_suppresses_late_callbacks(mesh):
    mesh.start()
    events = len(mesh.events)
    mesh.registry.close()
    assert all(timer.cancelled for timer in mesh.timers)
    mesh.now += 40
    for timer in mesh.timers:
        timer.fire()
    assert not mesh.registry.calls and not mesh.registry.by_user and len(mesh.events) == events
    assert not mesh.registry.contains(CALL_ID)
    with pytest.raises(ChatAccessError):
        mesh.start()


def test_disconnect_during_peer_acl_cannot_commit_room_or_resurrect_sid(mesh):
    def disconnect_caller(cid, actor):
        if actor.user_id == 2:
            mesh.clients.pop('user-1', None)
            mesh.generations.pop('user-1', None)

    mesh.access_hook = disconnect_caller
    with pytest.raises(ChatAccessError):
        mesh.start()
    assert not mesh.registry.calls and not mesh.registry.by_user and not mesh.events


def test_receiver_acl_refresh_rechecks_sender_liveness_before_signal(mesh):
    trio(mesh)
    mesh.events.clear()

    def disconnect_sender(cid, actor):
        if actor.user_id == 2:
            mesh.clients.pop('user-1', None)
            mesh.generations.pop('user-1', None)

    mesh.access_hook = disconnect_sender
    with pytest.raises(ChatAccessError):
        mesh.signal(1, 2)
    assert not mesh.only('group_call_signal')


def test_signal_after_target_membership_revocation_keeps_other_joined_pair(mesh):
    room = trio(mesh)
    mesh.roles[1].pop(2)
    with pytest.raises(ChatAccessError):
        mesh.signal(1, 2)
    assert mesh.registry.calls[CALL_ID] is room and set(room.members) == {1, 3}
    assert not mesh.only('group_call_signal')


def test_waiting_owner_media_snapshot_is_available_to_first_late_joiner(mesh):
    mesh.start()
    scope = {'call_id': CALL_ID, 'conversation_id': 1}
    mesh.invoke('media_status', 1, {**scope, 'type': 'mic', 'enabled': True, 'revision': 1})
    mesh.invoke('media_status', 1, {**scope, 'type': 'cam', 'enabled': False, 'revision': 1})
    assert not mesh.only('media_status')
    snapshot = mesh.join(2)
    owner = next(person for person in snapshot['participants'] if person['user_id'] == 1)
    assert owner['mic_enabled'] and not owner['cam_enabled'] and owner['media_revision'] == 1


def test_snapshot_preserves_independent_media_and_stream_revisions_for_join_ack_and_state(mesh):
    mesh.start()
    scope = {'call_id': CALL_ID, 'conversation_id': 1}
    mesh.invoke('media_status', 1, {**scope, 'type': 'mic', 'enabled': True, 'revision': 2})
    mesh.invoke('media_status', 1, {**scope, 'type': 'cam', 'enabled': False, 'revision': 5})
    mesh.invoke('stream_status', 1, {**scope, 'is_streaming': True, 'revision': 7})
    ack = mesh.join(2)
    owner = next(person for person in ack['participants'] if person['user_id'] == 1)
    assert owner['media_revision'] == 5
    assert owner['media_revisions'] == {'mic': 2, 'cam': 5}
    assert owner['stream_revision'] == 7
    assert owner['mic_enabled'] and not owner['cam_enabled'] and owner['is_sharing']
    newcomer = next(person for person in ack['participants'] if person['user_id'] == 2)
    assert newcomer['media_revision'] == 0
    assert newcomer['media_revisions'] == {'mic': 0, 'cam': 0}
    assert newcomer['stream_revision'] == 0
    state = next(state for state, sid in reversed(mesh.only('group_call_state')) if sid == 'user-2')
    assert next(person for person in state['participants'] if person['user_id'] == 1) == owner
    owner['media_revisions']['mic'] = 99
    assert mesh.registry.calls[CALL_ID].members[1].media_revisions == {'mic': 2, 'cam': 5, 'stream': 7}


@pytest.mark.parametrize(
    'method,extra',
    [
        ('media_status', {'type': [], 'enabled': True, 'revision': 1}),
        ('signal', {'type': [], 'payload': {'type': 'offer', 'sdp': SDP}}),
    ],
)
def test_unhashable_payload_type_returns_validation_error_not_internal_error(mesh, method, extra):
    trio(mesh)
    mesh.events.clear()
    with pytest.raises(ValidationError):
        mesh.invoke(method, 1, {'call_id': CALL_ID, 'conversation_id': 1, **extra})
    assert not mesh.events


def test_legacy_stream_event_cannot_overwrite_a_sequenced_snapshot(mesh):
    trio(mesh)
    scope = {'call_id': CALL_ID, 'conversation_id': 1}
    mesh.invoke('stream_status', 1, {**scope, 'is_streaming': True, 'revision': 4})
    count = len(mesh.only('stream_status'))
    mesh.invoke('stream_status', 1, {**scope, 'is_streaming': False})
    assert mesh.registry.calls[CALL_ID].members[1].is_sharing
    assert len(mesh.only('stream_status')) == count


def test_recipient_removed_during_acl_does_not_receive_call_content(mesh):
    room = trio(mesh)
    mesh.events.clear()

    def leave_receiver(cid, actor):
        if actor.user_id == 2 and 2 in room.members:
            mesh.registry.evict(cid, 2)

    mesh.access_hook = leave_receiver
    mesh.invoke('call_chat_message', 1, {'call_id': CALL_ID, 'conversation_id': 1, 'text': 'Remaining members only'})
    assert [sid for _, sid in mesh.only('call_chat_message')] == ['user-3']
    assert set(room.members) == {1, 3}


def test_removed_recipient_cannot_receive_a_later_active_room_snapshot(mesh):
    room = trio(mesh)
    mesh.events.clear()
    count = {'owner': 0}

    def remove_on_immediate_owner_refresh(cid, actor):
        if actor.user_id == 1:
            count['owner'] += 1
            if count['owner'] == 2:
                mesh.registry.evict(cid, 2)

    mesh.access_hook = remove_on_immediate_owner_refresh
    mesh.registry._publish(room)
    assert not any(state['status'] != 'ended' and sid == 'user-2' for state, sid in mesh.only('group_call_state'))
    assert set(room.members) == {1, 3}
