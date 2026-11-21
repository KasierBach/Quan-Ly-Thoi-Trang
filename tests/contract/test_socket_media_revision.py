"""The media-status revision is transport data, not a timestamp or caller identity."""

import pytest

from tests.contract.test_chat_server import ANSWER, CALL_ID, OFFER, ChatHarness


@pytest.fixture
def chat(app, monkeypatch):
    harness = ChatHarness(app, monkeypatch)
    try:
        yield harness
    finally:
        harness.close()


def active_call(chat):
    caller, recipient = chat.connect(1), chat.connect(3)
    data = {'conversation_id': 2, 'call_id': CALL_ID}
    assert caller.emit('call_user', {**data, 'offer': OFFER, 'target_user_id': 3, 'isVideo': True}, callback=True)[
        'success'
    ]
    assert recipient.emit('answer_call', {**data, 'answer': ANSWER}, callback=True)['success']
    caller.get_received()
    recipient.get_received()
    return caller, recipient, data


def test_valid_media_revisions_are_forwarded_with_canonical_identity(chat):
    caller, recipient, data = active_call(chat)
    result = caller.emit('media_status', {**data, 'type': 'mic', 'enabled': False, 'revision': 3}, callback=True)
    assert result['success'] is True
    message = next(packet['args'][0] for packet in recipient.get_received() if packet['name'] == 'media_status')
    assert message['revision'] == 3
    assert message['enabled'] is False
    assert message['sender_id'] == 1
    assert message['call_id'] == CALL_ID


@pytest.mark.parametrize('revision', [True, False, 0, -1, 2147483648, '3', 1.5, {}, []])
def test_malformed_media_revision_is_rejected_without_peer_event(chat, revision):
    caller, recipient, data = active_call(chat)
    result = caller.emit('media_status', {**data, 'type': 'cam', 'enabled': False, 'revision': revision}, callback=True)
    assert result['success'] is False
    assert result['status'] == 400
    assert recipient.get_received() == []


def test_legacy_media_status_without_revision_keeps_compatible_envelope(chat):
    caller, recipient, data = active_call(chat)
    assert caller.emit('media_status', {**data, 'type': 'mic', 'enabled': True}, callback=True)['success']
    message = next(packet['args'][0] for packet in recipient.get_received() if packet['name'] == 'media_status')
    assert 'revision' not in message
    assert message['enabled'] is True
