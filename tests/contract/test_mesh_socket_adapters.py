"""Real Socket.IO adapters for the process-local mesh registry."""

import pytest

from tests.contract.test_chat_server import ANSWER, CALL_ID, OFFER, ChatHarness, packets, ring


GROUP_CALL_ID = 'group_call_01234567'


@pytest.fixture(autouse=True)
def group_room(chat):
    chat.conversations[3]['members'] = {1: 'admin', 2: 'member', 3: 'member'}


@pytest.fixture
def chat(app, monkeypatch):
    harness = ChatHarness(app, monkeypatch)
    harness.handlers.mesh_calls.authorize = harness.access
    try:
        yield harness
    finally:
        harness.close()


def start_three(chat):
    owner, second, third = chat.connect(1), chat.connect(2), chat.connect(3)
    result = owner.emit(
        'group_call_start',
        {
            'call_id': GROUP_CALL_ID,
            'conversation_id': 3,
            'request_id': 'request_0123456789',
            'invite_user_ids': [2, 3],
            'isVideo': True,
        },
        callback=True,
    )
    assert result['success'] is True
    second_invite = packets(second, 'group_call_invited')[0]
    third_invite = packets(third, 'group_call_invited')[0]
    owner.get_received()
    return owner, second, third, second_invite, third_invite


def join(connection, invitation):
    result = connection.emit(
        'group_call_join',
        {
            'call_id': GROUP_CALL_ID,
            'conversation_id': 3,
            'invite_id': invitation['invite_id'],
        },
        callback=True,
    )
    assert result['success'] is True
    return result


def test_mesh_socket_start_join_directed_signal_and_selective_leave(chat):
    owner, second, third, second_invite, third_invite = start_three(chat)
    second_state = join(second, second_invite)
    join(third, third_invite)
    owner_events = packets(owner, 'group_call_state')
    final_state = owner_events[-1]
    assert final_state['status'] == 'active'
    assert {person['user_id'] for person in final_state['participants']} == {1, 2, 3}
    assert len(final_state['pairs']) == 3

    pair = next(pair for pair in second_state['pairs'] if set(pair['user_ids']) == {1, 2})
    offerer = owner if pair['offerer_user_id'] == 1 else second
    answerer = second if offerer is owner else owner
    target = 2 if offerer is owner else 1
    offer = offerer.emit(
        'group_call_signal',
        {
            'call_id': GROUP_CALL_ID,
            'conversation_id': 3,
            'target_user_id': target,
            'pair_id': pair['pair_id'],
            'peer_revision': pair['peer_revision'],
            'type': 'offer',
            'payload': OFFER,
        },
        callback=True,
    )
    assert offer['success'] is True
    directed = packets(answerer, 'group_call_signal')
    assert len(directed) == 1 and directed[0]['payload']['sdp'].endswith('offer')
    assert packets(third, 'group_call_signal') == []

    answer = answerer.emit(
        'group_call_signal',
        {
            'call_id': GROUP_CALL_ID,
            'conversation_id': 3,
            'target_user_id': pair['offerer_user_id'],
            'pair_id': pair['pair_id'],
            'peer_revision': pair['peer_revision'],
            'type': 'answer',
            'payload': ANSWER,
        },
        callback=True,
    )
    assert answer['success'] is True
    assert packets(offerer, 'group_call_signal')[0]['type'] == 'answer'

    left = third.emit(
        'group_call_leave',
        {'call_id': GROUP_CALL_ID, 'conversation_id': 3},
        callback=True,
    )
    assert left['success'] is True
    assert chat.handlers.mesh_calls.contains(GROUP_CALL_ID)
    assert {person['user_id'] for person in packets(owner, 'group_call_state')[-1]['participants']} == {1, 2}


def test_mesh_media_and_chat_reach_joined_members_not_invitees(chat):
    owner, second, third, second_invite, _ = start_three(chat)
    join(second, second_invite)
    owner.get_received()
    second.get_received()
    third.get_received()

    result = owner.emit(
        'media_status',
        {
            'call_id': GROUP_CALL_ID,
            'conversation_id': 3,
            'type': 'mic',
            'enabled': False,
            'revision': 1,
        },
        callback=True,
    )
    assert result['success'] is True
    assert packets(second, 'media_status')[0]['enabled'] is False
    assert packets(third, 'media_status') == []

    message = second.emit(
        'call_chat_message',
        {
            'call_id': GROUP_CALL_ID,
            'conversation_id': 3,
            'text': '<b>plain text</b>',
            'timestamp': 123,
        },
        callback=True,
    )
    assert message['success'] is True
    payload = packets(owner, 'call_chat_message')[0]
    assert payload['text'] == '<b>plain text</b>' and payload['sender_id'] == 2
    assert packets(third, 'call_chat_message') == []


def test_private_call_and_mesh_share_busy_reservations(chat):
    owner, _second, _third, _second_invite, _third_invite = start_three(chat)
    result = ring(chat, owner, call_id=CALL_ID)
    assert result['success'] is False
    assert result['status'] == 409
    assert CALL_ID not in chat.handlers.calls


def test_disconnect_removes_only_one_member_and_keeps_remaining_pair(chat):
    owner, second, third, second_invite, third_invite = start_three(chat)
    join(second, second_invite)
    join(third, third_invite)
    owner.get_received()
    second.get_received()
    third.disconnect()
    state = packets(owner, 'group_call_state')[-1]
    assert state['status'] == 'active'
    assert {person['user_id'] for person in state['participants']} == {1, 2}
    assert chat.handlers.mesh_calls.contains(GROUP_CALL_ID)
