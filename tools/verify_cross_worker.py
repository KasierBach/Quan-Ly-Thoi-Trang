"""Internal-only two-worker Socket.IO acceptance probe for docker-compose.scale.yml."""

import argparse
import json
import queue
import re
import time
from urllib.parse import urlsplit

import requests
import socketio


ALLOWED_WORKERS = {'web1', 'web2'}
PASSWORD = 'TestUser123!'


def worker_url(value):
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != 'http'
            or parsed.hostname not in ALLOWED_WORKERS
            or parsed.port != 4000
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {'', '/'}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('Workers must be exact internal http://web1:4000 or http://web2:4000 URLs') from None
    return f'http://{parsed.hostname}:4000'


def login(base_url, email):
    session = requests.Session()
    session.trust_env = False
    page = session.get(f'{base_url}/login', headers={'Host': 'localhost'}, timeout=10)
    page.raise_for_status()
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text)
    if token is None:
        raise RuntimeError('CSRF token missing')
    response = session.post(
        f'{base_url}/login',
        headers={'Host': 'localhost'},
        data={'email': email, 'password': PASSWORD, 'csrf_token': token.group(1)},
        allow_redirects=False,
        timeout=10,
    )
    if response.status_code != 302:
        raise RuntimeError(f'Login failed: {response.status_code}')
    page = session.get(f'{base_url}/messages', headers={'Host': 'localhost'}, timeout=10)
    page.raise_for_status()
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text)
    if token is None:
        raise RuntimeError('Post-login CSRF token missing')
    bootstrap = session.post(
        f'{base_url}/api/chat/guest-session',
        headers={'Host': 'localhost', 'X-CSRFToken': token.group(1)},
        timeout=10,
    )
    bootstrap.raise_for_status()
    return session, token.group(1), bootstrap.json()


def client(base_url, session, csrf_token, credentials):
    events = queue.Queue()
    connection = socketio.Client(http_session=session, reconnection=False, logger=False, engineio_logger=False)

    @connection.on('new_message')
    def new_message(data):
        events.put(data)

    connection.connect(
        base_url,
        headers={'Host': 'localhost'},
        auth={'csrf_token': csrf_token, 'auth_token': credentials['auth_token']},
        transports=['polling'],
        wait_timeout=10,
    )
    join = connection.call('join_conversation', {'conversation_id': 2}, timeout=10)
    if join.get('success') is not True:
        raise RuntimeError(f'Join failed: {join}')
    while not events.empty():
        events.get_nowait()
    return connection, events


def receive(events, expected_id):
    matched = []
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            item = events.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            break
        if item.get('id') == expected_id:
            matched.append(item)
            break
    time.sleep(0.5)
    while not events.empty():
        item = events.get_nowait()
        if item.get('id') == expected_id:
            matched.append(item)
    if len(matched) != 1:
        raise RuntimeError(f'Expected persisted message {expected_id} exactly once, got {len(matched)}')
    return matched[0]


def send(sender, receiver_events, text):
    result = sender.call('send_message', {'conversation_id': 2, 'content': text}, timeout=10)
    if result.get('success') is not True or not isinstance(result.get('id'), int):
        raise RuntimeError(f'Persisted send failed: {result}')
    delivered = receive(receiver_events, result['id'])
    if delivered.get('content') != text:
        raise RuntimeError('Delivered content does not match persisted content')
    return result['id']


def expect_no_message(events, forbidden_ids, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            item = events.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            return
        if item.get('id') in forbidden_ids:
            raise RuntimeError(f'Revoked recipient received message {item["id"]}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify scoped Redis delivery between internal scale workers')
    parser.add_argument('--worker-a', required=True)
    parser.add_argument('--worker-b', required=True)
    args = parser.parse_args(argv)
    try:
        first_url, second_url = worker_url(args.worker_a), worker_url(args.worker_b)
    except ValueError as error:
        parser.error(str(error))
    if first_url == second_url:
        parser.error('Two distinct internal workers are required')

    session_a, csrf_a, credentials_a = login(first_url, 'customer@example.test')
    session_b, csrf_b, credentials_b = login(second_url, 'other@example.test')
    first, events_a = client(first_url, session_a, csrf_a, credentials_a)
    second, events_b = client(second_url, session_b, csrf_b, credentials_b)
    try:
        first_id = send(first, events_b, 'cross-worker a-to-b')
        second_id = send(second, events_a, 'cross-worker b-to-a')
        leave = session_b.post(
            f'{second_url}/api/conversations/2/leave',
            headers={'Host': 'localhost', 'X-CSRFToken': csrf_b},
            timeout=10,
        )
        leave.raise_for_status()
        revoked = first.call('send_message', {'conversation_id': 2, 'content': 'after remote leave'}, timeout=10)
        if revoked.get('success') is not True or not isinstance(revoked.get('id'), int):
            raise RuntimeError(f'Post-leave persisted send failed: {revoked}')
        expect_no_message(events_b, {revoked['id']})
        print(
            json.dumps(
                {
                    'success': True,
                    'a_to_b_message_id': first_id,
                    'b_to_a_message_id': second_id,
                    'revoked_message_id': revoked['id'],
                    'revoked_recipient_deliveries': 0,
                }
            )
        )
        return 0
    finally:
        first.disconnect()
        second.disconnect()


if __name__ == '__main__':
    raise SystemExit(main())
